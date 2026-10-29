"""Small joint-subset gain predictor; fitting is strictly offline."""

import math
import re

import numpy as np

from phdsim.decision.urbaning import available_subsets, choose_subset

SCHEMA = 'phdsim-urbaning-joint-gain-v1'
TARGET = 'frame-micro-F1-BEV-IoU-0.5-minus-ego'
HEADS = ('vehicle_peer', 'infrastructure', 'all')
FEATURES = ('entropy_bits', 'detection_count_over_150', 'score_mean', 'score_std',
            'score_q10', 'score_q90') + tuple(
                'class_{}_{}'.format(c, stat) for c in range(1, 5)
                for stat in ('count_over_150', 'score_mean')) + ('vehicle_available', 'infra_available')


def recording_group(sequence):
    """Keep segments/views of the same original recording in one split."""
    match = re.fullmatch(r'(\d{8}_\d{4})_crossing[123]_\d{2}', sequence)
    if not match:
        raise ValueError('Invalid UrbanIng sequence identity')
    return match.group(1)


def ego_features(source_ids, entropy, ego_scores):
    """Only Car1 scores, Car1 entropy and available source categories.

    No timestamp, frame ID, GT, peer predictions or peer payload is accepted.
    Confidence summaries are features, not calibrated error probabilities.
    """
    scores = np.asarray(ego_scores, dtype=float)
    if scores.shape != (len(scores), 2) or not np.isfinite(scores).all():
        raise ValueError('Expected finite Nx2 ego scores')
    if (not math.isfinite(entropy) or not 0 <= entropy <= 1 or
            np.any((scores[:, 0] < 0) | (scores[:, 0] > 1)) or
            np.any(~np.isin(scores[:, 1], [1, 2, 3, 4]))):
        raise ValueError('Invalid ego evidence')
    confidence = scores[:, 0]
    values = [entropy, len(scores) / 150.]
    values.extend([float(confidence.mean()), float(confidence.std()),
                   float(np.quantile(confidence, .1)), float(np.quantile(confidence, .9))]
                  if len(scores) else [0.] * 4)
    for c in range(1, 5):
        selected = confidence[scores[:, 1] == c]
        values.extend([len(selected) / 150., float(selected.mean()) if len(selected) else 0.])
    options = available_subsets(source_ids)
    values.extend([float('vehicle_peer' in options), float('infrastructure' in options)])
    return np.asarray(values)


def fit_joint_gain(features, targets, available, alpha, train_sequences):
    """Fit three separate ridge heads, including an explicit both-partners head.

    targets/availability are Nx3 in HEADS order. Unavailable outcomes are not
    turned into ego fallback examples. Scaling and fitting use training only.
    """
    x, y, mask = np.asarray(features, float), np.asarray(targets, float), np.asarray(available, bool)
    if (x.ndim != 2 or x.shape[1] != len(FEATURES) or len(x) < 2 or
            y.shape != (len(x), 3) or mask.shape != y.shape or
            not np.isfinite(x).all() or not np.isfinite(y).all() or
            not math.isfinite(alpha) or alpha <= 0):
        raise ValueError('Invalid training arrays or regularization')
    sequences = sorted(set(train_sequences))
    if not sequences or any('crossing3' in s for s in sequences):
        raise ValueError('Reserve crossing3 for final evaluation')
    groups = sorted({recording_group(s) for s in sequences})
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-8] = 1.
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    penalty = np.diag([0.] + [alpha] * len(FEATURES))
    heads = {}
    for j, name in enumerate(HEADS):
        selected = mask[:, j]
        if selected.sum() < 2:
            raise ValueError('Need at least two feasible training examples for ' + name)
        a, b = design[selected], y[selected, j]
        heads[name] = np.linalg.solve(a.T @ a + penalty, a.T @ b).tolist()
    return {'schema': SCHEMA, 'target': TARGET, 'features': list(FEATURES),
            'mean': mean.tolist(), 'scale': scale.tolist(), 'heads': heads,
            'alpha': alpha, 'train_sequences': sequences, 'train_recording_groups': groups}


def predict_gains(model, features):
    if model.get('schema') != SCHEMA or model.get('target') != TARGET or model.get('features') != list(FEATURES):
        raise ValueError('Incompatible gain model')
    x = np.asarray(features, float)
    mean, scale = np.asarray(model['mean'], float), np.asarray(model['scale'], float)
    if (x.shape != (len(FEATURES),) or mean.shape != x.shape or scale.shape != x.shape or
            not np.isfinite([x, mean, scale]).all() or np.any(scale <= 0)):
        raise ValueError('Invalid model scaling or evidence')
    design = np.r_[1., (x - mean) / scale]
    result = {}
    for name in HEADS:
        weights = np.asarray(model['heads'][name], float)
        if weights.shape != design.shape or not np.isfinite(weights).all():
            raise ValueError('Invalid gain-model weights')
        result[name] = float(design @ weights)
    return result


def choose_learned_subset(model, source_ids, entropy, ego_scores):
    gains = predict_gains(model, ego_features(source_ids, entropy, ego_scores))
    return choose_subset(source_ids, gains, model['request_cost'])


def assert_unseen_recordings(model, sequences):
    used = set(model['train_recording_groups']) | set(model.get('validation_recording_groups', []))
    if used.intersection(recording_group(s) for s in sequences):
        raise ValueError('Evaluation overlaps policy training/validation recordings')
