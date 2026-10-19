'Reference labels are available only to training and evaluation.'
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Protocol

from phdsim.evaluation.results import QualityChange
from phdsim.core.identity import TargetRef
from phdsim.perception.results import TaskResult

class Evaluator(Protocol):
    metric_id: str
    direction: str

    def evaluate(self, target: TargetRef, before: TaskResult | None, after: TaskResult | None) -> QualityChange:
        ...

class BrierEvaluator:
    metric_id = 'binary-brier-v1'
    direction = 'lower_is_better'

    def __init__(self, labels: Mapping[TargetRef, int | None]) -> None:
        if any((label not in (None, 0, 1) for label in labels.values())):
            raise ValueError('Brier evaluator requires binary labels')
        self._labels = dict(labels)

    def _scores(self, target: TargetRef, result: TaskResult | None) -> tuple[float | None, float | None]:
        if result is not None and result.target != target:
            raise ValueError('Cannot evaluate a different target')
        label = self._labels.get(target)
        if result is None or result.prediction is None:
            return (None, None)
        p = result.prediction
        if not isinstance(p, (float, int)) or not isfinite(p) or (not 0 <= p <= 1):
            raise ValueError('Binary Brier score requires a probability in [0, 1]')
        if label is None:
            return (None, None)
        return ((p - label) ** 2, float(int(p >= 0.5) == label))

    def evaluate(self, target: TargetRef, before: TaskResult | None, after: TaskResult | None) -> QualityChange:
        score_before, accuracy_before = self._scores(target, before)
        score_after, accuracy_after = self._scores(target, after)
        gain = None if score_before is None or score_after is None else score_before - score_after
        uncertainty_reduction = None
        if before is not None and after is not None and (before.uncertainty is not None) and (after.uncertainty is not None):
            uncertainty_reduction = before.uncertainty - after.uncertainty
        return QualityChange(self.metric_id, self.direction, score_before, score_after, gain, accuracy_before, accuracy_after, uncertainty_reduction)
