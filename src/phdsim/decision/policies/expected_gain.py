"""Acquire the observation with the largest positive predicted net utility."""

from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from phdsim.learning.acquisition.features import acquisition_features
from phdsim.learning.acquisition.objectives import GAIN_METRICS
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView
from ..policy import Policy


@dataclass(frozen=True)
class ExpectedGain(Policy):
    """Acquire the observation with the largest positive predicted net utility.

    A frozen directional model estimates the reduction of the configured task
    loss from own-image confidence and optional own-image quality summaries.
    Utility subtracts the transfer penalty and the byte-dependent MB penalty.
    Neighbor pixels and predictions are unavailable before the pull. This
    version supports one complementary-modality pull; missing models or a
    nonpositive best utility lead to ``Stop``. Ties use action ID.
    """

    models: dict
    version: str
    include_quality: bool = True
    transfer_penalty: float = 0.
    megabyte_penalty: float = 0.
    name: str = 'learned_gain'
    gain_metric: str = 'brier'

    def __post_init__(self):
        if self.gain_metric not in GAIN_METRICS:
            raise ValueError('Unknown acquisition objective')
        if any(not isfinite(v) or v < 0 for v in (self.transfer_penalty, self.megabyte_penalty)):
            raise ValueError('Acquisition penalties must be finite and nonnegative')

    def estimate(self, view: DecisionView, candidate: ActionEstimate) -> tuple[float, float] | None:
        if view.result is None or len(view.result.evidence) != 1:
            return None  # This first model supports a single pull from one own image.
        own = view.result.evidence[0]
        if own.modality == candidate.action.modality:
            return None
        model = self.models.get((own.modality, candidate.action.modality))
        if model is None:
            return None
        gain = model.predict(acquisition_features(own, self.include_quality))
        n = candidate.cost.get('transfers')
        size = candidate.cost.get('bytes')
        if n is None or n.value is None or size is None or size.value is None:
            return None
        utility = gain - self.transfer_penalty * n.value - self.megabyte_penalty * size.value / 1_000_000
        return gain, utility

    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
        scored = [(estimate[1], candidate.action.action_id, candidate.action)
                  for candidate in candidates if (estimate := self.estimate(view, candidate)) is not None]
        if not scored:
            return Stop(view.receiver_id, view.target, view.candidate_block_reason or 'no_gain_model_for_action')
        best = sorted(scored, key=lambda row: (-row[0], row[1]))[0]
        if best[0] > 0:
            return best[2]
        return Stop(view.receiver_id, view.target, 'predicted_gain_below_cost')

    def configuration(self) -> dict[str, object]:
        return {'name': self.name, 'gain_model_version': self.version, 'include_quality': self.include_quality,
                'transfer_penalty': self.transfer_penalty, 'megabyte_penalty': self.megabyte_penalty,
                'gain_metric': self.gain_metric}
