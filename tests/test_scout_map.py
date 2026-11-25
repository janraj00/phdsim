import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.cli import main
from phdsim.cli.scout_map import load_config, make_replay


EXAMPLE = Path(__file__).resolve().parents[1] / "configs/scout/map.json"


class ScoutMapTests(unittest.TestCase):
    def test_example_export(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "maps/demo.json"
            args = ["scout-map", "--config", str(EXAMPLE), "--output", str(output)]
            main(args)
            saved = output.read_bytes()
            main(args)
            self.assertEqual(saved, output.read_bytes())
            replay = json.loads(saved)
        self.assertEqual(replay["schema"], "scout-replay-v1")
        self.assertEqual(replay["grid"], {"width": 80, "height": 60, "cell_size_m": 0.5})
        layers = replay["frames"][0]["layers"]
        self.assertEqual(Counter(layers["terrain"]), {0: 2640, 1: 480, 2: 1680})
        self.assertTrue(all(s >= g for s, g in zip(layers["surface"], layers["ground"], strict=True)))
        kind, seed, config, _ = load_config(EXAMPLE)
        other = make_replay(kind, seed + 1, config)["frames"][0]["layers"]
        self.assertNotEqual(layers["terrain"], other["terrain"])
        self.assertEqual(Counter(layers["terrain"]), Counter(other["terrain"]))

    def test_custom_profile_and_fractional_shares(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            profile_dir = root / "profiles"
            profile_dir.mkdir()
            materials = {name: [{"rgb": [0.5, 0.5, 0.5], "height_m": 0, "roughness_m": 0}]
                         for name in ("dust", "bedrock", "sand", "ice")}
            (profile_dir / "space.json").write_text(json.dumps(materials))
            path = root / "scene.json"
            path.write_text(json.dumps(dict(type="space", seed=1, width=3, height=1, cell_size_m=2,
                                            shares_pct={"bedrock": 37.5, "sand": 25, "dust": 37.5})))
            kind, seed, config, _ = load_config(path)
        counts = make_replay(kind, seed, config)["terrain"]["cell_counts"]
        self.assertEqual(counts, {"dust": 1, "bedrock": 1, "sand": 1, "ice": 0})
        tied = replace(config, width=1, shares_pct=(50, 50, 0, 0))
        self.assertEqual(make_replay(kind, seed, tied)["frames"][0]["layers"]["terrain"], [0])
        with self.assertRaisesRegex(ValueError, "sum to 100"):
            replace(config, shares_pct=(0, 25, 25, 0))
        with self.assertRaises(ValueError):
            replace(config, shares_pct=(-1, 50, 50, 1))
