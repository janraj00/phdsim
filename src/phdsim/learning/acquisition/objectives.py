"""Offline task losses that define the value of an additional observation."""

from math import isfinite
import numpy as np

GAIN_METRICS = ('brier', 'classification_error')


def task_loss(probability, label, metric):
    if not isfinite(probability) or not 0 <= probability <= 1 or label not in (0, 1):
        raise ValueError('Task loss requires a probability and binary reference label')
    if metric == 'brier':
        return (probability - label) ** 2
    if metric == 'classification_error':
        return float((probability >= 0.5) != (label == 1))
    raise ValueError(f'Unknown acquisition gain metric: {metric}')


def teacher_description(metric):
    if metric == 'classification_error':
        return 'classification error before - after, threshold 0.5; +1 repairs, -1 damages, 0 unchanged'
    if metric == 'brier':
        return 'Brier(own, label) - Brier(after fusion, label); negative gains retained'
    raise ValueError(f'Unknown acquisition gain metric: {metric}')


def gains(samples, probabilities, modality, metric='brier'):
    return np.array([task_loss(s[modality].probability, s['label'], metric) - task_loss(p, s['label'], metric)
                     for s, p in zip(samples, probabilities)])
