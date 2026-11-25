"""Uncertainty-based reference policy for semantic mapping with aerial views."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import dist, fsum, isfinite, log2

from phdsim.belief.semantic_terrain import Prediction
from phdsim.core.grid import Cell
from phdsim.planning.coverage_sweep import CaptureSite, Plot, SweepRobot
from phdsim.planning.x500_trajectory import FlightProfile, x500_flight
from phdsim.sensors.semantic_terrain import CapturePose, footprint_bounds, nadir_footprint_side


INITIAL_ALTITUDE_M = 3.0
DEFAULT_DRONE_FOV_DEG = 60.0


@dataclass(frozen=True)
class AerialSettings:
    altitudes_m: tuple[float, ...] = (2.0, 6.0)
    fov_deg: float = DEFAULT_DRONE_FOV_DEG
    initial_altitude_m: float = INITIAL_ALTITUDE_M
    time_budget: int = 21

    def __post_init__(self):
        if (not self.altitudes_m or len(set(self.altitudes_m)) != len(self.altitudes_m)
                or any(not isfinite(value) or value <= 0 for value in self.altitudes_m)):
            raise ValueError("provide distinct, positive and finite aerial altitudes")
        if not 0 < self.fov_deg < 180:
            raise ValueError("aerial FOV must be between 0 and 180 degrees")
        if not isfinite(self.initial_altitude_m) or self.initial_altitude_m <= 0:
            raise ValueError("initial aerial altitude must be positive and finite")
        if type(self.time_budget) is not int or self.time_budget < 1:
            raise ValueError("the aerial time budget must be a positive integer")


@dataclass(frozen=True)
class AerialView:
    site: CaptureSite
    standoff_m: float
    nominal_footprint_wh: Cell
    cell_indices: tuple[int, ...]


@dataclass(frozen=True)
class AerialTransit:
    origin_xy: Cell
    origin_altitude_m: float
    profile: FlightProfile


@dataclass(frozen=True)
class AerialAssignment:
    agent_id: str
    view: AerialView
    finish_tick: int
    energy: float
    transit: AerialTransit


def footprint_indices(rectangle: tuple[int, int, int, int], width: int) -> tuple[int, ...]:
    x, y, w, h = rectangle
    return tuple(row * width + column for row in range(y, y + h) for column in range(x, x + w))


def cell_uncertainty(estimate: Prediction | None) -> float:
    """Normalize class entropy to the same scale as a cell without evidence."""
    if estimate is None:
        return 1.0
    probabilities = estimate.probabilities
    if len(probabilities) == 1:
        return 0.0
    entropy = -fsum(p * log2(p) for p in probabilities if p > 0.0)
    return entropy / log2(len(probabilities))


class AerialPlanner:
    def __init__(self, plot: Plot, drones: tuple[SweepRobot, ...], settings: AerialSettings):
        self.plot = plot
        self.drones = drones
        self.settings = settings
        self.min_altitude = min(settings.altitudes_m)
        self.views = self._build_views()
        self.positions = {drone.agent_id: (drone.start_xy, settings.initial_altitude_m) for drone in drones}
        self.energy_reserved = dict.fromkeys(self.positions, 0.0)
        self.best_detail = [0.0] * (plot.width * plot.height)

    def _build_views(self) -> tuple[AerialView, ...]:
        views = []
        for altitude in self.settings.altitudes_m:
            side = nadir_footprint_side(altitude, self.settings.fov_deg, self.plot.cell_size_m)
            nominal_size = (side, side)
            for y in range(self.plot.height):
                for x in range(self.plot.width):
                    rectangle, _ = footprint_bounds(self.plot.width, self.plot.height,
                                                    CapturePose(x, y, altitude), nominal_size)
                    views.append(AerialView(CaptureSite((x, y), rectangle), altitude, nominal_size,
                                            footprint_indices(rectangle, self.plot.width)))
        return tuple(views)

    def record_samples(self, standoff_m: float, cells: Iterable[Cell]) -> None:
        """Track the finest aerial sampling scale received for each cell."""
        detail = self.min_altitude / standoff_m
        for x, y in cells:
            index = y * self.plot.width + x
            self.best_detail[index] = max(self.best_detail[index], detail)

    def dispatch(self, tick: int, estimates: tuple[Prediction | None, ...],
                 pending: tuple[tuple[str, tuple[int, int, int, int]], ...]) -> list[AerialAssignment]:
        """Rank feasible views using delivered evidence and already committed work."""
        uncertainty = [cell_uncertainty(estimate) for estimate in estimates]
        busy = {agent for agent, _ in pending}
        for _, rectangle in pending:
            for index in footprint_indices(rectangle, self.plot.width):
                uncertainty[index] *= 0.5

        assignments = []
        for drone in self.drones:
            if drone.agent_id in busy:
                continue
            selected = self._best_view(drone, tick, uncertainty)
            if selected is not None:
                assignments.append(selected)
                self.positions[drone.agent_id] = (selected.view.site.xy, selected.view.standoff_m)
                self.energy_reserved[drone.agent_id] += selected.energy
                for index in selected.view.cell_indices:
                    uncertainty[index] *= 0.5
        return assignments

    def _best_view(self, drone: SweepRobot, tick: int, uncertainty: list[float]) -> AerialAssignment | None:
        position, altitude = self.positions[drone.agent_id]
        best, best_score = None, (0.0, 0.0)
        for view in self.views:
            horizontal = dist(position, view.site.xy) * self.plot.cell_size_m
            climb = view.standoff_m - altitude
            profile = x500_flight(horizontal, climb)
            duration = profile.travel_ticks + drone.capture_ticks
            charge = (horizontal + abs(climb)) * drone.move_energy_per_m + drone.capture_energy
            if tick + duration > self.settings.time_budget:
                continue
            if self.energy_reserved[drone.agent_id] + charge > drone.energy_budget:
                continue
            detail = self.min_altitude / view.standoff_m
            gain = sum(uncertainty[index] * max(0.0, detail - self.best_detail[index])
                       for index in view.cell_indices) / duration
            score = (gain, -charge)
            if score > best_score:
                best_score = score
                transit = AerialTransit(position, altitude, profile)
                best = AerialAssignment(drone.agent_id, view, tick + duration, charge, transit)
        return best
