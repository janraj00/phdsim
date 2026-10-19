"""Predeclared model choices and cost curves; no test-selected settings."""

from dataclasses import dataclass
from math import isfinite
import json
from pathlib import Path

from .acquisition.objectives import GAIN_METRICS


@dataclass(frozen=True)
class LearningConfig:
    seed: int = 42
    meta_fraction: float = 0.3
    fusion_regularization: float = 10.
    gain_regularizations: tuple[float, ...] = (1., 10., 100.)
    transfer_penalties: tuple[float, ...] = (0., 0.01, 0.03, 0.06)
    megabyte_penalty: float = 0.
    entropy_thresholds: tuple[float, ...] = (0.5, 0.75, 0.85, 0.95, 1.)
    random_probabilities: tuple[float, ...] = (0.25, 0.5, 0.75)
    random_seeds: tuple[int, ...] = (17, 42, 97)
    gain_metric: str = 'brier'

    def __post_init__(self):
        if self.gain_metric not in GAIN_METRICS:
            raise ValueError(f'Unknown acquisition gain metric: {self.gain_metric}')
        if type(self.seed) is not int or not isfinite(self.meta_fraction) or not 0 < self.meta_fraction < 1:
            raise ValueError('Invalid learning split settings')
        if not isfinite(self.fusion_regularization) or self.fusion_regularization <= 0:
            raise ValueError('Fusion regularization must be positive')
        for name in ('gain_regularizations', 'transfer_penalties', 'entropy_thresholds', 'random_probabilities', 'random_seeds'):
            values = getattr(self, name)
            if not values or len(set(values)) != len(values) or not all(isfinite(v) for v in values):
                raise ValueError(f'{name} must contain distinct finite values')
        if min(self.gain_regularizations) <= 0 or min(self.transfer_penalties) < 0 or not isfinite(self.megabyte_penalty) or self.megabyte_penalty < 0:
            raise ValueError('Invalid regularization or acquisition cost')
        if any(not 0 <= v <= 1 for v in self.entropy_thresholds + self.random_probabilities):
            raise ValueError('Entropy thresholds and random probabilities must be in [0, 1]')
        if any(type(v) is not int for v in self.random_seeds):
            raise ValueError('Random seeds must be integers')

    @classmethod
    def load(cls, path):
        row = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        for name in ('gain_regularizations', 'transfer_penalties', 'entropy_thresholds', 'random_probabilities', 'random_seeds'):
            if name in row:
                row[name] = tuple(row[name])
        return cls(**row)
