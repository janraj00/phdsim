"""Offline quality changes; these reference-based scores are not policy inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class QualityChange:
    metric_id: str
    direction: Literal['lower_is_better', 'higher_is_better']
    before: float | None
    after: float | None
    gain: float | None
    accuracy_before: float | None
    accuracy_after: float | None
    uncertainty_reduction: float | None
