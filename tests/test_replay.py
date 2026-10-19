from dataclasses import replace
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from phdsim.perception import FitConfig
from tests.fixtures import GeneratorConfig
from phdsim.perception import load_scalar
from tests.fixtures import make_proxy_pool, train_scalar_pool
from phdsim.decision import AlwaysAcquire, NoAcquisition
from phdsim.decision.actions import Acquire
from phdsim.costs.types import CostComponent, CostVector
from phdsim.serialization import jsonable
from phdsim.evaluation.presence import BrierEvaluator
from phdsim.experiments.presence.replay import run_replay
from phdsim.datasets import ObservationPool, read_lines, write_lines
from phdsim.datasets import AgentSlot, allocate
from phdsim.costs import CostLedger
from phdsim.runtime.presence import ReplayEngine, transfer_cost


class RecordingPolicy:
    name = "recording"

    def __init__(self, acquire=True):
        self.calls = []
        self.delegate = AlwaysAcquire() if acquire else NoAcquisition()

    def choose(self, view, candidates):
        self.calls.append((view, candidates))
        return self.delegate.choose(view, candidates)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory()
        cls.pool = make_proxy_pool(Path(cls.temporary.name) / "demo", 17, GeneratorConfig(40, 10, 12))
        cls.schedule = allocate(cls.pool, (AgentSlot("rgb", "rgb", 5), AgentSlot("thermal", "thermal", 5)))
        cls.perception, cls.fusion = train_scalar_pool(cls.pool, ("rgb", "thermal"), FitConfig(epochs=25))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_engine(self, policy, *, schedule=None, budget=100, labels=None, neighbors=None):
        events = []
        engine = ReplayEngine(self.pool, schedule or self.schedule, self.perception, self.fusion,
                              BrierEvaluator(self.pool.read_labels() if labels is None else labels),
                              lambda row: load_scalar(self.pool, row), neighbors)
        ledger = CostLedger(CostVector((CostComponent("transfers", "transfer", budget),)), transfer_cost())
        results = engine.run(policy, ledger, lambda kind, data: events.append((kind, data)))
        return results, ledger, events

    def test_no_automatic_exchange_and_only_own_single_modality_initially(self):
        policy = RecordingPolicy(acquire=False)
        results, ledger, events = self.run_engine(policy)
        self.assertEqual(ledger.total.get("transfers").value, 0)
        self.assertFalse(any(kind == "transfers" for kind, _ in events))
        self.assertTrue(all(r["initial_result"] == r["final_result"] for r in results))
        for view, _ in policy.calls:
            self.assertEqual(len(view.observations), 1)
            self.assertEqual(view.modalities, (view.receiver_id,))
            self.assertFalse(hasattr(view, "labels") or hasattr(view, "pool"))

    def test_pull_transfers_original_observation_only_at_current_frame(self):
        results, ledger, events = self.run_engine(AlwaysAcquire())
        assignments = {(a.sequence_id, a.tick, a.agent_id): a.observation_id for a in self.schedule.assignments}
        self.assertEqual(ledger.total.get("transfers").value, 10)
        self.assertTrue(all(r["transfers"] == 1 for r in results))
        for kind, transfer in events:
            if kind != "transfers":
                continue
            observation = transfer["observation"]
            self.assertEqual(observation.observation_id, assignments[(*transfer["frame"], transfer["sender"])])
            self.assertEqual(observation, load_scalar(self.pool, self.pool.by_id[observation.observation_id]))
            self.assertNotEqual(transfer["sender"], transfer["receiver"])
            self.assertEqual(transfer["estimated_cost"], transfer["settled_cost"])

    def test_missing_neighbor_observation_does_not_expose_pool_or_future(self):
        schedule = allocate(self.pool, (AgentSlot("rgb", "rgb", 3), AgentSlot("thermal", "thermal", 1)))
        policy = RecordingPolicy()
        results, ledger, _ = self.run_engine(policy, schedule=schedule)
        self.assertEqual(ledger.total.get("transfers").value, 2)
        later = [r for r in results if r["frame"][1] > 0]
        self.assertTrue(all(r["transfers"] == 0 for r in later))
        allowed = {a.observation_id for a in schedule.assignments}
        for _, candidates in policy.calls:
            self.assertTrue(all(dict(c.action.parameters)["observation_id"] in allowed for c in candidates))

    def test_budget_blocks_transfers_and_topology_controls_candidates(self):
        results, ledger, events = self.run_engine(AlwaysAcquire(), budget=0)
        self.assertEqual(ledger.total.get("bytes").value, 0)
        self.assertTrue(all(r["stop_reason"] == "budget_blocked" for r in results))
        self.assertFalse(any(kind == "transfers" for kind, _ in events))
        _, disconnected, _ = self.run_engine(AlwaysAcquire(), neighbors={"rgb": (), "thermal": ()})
        self.assertEqual(disconnected.total.get("transfers").value, 0)
        _, capped, _ = self.run_engine(AlwaysAcquire(), budget=1)
        self.assertEqual(capped.total.get("transfers").value, 1)

    def test_labels_cannot_change_decisions_or_messages(self):
        first, second = RecordingPolicy(), RecordingPolicy()
        labels = {target: 1 - value for target, value in self.pool.read_labels().items()}
        _, _, before = self.run_engine(first)
        _, _, after = self.run_engine(second, labels=labels)
        self.assertEqual(first.calls, second.calls)
        self.assertEqual([e for e in before if e[0] in ("decisions", "transfers")],
                         [e for e in after if e[0] in ("decisions", "transfers")])

    def test_replicated_observation_is_not_pulled_or_counted_twice(self):
        schedule = allocate(self.pool, (AgentSlot("a", "rgb", 3), AgentSlot("b", "rgb", 3)), mode="replicate")
        results, ledger, _ = self.run_engine(AlwaysAcquire(), schedule=schedule)
        self.assertEqual(ledger.total.get("transfers").value, 0)
        self.assertTrue(all(len(r["final_result"].observation_ids) == 1 for r in results))

    def test_policy_cannot_request_unadvertised_source(self):
        class InvalidPolicy:
            name = "invalid"

            def choose(self, view, candidates):
                return Acquire("bad", view.receiver_id, "future-owner", view.target, "thermal")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_engine(InvalidPolicy())

    def test_exports_reproducible_models_frozen_and_test_labels_used_only_for_evaluation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = run_replay(self.pool, self.schedule, root / "first", threshold=0, fit=FitConfig(epochs=25))
            self.assertEqual(first, run_replay(self.pool, self.schedule, root / "second", threshold=0, fit=FitConfig(epochs=25)))
            for file in (root / "first").iterdir():
                self.assertEqual(file.read_bytes(), (root / "second" / file.name).read_bytes())
            self.assertEqual(first["policies"]["no_acquisition"]["transfers"], 0)
            self.assertEqual(first["policies"]["always_acquire"]["transfers"], 10)
            self.assertEqual(first["policies"]["uncertainty_threshold"]["transfers"], 10)
            shutil.copytree(self.pool.root, root / "changed_pool")
            label_path = root / "changed_pool" / "labels.jsonl"
            rows = read_lines(label_path)
            for row in rows:
                if row["target"]["id"].startswith("test-"):
                    row["label"] = 1 - row["label"]
            write_lines(label_path, rows)
            changed = ObservationPool(root / "changed_pool")
            run_replay(changed, self.schedule, root / "changed", threshold=0, fit=FitConfig(epochs=25))
            for name in ("models.json", "decisions.jsonl", "transfers.jsonl"):
                self.assertEqual((root / "first" / name).read_bytes(), (root / "changed" / name).read_bytes())
            self.assertTrue(all(row["split"] == "test" for row in read_lines(root / "first" / "experiences.jsonl")))
            with self.assertRaises(FileExistsError):
                run_replay(self.pool, self.schedule, root / "first")

    def test_scalar_adapter_does_not_claim_to_process_images(self):
        with self.assertRaisesRegex(ValueError, "real images"):
            load_scalar(self.pool, replace(self.pool.records[0], payload_format="rgb-image-v1"))


if __name__ == "__main__":
    unittest.main()
