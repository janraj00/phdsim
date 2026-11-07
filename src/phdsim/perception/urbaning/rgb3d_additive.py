"""LiDAR-preserving decision-level fusion; inference has no GT inputs.

Keep every original LiDAR proposal, even overlapping LiDAR proposals. Reject
RGB proposals overlapping any same-class original LiDAR box at BEV IoU > .2;
then suppress duplicate RGB additions only. No source score is calibrated.
"""
import numpy as np

from phdsim.evaluation.urbaning_cached import _polygon, polygon_iou, validate_arrays

OVERLAP_THRESHOLD = .2


def additive_fuse(lidar_boxes, lidar_scores, rgb_boxes, rgb_scores, *, lidar_first=False):
    """Return boxes, evaluation scores, union indices and candidate decisions.

    `lidar_first` is a declared rank-priority rule, not a probability model:
    LiDAR rank=.5+.5*original_score, RGB rank=.49*original_score. It places every
    LiDAR proposal above every RGB addition. Floating ties and greedy matching
    remain governed by the unchanged evaluator; no universal AP guarantee.
    Raw confidences are retained separately by the experiment.
    """
    lb, ls, rb, rs = map(np.asarray, (lidar_boxes, lidar_scores, rgb_boxes, rgb_scores))
    for boxes, scores in ((lb, ls), (rb, rs)):
        if scores.shape != (len(boxes), 2):
            raise ValueError('Expected Nx2 confidence/class pairs')
        validate_arrays(boxes, scores[:, 1], scores[:, 0])
    lp, rp = [_polygon(b) for b in lb], [_polygon(b) for b in rb]
    accepted = []
    decisions = []
    for i in np.argsort(-rs[:, 0], kind='stable'):
        blockers = [j for j in range(len(lb)) if ls[j, 1] == rs[i, 1]
                    and polygon_iou(rp[i], lp[j]) > OVERLAP_THRESHOLD]
        if blockers:
            decisions.append({'rgb_index': int(i), 'decision': 'overlaps_lidar',
                              'blocker_index': blockers[0]})
            continue
        blocker = next((j for j in accepted if rs[j, 1] == rs[i, 1]
                        and polygon_iou(rp[i], rp[j]) > OVERLAP_THRESHOLD), None)
        if blocker is not None:
            decisions.append({'rgb_index': int(i), 'decision': 'overlaps_rgb',
                              'blocker_index': int(blocker)})
            continue
        accepted.append(int(i))
        decisions.append({'rgb_index': int(i), 'decision': 'accepted'})
    keep = np.r_[np.arange(len(lb)), len(lb)+np.asarray(accepted, int)]
    boxes = np.concatenate([lb, rb])[keep]
    raw = np.concatenate([ls, rs])[keep]
    scores = np.asarray(raw, np.float64).copy()
    if lidar_first:
        scores[:len(lb), 0] = .5+.5*scores[:len(lb), 0]
        scores[len(lb):, 0] *= .49
    np.testing.assert_array_equal(boxes[:len(lb)], lb)
    if not lidar_first:
        np.testing.assert_array_equal(scores[:len(lb)], ls)
    if len(boxes) != len(lb)+len(accepted):
        raise ValueError('LiDAR preservation invariant failed')
    return boxes, scores, keep, decisions
