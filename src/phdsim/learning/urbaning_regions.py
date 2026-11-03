"""Fixed spatial inputs from Car1 detections and explicitly shared metadata only.

No GT, partner detections, point clouds or target-selected regions are accepted.
An empty cell means no cached Car1 detection, not observed free/unknown space.
"""

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets
from phdsim.learning.urbaning import ego_features
from phdsim.learning.urbaning_geometry import validate_transform

SCHEMA = 'phdsim-urbaning-regional-dataset-v1'
CELL_SIZE = 10.
MIN_XY, MAX_XY = -100., 100.
SIDE = 20
SPATIAL_CELLS = SIDE * SIDE
OVERFLOW = SPATIAL_CELLS
CELL_COUNT = SPATIAL_CELLS + 1
LOW_SCORE = .5
FEATURES = ('cell_x_over_100', 'cell_y_over_100', 'cell_radius_over_100',
            'overflow_cell', 'ego_entropy', 'ego_count_over_10', 'ego_score_mean',
            'ego_score_min', 'ego_score_std', 'ego_low_count_over_10', 'ego_empty') + tuple(
                'class_{}_{}'.format(c, name) for c in range(1, 5)
                for name in ('count_over_10', 'score_mean', 'score_min', 'low_count_over_10')) + (
                    'neighbor_count_over_10', 'neighbor_score_mean', 'neighbor_low_count_over_10') + tuple(
                        role + '_' + name for role in ('car2', 'infra')
                        for name in ('available', 'dx_over_100', 'dy_over_100', 'distance_over_100',
                                     'heading_sin', 'heading_cos', 'view_cosine', 'origin_inside_grid'))


def cell_centers():
    axis = MIN_XY + (np.arange(SIDE) + .5) * CELL_SIZE
    x, y = np.meshgrid(axis, axis, indexing='ij')
    # Overflow has no physical center; its coordinates are placeholders and its
    # explicit flag must remain available to any learner.
    return np.vstack([np.c_[x.ravel(), y.ravel()], [0., 0.]])


def assign_cells(centers):
    xy = np.asarray(centers, float)
    if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all():
        raise ValueError('Expected finite Nx2 centers')
    inside = ((xy >= MIN_XY) & (xy < MAX_XY)).all(axis=1)
    ids = np.full(len(xy), OVERFLOW, dtype=np.int64)
    indices = np.floor((xy[inside] - MIN_XY) / CELL_SIZE).astype(np.int64)
    ids[inside] = indices[:, 0] * SIDE + indices[:, 1]
    return ids


def _summaries(ids, confidence):
    count = np.bincount(ids, minlength=CELL_COUNT)
    total = np.bincount(ids, weights=confidence, minlength=CELL_COUNT)
    squares = np.bincount(ids, weights=confidence**2, minlength=CELL_COUNT)
    low = np.bincount(ids, weights=confidence < LOW_SCORE, minlength=CELL_COUNT)
    mean = np.divide(total, count, out=np.zeros(CELL_COUNT), where=count > 0)
    variance = np.divide(squares, count, out=np.zeros(CELL_COUNT), where=count > 0) - mean**2
    minimum = np.full(CELL_COUNT, np.inf)
    np.minimum.at(minimum, ids, confidence)
    minimum[count == 0] = 0.
    return count, total, low, mean, minimum, np.sqrt(np.maximum(variance, 0.))


def _neighbors(values):
    grid = np.pad(values[:SPATIAL_CELLS].reshape(SIDE, SIDE), 1)
    total = sum(grid[i:i+SIDE, j:j+SIDE] for i in range(3) for j in range(3))
    return np.r_[total.ravel(), 0.]


def regional_features(source_ids, entropy, ego_boxes, ego_scores, peer_to_ego):
    """401 cells x 46 inputs; all cells retained, including no-detection cells.

Cells use BEV box centroids, not box intersection area. All cached Car1 boxes
are inputs; offline evaluation applies its original radius filter separately.
Pose offsets are proxies; Infra's origin is not a physical pole or visibility.
"""
    ids = [str(i) for i in source_ids]
    if not ids or ids[0] != '100000':
        raise ValueError('Regional profile uses Car1 as reference')
    ego_features(ids, entropy, ego_scores)  # validate local scores, labels and IDs
    boxes, scores = np.asarray(ego_boxes, float), np.asarray(ego_scores, float)
    if boxes.shape != (len(scores), 8, 3) or not np.isfinite(boxes).all():
        raise ValueError('Expected finite Car1 boxes aligned with scores')
    if set(peer_to_ego) != set(ids[1:]):
        raise ValueError('Pose metadata must cover exactly the available peers')
    poses = {i: validate_transform(v) for i, v in peer_to_ego.items()}
    options = available_subsets(ids)
    available = np.array([a in options for a in ACTION_ORDER], dtype=bool)
    centers = cell_centers()
    cells = assign_cells(boxes[:, :4, :2].mean(axis=1))
    count, total, low, mean, minimum, std = _summaries(cells, scores[:, 0])
    columns = [centers[:, 0] / 100., centers[:, 1] / 100.,
               np.linalg.norm(centers, axis=1) / 100.,
               (np.arange(CELL_COUNT) == OVERFLOW).astype(float), np.full(CELL_COUNT, entropy),
               count / 10., mean, minimum, std, low / 10., (count == 0).astype(float)]
    for class_id in range(1, 5):
        mask = scores[:, 1] == class_id
        n, _, small, avg, least, _ = _summaries(cells[mask], scores[mask, 0])
        columns.extend([n / 10., avg, least, small / 10.])
    n, score_sum, small = _neighbors(count), _neighbors(total), _neighbors(low)
    columns.extend([n / 10., np.divide(score_sum, n, out=np.zeros(CELL_COUNT), where=n > 0), small / 10.])
    for role in ('vehicle_peer', 'infrastructure'):
        indices = options.get(role)
        if indices is None:
            columns.extend(np.zeros((8, CELL_COUNT)))
            continue
        pose = poses[ids[indices[1]]]
        position = pose[:2, 3]
        delta = centers - position
        distance = np.linalg.norm(delta, axis=1)
        denominator = np.linalg.norm(centers, axis=1) * distance
        cosine = np.divide(np.sum(centers * delta, axis=1), denominator,
                           out=np.zeros(CELL_COUNT), where=denominator > 1e-8)
        angle = np.arctan2(pose[1, 0], pose[0, 0])
        peer_columns = [np.ones(CELL_COUNT), delta[:, 0] / 100., delta[:, 1] / 100.,
                        distance / 100., np.full(CELL_COUNT, np.sin(angle)),
                        np.full(CELL_COUNT, np.cos(angle)), np.clip(cosine, -1., 1.),
                        np.full(CELL_COUNT, float(np.all((position >= MIN_XY) & (position < MAX_XY))))]
        # No geometric interpretation for overflow: keep only availability.
        for column in peer_columns[1:]:
            column[OVERFLOW] = 0.
        columns.extend(peer_columns)
    x = np.column_stack(columns).astype(np.float32)
    if x.shape != (CELL_COUNT, len(FEATURES)) or not np.isfinite(x).all():
        raise ValueError('Invalid regional inputs')
    return x, available
