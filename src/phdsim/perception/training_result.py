"""A trained adapter and its serializable, auditable model description."""

from dataclasses import dataclass

from .baseline import Perception


@dataclass(frozen=True)
class TrainingResult:
    perception: Perception
    class_prior: float
    model_snapshot: dict
