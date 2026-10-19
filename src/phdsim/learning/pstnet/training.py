"""Fit only the new gate; the authors' RGB and fusion weights stay frozen."""

from dataclasses import asdict
import numpy as np

from phdsim.models.linear import fit_linear
from phdsim.evaluation.segmentation import segmentation_metrics
from phdsim.perception.pstnet.features import FEATURE_NAMES


def frame_gain(row):
    return (segmentation_metrics(row['fusion_confusion'])['miou'] -
            segmentation_metrics(row['rgb_confusion'])['miou'])


def fit_acquisition(rows, regularizations=(1., 10., 100.)):
    # Reject mixed inputs, rather than silently fitting the official test set.
    if not rows or any(r['split'] != 'train' for r in rows):
        raise ValueError('Acquisition fitting accepts original TRAIN frames only')
    if len({r['frame_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate acquisition training frame')
    groups = sorted({r['group'] for r in rows})
    if len(groups) < 3:
        raise ValueError('Need at least three recording families for gain validation')
    if not regularizations or any(not np.isfinite(r) or r <= 0 for r in regularizations):
        raise ValueError('Ridge regularizations must be positive')
    x = [r['features'] for r in rows]
    if any(len(f) != len(FEATURE_NAMES) for f in x):
        raise ValueError('Acquisition feature schema mismatch')
    y = np.array([frame_gain(r) for r in rows])
    losses, folds = {r: [] for r in regularizations}, []
    oof = {r: np.zeros(len(rows)) for r in regularizations}
    for group in groups:
        train = [i for i, row in enumerate(rows) if row['group'] != group]
        held = [i for i, row in enumerate(rows) if row['group'] == group]
        folds.append({'held_out_family': group, 'train_frames': len(train), 'held_out_frames': len(held)})
        for reg in regularizations:
            model = fit_linear([x[i] for i in train], y[train], kind='ridge', regularization=reg)
            predictions = np.array([model.predict(x[i]) for i in held])
            oof[reg][held] = predictions
            losses[reg].append(float(np.mean((predictions - y[held]) ** 2)))
    selected = min(regularizations, key=lambda r: (np.mean(losses[r]), -r))
    model = fit_linear(x, y, kind='ridge', regularization=selected)
    return {'schema': 'phdsim-pstnet-acquisition-v1', 'feature_names': list(FEATURE_NAMES),
            'model': asdict(model), 'training_frame_ids': [r['frame_id'] for r in rows],
            'teacher': 'per-frame five-class IoU(fusion) minus IoU(RGB); absent classes contribute zero',
            'evaluation_metric': 'global pixel confusion summed BEFORE five-class mIoU',
            'vision_training_overlap': 'Official pretrained experts have already seen original train frames; gate validation holds out families only from gate fitting, not expert training',
            'selection': 'leave-one-recording-family-out on original train; family-balanced MSE; no test selection',
            'selected_regularization': selected,
            'cv_mse': {str(k): float(np.mean(v)) for k, v in losses.items()}, 'folds': folds,
            'oof_expected_gain': oof[selected].tolist(),
            'positive_targets': int((y > 0).sum()), 'negative_targets': int((y < 0).sum()),
            'zero_targets': int((y == 0).sum())}
