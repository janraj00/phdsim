"""The current local information a presence policy may inspect before transfer."""

from __future__ import annotations

from dataclasses import dataclass
from phdsim.core.identity import TargetRef
from phdsim.costs.types import CostVector
from phdsim.datasets.observations import ObservationRef
from phdsim.perception.results import TaskResult


@dataclass(frozen=True)
class DecisionView:
    receiver_id: str
    target: TargetRef
    result: TaskResult | None
    observations: tuple[ObservationRef, ...]
    attempted: tuple[tuple[str, str], ...]
    modalities: tuple[str, ...]
    source_ids: tuple[str, ...]
    remaining_budget: CostVector
    candidate_block_reason: str | None = None
