"""Tests for minimal config-driven SCOUT semantic benchmarks."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.cli.scout_bench import main as bench_cli_main
from phdsim.environments.semantic_terrain import TerrainConfig, generate_terrain
from phdsim.experiments.scout.bench_config import FleetSpec, VariantSpec, load_bench_config, parse_bench_config
from phdsim.experiments.scout.bench_runner import CLASSIFIER_REGISTRY, POLICY_REGISTRY, run_variant_seed
from phdsim.experiments.scout.semantic_mission import fit_classifier, semantic_replay
from phdsim.sensors.semantic_terrain import CaptureConditions


REPO_ROOT = Path(__file__).resolve().parents[1]
PRESET_CONFIG = REPO_ROOT / "configs" / "scout" / "bench_2uav_2ugv.json"


class ScoutBenchTests(unittest.TestCase):
    def test_preset_config_and_validation_rules(self):
        cfg = load_bench_config(PRESET_CONFIG)
        self.assertEqual(cfg.name, "bench-2uav-2ugv")
        self.assertEqual(len(cfg.variants), 5)
        self.assertTrue(len(cfg.seeds.cal) > 0)

        with self.assertRaises(ValueError):
            parse_bench_config({
                "name": "bad-overlap",
                "seeds": {"fit": [1, 2], "test": [2, 3]},
                "variants": [{"name": "v1", "label": "V1", "policy": "rgb_only"}],
            })

        with self.assertRaises(ValueError):
            parse_bench_config({
                "name": "dup-variant",
                "seeds": {"fit": [1], "test": [2]},
                "variants": [
                    {"name": "same", "label": "A", "policy": "rgb_only"},
                    {"name": "same", "label": "B", "policy": "rgb_only"},
                ],
            })

        agri_cfg = parse_bench_config({
            "name": "agri-smoke",
            "terrain": {"profile": "agri", "width": 16, "height": 12, "cell_size_m": 0.5},
            "seeds": {"fit": [1, 2], "test": [10]},
            "variants": [{"name": "rgb", "label": "RGB", "policy": "rgb_only"}],
        })
        terrain_cfg = agri_cfg.terrain.to_terrain_config()
        self.assertEqual(tuple(c.name for c in terrain_cfg.classes), ("exposed_soil", "gravel", "low_vegetation"))

    def test_selective_rovers_matches_semantic_mission_exactly(self):
        config = TerrainConfig()
        model = fit_classifier(config, (11, 12, 13), classifier="gaussian")
        _, ref_summary = semantic_replay(2021, model, config, selective_rovers=True)

        terrain = generate_terrain(2021, config)
        shade = frozenset((x, y) for x in range(2, 5) for y in range(2, 4))
        variant = VariantSpec(name="sel", label="Selective", policy="selective_rovers_entropy")
        replay, bench_summary = run_variant_seed(
            2021, terrain, model, variant, FleetSpec(), CaptureConditions(occluded_cells=shade), record_replay=True,
        )
        self.assertIsNotNone(replay)
        self.assertEqual(replay["schema"], "scout-replay-v1")
        self.assertAlmostEqual(
            bench_summary["accuracy_whole_area"],
            ref_summary["metrics"]["whole_map"]["fused"]["accuracy_whole_area"],
            places=9,
        )
        expected_rover_energy = ref_summary["energy_reserved"]["rover-1"] + ref_summary["energy_reserved"]["rover-2"]
        self.assertAlmostEqual(bench_summary["rover_energy"], expected_rover_energy, places=9)

    def test_cli_bench_exports_reports_csv_and_studio_replays(self):
        self.assertIn("gmm", CLASSIFIER_REGISTRY)
        self.assertIn("selective_rovers_entropy", POLICY_REGISTRY)
        self.assertIn("selective_rovers_voi", POLICY_REGISTRY)

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "bench-run"
            bench_cli_main([
                "--config", str(PRESET_CONFIG),
                "--test-seeds", "2021",
                "--output", str(out_dir),
            ])
            comparison = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(comparison["schema"], "scout-bench-v1")
            self.assertEqual(len(comparison["variants"]), 5)
            self.assertEqual(len(comparison["replays"]), 5)

            with (out_dir / "summary.csv").open(encoding="utf-8") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 5)

            replay = json.loads((out_dir / "selective_voi_05" / "mission.json").read_text(encoding="utf-8"))
            self.assertEqual(replay["schema"], "scout-replay-v1")
            self.assertEqual(len(replay["agents"]), 4)


if __name__ == "__main__":
    unittest.main()
