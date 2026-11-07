"""Offline object-appearance complementarity audit of completed native-depth outcomes.

No detector, fitting, score tuning or GT-based deployable fusion. Source AP must
reproduce before a report is accepted. Counts describe the saved operating point.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

from phdsim.evaluation.urbaning import CLASSES, IOU_THRESHOLDS, empty_statistics
from phdsim.evaluation.urbaning_cached import (
    _radius_mask, _polygon, polygon_iou, validate_arrays,
    aggregate_statistics, summarize_cached)
from phdsim.perception.urbaning.rgb3d_late import late_fuse

VARIANTS = ('lidar', 'rgb_baseline', 'rgb_depth_finetuned',
            'lidar_rgb_baseline', 'lidar_rgb_depth_finetuned')
FIELDS = ('gt', 'lidar_tp', 'rgb_tp', 'fusion_tp', 'both_detect',
          'rgb_additional', 'lidar_only', 'neither_detect', 'fusion_gained',
          'fusion_lost', 'rgb_additional_in_fusion', 'rgb_additional_lost',
          'lidar_pred', 'rgb_pred', 'fusion_pred', 'lidar_fp', 'rgb_fp', 'fusion_fp',
          'lost_lidar_suppressed_by_rgb', 'lost_lidar_suppressed_by_lidar',
          'lost_lidar_retained_matching_changed')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def match_frame(boxes, scores, gt_boxes, gt_labels):
    """Same float32 IoU, radius, class and greedy order as cached VOC evaluator.

    Also retain source prediction and GT indices at IoU .5. IDs are local to
    one frame; repeated track appearances are deliberately not deduplicated.
    """
    validate_arrays(boxes, scores[:, 1], scores[:, 0])
    validate_arrays(gt_boxes, gt_labels)
    pi = np.flatnonzero(_radius_mask(boxes))
    gi = np.flatnonzero(_radius_mask(gt_boxes))
    statistics = empty_statistics()
    matches = {}
    for cls, name in enumerate(CLASSES, 1):
        ids = pi[scores[pi, 1] == cls]
        ids = ids[np.argsort(-scores[ids, 0])]
        truth_ids = gi[gt_labels[gi] == cls]
        pred = [_polygon(boxes[i]) for i in ids]
        truth = [_polygon(gt_boxes[i]) for i in truth_ids]
        overlap = np.asarray([[polygon_iou(a, b) for b in truth] for a in pred],
                             np.float32).reshape(len(pred), len(truth))
        for threshold in IOU_THRESHOLDS:
            remaining = list(range(len(truth)))
            tp = []
            for p, row in zip(ids, overlap):
                best = int(np.argmax(row[remaining])) if remaining else None
                hit = best is not None and row[remaining[best]] >= threshold
                tp.append(int(hit))
                if hit:
                    g = remaining.pop(best)
                    if threshold == .5:
                        matches[int(truth_ids[g])] = int(p)
            statistics[name][threshold] = {
                'gt': len(truth), 'tp': tp, 'fp': [1-v for v in tp],
                'score': scores[ids, 0].tolist()}
    return statistics, matches, pi


def suppression_reason(pred_index, boxes, scores, keep):
    """Return actual first retained hard-NMS blocker, respecting stable ties."""
    order = np.argsort(-scores[:, 0], kind='stable')
    rank = np.empty(len(order), int)
    rank[order] = np.arange(len(order))
    poly = _polygon(boxes[pred_index])
    for k in keep:
        if rank[k] >= rank[pred_index]:
            break
        if scores[k, 1] == scores[pred_index, 1]:
            overlap = polygon_iou(poly, _polygon(boxes[k]))
            if overlap > .2:
                return int(k), overlap
    raise ValueError('Suppressed prediction has no earlier retained NMS blocker')


def describe_pair(data, rgb_boxes, rgb_scores, lidar_result, rgb_result, fused_result, keep):
    lb, ls, gt, labels = (data[k] for k in
                         ('lidar_boxes', 'lidar_scores', 'gt_boxes', 'gt_labels'))
    fb = np.concatenate([lb, rgb_boxes])[keep]
    fs = np.concatenate([ls, rgb_scores])[keep]
    all_boxes, all_scores = np.concatenate([lb, rgb_boxes]), np.concatenate([ls, rgb_scores])
    lstat, lm, lp = lidar_result
    rstat, rm, rp = rgb_result
    fstat, fm, fp = fused_result
    left, right, fused = set(lm), set(rm), set(fm)
    extra, lost, gained = right-left, left-fused, fused-left
    loss_rows = []
    for g in sorted(lost):
        pred = lm[g]
        row = {'gt_index': g, 'class': CLASSES[int(labels[g])-1],
               'gt_center': gt[g].mean(0).tolist(), 'lidar_prediction_index': pred,
               'lidar_score': float(ls[pred, 0]),
               'lidar_gt_iou': polygon_iou(_polygon(lb[pred]), _polygon(gt[g]))}
        if pred in keep:
            row['reason'] = 'lost_lidar_retained_matching_changed'
        else:
            blocker, overlap = suppression_reason(pred, all_boxes, all_scores, keep)
            source = 'lidar' if blocker < len(lb) else 'rgb'
            row.update(reason='lost_lidar_suppressed_by_'+source,
                       blocker_source=source, blocker_union_index=blocker,
                       blocker_score=float(all_scores[blocker, 0]),
                       blocker_lidar_iou=overlap,
                       blocker_gt_iou=polygon_iou(_polygon(all_boxes[blocker]), _polygon(gt[g])),
                       blocker_center=all_boxes[blocker].mean(0).tolist())
        loss_rows.append(row)
    counts = {}
    for cls, name in enumerate(CLASSES, 1):
        universe = set(np.flatnonzero(_radius_mask(gt) & (labels == cls)))
        def n(s): return len(s & universe)
        rows = [r for r in loss_rows if r['class'] == name]
        counts[name] = dict(zip(FIELDS, (
            len(universe), n(left), n(right), n(fused), n(left & right),
            n(extra), n(left-right), n(universe-(left | right)), n(gained),
            n(lost), n(extra & fused), n(extra-fused),
            int(sum(ls[lp, 1] == cls)), int(sum(rgb_scores[rp, 1] == cls)),
            int(sum(fs[fp, 1] == cls)), sum(lstat[name][.5]['fp']),
            sum(rstat[name][.5]['fp']), sum(fstat[name][.5]['fp']),
            sum(r['reason'] == 'lost_lidar_suppressed_by_rgb' for r in rows),
            sum(r['reason'] == 'lost_lidar_suppressed_by_lidar' for r in rows),
            sum(r['reason'] == 'lost_lidar_retained_matching_changed' for r in rows))))
    extras = [{'gt_index': g, 'class': CLASSES[int(labels[g])-1],
               'gt_center': gt[g].mean(0).tolist(), 'rgb_score': float(rgb_scores[rm[g], 0]),
               'rgb_gt_iou': polygon_iou(_polygon(rgb_boxes[rm[g]]), _polygon(gt[g])),
               'detected_after_fusion': g in fused} for g in sorted(extra)]
    gains = []
    for g in sorted(gained):
        p = fm[g]
        union_index = int(keep[p])
        gains.append({'gt_index': g, 'class': CLASSES[int(labels[g])-1],
                      'gt_center': gt[g].mean(0).tolist(),
                      'fusion_prediction_index': p, 'union_prediction_index': union_index,
                      'source': 'lidar' if union_index < len(lb) else 'rgb',
                      'score': float(fs[p, 0]), 'gt_iou': polygon_iou(_polygon(fb[p]), _polygon(gt[g])),
                      'detected_by_rgb_standalone': g in right})
    return {'classes': counts, 'losses': loss_rows, 'fusion_gained_objects': gains,
            'rgb_additional_objects': extras}


def audit_frame(data):
    gt, labels = data['gt_boxes'], data['gt_labels']
    arrays = {'lidar': (data['lidar_boxes'], data['lidar_scores']),
              'rgb_baseline': (data['rgb_baseline_boxes'], data['rgb_baseline_scores']),
              'rgb_depth_finetuned': (data['rgb_depth_boxes'], data['rgb_depth_scores'])}
    keeps = {}
    for stage in ('baseline', 'depth_finetuned'):
        b, s = arrays['rgb_'+stage]
        fb, fs, keep = late_fuse(*arrays['lidar'], b, s, .2)
        arrays['lidar_rgb_'+stage] = fb, fs
        keeps[stage] = keep
    results = {v: match_frame(b, s, gt, labels) for v, (b, s) in arrays.items()}
    pairs = {stage: describe_pair(data, *arrays['rgb_'+stage], results['lidar'],
                                 results['rgb_'+stage], results['lidar_rgb_'+stage], keeps[stage])
             for stage in keeps}
    return {v: r[0] for v, r in results.items()}, pairs


def combine(rows):
    by_class = {name: {f: sum(row['classes'][name][f] for row in rows) for f in FIELDS}
                for name in CLASSES}
    total = {f: sum(c[f] for c in by_class.values()) for f in FIELDS}
    for c in [total, *by_class.values()]:
        if not (c['lidar_tp'] + c['rgb_additional'] + c['neither_detect'] == c['gt']
                and c['fusion_tp'] == c['lidar_tp'] + c['fusion_gained'] - c['fusion_lost']
                and c['rgb_additional_in_fusion'] + c['rgb_additional_lost'] == c['rgb_additional']
                and sum(c[f] for f in FIELDS[-3:]) == c['fusion_lost']):
            raise ValueError('GT-identity accounting invariant failed')
    return {'total': total, 'classes': by_class}


def run(source, output, *, expected_counts=(400, 200)):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Use a fresh audit output directory; preserve previous outputs')
    raw = source.read_bytes()
    identity = sha(raw)
    completion = source.with_name('completed.json')
    if completion.is_file() and json.loads(completion.read_text())['sha256'] != identity:
        raise ValueError('Source ZIP differs from completed job checksum')
    output.mkdir(parents=True)
    result = {'schema': 'phdsim-rgb3d-complementarity-v1', 'source_sha256': identity,
              'runtime': {'python': sys.version, 'numpy': np.__version__},
              'code_sha256': {str(p): sha(p.read_bytes()) for p in (
                  Path(__file__), Path(__file__).parents[1]/'evaluation/urbaning_cached.py',
                  Path(__file__).parents[1]/'perception/urbaning/rgb3d_late.py')},
              'threshold': .5, 'splits': {},
              'interpretation': [
                  'Counts are GT object appearances per frame, not unique tracks or mAP.',
                  'Same existing saved scores/proposals; no added confidence threshold or tuning.',
                  'Union of matched GT sets is offline diagnostic coverage, not a deployable oracle fusion.',
                  'Greedy matching can change identities; gained fusion GT need not equal RGB-only GT.',
                  'TRAIN is descriptive; validation is one previously inspected development recording.',
                  'No fitting, detector, source modification, acquisition or crossing3.']}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or z.testzip() is not None:
            raise ValueError('Duplicate or corrupt archive members')
        source_report = json.loads(z.read('report.json'))
        if source_report.get('schema') != 'phdsim-rgb3d-native-depth-controlled-v1':
            raise ValueError('Expected completed native-depth controlled report')
        for split, count in zip(('train', 'validation'), expected_counts):
            entries = sorted(n for n in names if n.startswith('frames-'+split+'/') and n.endswith('.npz'))
            if len(entries) != count:
                raise ValueError(f'Expected {count} {split} frames, found {len(entries)}')
            stats = {v: [] for v in VARIANTS}
            frames = []
            for j, entry in enumerate(entries):
                with np.load(io.BytesIO(z.read(entry)), allow_pickle=False) as a:
                    data = {k: a[k] for k in a.files}
                fs, pairs = audit_frame(data)
                for v in VARIANTS:
                    stats[v].append(fs[v])
                sequence, frame, ego = Path(entry).stem.rsplit('_', 2)
                if not frame.isdigit() or not ego.isdigit():
                    raise ValueError('Unrecognized frame identity')
                frames.append({'key': sequence+':'+frame+':'+ego, 'sequence': sequence, 'pairs': pairs})
                if (j+1) % 25 == 0:
                    print('AUDIT', split, j+1, '/', count, flush=True)
            metrics = {v: {order: summarize_cached(aggregate_statistics(stats[v]), glob)
                           for order, glob in [('global_confidence_sort', True),
                                               ('upstream_default_frame_order', False)]} for v in VARIANTS}
            if metrics != source_report[split+'_metrics']:
                raise ValueError('Source AP parity failed; do not interpret complementarity counts')
            stages = {s: combine([f['pairs'][s] for f in frames]) for s in ('baseline', 'depth_finetuned')}
            sequences = {seq: {s: combine([f['pairs'][s] for f in frames if f['sequence'] == seq])
                               for s in stages} for seq in sorted({f['sequence'] for f in frames})}
            result['splits'][split] = {'frames': count, 'source_ap_reproduced': True,
                                      'metrics': metrics, 'stages': stages,
                                      'by_sequence': sequences, 'per_frame': frames}
            print('AP PARITY', split, 'all5 variants; class AP .3/.5/.7; both orders PASSED', flush=True)
    if sha(source.read_bytes()) != identity:
        raise ValueError('Source changed during audit')
    lines = ['# RGB / LiDAR object-appearance audit',
             'BEV IoU >= .5, same class and existing 0–100m corner-radius support.',
             'Extra RGB GT: matched by RGB alone, missed by LiDAR alone.',
             'Fusion gained/lost: GT match identities after fusion compared with LiDAR alone.',
             'Object counts describe appearances per frame, not unique tracks or mAP.\n']
    for split, data in result['splits'].items():
        lines += [f'## {split}: {data["frames"]} frames',
                  '| RGB variant | LiDAR TP | RGB TP | Extra RGB GT | Extra retained in fusion | Fusion gained | Fusion lost | Suppressed by RGB |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|']
        for s, row in data['stages'].items():
            c = row['total']
            lines.append('| '+s+' | '+' | '.join(str(c[k]) for k in (
                'lidar_tp', 'rgb_tp', 'rgb_additional', 'rgb_additional_in_fusion',
                'fusion_gained', 'fusion_lost', 'lost_lidar_suppressed_by_rgb'))+' |')
        lines += ['', '| Variant | BEV mAP@.5 (%) |', '|---|---:|']
        for v, metric in data['metrics'].items():
            m = metric['global_confidence_sort']['macro_ap']['0.5']
            lines.append(f'| {v} | {"N/A" if m is None else f"{100*m:.4f}"} |')
        for s, row in data['stages'].items():
            lines += ['', f'### {s}: per class',
                      '| Class | GT | LiDAR TP | RGB TP | Extra RGB GT | Fusion gained | Fusion lost |',
                      '|---|---:|---:|---:|---:|---:|---:|']
            for name, c in row['classes'].items():
                lines.append('| '+name+' | '+' | '.join(str(c[k]) for k in (
                    'gt', 'lidar_tp', 'rgb_tp', 'rgb_additional', 'fusion_gained', 'fusion_lost'))+' |')
    lines += ['', 'GT sets are an offline diagnosis. A new detection with a low score need not improve AP.',
              'Loss traces distinguish RGB/LiDAR NMS suppression from retained-prediction matching changes.',
              'All per-frame gains, losses, scores, IoUs and source indices are in report.json.']
    (output/'report.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'source-report.json').write_text(json.dumps(source_report, indent=2, allow_nan=False)+'\n')
    archive = output/'urbaning-rgb3d-complementarity.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('report.json', 'summary.md', 'source-report.json'):
            z.write(output/name, name)
    print('\n'.join(lines), flush=True)
    print('SHA256', sha(archive.read_bytes()), 'bytes', archive.stat().st_size, flush=True)
    print('DONE:', archive, flush=True)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
