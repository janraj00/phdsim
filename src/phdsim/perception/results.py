"""Immutable predictions and evidence produced from delivered observations."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from phdsim.core.identity import TargetRef

Prediction = float | str | bool | tuple[float, ...] | None


@dataclass(frozen=True)
class PerceptionEvidence:
    observation_id: str
    modality: str
    probability: float
    local_features: tuple[float, ...] = ()

    def __post_init__(self):
        if not self.observation_id or not self.modality or not isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError('Invalid perception evidence')
        if not all(isfinite(value) for value in self.local_features):
            raise ValueError('Local features must be finite')


@dataclass(frozen=True)
class TaskResult:
    target: TargetRef
    prediction: Prediction
    uncertainty: float | None
    observation_ids: tuple[str, ...]
    model_versions: tuple[str, ...]
    evidence: tuple[PerceptionEvidence, ...] = ()

    def __post_init__(self) -> None:
        evidence_ids = [item.observation_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids) or not set(evidence_ids) <= set(self.observation_ids):
            raise ValueError('Evidence must refer to distinct delivered observations')
        if self.prediction is not None:
            if isinstance(self.prediction, tuple):
                valid = all((isinstance(v, (float, int)) and isfinite(v) for v in self.prediction))
            elif isinstance(self.prediction, (float, int)):
                valid = isfinite(self.prediction)
            else:
                valid = isinstance(self.prediction, str)
            if not valid:
                raise ValueError('Prediction must be an immutable, finite supported value')
        if self.uncertainty is not None and (not isfinite(self.uncertainty) or self.uncertainty < 0):
            raise ValueError('Uncertainty must be nonnegative and finite')
