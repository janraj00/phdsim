"""Offline boosted gain heads with a plain JSON, NumPy-only predictor.

No detector, labels, or peer payloads enter the prediction interface. Existing
ridge model formats and their deployed consumers are deliberately unchanged.
"""

import math

import numpy as np

from phdsim.learning.urbaning import HEADS, TARGET, feature_spec, recording_group

SCHEMA = 'phdsim-urbaning-boosted-gain-v1'


def export_regressor(regressor):
    """Export squared-error GradientBoostingRegressor; never load pickle files."""
    if regressor.loss != 'squared_error':
        raise ValueError('Only the squared-error constant initializer is supported')
    return {'initial': float(regressor.init_.constant_.ravel()[0]),
            'learning_rate': float(regressor.learning_rate),
            'trees': [{'left': t.tree_.children_left.tolist(),
                       'right': t.tree_.children_right.tolist(),
                       'feature': t.tree_.feature.tolist(),
                       'threshold': t.tree_.threshold.tolist(),
                       'value': t.tree_.value[:, 0, 0].tolist()}
                      for t in regressor.estimators_[:, 0]]}


def predict_regressor(head, features):
    # sklearn's decision trees convert their input to float32 before branching.
    x = np.asarray(features, dtype=np.float32)
    if x.ndim != 1 or not np.isfinite(x).all():
        raise ValueError('Expected finite feature vector')
    initial, rate = head['initial'], head['learning_rate']
    if not math.isfinite(initial) or not math.isfinite(rate) or rate <= 0 or not head['trees']:
        raise ValueError('Invalid boosted head')
    total = float(initial)
    for tree in head['trees']:
        left, right, feature = (np.asarray(tree[k]) for k in ('left', 'right', 'feature'))
        threshold, value = (np.asarray(tree[k], dtype=float) for k in ('threshold', 'value'))
        n = len(left)
        if (n < 1 or any(a.shape != (n,) for a in (right, feature, threshold, value)) or
                any(a.dtype.kind not in 'iu' for a in (left, right, feature)) or
                not np.isfinite(threshold).all() or not np.isfinite(value).all()):
            raise ValueError('Invalid tree arrays')
        leaf = (left == -1) & (right == -1)
        branch = ~leaf
        nodes = np.arange(n)
        # Children strictly follow their parent: malformed JSON cannot loop.
        if (np.any(left[branch] <= nodes[branch]) or np.any(right[branch] <= nodes[branch]) or
                np.any(left[branch] >= n) or np.any(right[branch] >= n) or
                np.any(feature[branch] < 0) or np.any(feature[branch] >= len(x))):
            raise ValueError('Invalid tree topology or split feature')
        children = np.r_[left[branch], right[branch]]
        if not np.array_equal(np.sort(children), np.arange(1, n)):
            raise ValueError('Expected a connected tree with one parent per node')
        node = 0
        while not leaf[node]:
            node = left[node] if x[feature[node]] <= threshold[node] else right[node]
        total += rate * value[node]
    return float(total)


def fit_tree_gain(features, targets, available, train_sequences, feature_schema, *,
                  max_depth, min_samples_leaf, n_estimators=100, learning_rate=.05, seed=42):
    """Fit independent heads on feasible training outcomes, including joint gain."""
    from sklearn import __version__ as sklearn_version
    from sklearn.ensemble import GradientBoostingRegressor

    names = feature_spec(feature_schema)
    x, y, mask = np.asarray(features, float), np.asarray(targets, float), np.asarray(available, bool)
    if (x.ndim != 2 or x.shape[1] != len(names) or len(x) < 2 or
            y.shape != (len(x), 3) or mask.shape != y.shape or
            not np.isfinite(x).all() or not np.isfinite(y).all()):
        raise ValueError('Invalid training arrays')
    sequences = sorted(set(train_sequences))
    if not sequences or any('crossing3' in s for s in sequences):
        raise ValueError('Reserve crossing3; fit only on crossing1/2')
    groups = sorted({recording_group(s) for s in sequences})
    parameters = dict(loss='squared_error', max_depth=max_depth,
                      min_samples_leaf=min_samples_leaf, n_estimators=n_estimators,
                      learning_rate=learning_rate, random_state=seed, subsample=1.)
    heads, counts = {}, {}
    for j, name in enumerate(HEADS):
        selected = mask[:, j]
        if selected.sum() < 2:
            raise ValueError('Need at least two feasible training examples for ' + name)
        regressor = GradientBoostingRegressor(**parameters).fit(x[selected], y[selected, j])
        heads[name] = export_regressor(regressor)
        counts[name] = int(selected.sum())
    return {'schema': SCHEMA, 'feature_schema': feature_schema, 'target': TARGET,
            'features': list(names), 'heads': heads, 'parameters': parameters,
            'train_sequences': sequences, 'train_recording_groups': groups,
            'feasible_training_frames': counts, 'sklearn_version': sklearn_version}


def predict_tree_gains(model, features):
    names = feature_spec(model.get('feature_schema'))
    if (model.get('schema') != SCHEMA or model.get('target') != TARGET or
            model.get('features') != list(names) or np.shape(features) != (len(names),)):
        raise ValueError('Incompatible boosted gain model or evidence')
    return {name: predict_regressor(model['heads'][name], features) for name in HEADS}
