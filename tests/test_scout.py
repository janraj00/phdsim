"""Behavioral checks for information boundaries, timing and paired comparisons."""

from dataclasses import asdict, replace
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from phdsim.cli.scout import main
from phdsim.simulation.config import Config
from phdsim.experiments.scout.config import load_config
from phdsim.planning.grid import plan_path
from phdsim.decision.acquisition.view import DecisionView
from phdsim.decision.acquisition.no_scouting import NoScouting
from phdsim.simulation.events import EventQueue
from phdsim.experiments.scout.mission import simulate
from phdsim.belief.occupancy import Belief
from phdsim.sensors.observations import Observation
from phdsim.environments.corridors import generate_corridors


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_world_is_reproducible_and_has_a_real_path(self):
        for seed in range(10):
            config = replace(self.config, seed=seed)
            world = generate_corridors(config.world.size, config.seed)
            self.assertEqual(world, generate_corridors(config.world.size, config.seed))
            truth_as_belief = tuple(tuple(float(p) for p in row) for row in world.blocked)
            self.assertTrue(plan_path(truth_as_belief, world.start, world.goal, config.planning))
            self.assertNotEqual(world.prior, truth_as_belief)

    def test_bayesian_update_and_contact_facts(self):
        belief = Belief(((0.5, 0.5, 0.5),), (0, 0), (2, 0))
        belief.update(Observation("drone", 3, ((1, 0, True),), .9))
        self.assertAlmostEqual(belief.snapshot()[0][1], .9)
        belief.contact((1, 0), True)
        belief.update(Observation("rover", 4, ((1, 0, False),), .9))
        self.assertEqual(belief.snapshot()[0], (0., 1., 0.))

    def test_delivery_queue_does_not_release_early_and_keeps_order(self):
        queue = EventQueue()
        queue.schedule(7, "deliver", "first")
        queue.schedule(7, "deliver", "second")
        self.assertEqual(list(queue.due(6)), [])
        self.assertEqual([e[3] for e in queue.due(7)], ["first", "second"])
        self.assertEqual(list(queue.due(8)), [])

    def test_delayed_drone_payload_cannot_change_belief_before_delivery(self):
        config = replace(self.config, communication=replace(self.config.communication, delivery_delay=(50, 50)))

        class AskOnce(NoScouting):
            name = "ask_once"

            def __init__(self):
                self.views = []

            def request(self, view, path):
                self.views.append(view)
                return (16, 8) if view.tick == 0 else None

        policy = AskOnce()
        actual = simulate(config, policy)
        reference = simulate(config)
        self.assertEqual(actual["evaluation"]["final_belief"], reference["evaluation"]["final_belief"])
        self.assertEqual(actual["trajectory"], reference["trajectory"])
        self.assertEqual(actual["summary"]["requests"], 1)
        self.assertEqual(actual["summary"]["delivered"], 0)
        self.assertTrue(any(e["kind"] == "drone_capture" for e in actual["events"]))
        for view in policy.views:
            self.assertIsInstance(view, DecisionView)
            self.assertEqual(view.drone_position, generate_corridors(config.world.size, config.seed).start)
            self.assertFalse(set(asdict(view)) & {"truth", "world", "events", "payload", "future_observations"})

    def test_capture_delivery_order_and_budget_invariants(self):
        config = replace(self.config, policy="uncertainty_scouting",
                         acquisition=replace(self.config.acquisition, entropy_threshold=0.0))
        result = simulate(config)
        accepted = {e["request_id"]: e for e in result["events"] if e["kind"] == "request_accepted"}
        captures = {e["request_id"]: e for e in result["events"] if e["kind"] == "drone_capture"}
        deliveries = {e["request_id"]: e for e in result["events"] if e["kind"] == "observation_delivered"}
        self.assertTrue(deliveries)
        for request_id, event in deliveries.items():
            self.assertGreater(captures[request_id]["tick"], accepted[request_id]["tick"])
            self.assertGreater(event["tick"], captures[request_id]["tick"])
            self.assertEqual(event["captured_at"], captures[request_id]["tick"])
        summary = result["summary"]
        self.assertLessEqual(summary["energy_reserved"], config.mission.energy_budget)
        self.assertLessEqual(summary["elapsed_ticks"], config.mission.time_budget)
        self.assertEqual(summary["pending_requests_at_end"], summary["requests"]-summary["delivered"])
        self.assertAlmostEqual(summary["energy_reserved"], summary["rover_energy"]+summary["drone_energy_reserved"], places=5)

    def test_energy_controller_rejects_unaffordable_drone_request(self):
        config = replace(self.config, mission=replace(self.config.mission, energy_budget=1),
                         policy="uncertainty_scouting",
                         acquisition=replace(self.config.acquisition, entropy_threshold=0))
        result = simulate(config)
        self.assertEqual(result["summary"]["requests"], 0)
        self.assertLessEqual(result["summary"]["energy_reserved"], 1)
        self.assertTrue(any(e["kind"] == "request_rejected" and e["reason"] == "energy" for e in result["events"]))

    def test_paired_policy_runs_share_world_and_are_deterministic(self):
        left = simulate(self.config)
        right_config = replace(self.config, policy="uncertainty_scouting")
        right = simulate(right_config)
        self.assertEqual(left["summary"]["world_sha256"], right["summary"]["world_sha256"])
        self.assertEqual(right, simulate(right_config))
        self.assertEqual(left["summary"]["requests"], 0)

    def test_config_roundtrip_and_bad_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"config.json"
            path.write_text(json.dumps(self.config.to_dict()))
            self.assertEqual(load_config(path), self.config)
        for changes in ({"policy": "magic"}, {"rover": replace(self.config.rover, speed=0)},
                        {"communication": replace(self.config.communication, delivery_delay=(5, 1))},
                        {"acquisition": replace(self.config.acquisition, lookahead=0)}):
            with self.assertRaises(ValueError):
                replace(self.config, **changes)

    def test_cli_writes_reports_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, output = Path(tmp)/"config.json", Path(tmp)/"run"
            config.write_text(json.dumps(self.config.to_dict()))
            args = ["--config", str(config), "--output", str(output), "--compare"]
            with redirect_stdout(io.StringIO()):
                main(args)
            report = json.loads((output/"summary.json").read_text())
            self.assertEqual(len(report["runs"]), 2)
            self.assertTrue((output/"seed-42.svg").is_file())
            before = (output/"summary.json").read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)
            self.assertEqual(before, (output/"summary.json").read_bytes())

    def test_policy_and_belief_imports_do_not_load_hidden_environment(self):
        script = '''
import sys
from phdsim.decision.acquisition.factory import make_policy
from phdsim.belief.occupancy import Belief
for prefix in ("phdsim.environments", "phdsim.simulation", "phdsim.experiments", "torch", "numpy"):
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), prefix
'''
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
