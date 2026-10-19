"""Validate configuration and construct a concrete frozen policy."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from .policies.no_acquisition import NoAcquisition
from .policies.uncertainty_threshold import UncertaintyThreshold
from .policies.always_acquire import AlwaysAcquire
from .policy import Policy


@dataclass(frozen=True)
class DecisionConfig:
    method: str
    threshold: float | None = None
    name: str | None = None
    transfer_penalty: float = 0.
    megabyte_penalty: float = 0.
    probability: float = 0.5
    seed: int = 42

    def __post_init__(self):
        if self.method not in ('no_acquisition', 'always_acquire', 'uncertainty_threshold',
                               'random_acquisition', 'learned_gain', 'learned_gain_confidence'):
            raise ValueError(f'Unknown decision method: {self.method}')
        if self.method == 'uncertainty_threshold':
            UncertaintyThreshold(0.85 if self.threshold is None else self.threshold)
        elif self.threshold is not None:
            raise ValueError('Only uncertainty_threshold accepts a threshold')
        if self.name is not None and (not self.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in self.name)):
            raise ValueError('Decision name must be a nonempty safe identifier')
        if any(not isfinite(v) or v < 0 for v in (self.transfer_penalty, self.megabyte_penalty)):
            raise ValueError('Decision penalties must be finite and nonnegative')
        if self.method not in ('learned_gain', 'learned_gain_confidence') and (self.transfer_penalty or self.megabyte_penalty):
            raise ValueError('Only expected-gain decisions accept utility penalties')
        if not isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError('Random acquisition probability must be in [0, 1]')

    @property
    def key(self):
        return self.name or self.method

    def build(self, learned=None) -> Policy:
        if self.method == 'random_acquisition':
            from .policies.random_acquisition import RandomAcquisition
            return RandomAcquisition(self.probability, self.seed, self.key)
        if self.method in ('learned_gain', 'learned_gain_confidence'):
            if learned is None:
                raise ValueError('Expected gain requires a frozen learning bundle')
            from .policies.expected_gain import ExpectedGain
            return ExpectedGain(learned.gain_models[self.method], learned.version,
                                self.method == 'learned_gain', self.transfer_penalty,
                                self.megabyte_penalty, self.key, gain_metric=learned.gain_metric)
        if self.method == 'no_acquisition':
            return NoAcquisition(name=self.key)
        if self.method == 'always_acquire':
            return AlwaysAcquire(name=self.key)
        return UncertaintyThreshold(0.85 if self.threshold is None else self.threshold, name=self.key)
