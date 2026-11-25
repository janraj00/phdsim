"""Fuse delivered observations into an agent-local occupancy map."""

import math
from phdsim.core.grid import Cell
from phdsim.sensors.observations import Observation

class Belief:
    def __init__(self, prior, start: Cell, goal: Cell):
        self.probabilities = [list(row) for row in prior]
        self.facts = {start: False, goal: False}
        self._apply_facts()

    def _apply_facts(self):
        for (x, y), blocked in self.facts.items():
            self.probabilities[y][x] = float(blocked)

    def update(self, observation: Observation):
        a = observation.accuracy
        for x, y, reported_blocked in observation.cells:
            p = self.probabilities[y][x]
            likelihood_blocked = a if reported_blocked else 1-a
            likelihood_free = 1-likelihood_blocked
            denominator = p*likelihood_blocked + (1-p)*likelihood_free
            self.probabilities[y][x] = p*likelihood_blocked / denominator
        self._apply_facts()

    def contact(self, cell: Cell, blocked: bool):
        self.facts[cell] = blocked
        self._apply_facts()

    def snapshot(self):
        return tuple(map(tuple, self.probabilities))

def entropy(p: float) -> float:
    return -p*math.log2(p)-(1-p)*math.log2(1-p) if 0 < p < 1 else 0.0
