"""Matched semantic ablation on structural fixtures; run with python -m and --output FILE."""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from phdsim.belief.semantic_terrain import (
    MODES, Capture, CellFeatures, Grid, Sample, TerrainClassifier, extract_features,
)
from phdsim.core.randomness import keyed_rng
from phdsim.evaluation.semantic_terrain import semantic_metrics


CLASSES = ("soil", "rock", "vegetation")
FIT_SEEDS = (11, 12, 13)
TEST_SEEDS = (101, 102, 103)


@dataclass(frozen=True)
class Fixture:
    grid: Grid
    captures: tuple[Capture, ...]
    reference: tuple[str, ...]
    hard_patch: tuple[bool, ...]


def make_fixture(seed: int) -> Fixture:
    """Synthetic measured templates, independent of the physical terrain/sensor implementation."""
    grid = Grid(12, 8, 0.5)
    brown, gray, green = (0.48, 0.36, 0.25), (0.57, 0.56, 0.54), (0.29, 0.49, 0.24)
    # Several patches share colour or relief. The final patch overlaps soil in both cues.
    patches = [
        ("soil", brown, 0.01, False), ("soil", brown, 0.03, False),
        ("rock", gray, 0.02, False), ("vegetation", green, 0.16, False),
        ("vegetation", brown, 0.18, True), ("vegetation", brown, 0.02, True),
    ]
    rng = keyed_rng(seed, "semantic-fixture")
    rng.shuffle(patches)
    reference, hard, rgb, lidar = [], [], [], []
    # Both captures cover this rectangle at the same tick. Omitted samples are invalid.
    brightness = rng.uniform(-0.05, 0.05)
    elevation_datum = rng.uniform(-4, 4)
    for y in range(grid.height):
        for x in range(grid.width):
            label, color, relief, difficult = patches[(y // 4) * 3 + x // 4]
            reference.append(label)
            hard.append(difficult)
            channels = tuple(c + brightness + rng.uniform(-0.07, 0.07) for c in color)
            height = elevation_datum + 0.007 * x + ((x + y) % 2) * relief + rng.uniform(-0.015, 0.015)
            if rng.random() > 0.13:
                rgb.append(Sample((x, y), channels))
            if rng.random() > 0.30:
                lidar.append(Sample((x, y), (height,)))
    camera = Capture(f"{seed}-rgb", "camera", "rgb", 0, tuple(rgb))
    scanner = Capture(f"{seed}-lidar", "scanner", "lidar", 0, tuple(lidar))
    return Fixture(grid, (camera, scanner, camera), tuple(reference), tuple(hard))


def compare_observations(grid: Grid, captures: tuple[Capture, ...], model: TerrainClassifier):
    """Runtime entry point. The caller supplies only available captures in a common grid frame."""
    features = extract_features(grid, captures)
    return {mode: model.predict(features, mode) for mode in MODES}


def run_fixture_comparison(fit_seeds=FIT_SEEDS, test_seeds=TEST_SEEDS) -> dict:
    fit_seeds, test_seeds = tuple(fit_seeds), tuple(test_seeds)
    all_seeds = fit_seeds + test_seeds
    if not fit_seeds or not test_seeds or len(set(all_seeds)) != len(all_seeds):
        raise ValueError("provide nonempty fitting and test splits with unique, disjoint seeds")
    examples: list[tuple[str, CellFeatures]] = []
    for seed in fit_seeds:
        scene = make_fixture(seed)
        features = extract_features(scene.grid, scene.captures)
        examples.extend(zip(scene.reference, features, strict=True))
    model = TerrainClassifier.fit(CLASSES, examples)

    scenes, reference, hard, common = [], [], [], []
    pooled = {mode: [] for mode in MODES}
    for seed in test_seeds:
        scene = make_fixture(seed)
        maps = compare_observations(scene.grid, scene.captures, model)
        reference.extend(scene.reference)
        hard.extend(scene.hard_patch)
        common.extend(a is not None and b is not None
                      for a, b in zip(maps["rgb"], maps["lidar"], strict=True))
        for mode in MODES:
            pooled[mode].extend(maps[mode])
        scenes.append({
            "seed": seed, "grid": asdict(scene.grid),
            "deliveries": [capture.observation_id for capture in scene.captures],
            "captures": [asdict(c) for c in dict.fromkeys(scene.captures)],
            "offline_reference": {"labels": scene.reference, "hard_patch": scene.hard_patch},
            "maps": {mode: [asdict(p) if p is not None else None for p in maps[mode]] for mode in MODES},
        })
    masks = {"whole_map": None, "paired_support": common, "hard_patch": hard}
    metrics = {region: {mode: semantic_metrics(CLASSES, reference, pooled[mode], mask) for mode in MODES}
               for region, mask in masks.items()}
    return {
        "source": "structural fixture", "fit_seeds": fit_seeds, "test_seeds": test_seeds,
        "model": asdict(model), "metrics": metrics, "scenes": scenes,
        "assumptions": (
            "Stationary registered terrain. Fixture appearance and relief overlap across classes. "
            "RGB brightness is shared within a capture. No coupled RGB/LiDAR noise model. "
            "Class probabilities use uniform priors and conditionally independent Gaussian features "
            "without post-fit calibration. Probability order follows model.classes."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New JSON file for the comparison")
    parser.add_argument("--fit-seeds", type=int, nargs="+", default=FIT_SEEDS)
    parser.add_argument("--test-seeds", type=int, nargs="+", default=TEST_SEEDS)
    args = parser.parse_args()
    result = run_fixture_comparison(args.fit_seeds, args.test_seeds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, allow_nan=False, indent=2)
        fp.write("\n")
    for mode, row in result["metrics"]["whole_map"].items():
        print(f"{mode:5}  correct {row['correct']}/{row['cells']}  resolved {row['resolved']}/{row['cells']}")


if __name__ == "__main__":
    main()
