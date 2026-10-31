"""Pre-query geometry features: ego detections and explicitly shared peer poses.

Pose transforms are peer LiDAR frame -> ego LiDAR frame. No peer detections,
point clouds or ground truth are accepted. Infrastructure pose is a site-frame
origin proxy, not a physical roadside sensor position or visibility estimate.
"""

import numpy as np

from phdsim.learning.urbaning import FEATURES as EGO_FEATURES, ego_features
from phdsim.decision.urbaning import available_subsets

SCHEMA = 'phdsim-urbaning-joint-gain-geometry-v1'
PEER_FEATURES = ('dx_over_100', 'dy_over_100', 'heading_sin', 'heading_cos',
                 'uncertain_count_over_150', 'uncertain_min_distance_over_100',
                 'uncertain_mean_distance_over_100', 'uncertain_view_cosine')
FEATURES = EGO_FEATURES + tuple(
    role + '_' + name for role in ('vehicle', 'infra') for name in PEER_FEATURES)
SCORE_THRESHOLD = .5  # fixed feature definition, never selected using test labels


def validate_transform(value):
    matrix = np.asarray(value, float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all() or
            not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-6) or
            not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-5) or
            not np.isclose(np.linalg.det(matrix[:3, :3]), 1., atol=1e-5)):
        raise ValueError('Expected a finite rigid peer-to-ego transform')
    return matrix


def geometry_features(source_ids, entropy, ego_scores, ego_boxes, peer_to_ego):
    """32 features, invariant to detection order; all geometry uses ego coordinates.

Low-score means detection score < .5, not a calibrated error probability.
Distance is in 3D projected to the BEV plane. No-low-score and absent-peer
distance features are zero, disambiguated by counts and availability flags.
"""
    base = ego_features(source_ids, entropy, ego_scores)
    boxes = np.asarray(ego_boxes, float)
    if boxes.shape != (len(ego_scores), 8, 3) or not np.isfinite(boxes).all():
        raise ValueError('Expected finite ego Nx8x3 boxes aligned with scores')
    ids = [str(i) for i in source_ids]
    if set(peer_to_ego) != set(ids[1:]):
        raise ValueError('Pose metadata must cover exactly the available peers')
    matrices = {key: validate_transform(value) for key, value in peer_to_ego.items()}
    scores = np.asarray(ego_scores, float)[:, 0]
    low = scores < SCORE_THRESHOLD
    centers = boxes.mean(axis=1)[low, :2]
    weights = 1. - scores[low]
    features = list(base)
    for action in ('vehicle_peer', 'infrastructure'):
        indices = available_subsets(ids).get(action)
        if indices is None:
            features.extend([0.] * len(PEER_FEATURES))
            continue
        matrix = matrices[ids[indices[1]]]
        position = matrix[:2, 3]
        heading = np.arctan2(matrix[1, 0], matrix[0, 0])
        values = [position[0] / 100., position[1] / 100., np.sin(heading), np.cos(heading),
                  len(centers) / 150.]
        if len(centers):
            delta = centers - position
            distances = np.linalg.norm(delta, axis=1)
            # Cosine of ego->object vs peer->object: smaller means a different viewpoint.
            denominator = np.linalg.norm(centers, axis=1) * distances
            cosine = np.divide(np.sum(centers * delta, axis=1), denominator,
                               out=np.zeros(len(centers)), where=denominator > 1e-8)
            values.extend([distances.min() / 100., np.average(distances, weights=weights) / 100.,
                           np.average(np.clip(cosine, -1., 1.), weights=weights)])
        else:
            values.extend([0.] * 3)
        features.extend(values)
    return np.asarray(features, float)
