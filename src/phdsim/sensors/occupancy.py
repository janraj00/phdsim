"""Noisy binary sensing model, invoked by the simulator at capture time."""

from typing import TYPE_CHECKING
from phdsim.core.grid import Cell
from phdsim.core.randomness import keyed_rng
from .observations import Observation

if TYPE_CHECKING:
    from phdsim.environments.grid import World

def footprint(center: Cell, radius: int, size: tuple[int, int]) -> tuple[Cell, ...]:
    w, h = size
    cx, cy = center
    return tuple((x, y) for y in range(max(0, cy-radius), min(h, cy+radius+1))
                 for x in range(max(0, cx-radius), min(w, cx+radius+1))
                 if (x-cx)**2 + (y-cy)**2 <= radius**2)

def observe(world: "World", sensor: str, position: Cell, radius: int, accuracy: float, tick: int):
    cells = []
    for x, y in footprint(position, radius, world.size):
        truth = world.blocked[y][x]
        correct = keyed_rng(world.seed, "sensor", sensor, tick, x, y).random() < accuracy
        cells.append((x, y, truth if correct else not truth))
    return Observation(sensor, tick, tuple(cells), accuracy)
