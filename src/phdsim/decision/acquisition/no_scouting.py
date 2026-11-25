"""Acquisition baseline which never requests a helper observation."""

from phdsim.core.grid import Cell
from .view import DecisionView

class NoScouting:
    name = "no_scouting"

    def request(self, view: DecisionView, path: tuple[Cell, ...]) -> Cell | None:
        return None
