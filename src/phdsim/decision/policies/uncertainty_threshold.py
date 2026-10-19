"""Acquire while the current result's binary entropy reaches the threshold."""

from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView
from ..policy import Policy


@dataclass(frozen=True)
class UncertaintyThreshold(Policy):
    """Acquire while the current result's binary entropy reaches the threshold.

    ``threshold`` is entropy in bits (0 means certainty, 1 maximum uncertainty),
    rather than a classification-probability cutoff. Missing results, missing
    uncertainty, sufficient confidence or no available action lead to ``Stop``.
    Candidate ties use action ID; no gain model is consulted.
    """

    threshold: float = 0.85
    name: str = 'uncertainty_threshold'

    def __post_init__(self) -> None:
        if not isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError('Entropy threshold must be in [0, 1]')

    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
        if view.result is None:
            return Stop(view.receiver_id, view.target, 'no_result')
        if view.result.uncertainty is None:
            return Stop(view.receiver_id, view.target, 'uncertainty_unavailable')
        if view.result.uncertainty < self.threshold:
            return Stop(view.receiver_id, view.target, 'confidence_sufficient')
        if not candidates:
            return Stop(view.receiver_id, view.target, view.candidate_block_reason or 'no_available_actions')
        return min(candidates, key=lambda candidate: candidate.action.action_id).action

    def configuration(self) -> dict[str, object]:
        return {'name': self.name, 'threshold': self.threshold}
