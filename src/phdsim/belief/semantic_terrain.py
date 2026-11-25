"""Cell features and a diagonal Gaussian classifier for registered terrain samples."""

from dataclasses import dataclass
from math import exp, fsum, isfinite, log, sqrt
from statistics import fmean, pvariance
from typing import Iterable, Literal

from phdsim.core.grid import Cell


Mode = Literal["rgb", "lidar", "fused"]
MODES: tuple[Mode, ...] = ("rgb", "lidar", "fused")


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    cell_size_m: float

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (self.width, self.height)):
            raise ValueError("grid dimensions must be positive integers")
        if not isfinite(self.cell_size_m) or self.cell_size_m <= 0:
            raise ValueError("cell_size_m must be positive and finite")

    def index(self, xy: Cell) -> int:
        x, y = xy
        if not (type(x) is int and type(y) is int and 0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"cell outside grid: {xy}")
        return y * self.width + x


@dataclass(frozen=True)
class Sample:
    """One valid return. Values are normalized RGB or one surface elevation in metres."""

    xy: Cell
    values: tuple[float, ...]


@dataclass(frozen=True)
class Capture:
    observation_id: str
    sensor_id: str
    modality: Literal["rgb", "lidar"]
    capture_tick: int
    samples: tuple[Sample, ...]


@dataclass(frozen=True)
class Feature:
    values: tuple[float, ...]
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class CellFeatures:
    rgb: Feature | None
    lidar: Feature | None


def extract_features(grid: Grid, captures: Iterable[Capture]) -> tuple[CellFeatures, ...]:
    """Pool valid samples, counting an immutable capture only once, in row-major order."""
    unique = {}
    for capture in captures:
        if not capture.observation_id or not capture.sensor_id or capture.modality not in ("rgb", "lidar"):
            raise ValueError("a capture needs an ID, sensor ID and supported modality")
        previous = unique.setdefault(capture.observation_id, capture)
        if previous != capture:
            raise ValueError(f"conflicting capture for observation ID {capture.observation_id!r}")

    returns = {"rgb": {}, "lidar": {}}
    for oid, capture in sorted(unique.items()):
        cells = returns[capture.modality]
        channels = 3 if capture.modality == "rgb" else 1
        for sample in capture.samples:
            i = grid.index(sample.xy)
            if len(sample.values) != channels or not all(map(isfinite, sample.values)):
                raise ValueError(f"invalid {capture.modality} sample at {sample.xy}")
            if channels == 3 and not all(0 <= v <= 1 for v in sample.values):
                raise ValueError("RGB samples must be normalized")
            cells.setdefault(i, []).append((oid, sample.values))

    def pool(samples):
        ids, vectors = zip(*samples)
        return Feature(tuple(map(fmean, zip(*vectors))), tuple(sorted(set(ids))))

    rgb = {i: pool(records) for i, records in returns["rgb"].items()}
    heights = {i: pool(records) for i, records in returns["lidar"].items()}
    roughness = {}
    for i, center in heights.items():
        x, y = i % grid.width, i // grid.width
        neighbors = [heights[j] for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))
                     if 0 <= nx < grid.width and 0 <= ny < grid.height
                     and (j := ny * grid.width + nx) in heights]
        if neighbors:
            # RMS of observed one-cell slopes. An isolated return has no slope estimate.
            rms = sqrt(fmean((n.values[0] - center.values[0])**2 for n in neighbors)) / grid.cell_size_m
            ids = set(center.observation_ids).union(*(n.observation_ids for n in neighbors))
            roughness[i] = Feature((rms,), tuple(sorted(ids)))
    return tuple(CellFeatures(rgb.get(i), roughness.get(i)) for i in range(grid.width * grid.height))


@dataclass(frozen=True)
class Gaussian:
    mean: tuple[float, ...]
    variance: tuple[float, ...]

    @classmethod
    def fit(cls, vectors, min_std: float):
        columns = tuple(zip(*vectors, strict=True))
        if not columns:
            raise ValueError("each training class needs valid features from each modality")
        return cls(tuple(map(fmean, columns)), tuple(max(pvariance(c), min_std**2) for c in columns))

    def log_likelihood(self, feature: Feature) -> float:
        # The common Gaussian normalization constant cancels across classes.
        return -0.5 * fsum(log(v) + (x - m)**2 / v
                           for x, m, v in zip(feature.values, self.mean, self.variance, strict=True))


@dataclass(frozen=True)
class Prediction:
    label: str
    probabilities: tuple[float, ...]
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class TerrainClassifier:
    """Equal class priors, independent Gaussian features conditional on class."""

    classes: tuple[str, ...]
    rgb: tuple[Gaussian, ...]
    lidar: tuple[Gaussian, ...]

    @classmethod
    def fit(cls, classes: tuple[str, ...], examples: Iterable[tuple[str, CellFeatures]]):
        """Offline supervision. Variable sensor support is kept in each training scene."""
        if not classes or len(set(classes)) != len(classes):
            raise ValueError("classes must be nonempty and unique")
        groups = {label: [] for label in classes}
        for label, cell in examples:
            groups[label].append(cell)
        # Floors in normalized channel units and metres per metre, respectively.
        rgb = tuple(Gaussian.fit((c.rgb.values for c in group if c.rgb), 0.04) for group in groups.values())
        lidar = tuple(Gaussian.fit((c.lidar.values for c in group if c.lidar), 0.02) for group in groups.values())
        return cls(classes, rgb, lidar)

    def predict(self, cells: Iterable[CellFeatures], mode: Mode) -> tuple[Prediction | None, ...]:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        predictions = []
        for cell in cells:
            evidence = []
            if cell.rgb is not None and mode in ("rgb", "fused"):
                evidence.append((cell.rgb, self.rgb))
            if cell.lidar is not None and mode in ("lidar", "fused"):
                evidence.append((cell.lidar, self.lidar))
            if not evidence:
                predictions.append(None)
                continue
            scores = [fsum(models[i].log_likelihood(f) for f, models in evidence)
                      for i in range(len(self.classes))]
            best = max(range(len(scores)), key=scores.__getitem__)
            weights = [exp(s - scores[best]) for s in scores]
            total = fsum(weights)
            ids = tuple(sorted({oid for f, _ in evidence for oid in f.observation_ids}))
            predictions.append(Prediction(self.classes[best], tuple(w / total for w in weights), ids))
        return tuple(predictions)
