"""NumPy evaluation of saved UrbanIng boxes, without a detector runtime.

This independently implemented evaluator uses the documented stage 1 protocol:
greedy score-ordered same-class BEV matching and globally sorted VOC AP. The
cache reader cross-checks all fixed baselines against the original run metrics.
No upstream source is redistributed here.
"""

import numpy as np

from phdsim.evaluation.urbaning import CLASSES, IOU_THRESHOLDS, empty_statistics


def validate_arrays(boxes, labels, scores=None):
    boxes, labels = np.asarray(boxes), np.asarray(labels)
    if (boxes.shape != (len(boxes), 8, 3) or labels.shape != (len(boxes),) or
            not np.isfinite(boxes).all() or not np.isin(labels, [1, 2, 3, 4]).all()):
        raise ValueError('Invalid cached boxes or class labels')
    if scores is not None and (np.shape(scores) != (len(boxes),) or
                               not np.isfinite(scores).all() or
                               np.any((scores < 0) | (scores > 1))):
        raise ValueError('Invalid cached confidence scores')


def _radius_mask(boxes):
    squared = np.square(boxes).sum(axis=2)
    return ((squared > 0) & (squared < 100 ** 2)).any(axis=1)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _area(points):
    if len(points) < 3:
        return 0.
    shifted = np.asarray(points) - points[0]
    return abs(sum(_cross(a, b) for a, b in zip(shifted, np.roll(shifted, -1, axis=0)))) / 2


def _polygon(box):
    points = np.asarray(box[:4, :2], dtype=float)
    turns = [_cross(points[(i + 1) % 4] - points[i],
                    points[(i + 2) % 4] - points[(i + 1) % 4]) for i in range(4)]
    if _area(points) <= 0 or not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        raise ValueError('Expected a nondegenerate convex BEV box')
    return points


def polygon_iou(a, b):
    """Convex clipping of the two oriented BEV rectangles, in double precision."""
    if np.any(a.max(axis=0) <= b.min(axis=0)) or np.any(b.max(axis=0) <= a.min(axis=0)):
        return 0.
    orientation = np.sign(_cross(b[1] - b[0], b[2] - b[1]))
    clipped = list(a)
    for start, end in zip(b, np.roll(b, -1, axis=0)):
        edge = end - start
        incoming, clipped = clipped, []
        if not incoming:
            return 0.
        previous = incoming[-1]
        previous_side = orientation * _cross(edge, previous - start)
        for current in incoming:
            current_side = orientation * _cross(edge, current - start)
            if (current_side >= 0) != (previous_side >= 0):
                fraction = previous_side / (previous_side - current_side)
                clipped.append(previous + fraction * (current - previous))
            if current_side >= 0:
                clipped.append(current)
            previous, previous_side = current, current_side
    intersection = _area(clipped)
    return float(np.clip(intersection / (_area(a) + _area(b) - intersection), 0., 1.))


def frame_statistics(boxes, scores, gt_boxes, gt_labels):
    scores = np.asarray(scores)
    if scores.shape != (len(boxes), 2):
        raise ValueError('Expected Nx2 score/class array')
    validate_arrays(boxes, scores[:, 1], scores[:, 0])
    validate_arrays(gt_boxes, gt_labels)
    pred_keep, gt_keep = _radius_mask(boxes), _radius_mask(gt_boxes)
    boxes, scores = boxes[pred_keep], scores[pred_keep]
    gt_boxes, gt_labels = gt_boxes[gt_keep], gt_labels[gt_keep]
    result = empty_statistics()
    for class_id, name in enumerate(CLASSES, start=1):
        selected = scores[:, 1] == class_id
        confidence = scores[selected, 0]
        order = np.argsort(-confidence)
        pred = [_polygon(box) for box in boxes[selected][order]]
        truth = [_polygon(box) for box in gt_boxes[gt_labels == class_id]]
        overlap = np.asarray([[polygon_iou(a, b) for b in truth] for a in pred],
                             dtype=np.float32).reshape(len(pred), len(truth))
        for threshold in IOU_THRESHOLDS:
            remaining = list(range(len(truth)))
            tp = []
            for row in overlap:
                best = int(np.argmax(row[remaining])) if remaining else None
                matched = best is not None and row[remaining[best]] >= threshold
                tp.append(int(matched))
                if matched:
                    remaining.pop(best)
            result[name][threshold] = {'gt': len(truth), 'tp': tp,
                                       'fp': [1 - v for v in tp],
                                       'score': confidence[order].tolist()}
    return result


def frame_f1(statistics):
    """Micro F1 over all four classes at IoU .5; an explicit training surrogate."""
    rows = [statistics[name][0.5] for name in CLASSES]
    tp = sum(sum(row['tp']) for row in rows)
    fp = sum(sum(row['fp']) for row in rows)
    gt = sum(row['gt'] for row in rows)
    return 2 * tp / (gt + tp + fp) if gt + tp + fp else 1.


def aggregate_statistics(frame_stats):
    total = empty_statistics()
    for frame in frame_stats:
        for name in CLASSES:
            for iou in IOU_THRESHOLDS:
                total[name][iou]['gt'] += frame[name][iou]['gt']
                for field in ('tp', 'fp', 'score'):
                    total[name][iou][field].extend(frame[name][iou][field])
    return total


def summarize_cached(statistics):
    result = {'classes': {}, 'macro_ap': {}, 'metric': 'BEV polygon IoU; VOC AP; global sort'}
    for name in CLASSES:
        result['classes'][name] = {'ground_truth_count': statistics[name][0.3]['gt'], 'ap': {}}
        for threshold in IOU_THRESHOLDS:
            row = statistics[name][threshold]
            if row['gt'] == 0:
                ap = None
            else:
                order = np.argsort(-np.asarray(row['score']))
                tp = np.cumsum(np.asarray(row['tp'])[order])
                fp = np.cumsum(np.asarray(row['fp'])[order])
                recall = np.r_[0., tp / (row['gt'] + 1e-9), 1.]
                precision = np.r_[0., tp / (tp + fp + 1e-9), 0.]
                envelope = np.maximum.accumulate(precision[::-1])[::-1]
                ap = float(np.sum(np.diff(recall) * envelope[1:]))
            result['classes'][name]['ap'][str(threshold)] = ap
    for threshold in IOU_THRESHOLDS:
        values = [result['classes'][name]['ap'][str(threshold)] for name in CLASSES]
        result['macro_ap'][str(threshold)] = sum(values) / 4 if None not in values else None
    return result
