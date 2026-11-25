"""Conservative energy reservations for the synthetic rover/drone mission."""

from dataclasses import dataclass


@dataclass
class MissionLedger:
    budget: float
    total: float = 0.0
    rover: float = 0.0
    drone: float = 0.0

    @property
    def remaining(self) -> float:
        return self.budget - self.total

    def charge_rover(self, cost: float):
        self.total += cost
        self.rover += cost

    def reserve_drone(self, cost: float):
        self.total += cost
        self.drone += cost
