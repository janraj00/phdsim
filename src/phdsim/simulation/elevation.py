"""A concurrent elevation-mapping experiment with exact poses and immediate sharing."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from phdsim.belief.elevation import ElevationTile, expected_coverage, qualified_fraction
from phdsim.core.grid import Cell
from phdsim.decision.acquisition.elevation import (
    Assignment, ElevationPlanner, Robot, forecast_from_belief, project, reserve,
)
from phdsim.environments.elevation import PRIOR_STD_M, ElevationWorld
from phdsim.evaluation.elevation import elevation_metrics
from phdsim.sensors.elevation import measure


@dataclass(frozen=True)
class MappingConfig:
    time_budget: int = 60
    aerial_energy: float = 90
    ground_energy: float = 40
    tolerance_m: float = 0.25
    confidence: float = 0.90
    coverage: float = 0.85
    poor_probability: float = 0.30


def initial_fleet(config: MappingConfig) -> dict[str, Robot]:
    return {"drone-1": Robot((1.5, 1.5), config.aerial_energy, 5, 0.8, ("low", "high")),
            "drone-2": Robot((29.5, 29.5), config.aerial_energy, 5, 0.8, ("low", "high")),
            "rover": Robot((15.5, 15.5), config.ground_energy, 2, 0.35, ("ground",))}


def initial_belief(coarse_m: dict[Cell, tuple[float, ...]]) -> dict[Cell, ElevationTile]:
    return {cell: ElevationTile(heights, PRIOR_STD_M**-2) for cell, heights in coarse_m.items()}


def fixed_schedule(config: MappingConfig, planner: ElevationPlanner,
                   belief: dict[Cell, ElevationTile]) -> list[Assignment]:
    """Build the full schedule before launch using the same scorer as replanning."""
    robots = initial_fleet(config)
    forecast = forecast_from_belief(belief, config.poor_probability)
    schedule, active = [], []
    tick = 0
    while True:
        active = [item for item in active if item.finish > tick]
        new = planner.dispatch(tick, robots, {item.robot for item in active}, forecast)
        schedule.extend(new)
        active.extend(new)
        if not active:
            return schedule
        tick = min(item.finish for item in active)


def simulate(world: ElevationWorld, config: MappingConfig, planner: ElevationPlanner,
             schedule: list[Assignment], seed: int, *, adaptive: bool, stop_on_quality: bool = True) -> dict:
    robots, belief = initial_fleet(config), initial_belief(world.coarse_m)
    by_start = defaultdict(list)
    for action in schedule:
        by_start[action.start].append(action)

    active: list[tuple[Assignment, int]] = []
    attempts = Counter()
    events, snapshots = [], []
    tick = 0
    declared_tick = None
    while True:
        completed = [item for item in active if item[0].finish == tick]
        active = [item for item in active if item[0].finish > tick]
        for action, attempt in completed:
            readings = measure(world, action.view, seed, attempt)
            for reading in readings:
                belief[reading.tile] = belief[reading.tile].update(reading)
            events.append({"event": "measurement", "tick": tick, "robot": action.robot,
                           "mode": action.view.mode, "anchor": action.view.anchor,
                           "tiles": [{"tile": r.tile, "poor_imaging": r.poor_imaging,
                                      "precision": r.precision} for r in readings]})

        # The controller stops on its own map. Evaluate reference error after the run.
        estimated = qualified_fraction(belief, config.tolerance_m, config.confidence)
        snapshots.append((tick, estimated, belief.copy()))
        if stop_on_quality and estimated >= config.coverage:
            declared_tick = tick
            break
        if tick == config.time_budget:
            break

        if adaptive and tick > 0:
            forecast = forecast_from_belief(belief, config.poor_probability)
            for assignment, _ in active:
                project(forecast, assignment.view)
            new = planner.dispatch(tick, robots, {item.robot for item, _ in active}, forecast)
        else:
            new = by_start[tick]
            for assignment in new:
                reserve(robots, assignment)
        for assignment in new:
            key = assignment.view.mode, assignment.view.anchor
            attempts[key] += 1
            active.append((assignment, attempts[key]))
            events.append({"event": "dispatch", "tick": tick, "robot": assignment.robot,
                           "mode": assignment.view.mode, "anchor": assignment.view.anchor,
                           "finish": assignment.finish, "energy": assignment.energy})
        if not active:
            break
        tick = min(item.finish for item, _ in active)

    trace = [{"tick": time, "estimated_qualified_fraction": estimated,
              **elevation_metrics(snapshot, world.truth_m, config.tolerance_m)}
             for time, estimated, snapshot in snapshots]
    if not stop_on_quality:
        for entry, (_, _, snapshot) in zip(trace, snapshots, strict=True):
            entry["expected_coverage"] = expected_coverage(snapshot, config.tolerance_m)
    verified = declared_tick is not None and trace[-1]["actual_fraction"] >= config.coverage
    status = "quality_declared" if declared_tick is not None else (
        "time_budget" if tick == config.time_budget else "no_feasible_gain")
    initial = initial_fleet(config)
    final_map = [{"tile": cell, "heights_m": tile.heights_m, "precision": tile.precision,
                  "poor_imaging": tile.poor_imaging} for cell, tile in belief.items()]
    return {"trace": trace, "events": events, "final_map": final_map, "summary": {
        "policy": "adaptive" if adaptive else "fixed", "seed": seed,
        "status": status,
        "declared_tick": declared_tick, "elapsed_ticks": tick,
        "verified_at_declaration": verified,
        "premature_declaration": declared_tick is not None and not verified,
        "energy_reserved": {name: initial[name].energy - state.energy for name, state in robots.items()},
        "pending_measurements": len(active), "completed_measurements": sum(
            event["event"] == "measurement" for event in events),
        **{key: value for key, value in trace[-1].items() if key != "tick"},
    }}
