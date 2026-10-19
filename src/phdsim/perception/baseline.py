'Perception: frozen task models fitted on training observations only.'
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from math import exp, isfinite, log1p, sqrt
from pathlib import Path
from typing import Protocol
import json
import numpy as np

from PIL import Image

from phdsim.datasets import ObservationPool, PoolRecord
from phdsim.probability import binary_entropy, sigmoid
from phdsim.datasets.observations import Observation
from phdsim.core.identity import TargetRef, stable_id
from phdsim.perception.results import TaskResult

class Perception(Protocol):
    supported_modalities: tuple[str, ...]
    version: str

    def process(self, observation: Observation) -> TaskResult:
        ...

@dataclass(frozen=True)
class FitConfig:
    epochs: int = 250
    learning_rate: float = 0.2
    regularization: float = 0.001

    def __post_init__(self) -> None:
        if not isinstance(self.epochs, int) or self.epochs < 1:
            raise ValueError('Training requires a positive epoch count')
        if not isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError('Learning rate must be positive and finite')
        if not isfinite(self.regularization) or self.regularization < 0:
            raise ValueError('Regularization must be nonnegative and finite')

@dataclass(frozen=True)
class LogisticModel:
    modality: str
    intercept: float
    coefficient: float
    center: float
    scale: float
    train_count: int
    training_sha256: str
    initial_log_loss: float
    final_log_loss: float
    version: str

    def predict(self, measurement: float) -> float:
        if not isfinite(measurement):
            raise ValueError('Measurement must be finite')
        return sigmoid(self.intercept + self.coefficient * (measurement - self.center) / self.scale)

def fit_scalar_samples(samples: tuple[tuple[TargetRef, float, int], ...], modality: str, config: FitConfig=FitConfig()) -> LogisticModel:
    """Fit a modality adapter's explicitly selected training samples only."""
    labels = tuple((label for _, _, label in samples))
    if not labels or set(labels) != {0, 1}:
        raise ValueError('Training data must include both binary classes')
    raw = tuple((value for _, value, _ in samples))
    if not all((isfinite(value) for value in raw)):
        raise ValueError('Training measurements must be finite')
    center = sum(raw) / len(raw)
    scale = sqrt(sum(((value - center) ** 2 for value in raw)) / len(raw)) or 1.0
    features = tuple(((value - center) / scale for value in raw))
    intercept = coefficient = 0.0

    def loss() -> float:
        total = 0.0
        for value, label in zip(features, labels):
            score = intercept + coefficient * value
            total += max(score, 0) - score * label + log1p(exp(-abs(score)))
        return total / len(labels)
    initial_loss = loss()
    for _ in range(config.epochs):
        bias_gradient = weight_gradient = 0.0
        for value, label in zip(features, labels):
            error = sigmoid(intercept + coefficient * value) - label
            bias_gradient += error
            weight_gradient += error * value
        intercept -= config.learning_rate * bias_gradient / len(labels)
        coefficient -= config.learning_rate * (weight_gradient / len(labels) + config.regularization * coefficient)
    final_loss = loss()
    fingerprint = sha256(json.dumps([(target.kind, target.id, value, label) for target, value, label in samples], separators=(',', ':')).encode()).hexdigest()
    version = stable_id('scalar-logistic-v1', modality, fingerprint, repr((intercept, coefficient, center, scale)))
    return LogisticModel(modality, intercept, coefficient, center, scale, len(labels), fingerprint, initial_loss, final_loss, version)

def load_scalar(pool: ObservationPool, row: PoolRecord) -> Observation:
    if row.payload_format != 'scalar-json-v1':
        raise ValueError('Scalar demo requires scalar-json-v1; real images need a task-specific perception adapter')
    value = json.loads(pool.read_payload(row.observation_id))
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError('Scalar payload must be a finite number')
    return Observation(row.observation_id, row.stream_id, row.modality, row.target, float(value), row.observation_id, pool.manifest['dataset_version'])

@dataclass(frozen=True)
class ScalarPoolPerception:
    models: tuple[LogisticModel, ...]

    @property
    def version(self) -> str:
        return stable_id('scalar-pool-perception-v1', *(m.version for m in self.models))

    @property
    def supported_modalities(self) -> tuple[str, ...]:
        return tuple((model.modality for model in self.models))

    def process(self, observation: Observation) -> TaskResult:
        model = next((m for m in self.models if m.modality == observation.modality), None)
        if model is None or type(observation.payload) not in (int, float):
            raise ValueError('Unsupported scalar modality/payload')
        probability = model.predict(observation.payload)
        return TaskResult(observation.target, probability, binary_entropy(probability), (observation.observation_id,), (model.version,))

@dataclass(frozen=True)
class TrainedScalarPerception:
    perception: ScalarPoolPerception
    class_prior: float

def train_scalar_perception(pool: ObservationPool, modalities: tuple[str, ...], config: FitConfig=FitConfig()) -> TrainedScalarPerception:
    """Train perception and a class prior, without selecting a fusion algorithm."""
    labels = pool.read_labels()
    training = tuple((r for r in pool.records if r.split == 'train' and r.modality in modalities))
    by_modality = {}
    for modality in modalities:
        rows = tuple((r for r in training if r.modality == modality))
        targets = [r.target for r in rows]
        if not rows or len(set(targets)) != len(targets):
            raise ValueError('Scalar task requires one training observation per target and modality')
        by_modality[modality] = rows
    target_sets = [set((r.target for r in rows)) for rows in by_modality.values()]
    if any((targets != target_sets[0] for targets in target_sets)):
        raise ValueError('Scalar evidence fusion requires paired training target sets')
    if any((type(labels.get(target)) is not int or labels[target] not in (0, 1) for target in target_sets[0])):
        raise ValueError('Scalar training requires binary reference labels')
    models = tuple((fit_scalar_samples(tuple(((r.target, load_scalar(pool, r).payload, labels[r.target]) for r in by_modality[modality])), modality, config) for modality in modalities))
    prior = (sum((labels[target] for target in target_sets[0])) + 1) / (len(target_sets[0]) + 2)
    return TrainedScalarPerception(ScalarPoolPerception(models), prior)

@dataclass(frozen=True)
class ImagePayload:
    """Virtual delivery of the original image; paths never enter DecisionView."""

    path: str
    sha256: str


def load_observation(pool: ObservationPool, row: PoolRecord) -> Observation:
    if row.payload_format == "scalar-json-v1":
        return load_scalar(pool, row)
    expected = {"rgb": "rgb-png-v1", "thermal": "thermal-png-v1"}
    if expected.get(row.modality) != row.payload_format:
        raise ValueError("Unsupported image modality or payload format")
    # Verify actual delivered bytes, rather than trusting filenames or cached features.
    pool.read_payload(row.observation_id)
    payload = ImagePayload(str(pool.payload_path(row)), row.payload_sha256)
    return Observation(row.observation_id, row.stream_id, row.modality, row.target,
                       payload, row.observation_id, pool.manifest["dataset_version"])


@lru_cache(maxsize=4096)
def image_features(payload: ImagePayload, modality: str) -> tuple[float, ...]:
    """Fixed 8x8 spatial averages + 16-bin histograms; no masks or labels."""
    content = Path(payload.path).read_bytes()
    if sha256(content).hexdigest() != payload.sha256:
        raise ValueError("Image fingerprint mismatch")
    with Image.open(BytesIO(content)) as source:
        if source.format != "PNG" or modality not in ("rgb", "thermal"):
            raise ValueError("Expected RGB/thermal PNG")
        image = source.convert("RGB" if modality == "rgb" else "L")
        thumbnail = np.asarray(image.resize((8, 8), Image.Resampling.BOX), dtype=np.float64) / 255
        pixels = np.asarray(image, dtype=np.float64) / 255
    if pixels.ndim == 2:
        pixels, thumbnail = pixels[..., None], thumbnail[..., None]
    features = [thumbnail.ravel()]
    for channel in range(pixels.shape[-1]):
        values = pixels[..., channel]
        histogram = np.histogram(values, bins=16, range=(0, 1))[0] / values.size
        features.extend((histogram, np.array([values.mean(), values.std()])))
    return tuple(float(v) for v in np.concatenate(features))


@dataclass(frozen=True)
class ImageModel:
    modality: str
    intercept: float
    coefficients: tuple[float, ...]
    center: tuple[float, ...]
    scale: tuple[float, ...]
    train_count: int
    training_sha256: str
    initial_log_loss: float
    final_log_loss: float
    version: str
    features: str = "spatial-8x8-histogram16-mean-std-v1"

    def predict(self, payload: ImagePayload) -> float:
        values = np.array(image_features(payload, self.modality))
        standardized = (values - np.array(self.center)) / np.array(self.scale)
        return sigmoid(self.intercept + float(standardized @ np.array(self.coefficients)))


@dataclass(frozen=True)
class ImagePerception:
    models: tuple[ImageModel, ...]

    @property
    def supported_modalities(self) -> tuple[str, ...]:
        return tuple(model.modality for model in self.models)

    @property
    def version(self) -> str:
        return stable_id("image-presence-perception-v1", *(m.version for m in self.models))

    def process(self, observation: Observation) -> TaskResult:
        if not isinstance(observation.payload, ImagePayload):
            raise ValueError("Image perception requires an original image payload")
        model = next((m for m in self.models if m.modality == observation.modality), None)
        if model is None:
            raise ValueError("Unsupported image modality")
        probability = model.predict(observation.payload)
        return TaskResult(observation.target, probability, binary_entropy(probability),
                          (observation.observation_id,), (model.version,))


@dataclass(frozen=True)
class TrainedImagePerception:
    perception: ImagePerception
    class_prior: float


def train_image_perception(pool: ObservationPool, modalities: tuple[str, ...],
                           config: FitConfig = FitConfig()) -> TrainedImagePerception:
    """Independent modality models; normalization and fitting use train only."""
    labels = pool.read_labels()
    rows_by_modality = {m: tuple(r for r in pool.records if r.split == "train" and r.modality == m)
                        for m in modalities}
    target_sets = [set(r.target for r in rows) for rows in rows_by_modality.values()]
    if not target_sets or not target_sets[0] or any(t != target_sets[0] for t in target_sets):
        raise ValueError("Image task requires paired training target sets")
    if any(type(labels.get(t)) is not int or labels[t] not in (0, 1) for t in target_sets[0]):
        raise ValueError("Image training requires binary reference labels")
    models = []
    for modality, rows in rows_by_modality.items():
        if len({r.target for r in rows}) != len(rows):
            raise ValueError("Image task requires one training observation per target/modality")
        x = np.array([image_features(load_observation(pool, r).payload, modality) for r in rows])
        y = np.array([labels[r.target] for r in rows], dtype=np.float64)
        if set(y) != {0, 1}:
            raise ValueError("Image training data must include both classes")
        center, scale = x.mean(axis=0), x.std(axis=0)
        scale[scale < 1e-6] = 1.0
        x = (x - center) / scale
        weights = np.zeros(x.shape[1])
        intercept = 0.0
        initial = float(np.log(2))
        # Bound the learning step using training features; fixed settings, no test tuning.
        step = config.learning_rate / max(1.0, float(np.sum(x * x) / len(x) / 4))
        for _ in range(config.epochs):
            scores = np.clip(intercept + x @ weights, -40, 40)
            error = 1 / (1 + np.exp(-scores)) - y
            intercept -= step * float(error.mean())
            weights -= step * (x.T @ error / len(y) + config.regularization * weights)
        scores = intercept + x @ weights
        final = float(np.mean(np.logaddexp(0, scores) - scores * y))
        fingerprint = sha256(json.dumps([(r.observation_id, r.payload_sha256, labels[r.target]) for r in rows],
                                        separators=(",", ":")).encode()).hexdigest()
        version = stable_id("image-logistic-v1", modality, fingerprint, repr(config),
                            repr((intercept, weights.tolist(), center.tolist(), scale.tolist())))
        models.append(ImageModel(modality, intercept, tuple(weights), tuple(center), tuple(scale),
                                 len(rows), fingerprint, initial, final, version))
    prior = (sum(labels[t] for t in target_sets[0]) + 1) / (len(target_sets[0]) + 2)
    return TrainedImagePerception(ImagePerception(tuple(models)), prior)


def train_pool(pool: ObservationPool, modalities: tuple[str, ...], config: FitConfig = FitConfig()):
    formats = {r.payload_format for r in pool.records if r.modality in modalities}
    if formats == {"scalar-json-v1"}:
        return train_scalar_perception(pool, modalities, config)
    if formats <= {"rgb-png-v1", "thermal-png-v1"}:
        return train_image_perception(pool, modalities, config)
    raise ValueError("Mixed/unsupported payload formats for the binary task")
