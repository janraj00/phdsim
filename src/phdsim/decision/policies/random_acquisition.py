"""Acquire with a fixed probability as a reproducible random reference."""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView
from ..policy import Policy


@dataclass(frozen=True)
class RandomAcquisition(Policy):
    """Acquire with a fixed probability as a reproducible random reference.

    A hash of seed, receiver and target supplies the coin toss. Target IDs are
    used only to reproduce the draw, never as learned features. An accepted
    draw selects the smallest action ID; no candidates means ``Stop``.
    """

    probability: float = 0.5
    seed: int = 42
    name: str = 'random_acquisition'

    def __post_init__(self):
        if not isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError('Random acquisition probability must be in [0, 1]')

    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
        if not candidates:
            return Stop(view.receiver_id, view.target, view.candidate_block_reason or 'no_available_actions')
        # Target IDs only seed a stable coin toss; they are never learned features.
        key = f'{self.seed}:{view.receiver_id}:{view.target.kind}:{view.target.id}'
        draw = int.from_bytes(sha256(key.encode()).digest()[:8], 'big') / 2**64
        if draw < self.probability:
            return min(candidates, key=lambda c: c.action.action_id).action
        return Stop(view.receiver_id, view.target, 'random_skip')

    def configuration(self) -> dict[str, object]:
        return {'name': self.name, 'probability': self.probability, 'seed': self.seed}
