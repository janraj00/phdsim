"""Run matched fixed and adaptive terrain reconstruction experiments."""

from dataclasses import asdict
import hashlib
import json
from math import isfinite
from pathlib import Path
from statistics import mean

from phdsim.decision.acquisition.elevation import ElevationPlanner
from phdsim.environments.elevation import SIDE, TILE_SIDE, generate_world
from phdsim.simulation.elevation import (
    MappingConfig, fixed_schedule, initial_belief, initial_fleet, simulate,
)
from .elevation_report import coverage_svg
from .provenance import source_identity


def load_config(path: Path) -> tuple[MappingConfig, bytes]:
    raw = path.read_bytes()
    config = MappingConfig(**json.loads(raw))
    if type(config.time_budget) is not int or config.time_budget <= 0:
        raise ValueError("time_budget must be a positive integer")
    for field in ("aerial_energy", "ground_energy", "tolerance_m", "confidence", "coverage", "poor_probability"):
        value = getattr(config, field)
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"{field} must be a finite number")
    if min(config.aerial_energy, config.ground_energy, config.tolerance_m) <= 0:
        raise ValueError("Energy budgets and error tolerance must be positive")
    if not 0 < config.confidence < 1 or not 0 < config.coverage <= 1 or not 0 <= config.poor_probability <= 1:
        raise ValueError("confidence must be in (0, 1), coverage in (0, 1], and poor_probability in [0, 1]")
    return config, raw


def run_experiment(config_path: Path, output: Path, seeds: list[int]) -> None:
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Supply unique paired seeds")
    config, raw = load_config(config_path)
    output.mkdir(parents=True, exist_ok=False)
    planner = ElevationPlanner(config.time_budget, config.tolerance_m, config.confidence)
    groups = {"fixed": [], "adaptive": []}
    for seed in seeds:
        world = generate_world(seed, config.poor_probability)
        schedule = fixed_schedule(config, planner, initial_belief(world.coarse_m))
        for policy, group in groups.items():
            result = simulate(world, config, planner, schedule, seed, adaptive=policy == "adaptive")
            group.append(result)
            summary = result["summary"]
            (output / f"seed-{seed}-{policy}.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
            print(f'{policy} seed={seed}: declared={summary["declared_tick"]}, '
                  f'actual={summary["actual_fraction"]:.1%}, elapsed={summary["elapsed_ticks"]}')
    aggregate = {}
    for policy, group in groups.items():
        runs = [result["summary"] for result in group]
        aggregate[policy] = {
            "declared": sum(run["declared_tick"] is not None for run in runs),
            "verified": sum(run["verified_at_declaration"] for run in runs),
            "premature": sum(run["premature_declaration"] for run in runs),
            "mean_actual_fraction_at_end": mean(run["actual_fraction"] for run in runs),
            "mean_elapsed_ticks_all_runs": mean(run["elapsed_ticks"] for run in runs),
            "mean_ticks_with_unverified_runs_charged_full_budget": mean(
                run["elapsed_ticks"] if run["verified_at_declaration"] else config.time_budget for run in runs),
            "mean_total_energy_reserved": mean(sum(run["energy_reserved"].values()) for run in runs),
            "runs": runs,
        }
    provenance = source_identity(extra_sources=("cli/scout_elevation.py", "evaluation/elevation.py"))
    provenance["config_sha256"] = hashlib.sha256(raw).hexdigest()
    report = {"provenance": provenance, "seeds": seeds, "grid_side": SIDE, "tile_side": TILE_SIDE,
              "config": asdict(config), "fleet": {k: asdict(v) for k, v in initial_fleet(config).items()},
              "aggregate": aggregate}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "coverage.svg").write_text(coverage_svg(groups, config.time_budget, config.coverage))
