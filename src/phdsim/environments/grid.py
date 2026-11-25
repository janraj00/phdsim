"""Hidden grid truth and public initial prior; accessible to the simulator only."""

from dataclasses import dataclass
from phdsim.core.grid import Cell

@dataclass(frozen=True)
class WorldConfig:
    size: tuple[int, int] = (32, 32)
    generator: str = "alternative_corridors"
    initial_map: str = "uncertain"

@dataclass(frozen=True)
class World:
    blocked: tuple[tuple[bool, ...], ...]
    prior: tuple[tuple[float, ...], ...]
    start: Cell
    goal: Cell
    seed: int

    @property
    def size(self):
        return len(self.blocked[0]), len(self.blocked)
