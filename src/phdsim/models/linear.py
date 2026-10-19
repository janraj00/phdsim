"""Small regularized models, persisted as plain JSON without pickle."""

from dataclasses import dataclass
import numpy as np

from phdsim.probability import sigmoid


@dataclass(frozen=True)
class LinearModel:
    kind: str
    center: tuple[float, ...]
    scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    regularization: float

    def __post_init__(self):
        values = (*self.center, *self.scale, *self.coefficients, self.intercept, self.regularization)
        if self.kind not in ('logistic', 'ridge') or not all(np.isfinite(v) for v in values):
            raise ValueError('Invalid fitted linear model')
        if not self.center or not len(self.center) == len(self.scale) == len(self.coefficients):
            raise ValueError('Model feature dimensions differ')
        if min(self.scale) <= 0 or self.regularization <= 0:
            raise ValueError('Model scale and regularization must be positive')

    def predict(self, features):
        if len(features) != len(self.center) or not all(np.isfinite(v) for v in features):
            raise ValueError('Unexpected model features')
        value = self.intercept + sum(w * (x - c) / s for x, c, s, w in
                                     zip(features, self.center, self.scale, self.coefficients))
        return sigmoid(value) if self.kind == 'logistic' else float(value)

    @classmethod
    def from_dict(cls, row):
        return cls(**{**row, **{k: tuple(row[k]) for k in ('center', 'scale', 'coefficients')}})


def fit_linear(features, targets, *, kind, regularization):
    x, y = np.asarray(features, dtype=float), np.asarray(targets, dtype=float)
    if x.ndim != 2 or len(x) != len(y) or len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid training samples')
    if kind == 'logistic' and not set(y) <= {0, 1}:
        raise ValueError('Logistic fitting needs binary labels')
    center, scale = x.mean(0), x.std(0)
    scale[scale < 1e-8] = 1
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    penalty = np.eye(design.shape[1]) * regularization
    penalty[0, 0] = 0
    if kind == 'logistic':
        # A weak intercept prior makes single-class inner recording folds well-defined.
        penalty[0, 0] = 0.1
    if kind == 'ridge':
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    elif kind == 'logistic':
        weights = np.zeros(design.shape[1])
        weights[0] = np.log((y.sum() + 0.5) / (len(y) - y.sum() + 0.5))
        def loss(w):
            z = design @ w
            return np.sum(np.logaddexp(0, z) - y * z) + 0.5 * w @ penalty @ w
        for _ in range(80):
            z = design @ weights
            p = 1 / (1 + np.exp(-np.clip(z, -40, 40)))
            gradient = design.T @ (p - y) + penalty @ weights
            hessian = design.T @ ((p * (1 - p))[:, None] * design) + penalty
            step = np.linalg.solve(hessian + np.eye(len(weights)) * 1e-10, gradient)
            rate, before = 1., loss(weights)
            while rate > 1e-8 and loss(weights - rate * step) > before:
                rate *= 0.5
            weights -= rate * step
            if np.max(np.abs(rate * step)) < 1e-8:
                break
    else:
        raise ValueError('Unknown fitting objective')
    return LinearModel(kind, tuple(center), tuple(scale), tuple(weights[1:]), float(weights[0]), regularization)
