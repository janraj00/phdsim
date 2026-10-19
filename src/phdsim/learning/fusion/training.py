"""Fit late fusion and generate predictions excluding each held-out recording family."""

import numpy as np
from .features import fusion_features
from phdsim.models.linear import fit_linear


def fit_fusion(samples, regularization):
    return fit_linear([fusion_features(s['rgb'].probability, s['thermal'].probability) for s in samples],
                      [s['label'] for s in samples], kind='logistic', regularization=regularization)


def fused_probabilities(train, evaluate, method, regularization):
    if method == 'mean_probability':
        return [(s['rgb'].probability + s['thermal'].probability) / 2 for s in evaluate]
    if method != 'learned_probability':
        raise ValueError('Unsupported meta fusion method')
    model = fit_fusion(train, regularization)
    return [model.predict(fusion_features(s['rgb'].probability, s['thermal'].probability)) for s in evaluate]


def crossfit_fusion(samples, method, regularization):
    groups = sorted({s['group'] for s in samples})
    probabilities = np.zeros(len(samples))
    for group in groups:
        train = [s for s in samples if s['group'] != group]
        indices = [i for i, s in enumerate(samples) if s['group'] == group]
        values = fused_probabilities(train, [samples[i] for i in indices], method, regularization)
        probabilities[indices] = values
    return probabilities
