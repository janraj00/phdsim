"""Small, reproducible RGB segmentation pilot configuration."""

from dataclasses import dataclass
import json
from pathlib import Path
import math


@dataclass(frozen=True)
class RgbTrainingConfig:
    epochs: int = 5
    train_frames: int = 48
    validation_frames: int = 24
    seed: int = 42
    cpu_threads: int = 6
    encoder_learning_rate: float = .0001
    decoder_learning_rate: float = .001
    weight_decay: float = .0001
    gradient_clip: float = 5.
    validation_families: tuple[str, ...] = ('bag1', 'bag7', 'bag11')
    acquisition_families: tuple[str, ...] = ('bag4', 'bag5', 'bag6', 'bag8', 'bag12', 'bag17')

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in
               (self.epochs, self.train_frames, self.validation_frames, self.cpu_threads)):
            raise ValueError('Epochs, frame counts and threads must be positive integers')
        if any(not math.isfinite(v) or v <= 0 for v in
               (self.encoder_learning_rate, self.decoder_learning_rate, self.weight_decay, self.gradient_clip)):
            raise ValueError('Training rates, decay and gradient clip must be finite and positive')
        if not self.validation_families or not self.acquisition_families or set(self.validation_families) & set(self.acquisition_families):
            raise ValueError('Validation and acquisition families must be nonempty and disjoint')

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return cls(**{**value, **{k: tuple(value[k]) for k in ('validation_families', 'acquisition_families') if k in value}})
