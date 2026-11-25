"""Helper flight quote and feasibility controller; no terrain truth access."""

from dataclasses import dataclass
import math
from phdsim.core.grid import Cell
from phdsim.communication.delayed import CommunicationConfig
from phdsim.sensors.occupancy import footprint

@dataclass(frozen=True)
class DroneConfig:
    speed: float = 3.0
    sensor_radius: int = 5
    sensor_accuracy: float = 0.9
    move_energy: float = 0.3
    measurement_ticks: int = 1
    measurement_energy: float = 2.0


@dataclass(frozen=True)
class FlightQuote:
    target: Cell
    capture_at: int
    energy: float


@dataclass
class Drone:
    position: Cell
    config: DroneConfig
    busy: bool = False

    def quote(self, target: Cell, tick: int, size, link: CommunicationConfig) -> FlightQuote:
        if not (isinstance(target, tuple) and len(target) == 2 and
                all(type(v) is int for v in target) and
                0 <= target[0] < size[0] and 0 <= target[1] < size[1]):
            raise ValueError("Acquisition target must be an in-bounds integer cell")
        distance = math.dist(self.position, target)
        capture_at = tick + math.ceil(distance / self.config.speed) + self.config.measurement_ticks
        byte_count = len(footprint(target, self.config.sensor_radius, size)) * link.bytes_per_cell
        cost = (distance * self.config.move_energy + self.config.measurement_energy
                + byte_count * link.energy_per_byte)
        return FlightQuote(target, capture_at, cost)

    def rejection_reason(self, quote: FlightQuote, remaining_energy: float,
                         rover_reserve: float, deadline: int, minimum_delay: int) -> str | None:
        if self.busy:
            return "drone_busy"
        if quote.energy + rover_reserve > remaining_energy:
            return "energy"
        if quote.capture_at + minimum_delay > deadline:
            return "mission_deadline"
        return None
