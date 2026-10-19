from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.perception import FitConfig
from tests.fixtures import GeneratorConfig
from tests.fixtures import make_proxy_pool
from phdsim.decision import DecisionConfig, choose_action
from phdsim.costs.types import CostVector
from phdsim.decision.view import DecisionView
from phdsim.decision.actions import Stop
from phdsim.core.identity import TargetRef
from phdsim.perception.results import TaskResult
from phdsim.experiments.presence.replay import ProcessingConfig
from phdsim.experiments.presence.replay import run_replay
from phdsim.fusion import FusionConfig, IndependentEvidenceFusion, MeanProbabilityFusion
from phdsim.datasets import read_lines, write_json
from phdsim.datasets import AgentSlot, allocate


class FusionDecisionTests(unittest.TestCase):
    def test_probability_fusion_methods_have_distinct_meaning(self):
        target = TargetRef("sample", "one")
        first = TaskResult(target, 0.6, None, ("rgb-1",), ("rgb-model",))
        second = TaskResult(target, 0.8, None, ("thermal-1",), ("thermal-model",))
        independent = IndependentEvidenceFusion(0.5).update(first, second)
        mean = MeanProbabilityFusion().update(first, second)
        self.assertAlmostEqual(independent.prediction, 6 / 7)
        self.assertAlmostEqual(mean.prediction, 0.7)
        self.assertEqual(independent.observation_ids, mean.observation_ids)
        self.assertLess(independent.uncertainty, mean.uncertainty)

    def test_fusion_rejects_duplicate_evidence_and_mismatched_targets(self):
        first = TaskResult(TargetRef("sample", "one"), 0.6, None, ("obs-1",), ("model",))
        different = TaskResult(TargetRef("sample", "two"), 0.8, None, ("obs-2",), ("model",))
        for fusion in (IndependentEvidenceFusion(0.5), MeanProbabilityFusion()):
            with self.subTest(fusion=fusion), self.assertRaises(ValueError):
                fusion.update(first, first)
            with self.subTest(fusion=fusion), self.assertRaises(ValueError):
                fusion.update(first, different)

    def test_configuration_is_strict_and_has_two_independent_sections(self):
        settings = ProcessingConfig.defaults(0.7)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "processing.json"
            write_json(path, asdict(settings))
            self.assertEqual(settings, ProcessingConfig.load(path))
            write_json(path, {"fusion": {"method": "typo"}, "decisions": [{"method": "always_acquire"}]})
            with self.assertRaisesRegex(ValueError, "fusion"):
                ProcessingConfig.load(path)
        with self.assertRaisesRegex(ValueError, "decision"):
            DecisionConfig("typo")
        with self.assertRaisesRegex(ValueError, "threshold"):
            DecisionConfig("always_acquire", 0.8)
        with self.assertRaises(ValueError):
            ProcessingConfig(FusionConfig(), (DecisionConfig("always_acquire"), DecisionConfig("always_acquire")))

    def test_decision_cannot_stop_a_different_agent(self):
        class WrongRecipient:
            def choose(self, view, candidates):
                return Stop("different-agent", view.target, "stop")
        view = DecisionView("agent-1", TargetRef("sample", "one"), None, (), (), ("rgb",), (), CostVector())
        with self.assertRaisesRegex(ValueError, "recipient"):
            choose_action(WrongRecipient(), view, ())

    def test_changing_fusion_keeps_perception_data_and_always_pull_actions_fixed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = make_proxy_pool(root / "input", 17, GeneratorConfig(40, 10, 12))
            schedule = allocate(pool, (AgentSlot("rgb", "rgb", 5), AgentSlot("thermal", "thermal", 5)))
            manifest_before = (pool.root / "observations.jsonl").read_bytes()
            settings = ProcessingConfig(FusionConfig(), (DecisionConfig("always_acquire"),))
            mean_settings = ProcessingConfig(FusionConfig("mean_probability"), settings.decisions)
            for name, configuration in (("independent", settings), ("mean", mean_settings)):
                result = run_replay(pool, schedule, root / name, fit=FitConfig(epochs=25), processing=configuration)
                self.assertEqual(result["policies"]["always_acquire"]["transfers"], 10)
            independent_models = (root / "independent" / "models.json").read_text()
            self.assertEqual(json.loads(independent_models)["perception"],
                             json.loads((root / "mean" / "models.json").read_text())["perception"])
            self.assertEqual((root / "independent" / "transfers.jsonl").read_bytes(),
                             (root / "mean" / "transfers.jsonl").read_bytes())
            first = read_lines(root / "independent" / "experiences.jsonl")
            second = read_lines(root / "mean" / "experiences.jsonl")
            self.assertTrue(any(a["result_after"]["prediction"] != b["result_after"]["prediction"]
                                for a, b in zip(first, second)))
            self.assertEqual(manifest_before, (pool.root / "observations.jsonl").read_bytes())

    def test_changing_decision_keeps_fusion_and_perception_models_fixed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = make_proxy_pool(root / "input", 17, GeneratorConfig(40, 10, 12))
            schedule = allocate(pool, (AgentSlot("rgb", "rgb", 5), AgentSlot("thermal", "thermal", 5)))
            for method, expected in (("no_acquisition", 0), ("always_acquire", 10)):
                settings = ProcessingConfig(FusionConfig(), (DecisionConfig(method),))
                result = run_replay(pool, schedule, root / method, fit=FitConfig(epochs=25), processing=settings)
                self.assertEqual(result["policies"][method]["transfers"], expected)
            self.assertEqual((root / "no_acquisition" / "models.json").read_bytes(),
                             (root / "always_acquire" / "models.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
