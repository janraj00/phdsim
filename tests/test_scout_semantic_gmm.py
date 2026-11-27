"""Tests for the plug-in SemanticEstimator protocol and JointGMMClassifier."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.belief.semantic_gmm import JointGMMClassifier
from phdsim.belief.semantic_terrain import (
    CellFeatures,
    Feature,
    Mode,
    Prediction,
    SemanticEstimator,
    TerrainClassifier,
)
from phdsim.environments.semantic_terrain import TerrainConfig
from phdsim.experiments.scout.semantic_mission import fit_classifier, main, semantic_replay


def _paired(rgb, lidar, obs_prefix="obs"):
    return CellFeatures(
        Feature(tuple(rgb), (f"{obs_prefix}-rgb",)),
        Feature((lidar,), (f"{obs_prefix}-lidar",)),
    )


class JointGMMClassifierTests(unittest.TestCase):
    def test_both_classifiers_implement_plug_in_protocol(self):
        examples = [
            ("soil", _paired((0.3, 0.25, 0.2), 0.02, "s1")),
            ("soil", _paired((0.32, 0.27, 0.22), 0.03, "s2")),
            ("rock", _paired((0.65, 0.62, 0.58), 0.02, "r1")),
            ("rock", _paired((0.31, 0.26, 0.21), 0.35, "r2")),
        ]
        gaussian = TerrainClassifier.fit(("soil", "rock"), examples)
        gmm = JointGMMClassifier.fit(("soil", "rock"), examples, n_components=2)
        self.assertIsInstance(gaussian, SemanticEstimator)
        self.assertIsInstance(gmm, SemanticEstimator)

    def test_joint_mixture_preserves_bright_flat_rock_and_disambiguates_dark_rough_rock(self):
        examples = []
        for i in range(12):
            delta = (i - 5.5) * 0.004
            # Soil is dark and flat.
            examples.append(("soil", _paired((0.32 + delta, 0.28 + delta, 0.23 + delta), 0.02 + abs(delta), f"s{i}")))
            # Rock has two distinct joint modes: bright+flat AND dark+rough.
            examples.append(("rock", _paired((0.64 + delta, 0.61 + delta, 0.55 + delta), 0.02 + abs(delta), f"rb{i}")))
            examples.append(("rock", _paired((0.32 + delta, 0.28 + delta, 0.23 + delta), 0.32 + abs(delta), f"rd{i}")))

        gmm = JointGMMClassifier.fit(("soil", "rock"), examples, n_components=2, seed=7)
        gmm_repeat = JointGMMClassifier.fit(("soil", "rock"), examples, n_components=2, seed=7)
        self.assertEqual(gmm, gmm_repeat)

        probe = (
            _paired((0.64, 0.61, 0.55), 0.02, "bright-flat"),
            _paired((0.32, 0.28, 0.23), 0.32, "dark-rough"),
            _paired((0.32, 0.28, 0.23), 0.02, "dark-flat"),
            CellFeatures(Feature((0.64, 0.61, 0.55), ("rgb-only",)), None),
            CellFeatures(None, Feature((0.32,), ("lidar-only",))),
            CellFeatures(None, None),
        )

        fused = gmm.predict(probe, "fused")
        self.assertEqual(fused[0].label, "rock")
        self.assertEqual(fused[1].label, "rock")
        self.assertEqual(fused[2].label, "soil")
        self.assertEqual(fused[3].label, "rock")
        self.assertEqual(fused[4].label, "rock")
        self.assertIsNone(fused[5])
        self.assertEqual(fused[0].observation_ids, ("bright-flat-lidar", "bright-flat-rgb"))
        for pred in fused[:5]:
            self.assertAlmostEqual(sum(pred.probabilities), 1.0, places=9)
            self.assertTrue(all(0.0 <= p <= 1.0 for p in pred.probabilities))

        rgb_only = gmm.predict(probe, "rgb")
        self.assertEqual(rgb_only[0].label, "rock")
        self.assertEqual(rgb_only[3].observation_ids, ("rgb-only",))
        self.assertIsNone(rgb_only[4])

        lidar_only = gmm.predict(probe, "lidar")
        self.assertIsNone(lidar_only[3])
        self.assertEqual(lidar_only[4].label, "rock")
        self.assertEqual(lidar_only[4].observation_ids, ("lidar-only",))

    def test_validation_rejects_bad_configs_and_inputs(self):
        valid = [
            ("soil", _paired((0.3, 0.25, 0.2), 0.02)),
            ("rock", _paired((0.6, 0.6, 0.5), 0.25)),
        ]
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit((), valid)
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit(("soil", "soil"), valid)
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit(("soil", "rock"), valid, n_components=0)
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit(("soil", "rock"), valid, n_iters=0)
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit(("soil", "rock"), [("soil", _paired((0.3, 0.25, 0.2), 0.02))])
        with self.assertRaises(ValueError):
            JointGMMClassifier.fit(("soil", "rock"), [("unknown", _paired((0.3, 0.25, 0.2), 0.02))])

        model = JointGMMClassifier.fit(("soil", "rock"), valid, n_components=1)
        with self.assertRaises(ValueError):
            model.predict([CellFeatures(None, None)], "thermal")  # type: ignore[arg-type]

    def test_mission_accepts_arbitrary_plug_in_estimator_and_cli_gmm(self):
        class ConstantPlugInEstimator:
            classes = ("exposed_soil", "rock", "low_vegetation")

            def predict(self, cells, mode: Mode):
                out = []
                for cell in cells:
                    has_rgb = cell.rgb is not None and mode in ("rgb", "fused")
                    has_lidar = cell.lidar is not None and mode in ("lidar", "fused")
                    if not has_rgb and not has_lidar:
                        out.append(None)
                        continue
                    ids = tuple(sorted(
                        set(cell.rgb.observation_ids if has_rgb else ())
                        | set(cell.lidar.observation_ids if has_lidar else ())
                    ))
                    out.append(Prediction("rock", (0.2, 0.5, 0.3), ids))
                return tuple(out)

        config = TerrainConfig()
        estimator = ConstantPlugInEstimator()
        self.assertIsInstance(estimator, SemanticEstimator)
        replay, summary = semantic_replay(2021, estimator, config, selective_rovers=True)
        self.assertEqual(replay["schema"], "scout-replay-v1")
        self.assertGreater(summary["metrics"]["whole_map"]["fused"]["resolved"], 0)

        gmm = fit_classifier(config, (11, 12, 13), classifier="gmm", gmm_components=3)
        self.assertIsInstance(gmm, JointGMMClassifier)

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "gmm-run"
            main([
                "--output", str(out_dir),
                "--fit-seeds", "11", "12", "13",
                "--test-seeds", "2021",
                "--selective-rovers",
                "--classifier", "gmm",
                "--gmm-components", "3",
            ])
            report = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            mission = json.loads((out_dir / "mission.json").read_text(encoding="utf-8"))
            self.assertEqual(report["classifier"], "gmm")
            self.assertEqual(report["gmm_components"], 3)
            self.assertEqual(mission["schema"], "scout-replay-v1")
            self.assertEqual(len(mission["agents"]), 4)


if __name__ == "__main__":
    unittest.main()
