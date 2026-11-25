"""Synthetic elevation and imaging conditions, with an independent coarse prior."""

from dataclasses import dataclass
from math import cos, sin, sqrt

from phdsim.core.grid import Cell
from phdsim.core.randomness import keyed_rng


SIDE = 32
TILE_SIDE = 4
TILES = SIDE // TILE_SIDE
CELLS_PER_TILE = TILE_SIDE ** 2
PRIOR_STD_M = 0.5


def tiles() -> tuple[Cell, ...]:
    return tuple((x, y) for y in range(TILES) for x in range(TILES))


def cells(tile: Cell) -> tuple[Cell, ...]:
    tx, ty = tile
    return tuple((x, y) for y in range(ty * TILE_SIDE, (ty + 1) * TILE_SIDE)
                 for x in range(tx * TILE_SIDE, (tx + 1) * TILE_SIDE))


@dataclass(frozen=True)
class ElevationWorld:
    coarse_m: dict[Cell, tuple[float, ...]]
    truth_m: dict[Cell, tuple[float, ...]]
    poor_imaging: dict[Cell, bool]


def generate_world(seed: int, poor_probability: float) -> ElevationWorld:
    """Add a spatially smooth residual with a 0.5 m Gaussian marginal at each cell."""
    rng = keyed_rng(seed, "terrain")
    phase_x, phase_y = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    centers = tuple((x, y, rng.gauss(0, 1)) for x in range(-4, SIDE + 5, 4)
                    for y in range(-4, SIDE + 5, 4))
    coarse, truth, poor = {}, {}, {}
    for tile in tiles():
        prior, heights = [], []
        for x, y in cells(tile):
            height = 0.06 * x + cos(y / 9 + phase_y) + sin(x / 8 + phase_x)
            # Compact bumps add local hills and depressions without exposing
            # the realized residual through the public coarse model.
            weights = [(max(0.0, 1 - ((x - cx)**2 + (y - cy)**2) / 36)**2, z)
                       for cx, cy, z in centers if abs(x - cx) < 6 and abs(y - cy) < 6]
            residual = sum(w * z for w, z in weights) / sqrt(sum(w * w for w, _ in weights))
            prior.append(height)
            heights.append(height + PRIOR_STD_M * residual)
        coarse[tile] = tuple(prior)
        truth[tile] = tuple(heights)
        poor[tile] = keyed_rng(seed, "imaging", tile).random() < poor_probability
    return ElevationWorld(coarse, truth, poor)
