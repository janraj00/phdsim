"""Perception adapters. Neural dependencies load only for a CNN experiment."""

from .baseline import (
    FitConfig, ImageModel, ImagePayload, ImagePerception, LogisticModel,
    Perception, ScalarPoolPerception, image_features, load_observation, load_scalar,
    train_image_perception, train_pool, train_scalar_perception,
)
from .cnn_config import CnnConfig
from .training_result import TrainingResult
