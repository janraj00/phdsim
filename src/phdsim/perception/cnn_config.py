"""Explicit settings for two independent transfer-learning runs."""

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path


@dataclass(frozen=True)
class CnnConfig:
    architecture: str = "resnet18"
    weights: str = "IMAGENET1K_V1"
    image_height: int = 216
    image_width: int = 384
    epochs: int = 6
    batch_size: int = 8
    learning_rate: float = 0.0001
    head_learning_rate: float = 0.001
    weight_decay: float = 0.0001
    seed: int = 42
    cpu_threads: int = 6
    trainable: str = "layer4_and_head"
    torch_cache: str = "D:/Doktorat/Platforma/cache/torch"

    def __post_init__(self):
        if self.architecture != "resnet18" or self.weights != "IMAGENET1K_V1":
            raise ValueError("This adapter supports ResNet-18 with ImageNet1K V1 initialization")
        for name in ("image_height", "image_width", "epochs", "batch_size", "cpu_threads"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"Positive integer required: {name}")
        if min(self.image_height, self.image_width) < 32:
            raise ValueError("CNN input dimensions must be at least 32 pixels")
        if type(self.seed) is not int or self.trainable not in ("head", "layer4_and_head"):
            raise ValueError("Invalid seed or trainable layer selection")
        for rate in (self.learning_rate, self.head_learning_rate):
            if not isfinite(rate) or rate <= 0:
                raise ValueError("Learning rates must be positive and finite")
        if not isfinite(self.weight_decay) or self.weight_decay < 0:
            raise ValueError("Weight decay must be finite and nonnegative")

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8-sig")))
