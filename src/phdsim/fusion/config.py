"""Fusion component."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, log2
from typing import Protocol
from phdsim.probability import binary_entropy, logit, sigmoid
from phdsim.perception.results import TaskResult
from phdsim.core.identity import stable_id
from .independent_evidence import IndependentEvidenceFusion
from .mean_probability import MeanProbabilityFusion
from .base import Fusion


@dataclass(frozen=True)
class FusionConfig:
    method: str = 'independent_log_odds'

    def __post_init__(self):
        if self.method not in ('independent_log_odds', 'mean_probability', 'learned_probability'):
            raise ValueError(f'Unknown fusion method: {self.method}')

    def build(self, training_prior: float, learned=None) -> Fusion:
        if self.method == 'learned_probability':
            if learned is None or learned.fusion_method != self.method:
                raise ValueError('Learned fusion requires a compatible frozen learning bundle')
            return learned.fusion
        if self.method == 'independent_log_odds':
            return IndependentEvidenceFusion(training_prior)
        return MeanProbabilityFusion()
