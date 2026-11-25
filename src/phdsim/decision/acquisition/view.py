"""Immutable evidence available before requesting a new observation."""

from dataclasses import dataclass
from phdsim.core.grid import Cell

@dataclass(frozen=True)
class DecisionView:
    tick: int
    position: Cell
    goal: Cell
    probabilities: tuple[tuple[float, ...], ...]
    drone_position: Cell
    drone_busy: bool
    remaining_energy: float
    remaining_ticks: int
    requests_sent: int
    last_request_at: int | None
