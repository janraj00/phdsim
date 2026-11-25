"""Rover motion state; physical collision checks belong to the environment."""

from dataclasses import dataclass
import math
from phdsim.core.grid import Cell

@dataclass(frozen=True)
class RoverConfig:
    speed: float = 1.0
    sensor_radius: int = 2
    sensor_accuracy: float = 0.85
    move_energy: float = 1.0


@dataclass
class Rover:
    position: Cell
    config: RoverConfig
    pending_move: tuple[int, Cell] | None = None

    def arrive(self, tick: int) -> bool:
        if self.pending_move is None or self.pending_move[0] > tick:
            return False
        self.position = self.pending_move[1]
        self.pending_move = None
        return True

    def depart(self, target: Cell, tick: int) -> int:
        arrival = tick + max(1, math.ceil(1 / self.config.speed))
        self.pending_move = arrival, target
        return arrival
