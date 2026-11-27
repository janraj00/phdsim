"""Joint diagonal Gaussian mixture classifier for multimodal terrain features.

Each class is modeled as a mixture of diagonal Gaussians over the joint
(RGB, LiDAR) feature vector. Missing modalities are handled by exact
marginalization over the unobserved coordinates, so a single fitted model
supports RGB-only, LiDAR-only and fused inference without assuming conditional
independence between appearance and surface geometry within a class.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, fsum, log, sqrt
from statistics import fmean
from typing import Iterable

from phdsim.belief.semantic_terrain import MODES, CellFeatures, Mode, Prediction
from phdsim.core.randomness import keyed_rng


_RGB_DIMS = 3
_LIDAR_DIMS = 1
_JOINT_DIMS = _RGB_DIMS + _LIDAR_DIMS
_MIN_VARIANCE = (0.04**2, 0.04**2, 0.04**2, 0.02**2)


@dataclass(frozen=True)
class MixtureComponent:
    """One diagonal Gaussian component over joint (R, G, B, LiDAR roughness) features."""

    weight: float
    mean: tuple[float, float, float, float]
    variance: tuple[float, float, float, float]

    def __post_init__(self):
        if not (0.0 < self.weight <= 1.0):
            raise ValueError("component weight must be in (0, 1]")
        if len(self.mean) != _JOINT_DIMS or len(self.variance) != _JOINT_DIMS:
            raise ValueError(f"component parameters must have {_JOINT_DIMS} dimensions")
        if any(v <= 0.0 for v in self.variance):
            raise ValueError("component variances must be positive")

    def _compiled(self) -> tuple[float, ...]:
        m0, m1, m2, m3 = self.mean
        v0, v1, v2, v3 = self.variance
        lw = log(self.weight)
        lv0, lv1, lv2, lv3 = log(v0), log(v1), log(v2), log(v3)
        return (
            m0, m1, m2, m3,
            0.5 / v0, 0.5 / v1, 0.5 / v2, 0.5 / v3,
            lw - 0.5 * (lv0 + lv1 + lv2),
            lw - 0.5 * lv3,
            lw - 0.5 * (lv0 + lv1 + lv2 + lv3),
        )


def _fit_class_mixture(
    points: list[tuple[float, float, float, float]],
    *,
    class_name: str,
    n_components: int,
    n_iters: int,
    seed: int,
) -> tuple[MixtureComponent, ...]:
    k = min(n_components, len(points))
    rng = keyed_rng(seed, "joint-gmm-init", class_name, n_components)

    col_means = [fmean(p[d] for p in points) for d in range(_JOINT_DIMS)]
    col_stds = [
        max(sqrt(fmean((p[d] - col_means[d]) ** 2 for p in points)), sqrt(_MIN_VARIANCE[d]))
        for d in range(_JOINT_DIMS)
    ]

    def sq_dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return (
            ((a[0] - b[0]) / col_stds[0]) ** 2
            + ((a[1] - b[1]) / col_stds[1]) ** 2
            + ((a[2] - b[2]) / col_stds[2]) ** 2
            + ((a[3] - b[3]) / col_stds[3]) ** 2
        )

    # Deterministic k-means++ seeding in standardized feature space.
    centers = [points[rng.randrange(len(points))]]
    while len(centers) < k:
        dists = [min(sq_dist(p, c) for c in centers) for p in points]
        total_d = fsum(dists)
        if total_d <= 0.0:
            centers.append(points[rng.randrange(len(points))])
            continue
        target = rng.random() * total_d
        acc = 0.0
        chosen = points[-1]
        for p, dist_val in zip(points, dists, strict=True):
            acc += dist_val
            if acc >= target:
                chosen = p
                break
        centers.append(chosen)

    weights = [1.0 / k] * k
    means = [list(c) for c in centers]
    variances = [[max(col_stds[d] ** 2 * 0.5, _MIN_VARIANCE[d]) for d in range(_JOINT_DIMS)] for _ in range(k)]

    n_points = len(points)
    for _ in range(n_iters):
        compiled = [
            MixtureComponent(max(weights[j], 1e-12), tuple(means[j]), tuple(variances[j]))._compiled()
            for j in range(k)
        ]
        resp_sum = [0.0] * k
        mean_num = [[0.0] * _JOINT_DIMS for _ in range(k)]
        m2_num = [[0.0] * _JOINT_DIMS for _ in range(k)]
        for x0, x1, x2, x3 in points:
            log_p = [
                c[10] - ((x0 - c[0]) ** 2 * c[4] + (x1 - c[1]) ** 2 * c[5]
                         + (x2 - c[2]) ** 2 * c[6] + (x3 - c[3]) ** 2 * c[7])
                for c in compiled
            ]
            top = max(log_p)
            raw = [exp(v - top) for v in log_p]
            inv_denom = 1.0 / fsum(raw)
            for j in range(k):
                r = raw[j] * inv_denom
                resp_sum[j] += r
                mn, m2n = mean_num[j], m2_num[j]
                mn[0] += r * x0
                mn[1] += r * x1
                mn[2] += r * x2
                mn[3] += r * x3
                m2n[0] += r * x0 * x0
                m2n[1] += r * x1 * x1
                m2n[2] += r * x2 * x2
                m2n[3] += r * x3 * x3

        for j in range(k):
            nk = resp_sum[j]
            if nk < 1e-6:
                weights[j] = 0.0
                continue
            weights[j] = nk / n_points
            for d in range(_JOINT_DIMS):
                mu = mean_num[j][d] / nk
                means[j][d] = mu
                variances[j][d] = max(m2_num[j][d] / nk - mu * mu, _MIN_VARIANCE[d])

    active = [(weights[j], tuple(means[j]), tuple(variances[j])) for j in range(k) if weights[j] > 1e-6]
    total_w = fsum(w for w, _, _ in active)
    return tuple(MixtureComponent(w / total_w, m, v) for w, m, v in active)


@dataclass(frozen=True)
class JointGMMClassifier:
    """Equal class priors with a per-class joint diagonal Gaussian mixture."""

    classes: tuple[str, ...]
    mixtures: tuple[tuple[MixtureComponent, ...], ...]

    @classmethod
    def fit(
        cls,
        classes: tuple[str, ...],
        examples: Iterable[tuple[str, CellFeatures]],
        *,
        n_components: int = 3,
        n_iters: int = 25,
        seed: int = 0,
    ) -> JointGMMClassifier:
        """Offline supervision using paired (RGB, LiDAR) cell features."""
        if not classes or len(set(classes)) != len(classes):
            raise ValueError("classes must be nonempty and unique")
        if type(n_components) is not int or n_components < 1:
            raise ValueError("n_components must be a positive integer")
        if type(n_iters) is not int or n_iters < 1:
            raise ValueError("n_iters must be a positive integer")
        if type(seed) is not int:
            raise ValueError("seed must be an integer")

        groups: dict[str, list[tuple[float, float, float, float]]] = {label: [] for label in classes}
        for label, cell in examples:
            if label not in groups:
                raise ValueError(f"unknown class label {label!r}")
            if cell.rgb is not None and cell.lidar is not None:
                if len(cell.rgb.values) != _RGB_DIMS or len(cell.lidar.values) != _LIDAR_DIMS:
                    raise ValueError("expected 3 RGB channels and 1 LiDAR feature")
                groups[label].append((*cell.rgb.values, *cell.lidar.values))

        mixtures = []
        for label in classes:
            if not groups[label]:
                raise ValueError(f"class {label!r} needs paired RGB and LiDAR training features")
            mixtures.append(
                _fit_class_mixture(
                    groups[label],
                    class_name=label,
                    n_components=n_components,
                    n_iters=n_iters,
                    seed=seed,
                )
            )
        return cls(classes, tuple(mixtures))

    def predict(self, cells: Iterable[CellFeatures], mode: Mode) -> tuple[Prediction | None, ...]:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")

        compiled_mixtures = tuple(tuple(comp._compiled() for comp in comps) for comps in self.mixtures)
        n_classes = len(self.classes)
        predictions: list[Prediction | None] = []
        for cell in cells:
            rgb = cell.rgb if mode in ("rgb", "fused") else None
            lidar = cell.lidar if mode in ("lidar", "fused") else None
            if rgb is None and lidar is None:
                predictions.append(None)
                continue

            scores: list[float] = []
            if rgb is not None and lidar is not None:
                x0, x1, x2 = rgb.values
                x3 = lidar.values[0]
                ids = tuple(sorted(set(rgb.observation_ids) | set(lidar.observation_ids)))
                for comps in compiled_mixtures:
                    comp_logs = [
                        c[10] - ((x0 - c[0]) ** 2 * c[4] + (x1 - c[1]) ** 2 * c[5]
                                 + (x2 - c[2]) ** 2 * c[6] + (x3 - c[3]) ** 2 * c[7])
                        for c in comps
                    ]
                    top = max(comp_logs)
                    scores.append(top + log(fsum(exp(v - top) for v in comp_logs)))
            elif rgb is not None:
                x0, x1, x2 = rgb.values
                ids = rgb.observation_ids
                for comps in compiled_mixtures:
                    comp_logs = [
                        c[8] - ((x0 - c[0]) ** 2 * c[4] + (x1 - c[1]) ** 2 * c[5] + (x2 - c[2]) ** 2 * c[6])
                        for c in comps
                    ]
                    top = max(comp_logs)
                    scores.append(top + log(fsum(exp(v - top) for v in comp_logs)))
            else:
                x3 = lidar.values[0]
                ids = lidar.observation_ids
                for comps in compiled_mixtures:
                    comp_logs = [c[9] - (x3 - c[3]) ** 2 * c[7] for c in comps]
                    top = max(comp_logs)
                    scores.append(top + log(fsum(exp(v - top) for v in comp_logs)))

            best = max(range(n_classes), key=scores.__getitem__)
            top_score = scores[best]
            weights = [exp(s - top_score) for s in scores]
            inv_total = 1.0 / fsum(weights)
            predictions.append(Prediction(self.classes[best], tuple(w * inv_total for w in weights), ids))
        return tuple(predictions)
