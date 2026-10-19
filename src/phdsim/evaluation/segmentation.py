"""Global pixel IoU matching the upstream five-class iouEval."""

import numpy as np

CLASSES = ('background', 'fire_extinguisher', 'backpack', 'hand_drill', 'survivor')


def confusion_matrix(prediction, reference):
    prediction, reference = np.asarray(prediction), np.asarray(reference)
    if prediction.shape != reference.shape or not np.isin(prediction, np.arange(5)).all() or not np.isin(reference, np.arange(5)).all():
        raise ValueError('Expected equally shaped class-index masks with classes 0..4')
    return np.bincount((reference.astype(np.int64) * 5 + prediction).ravel(), minlength=25).reshape(5, 5)


def segmentation_metrics(confusion):
    matrix = np.asarray(confusion)
    if matrix.shape != (5, 5) or not np.isfinite(matrix).all() or (matrix < 0).any():
        raise ValueError('Invalid five-class confusion matrix')
    tp = np.diag(matrix).astype(float)
    union = matrix.sum(0) + matrix.sum(1) - tp
    iou = tp / (union + 1e-15)
    return {'miou': float(iou.mean()), 'class_iou': dict(zip(CLASSES, map(float, iou))),
            'pixels': int(matrix.sum()), 'confusion': matrix.tolist()}


def summarize_choices(rows, choices):
    if len(rows) != len(choices) or not rows:
        raise ValueError('Expected one acquisition decision per frame')
    total = sum((np.asarray(r['fusion_confusion'] if pull else r['rgb_confusion'], dtype=np.int64)
                 for r, pull in zip(rows, choices)), start=np.zeros((5, 5), dtype=np.int64))
    return {**segmentation_metrics(total), 'frames': len(rows), 'pulls': sum(map(bool, choices)),
            'transferred_bytes': sum(r['thermal_bytes'] for r, pull in zip(rows, choices) if pull),
            'acquisition_rate': float(np.mean(choices))}

