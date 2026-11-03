"""Signed regional error-reduction regression; no acquisition decisions or GT inputs."""

import numpy as np

from phdsim.learning.urbaning_regions import FEATURES

MODEL_SCHEMA = 'phdsim-urbaning-regional-ridge-v1'
HEADS = ('vehicle_peer', 'infrastructure', 'all')
ALPHAS = (.01, .1, 1.)
_GEOMETRY = tuple(range(4)) + tuple(range(30, 46))
_LOCAL = tuple(range(4, 11))
PROFILES = {
    'geometry': _GEOMETRY,
    'local': (3,) + _LOCAL + (30, 38),
    'geometry_local': _GEOMETRY + _LOCAL,
    'geometry_local_neighbors': _GEOMETRY + _LOCAL + (27, 28, 29),
    'full': tuple(range(len(FEATURES))),
}


def validate_inputs(features, available):
    x, mask = np.asarray(features), np.asarray(available)
    if x.ndim != 3 or x.shape[1:] != (401, len(FEATURES)) or not np.isfinite(x).all():
        raise ValueError('Expected finite frames x 401 x ordered input features')
    if mask.dtype != bool or mask.shape != (len(x), 4) or not mask[:, 0].all():
        raise ValueError('Invalid public availability mask')
    if not np.array_equal(mask[:, 3], mask[:, 1] & mask[:, 2]):
        raise ValueError('Joint availability must require both peers')
    for j, col in ((1, 30), (2, 38)):
        if not np.array_equal(x[:, :, col], np.broadcast_to(mask[:, j, None], x.shape[:2])):
            raise ValueError('Feature/mask availability differs')
    return x, mask


def fit_candidates(features, available, targets, profile):
    """Train-only scaling and three separately masked action heads, four classes each.

    Objective per action/class: mean((prediction-target)**2) + alpha*||w||².
    Intercept is unpenalized; all 401 cells retained with equal cell weight.
    The joint action is directly supervised, never a sum of single-peer heads.
    """
    x, mask = validate_inputs(features, available)
    y = np.asarray(targets)
    if y.shape != (len(x), 401, 3, 4) or not np.isfinite(y).all():
        raise ValueError('Invalid signed error-reduction targets')
    indices = PROFILES[profile]
    models = [{'schema': MODEL_SCHEMA, 'profile': profile, 'alpha': a,
               'input_features': list(FEATURES), 'selected_indices': list(indices),
               'selected_features': [FEATURES[i] for i in indices],
               'target': '-(delta_fp + delta_fn), separately by class',
               'heads': {}} for a in ALPHAS]
    for j, action in enumerate(HEADS):
        valid = mask[:, j+1]
        if valid.sum() < 2:
            raise ValueError('Need at least two feasible training frames per action')
        a = x[valid][:, :, indices].reshape(-1, len(indices)).astype(float)
        b = y[valid, :, j].reshape(-1, 4).astype(float)
        mean, scale = a.mean(axis=0), a.std(axis=0)
        scale[scale < 1e-8] = 1.
        design = np.column_stack((np.ones(len(a)), (a - mean) / scale))
        gram, rhs = design.T @ design / len(a), design.T @ b / len(a)
        penalty = np.eye(design.shape[1]); penalty[0, 0] = 0.
        for model in models:
            weights = np.linalg.solve(gram + model['alpha'] * penalty, rhs)
            model['heads'][action] = {'mean': mean.tolist(), 'scale': scale.tolist(),
                                      'weights': weights.tolist(), 'train_frames': int(valid.sum()),
                                      'train_cells': len(a)}
    return models


def predict(model, features, available):
    """Deployment boundary: accepts only Car1 summaries and public metadata.

    Unavailable heads are zero placeholders; callers must retain the mask.
    Signed predictions are not clipped or interpreted as F1 gains/probabilities.
    """
    x, mask = validate_inputs(features, available)
    profile = model.get('profile')
    if (model.get('schema') != MODEL_SCHEMA or profile not in PROFILES
            or model.get('input_features') != list(FEATURES)
            or model.get('selected_indices') != list(PROFILES[profile])
            or model.get('selected_features') != [FEATURES[i] for i in PROFILES[profile]]):
        raise ValueError('Unsupported regional model or reordered features')
    selected = x[:, :, PROFILES[profile]].astype(float)
    result = np.zeros((len(x), 401, 3, 4))
    for j, action in enumerate(HEADS):
        head = model['heads'][action]
        mean, scale, weights = (np.asarray(head[k], float) for k in ('mean', 'scale', 'weights'))
        width = len(PROFILES[profile])
        if (mean.shape != (width,) or scale.shape != (width,) or weights.shape != (width+1, 4)
                or not all(np.isfinite(v).all() for v in (mean, scale, weights)) or (scale <= 0).any()):
            raise ValueError('Malformed regional model coefficients')
        result[:, :, j] = ((selected - mean) / scale) @ weights[1:] + weights[0]
        result[~mask[:, j+1], :, j] = 0.
    if not np.isfinite(result).all():
        raise ValueError('Nonfinite regional predictions')
    return result
