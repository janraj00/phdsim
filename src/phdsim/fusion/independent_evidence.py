"""Fusion component."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, log2
from typing import Protocol
from phdsim.probability import binary_entropy, logit, sigmoid
from phdsim.perception.results import TaskResult
from phdsim.core.identity import stable_id


@dataclass(frozen=True)
class IndependentEvidenceFusion:
    """Add posterior log odds, correcting the duplicated training prior."""
    prior: float

    def __post_init__(self) -> None:
        if not isfinite(self.prior) or not 0 < self.prior < 1:
            raise ValueError('Fusion prior must be strictly between zero and one')

    @property
    def version(self) -> str:
        return stable_id('independent-log-odds-v1', repr(self.prior))

    def update(self, previous: TaskResult | None, incoming: TaskResult) -> TaskResult:
        if not isinstance(incoming.prediction, (int, float)) or not 0 <= incoming.prediction <= 1:
            raise ValueError('Fusion expects probabilities')
        if previous is None:
            probability = float(incoming.prediction)
            observations = incoming.observation_ids
            versions = incoming.model_versions
        else:
            if previous.target != incoming.target:
                raise ValueError('Cannot fuse different targets')
            if set(previous.observation_ids) & set(incoming.observation_ids):
                raise ValueError('Cannot fuse duplicate observations')
            if not isinstance(previous.prediction, (int, float)) or not 0 <= previous.prediction <= 1:
                raise ValueError('Fusion expects probabilities')
            probability = sigmoid(logit(previous.prediction) + logit(incoming.prediction) - logit(self.prior))
            observations = previous.observation_ids + incoming.observation_ids
            versions = previous.model_versions + incoming.model_versions
        evidence = (() if previous is None else previous.evidence) + incoming.evidence
        return TaskResult(incoming.target, probability, binary_entropy(probability), observations,
                          tuple(dict.fromkeys(versions + (self.version,))), evidence)
