"""Synthetic elevation measurements and declared observation likelihoods."""

from dataclasses import dataclass
from math import hypot, sqrt

from phdsim.core.grid import Cell
from phdsim.core.randomness import keyed_rng
from phdsim.environments.elevation import TILE_SIDE, TILES, ElevationWorld


@dataclass(frozen=True)
class Footprint:
    tile: Cell
    clear_precision: float
    poor_precision: float


@dataclass(frozen=True)
class ElevationView:
    mode: str
    anchor: Cell
    pose: tuple[float, float]
    footprint: tuple[Footprint, ...]


@dataclass(frozen=True)
class ElevationReading:
    tile: Cell
    heights_m: tuple[float, ...]
    precision: float
    poor_imaging: bool | None


def candidate_views(mode: str) -> tuple[ElevationView, ...]:
    # Ground, low and high modes use representative standoff to the tile
    # center. Elevation error std grows with standoff in each mode.
    span, height, intercept, slope, poor_factor = {
        "ground": (1, 0.8, 0.055, 0.008, 1.0),
        "low": (1, 2.0, 0.075, 0.012, 3.6),
        "high": (2, 6.0, 0.075, 0.012, 3.6),
    }[mode]
    views = []
    for y in range(TILES - span + 1):
        for x in range(TILES - span + 1):
            px, py = ((axis + span / 2) * TILE_SIDE - 0.5 for axis in (x, y))
            footprint = []
            for ty in range(y, y + span):
                for tx in range(x, x + span):
                    horizontal = hypot((tx + 0.5) * TILE_SIDE - 0.5 - px,
                                       (ty + 0.5) * TILE_SIDE - 0.5 - py)
                    std = intercept + slope * hypot(height, horizontal)
                    footprint.append(Footprint((tx, ty), std**-2, (std * poor_factor)**-2))
            views.append(ElevationView(mode, (x, y), (px, py), tuple(footprint)))
    return tuple(views)


def measure(world: ElevationWorld, view: ElevationView, seed: int,
            attempt: int) -> tuple[ElevationReading, ...]:
    readings = []
    for part in view.footprint:
        poor = world.poor_imaging[part.tile] if view.mode != "ground" else None
        precision = part.poor_precision if poor else part.clear_precision
        rng = keyed_rng(seed, "elevation measurement", view.mode, view.anchor, attempt, part.tile)
        values = tuple(z + rng.gauss(0, 1 / sqrt(precision)) for z in world.truth_m[part.tile])
        readings.append(ElevationReading(part.tile, values, precision, poor))
    return tuple(readings)
