'Probability helpers.'
from __future__ import annotations

from math import exp, log, log1p

def sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    value_exp = exp(value)
    return value_exp / (1.0 + value_exp)

def logit(probability: float) -> float:
    clipped = min(1 - 1e-12, max(1e-12, probability))
    return log(clipped) - log1p(-clipped)

def binary_entropy(probability: float) -> float:
    if probability <= 0 or probability >= 1:
        return 0.0
    return -(probability * log(probability) + (1 - probability) * log1p(-probability)) / log(2)
