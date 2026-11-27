"""Unit and integration tests for model-agnostic CrossModalGainEstimator and VoI rover dispatch."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.belief.semantic_terrain import Prediction
from phdsim.decision.acquisition.semantic_voi import CrossModalGainEstimator, SelectiveRoverVoIPlanner
from phdsim.experiments.scout.bench_config import parse_bench_config
from phdsim.experiments.scout.bench_runner import run_benchmark
from phdsim.planning.coverage_sweep import Plot, SweepRobot


class SemanticVoITests(unittest.TestCase):
    def test_gain_estimator_distinguishes_resolvable_from_unresolvable_confusion(self):
        # Class 0 vs 1 confusion is resolvable by LiDAR (+1), while class 0 vs 2 is unresolvable (0)
        # and confident class 1 is slightly hurt by LiDAR (-1).
        examples = []
        for _ in range(30):
            examples.append((Prediction("soil", (0.52, 0.48, 0.0), ("rgb",)), 1))
            examples.append((Prediction("soil", (0.52, 0.0, 0.48), ("rgb",)), 0))
            examples.append((Prediction("rock", (0.05, 0.90, 0.05), ("rgb",)), -1))

        estimator = CrossModalGainEstimator.fit(examples, bins=8, prior_strength=3.0)
        g_resolvable = estimator.expected_gain(Prediction("soil", (0.52, 0.48, 0.0), ("rgb",)))
        g_unresolvable = estimator.expected_gain(Prediction("soil", (0.52, 0.0, 0.48), ("rgb",)))
        g_harmful = estimator.expected_gain(Prediction("rock", (0.05, 0.90, 0.05), ("rgb",)))

        self.assertGreater(g_resolvable, 0.7)
        self.assertLess(abs(g_unresolvable), 0.15)
        self.assertLess(g_harmful, -0.5)
        self.assertEqual(estimator.expected_gain(None), 0.0)

    def test_voi_planner_skips_unresolvable_sites_and_targets_resolvable_ones(self):
        examples = [
            *((Prediction("soil", (0.52, 0.48, 0.0), ("rgb",)), 1) for _ in range(25)),
            *((Prediction("soil", (0.52, 0.0, 0.48), ("rgb",)), 0) for _ in range(25)),
        ]
        estimator = CrossModalGainEstimator.fit(examples, bins=8, prior_strength=2.0)

        plot = Plot(10, 5, 0.5)
        rover = SweepRobot("rover-1", (0, 0), 0.7, 2, 0.4, 1, 65)
        planner = SelectiveRoverVoIPlanner(plot, (rover,), deadline=40, gain_estimator=estimator, min_site_gain=1.0)

        # Left 5x5 tile (closer to rover!) has unresolvable (0 vs 2) high entropy.
        # Right 5x5 tile (farther!) has resolvable (0 vs 1) high entropy.
        rgb = []
        for y in range(plot.height):
            for x in range(plot.width):
                if x < 5:
                    rgb.append(Prediction("soil", (0.52, 0.0, 0.48), ("rgb-1",)))
                else:
                    rgb.append(Prediction("soil", (0.52, 0.48, 0.0), ("rgb-2",)))
        lidar = (None,) * (plot.width * plot.height)

        assignments = planner.dispatch(0, tuple(rgb), lidar, ())
        self.assertEqual(len(assignments), 1)
        # Must skip the closer unresolvable left tile and choose the right resolvable tile.
        self.assertGreaterEqual(assignments[0].capture.site.xy[0], 5)

        # After the right tile is visited, left tile still has ~0 gain -> rover stops (no dispatch).
        second = planner.dispatch(20, tuple(rgb), lidar, ())
        self.assertEqual(second, [])

    def test_voi_policy_requires_nonempty_disjoint_cal_split(self):
        cfg_no_cal = parse_bench_config({
            "name": "missing-cal",
            "seeds": {"fit": [11, 12], "cal": [], "test": [2021]},
            "variants": [{"name": "voi", "label": "VoI", "policy": "selective_rovers_voi"}],
        })
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_benchmark(cfg_no_cal, Path(tmp) / "out")

    def test_voi_end_to_end_in_benchmark_runner(self):
        cfg = parse_bench_config({
            "name": "voi-e2e",
            "seeds": {"fit": [11, 12, 13], "cal": [101, 102, 103], "test": [2021]},
            "classifier": {"type": "gmm", "params": {"n_components": 3}},
            "variants": [
                {"name": "rgb", "label": "RGB", "policy": "rgb_only"},
                {"name": "voi", "label": "VoI", "policy": "selective_rovers_voi", "policy_params": {"min_site_gain": 0.5}},
            ],
        })
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "voi-run"
            comparison = run_benchmark(cfg, out_dir)
            self.assertEqual(len(comparison["variants"]), 2)
            self.assertEqual(comparison["variants"][1]["policy"], "selective_rovers_voi")
            self.assertTrue((out_dir / "voi" / "mission.json").is_file())


if __name__ == "__main__":
    unittest.main()
