"""Acquisition actions, stopping decisions and advertised candidate estimates."""

from __future__ import annotations

from dataclasses import dataclass
from phdsim.core.identity import TargetRef
from phdsim.costs.types import CostVector


@dataclass(frozen=True)
class Acquire:
    action_id: str
    receiver_id: str
    source_id: str
    target: TargetRef
    modality: str
    parameters: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_id, self.modality)


@dataclass(frozen=True)
class Stop:
    receiver_id: str
    target: TargetRef
    reason: str


@dataclass(frozen=True)
class ActionEstimate:
    action: Acquire
    cost: CostVector
    predicted_gain: float | None = None
    gain_model_version: str | None = None
    cost_model_version: str | None = None
