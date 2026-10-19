"""Fusion component."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, log2
from typing import Protocol
from phdsim.probability import binary_entropy, logit, sigmoid
from phdsim.perception.results import TaskResult
from phdsim.core.identity import stable_id


@dataclass(frozen=True)
class MeanProbabilityFusion:
    """Incoming predictions are atomic probabilities or means over their evidence."""
    version: str = 'mean-probability-v1'

    def update(self, previous: TaskResult | None, incoming: TaskResult) -> TaskResult:
        if previous is not None and previous.target != incoming.target:
            raise ValueError('Cannot fuse different targets')
        if not isinstance(incoming.prediction, (float, int)):
            raise ValueError('This fusion expects probability predictions')
        if previous is None:
            probability = float(incoming.prediction)
            observation_ids = incoming.observation_ids
            versions = incoming.model_versions
        else:
            if not isinstance(previous.prediction, (float, int)):
                raise ValueError('This fusion expects probability predictions')
            if set(previous.observation_ids) & set(incoming.observation_ids):
                raise ValueError('Cannot fuse an observation twice')
            count_before = len(previous.observation_ids)
            count_new = len(incoming.observation_ids)
            probability = (previous.prediction * count_before + incoming.prediction * count_new) / (count_before + count_new)
            observation_ids = previous.observation_ids + incoming.observation_ids
            versions = previous.model_versions + incoming.model_versions
        if not 0 <= probability <= 1:
            raise ValueError('Fused probability is outside [0, 1]')
        entropy = 0.0 if probability in (0.0, 1.0) else -probability * log2(probability) - (1 - probability) * log2(1 - probability)
        evidence = (() if previous is None else previous.evidence) + incoming.evidence
        return TaskResult(incoming.target, probability, entropy, observation_ids,
                          tuple(dict.fromkeys(versions + (self.version,))), evidence)
