"""Evaluate alternative map completion rules on identical observation traces."""

from dataclasses import asdict
import hashlib
import json
from math import ceil
from pathlib import Path
from statistics import mean

from phdsim.decision.acquisition.elevation import ElevationPlanner
from phdsim.environments.elevation import generate_world
from phdsim.simulation.elevation import fixed_schedule, initial_belief, simulate
from .elevation import load_config
from .provenance import source_identity


def premature_score(trace: list[dict], goal: float) -> float:
    """Largest predicted coverage reached while reference quality was still below target."""
    return max((row["expected_coverage"] for row in trace if row["actual_fraction"] < goal), default=0.0)


def calibrate_threshold(traces: list[list[dict]], goal: float, risk: float) -> float:
    scores = sorted(premature_score(trace, goal) for trace in traces)
    rank = ceil((len(scores) + 1) * (1 - risk))
    # A threshold of 1 rejects every possible score under the strict comparison.
    return scores[rank - 1] if rank <= len(scores) else 1.0


def stopping_outcomes(trace: list[dict], goal: float, threshold: float) -> dict:
    rules = {
        "pointwise": lambda row: row["estimated_qualified_fraction"] >= goal,
        "expected_coverage": lambda row: row["expected_coverage"] >= goal,
        "calibrated_coverage": lambda row: row["expected_coverage"] >= goal
        and row["expected_coverage"] > threshold,
    }
    outcomes = {}
    for name, can_stop in rules.items():
        stop = next((row for row in trace if can_stop(row)), None)
        outcomes[name] = {"tick": stop["tick"] if stop else None,
                          "verified": stop is not None and stop["actual_fraction"] >= goal,
                          "actual_fraction": stop["actual_fraction"] if stop else None}
    return outcomes


def aggregate_runs(runs: list[dict], time_budget: int) -> dict:
    summary = {}
    for rule in runs[0]["outcomes"]:
        outcomes = [run["outcomes"][rule] for run in runs]
        declared = sum(outcome["tick"] is not None for outcome in outcomes)
        verified = sum(outcome["verified"] for outcome in outcomes)
        both_verified = [(run["outcomes"]["pointwise"]["tick"], outcome["tick"])
                         for run, outcome in zip(runs, outcomes, strict=True)
                         if run["outcomes"]["pointwise"]["verified"] and outcome["verified"]]
        summary[rule] = {
            "declared": declared, "verified": verified, "premature": declared - verified,
            "premature_fraction_of_missions": (declared - verified) / len(runs),
            "premature_fraction_of_declarations": (declared - verified) / declared if declared else None,
            "mean_tick_verified_only": mean(o["tick"] for o in outcomes if o["verified"]) if verified else None,
            "mean_tick_unverified_charged_budget": mean(
                o["tick"] if o["verified"] else time_budget for o in outcomes),
            "both_verified_with_pointwise": len(both_verified),
            "mean_ticks_earlier_when_both_verified": mean(a - b for a, b in both_verified)
            if both_verified else None,
        }
    return summary


def run_stopping_experiment(config_path: Path, output: Path, test_seeds: list[int],
                            calibration_seeds: list[int], risk: float = 0.05) -> None:
    if not test_seeds or not calibration_seeds:
        raise ValueError("Provide nonempty test and calibration splits")
    combined = [*test_seeds, *calibration_seeds]
    if len(set(combined)) != len(combined):
        raise ValueError("Calibration and test seeds must be unique and disjoint")
    if not 0 < risk < 1:
        raise ValueError("Mission risk must be between 0 and 1")
    config, raw = load_config(config_path)
    output.mkdir(parents=True, exist_ok=False)
    planner = ElevationPlanner(config.time_budget, config.tolerance_m, config.confidence)
    policies = {"fixed": False, "adaptive": True}

    def collect(seeds):
        for seed in seeds:
            world = generate_world(seed, config.poor_probability)
            schedule = fixed_schedule(config, planner, initial_belief(world.coarse_m))
            for policy, adaptive in policies.items():
                trace = simulate(world, config, planner, schedule, seed, adaptive=adaptive,
                                 stop_on_quality=False)["trace"]
                yield policy, seed, trace

    calibration = {policy: [] for policy in policies}
    for policy, seed, trace in collect(calibration_seeds):
        calibration[policy].append(trace)
    thresholds = {policy: calibrate_threshold(traces, config.coverage, risk)
                  for policy, traces in calibration.items()}

    runs = {policy: [] for policy in policies}
    with (output / "test_traces.jsonl").open("w") as file:
        for policy, seed, trace in collect(test_seeds):
            run = {"seed": seed, "outcomes": stopping_outcomes(trace, config.coverage, thresholds[policy]),
                   "earliest_actual_goal_tick": next((row["tick"] for row in trace
                                                      if row["actual_fraction"] >= config.coverage), None)}
            runs[policy].append(run)
            file.write(json.dumps({"policy": policy, **run, "trace": trace}, allow_nan=False) + "\n")

    provenance = source_identity(extra_sources=("cli/scout_elevation.py", "evaluation/elevation.py"))
    provenance["config_sha256"] = hashlib.sha256(raw).hexdigest()
    report = {"provenance": provenance, "config": asdict(config), "risk": risk,
              "calibration_seeds": calibration_seeds, "test_seeds": test_seeds,
              "policies": {policy: {"threshold": thresholds[policy],
                                    "calibration_maxima": [premature_score(t, config.coverage)
                                                           for t in calibration[policy]],
                                    "actual_goal_reached_at_some_point": sum(
                                        run["earliest_actual_goal_tick"] is not None for run in cases),
                                    "aggregate": aggregate_runs(cases, config.time_budget)}
                           for policy, cases in runs.items()}}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for policy, result in report["policies"].items():
        print(f'{policy}: calibrated threshold {result["threshold"]:.4f}')
        for rule, metric in result["aggregate"].items():
            print(f'  {rule}: {metric["verified"]}/{len(test_seeds)} verified, '
                  f'{metric["premature"]} premature, '
                  f'{metric["mean_tick_unverified_charged_budget"]:.2f} ticks with failures charged full budget')
