"""Paired BEV AP using the pinned upstream matching implementation."""

import copy

CLASSES = ('Vehicle', 'Heavy_Vehicle', '2Wheeler', 'Pedestrian')
IOU_THRESHOLDS = (0.3, 0.5, 0.7)


def empty_statistics():
    return {name: {iou: {'tp': [], 'fp': [], 'gt': 0, 'score': []}
                   for iou in IOU_THRESHOLDS} for name in CLASSES}


def accumulate(statistics, boxes, scores, gt_boxes, gt_labels):
    from opencood.utils import box_utils, eval_utils

    # The checkpoint has a rectangular evaluation ROI. Retain the upstream
    # additional 0-100m corner-radius filter for comparison with its full range.
    gt_boxes, gt_keep = box_utils.filter_boxes_within_min_max_radius(gt_boxes, 0, 100)
    gt_labels = gt_labels[gt_keep]
    boxes, pred_keep = box_utils.filter_boxes_within_min_max_radius(boxes, 0, 100)
    scores = scores[pred_keep]
    for class_id, name in enumerate(CLASSES, start=1):
        mask = scores[:, 1] == class_id
        for iou in IOU_THRESHOLDS:
            eval_utils.caluclate_tp_fp(boxes[mask], scores[mask, 0],
                                      gt_boxes[gt_labels == class_id], statistics[name], iou)


def summarize(statistics):
    from opencood.utils import eval_utils

    report = {'metric': 'BEV polygon IoU; VOC interpolated AP; global confidence sort',
              'distance': 'upstream 0-100m corner-radius filter', 'classes': {}, 'macro_ap': {}}
    for name in CLASSES:
        count = statistics[name][IOU_THRESHOLDS[0]]['gt']
        report['classes'][name] = {'ground_truth_count': count, 'ap': {
            str(iou): float(eval_utils.calculate_ap(copy.deepcopy(statistics[name]), iou, True)[0])
            if count else None for iou in IOU_THRESHOLDS}}
    for iou in IOU_THRESHOLDS:
        values = [report['classes'][name]['ap'][str(iou)] for name in CLASSES]
        # Tiny smoke subsets may not contain all classes. Do not manufacture a
        # four-class mAP by treating missing classes as zero or silently dropping them.
        report['macro_ap'][str(iou)] = sum(values) / len(values) if all(v is not None for v in values) else None
    return report
