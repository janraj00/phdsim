"""Choose feasible elevation observations from reported or forecast precision."""

from dataclasses import dataclass, replace
from math import ceil, dist

from phdsim.belief.elevation import ElevationTile, probability_within
from phdsim.core.grid import Cell
from phdsim.sensors.elevation import ElevationView, candidate_views


@dataclass(frozen=True)
class Robot:
    position: tuple[float, float]
    energy: float
    speed: float
    energy_per_m: float
    modes: tuple[str, ...]


@dataclass(frozen=True)
class Assignment:
    robot: str
    view: ElevationView
    start: int
    finish: int
    energy: float


@dataclass(frozen=True)
class ForecastTile:
    clear_precision: float
    poor_precision: float
    poor_probability: float


def forecast_from_belief(belief: dict[Cell, ElevationTile], poor_probability: float
                         ) -> dict[Cell, ForecastTile]:
    return {cell: ForecastTile(tile.precision, tile.precision,
                               poor_probability if tile.poor_imaging is None else float(tile.poor_imaging))
            for cell, tile in belief.items()}


def project(forecast: dict[Cell, ForecastTile], view: ElevationView) -> None:
    for part in view.footprint:
        previous = forecast[part.tile]
        forecast[part.tile] = replace(previous,
                                      clear_precision=previous.clear_precision + part.clear_precision,
                                      poor_precision=previous.poor_precision + part.poor_precision)


def reserve(robots: dict[str, Robot], action: Assignment) -> None:
    robot = robots[action.robot]
    robots[action.robot] = replace(robot, position=action.view.pose, energy=robot.energy - action.energy)


class ElevationPlanner:
    def __init__(self, time_budget: int, tolerance_m: float, confidence: float):
        self.time_budget = time_budget
        self.tolerance_m = tolerance_m
        self.confidence = confidence
        self.views = {mode: candidate_views(mode) for mode in ("ground", "low", "high")}

    def gains(self, view: ElevationView, forecast: dict[Cell, ForecastTile]) -> tuple[float, float]:
        qualified_gain = probability_gain = 0.0
        for part in view.footprint:
            current = forecast[part.tile]
            for weight, precision, extra in (
                (1 - current.poor_probability, current.clear_precision, part.clear_precision),
                (current.poor_probability, current.poor_precision, part.poor_precision),
            ):
                if weight == 0:
                    continue
                before = probability_within(precision, self.tolerance_m)
                if before >= self.confidence:
                    continue
                after = probability_within(precision + extra, self.tolerance_m)
                qualified_gain += weight * (after >= self.confidence)
                probability_gain += weight * (min(after, self.confidence) - before)
        return qualified_gain, probability_gain

    def dispatch(self, tick: int, robots: dict[str, Robot], busy: set[str],
                 forecast: dict[Cell, ForecastTile]) -> list[Assignment]:
        """Add commitments to the forecast so successive picks share their expected coverage."""
        available = {name: robot for name, robot in robots.items() if name not in busy}
        actions = []
        while available:
            best, best_score = None, (0.0, 0.0, 0.0)
            for name, robot in available.items():
                for mode in robot.modes:
                    capture_ticks, capture_energy = {"ground": (1, 1.0), "low": (2, 2.0),
                                                     "high": (3, 3.0)}[mode]
                    for view in self.views[mode]:
                        distance = dist(robot.position, view.pose)
                        duration = ceil(distance / robot.speed) + capture_ticks
                        charge = distance * robot.energy_per_m + capture_energy
                        if tick + duration > self.time_budget or charge > robot.energy:
                            continue
                        qualified, probability = self.gains(view, forecast)
                        score = (qualified / duration, probability / duration, -charge)
                        if score > best_score:
                            best_score = score
                            best = Assignment(name, view, tick, tick + duration, charge)
            if best is None:
                break
            actions.append(best)
            del available[best.robot]
            project(forecast, best.view)
            reserve(robots, best)
        return actions
