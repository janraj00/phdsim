"""Acquire every currently available observation allowed by the engine."""

from __future__ import annotations
from dataclasses import dataclass
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView
from ..policy import Policy


@dataclass(frozen=True)
class AlwaysAcquire(Policy):
    """Acquire every currently available observation allowed by the engine.

    Chooses the candidate with the smallest action ID for reproducibility.
    After each delivery the engine asks again; acquisition ends when no legal
    candidate remains, including when the shared budget blocks transfers.
    """

    name: str = 'always_acquire'

    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
        if candidates:
            return min(candidates, key=lambda candidate: candidate.action.action_id).action
        return Stop(view.receiver_id, view.target, view.candidate_block_reason or 'no_available_actions')

    def configuration(self) -> dict[str, object]:
        return {'name': self.name}
