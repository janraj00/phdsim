"""Fixed two-robot sweeps over a rectangular, obstacle-free simulation grid.

Coordinates are cell indices (x, y), with y increasing downwards. Each supplied
site is available to either robot and carries its nominal rectangular support.
Routes are open, with both robots available at tick zero. Each move uses the
robot's travel model and each stationary capture takes whole ticks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from heapq import merge
from itertools import groupby, product
from math import ceil, dist, isclose, isfinite
from operator import attrgetter
from typing import Iterable, Sequence

from phdsim.core.grid import Cell


@dataclass(frozen=True)
class Plot:
    width: int
    height: int
    cell_size_m: float

    def __post_init__(self):
        if any(type(n) is not int or n < 1 for n in (self.width, self.height)):
            raise ValueError("plot dimensions must be positive integers")
        if not isfinite(self.cell_size_m) or self.cell_size_m <= 0:
            raise ValueError("cell_size_m must be finite and positive")


@dataclass(frozen=True)
class CaptureSite:
    xy: Cell
    footprint: tuple[int, int, int, int]  # left, top, width, height in cells


@dataclass(frozen=True)
class SweepRobot:
    agent_id: str
    start_xy: Cell
    speed_m_per_tick: float | None
    capture_ticks: int
    move_energy_per_m: float
    capture_energy: float
    energy_budget: float
    move_duration_ticks: Callable[[float], int] | None = None

    def __post_init__(self):
        if not self.agent_id or len(self.start_xy) != 2 or any(
            type(n) is not int for n in self.start_xy
        ):
            raise ValueError("expected an agent ID and integer start coordinates")
        if self.speed_m_per_tick is None:
            if self.move_duration_ticks is None:
                raise ValueError("expected a speed or travel model")
        elif not isfinite(self.speed_m_per_tick) or self.speed_m_per_tick <= 0:
            raise ValueError("speed must be finite and positive")
        if type(self.capture_ticks) is not int or self.capture_ticks < 1:
            raise ValueError("capture_ticks must be a positive integer")
        costs = (self.move_energy_per_m, self.capture_energy, self.energy_budget)
        if any(not isfinite(v) or v < 0 for v in costs):
            raise ValueError("energy costs and budget must be finite and nonnegative")

    def travel_ticks(self, distance_m: float) -> int:
        if self.move_duration_ticks is not None:
            return self.move_duration_ticks(distance_m)
        assert self.speed_m_per_tick is not None
        return ceil(distance_m / self.speed_m_per_tick)


@dataclass(frozen=True)
class Capture:
    site: CaptureSite
    start_tick: int   # depart previous pose (or start_xy)
    arrival_tick: int
    finish_tick: int  # nominal coverage becomes available here
    travel_m: float
    move_energy: float
    capture_energy: float


@dataclass(frozen=True)
class RobotRoute:
    agent_id: str
    captures: tuple[Capture, ...]

    @property
    def finish_tick(self) -> int:
        return self.captures[-1].finish_tick if self.captures else 0

    @property
    def travel_m(self) -> float:
        return sum(c.travel_m for c in self.captures)

    @property
    def energy(self) -> float:
        return sum(c.move_energy + c.capture_energy for c in self.captures)


@dataclass(frozen=True)
class SweepPlan:
    orientation: str
    split: int         # number of strips in the top/left block
    first_block_agent: str
    routes: tuple[RobotRoute, RobotRoute]  # input robot order
    covered_cells: int

    @property
    def makespan_ticks(self) -> int:
        return max(route.finish_tick for route in self.routes)


def regular_sites(plot: Plot, footprint_size: Cell) -> tuple[CaptureSite, ...]:
    """Tile using supplied support dimensions. Shift the last tile to the edge.

    Use the actual tile midpoint rounded toward its top-left cell as the pose.
    A footprint larger than the plot spans the whole plot along that dimension.
    """
    w, h = footprint_size
    if any(type(n) is not int or n < 1 for n in (w, h)):
        raise ValueError("footprint dimensions must be positive integers")
    w, h = min(w, plot.width), min(h, plot.height)
    result = []
    for y in range(0, plot.height, h):
        top = min(y, plot.height - h)
        for x in range(0, plot.width, w):
            left = min(x, plot.width - w)
            xy = (left + (w - 1) // 2, top + (h - 1) // 2)
            result.append(CaptureSite(xy, (left, top, w, h)))
    return tuple(result)


def _support_mask(plot: Plot, site: CaptureSite) -> int:
    x, y = site.xy
    left, top, w, h = site.footprint
    if any(type(n) is not int for n in (x, y, left, top, w, h)):
        raise ValueError("poses and footprints must use integer cell coordinates")
    if not (0 <= x < plot.width and 0 <= y < plot.height):
        raise ValueError("capture pose outside plot")
    if not (0 <= left < left + w <= plot.width and 0 <= top < top + h <= plot.height):
        raise ValueError("expected a nonempty footprint inside the plot")
    row = ((1 << w) - 1) << left
    return sum(row << (i * plot.width) for i in range(top, top + h))


def _route_options(robot, strips, cell_size_m):
    """Trace affordable prefixes from both strip ends and both first-row ends."""
    if not strips:
        return [()]
    options = []
    for reverse_strips in range(2 if len(strips) > 1 else 1):
        ordered = strips[::-1] if reverse_strips else strips
        for reverse_first in range(2 if any(len(s) > 1 for s in strips) else 1):
            sites = (
                site
                for i, strip in enumerate(ordered)
                for site in (reversed(strip) if (i + reverse_first) % 2 else strip)
            )
            options.append(_trace(robot, sites, cell_size_m))
    return options


def _trace(robot, sites, cell_size_m):
    xy, tick, energy = robot.start_xy, 0, 0.0
    captures = []
    for site in sites:
        travel_m = dist(xy, site.xy) * cell_size_m
        move_energy = travel_m * robot.move_energy_per_m
        energy += move_energy + robot.capture_energy
        if energy > robot.energy_budget and not isclose(energy, robot.energy_budget, rel_tol=1e-12):
            break
        arrival = tick + robot.travel_ticks(travel_m)
        finish = arrival + robot.capture_ticks
        captures.append(Capture(site, tick, arrival, finish, travel_m,
                                move_energy, robot.capture_energy))
        xy, tick = site.xy, finish
    return tuple(captures)


def _score(first, second, masks):
    # For two fixed orders, all affordable captures give the largest union.
    # The earliest horizon attaining that union is the last new cell's tick.
    covered = finish = 0
    for capture in merge(first, second, key=attrgetter("finish_tick")):
        updated = covered | masks[capture.site]
        if updated != covered:
            finish = capture.finish_tick
            covered = updated
    return covered.bit_count(), -finish


def plan_coverage_sweep(
    plot: Plot, sites: Iterable[CaptureSite], robots: Sequence[SweepRobot]
) -> SweepPlan:
    """Maximize nominal union, then minimize makespan among sweep prefixes.

    Group sites into rows or columns. Split the ordered strips into two
    contiguous blocks (either may be empty), swap assignments and try every
    corner start independently for each serpentine route. Exact ties keep the
    first candidate: horizontal before vertical, ascending split, input robot
    order for the first block, and increasing coordinates first.
    """
    if len(robots) != 2 or robots[0].agent_id == robots[1].agent_id:
        raise ValueError("expected two robots with distinct IDs")
    sites = tuple(sites)
    masks = {site: _support_mask(plot, site) for site in sites}
    if len({site.xy for site in sites}) != len(sites):
        raise ValueError("capture poses must be unique")

    best_score = (-1, 0)
    for orientation, along, across in (("horizontal", 0, 1), ("vertical", 1, 0)):
        ordered = sorted(sites, key=lambda s: (s.xy[across], s.xy[along]))
        strips = [tuple(group) for _, group in groupby(ordered, key=lambda s: s.xy[across])]
        for split in range(len(strips) + 1):
            blocks = (strips[:split], strips[split:])
            for first_block in (0, 1):
                options = [
                    _route_options(robot, blocks[i ^ first_block], plot.cell_size_m)
                    for i, robot in enumerate(robots)
                ]
                for pair in product(*options):
                    score = _score(*pair, masks)
                    if score <= best_score:
                        continue
                    best_score = score
                    routes = [
                        RobotRoute(robot.agent_id, tuple(c for c in path if c.finish_tick <= -score[1]))
                        for robot, path in zip(robots, pair)
                    ]
                    best = SweepPlan(orientation, split, robots[first_block].agent_id,
                                     (routes[0], routes[1]), score[0])
    return best
