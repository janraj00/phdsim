"""Delivered observations and lightweight references, without prediction or policy state."""

from __future__ import annotations

from dataclasses import dataclass
from phdsim.core.identity import TargetRef


@dataclass(frozen=True)
class ObservationRef:
    observation_id: str
    source_id: str
    modality: str
    target: TargetRef


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_id: str
    modality: str
    target: TargetRef
    payload: object
    record_id: str
    dataset_version: str

    def reference(self) -> ObservationRef:
        return ObservationRef(self.observation_id, self.source_id, self.modality, self.target)
