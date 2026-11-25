"""Replay a completed RGB experiment; inspect predictions and actual TRAIN coverage.

Offline diagnosis only: no training, checkpoint selection, detector, or GT-based
deployable policy. Inputs are the verified compact source/native metadata ZIPs.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import (
    _polygon, _radius_mask, polygon_iou, aggregate_statistics, summarize_cached)
from phdsim.experiments.urbaning_rgb3d_complementarity import match_frame
from phdsim.perception.urbaning.rgb3d_finetune import projected_targets

RGB = ('rgb_outdoor', 'rgb_depth', 'rgb_coarse_initialized', 'rgb_heads_finetuned')
EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
         (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def metric_difference(actual, expected, tolerance=1e-7):
    """Float reduction portability only; counts/metadata must still match exactly."""
    if isinstance(actual, dict):
        if set(actual) != set(expected):
            raise ValueError('Metric keys differ')
        return max((metric_difference(actual[k], expected[k], tolerance) for k in actual), default=0.)
    if isinstance(actual, float) and isinstance(expected, (int, float)):
        difference = abs(actual-expected)
        if not np.isfinite(difference) or difference > tolerance:
            raise ValueError(f'Metric difference {difference} exceeds fixed tolerance {tolerance}')
        return difference
    if actual != expected:
        raise ValueError('Non-floating metric metadata/counts differ')
    return 0.


def near_plane_blockers(gt, e, k, width, height):
    """Reproduce the exact historical whole-image rejection condition."""
    optical = gt @ e[:3, :3].T + e[:3, 3]
    candidates = np.where((optical[:, :, 2].min(1) <= .1) & (optical[:, :, 2].max(1) > .1))[0]
    blockers = []
    for i in candidates:
        cam = optical[i]
        vertices = list(cam[cam[:, 2] > .1])
        for a, b in EDGES:
            if (cam[a, 2] > .1) != (cam[b, 2] > .1):
                t = (.1-cam[a, 2])/(cam[b, 2]-cam[a, 2])
                vertices.append(cam[a]+t*(cam[b]-cam[a]))
        points = np.asarray(vertices) @ k.T
        uv = points[:, :2]/points[:, 2:3]
        lo, hi = uv.min(0), uv.max(0)
        clipped = np.r_[np.maximum(lo, (0, 0)), np.minimum(hi, (width, height))]
        if np.all(clipped[2:] > clipped[:2]):
            blockers.append({'gt_index': int(i), 'clipped_rect': clipped.tolist(),
                             'center_car1': gt[i].mean(0).tolist()})
    return blockers


def overlap_matrix(boxes, truth):
    """All-class IoU for error descriptions; AABB rejection saves geometry work."""
    result = np.zeros((len(boxes), len(truth)), np.float32)
    if not len(boxes) or not len(truth):
        return result
    lo, hi = boxes[:, :4, :2].min(1), boxes[:, :4, :2].max(1)
    gl, gh = truth[:, :4, :2].min(1), truth[:, :4, :2].max(1)
    candidate = (np.minimum(hi[:, None], gh) > np.maximum(lo[:, None], gl)).all(2)
    polygons, gpolygons = [_polygon(b) for b in boxes], [_polygon(b) for b in truth]
    for p, g in zip(*np.where(candidate)):
        result[p, g] = polygon_iou(polygons[p], gpolygons[g])
    return result


def fp_rows(boxes, scores, gt, labels, matched):
    pi, gi = np.flatnonzero(_radius_mask(boxes)), np.flatnonzero(_radius_mask(gt))
    overlap = overlap_matrix(boxes[pi], gt[gi])
    matched_predictions = set(matched.values())
    rows = []
    for j, p in enumerate(pi):
        if int(p) in matched_predictions:
            continue
        values = overlap[j]
        same = labels[gi] == scores[p, 1]
        best_same = float(values[same].max()) if same.any() else 0.
        best = int(np.argmax(values)) if len(values) else None
        best_any = float(values[best]) if best is not None else 0.
        if best_same >= .5:
            reason = 'same_class_duplicate_at_05'
        elif best_any >= .5:
            reason = 'other_class_overlap_at_05'
        elif best_same >= .1:
            reason = 'same_class_overlap_01_to_05'
        elif best_any > 0:
            reason = 'weak_or_other_class_overlap_below_05'
        else:
            reason = 'no_gt_bev_overlap'
        rows.append({'prediction_index': int(p), 'class': CLASSES[int(scores[p, 1])-1],
                     'score': float(scores[p, 0]), 'reason': reason,
                     'best_same_class_iou': best_same, 'best_any_class_iou': best_any,
                     'nearest_overlap_gt_index': int(gi[best]) if best is not None and best_any else None})
    return rows


def audit(inputs, metadata, output):
    if output.exists():
        raise ValueError('Use a fresh audit output directory')
    output.mkdir(parents=True)
    source_bytes = inputs.read_bytes()
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as z, zipfile.ZipFile(metadata) as native:
        if z.testzip() is not None or native.testzip() is not None:
            raise ValueError('CRC failed')
        receipt = json.loads(z.read('source-receipt.json'))
        for name, expected in receipt['members'].items():
            if sha(z.read(name)) != expected:
                raise ValueError('Source member digest changed: '+name)
        r = json.loads(z.read('report.json'))
        if r['schema'] != 'phdsim-rgb3d-four-class-heads-v1':
            raise ValueError('Unexpected source experiment')
        inventory = json.loads(z.read('train-inventory.json'))
        shape_info = json.loads(native.read('metadata-receipt.json'))
        training = [json.loads(line) for line in z.read('training.jsonl').splitlines()]
        variants = tuple(r['splits']['train']['metrics'])
        results = {'source': receipt, 'compact_inputs_sha256': sha(source_bytes),
                   'metadata_sha256': sha(metadata.read_bytes()), 'splits': {}}
        candidates = []
        frame_cache = {}
        for split, count in (('train', 400), ('validation', 200)):
            rows = r['splits'][split]['frames']
            if len(rows) != count:
                raise ValueError('Frame count differs')
            stats = {v: [] for v in variants}
            complementarity = {v: Counter() for v in variants if v != 'lidar'}
            fp_counts = {v: Counter() for v in RGB}
            fp_scores = {v: [] for v in RGB}
            per_frame = []
            for j, frame in enumerate(rows):
                key = frame['key']
                raw = z.read('frames-'+split+'/'+key.replace(':', '_')+'.npz')
                if sha(raw) != frame['sha256']:
                    raise ValueError('Prediction receipt differs')
                with np.load(io.BytesIO(raw), allow_pickle=False) as f:
                    d = {name: f[name].copy() for name in f.files}
                if split == 'train':
                    frame_cache[key] = (d['gt_boxes'], d['gt_labels'])
                matches = {}
                for v in variants:
                    ss, mm, _ = match_frame(d[v+'_boxes'], d[v+'_scores'], d['gt_boxes'], d['gt_labels'])
                    stats[v].append(ss)
                    matches[v] = mm
                lidar_gt = set(matches['lidar'])
                row_counts = {}
                for v in complementarity:
                    right = set(matches[v])
                    row_counts[v] = {'gained': len(right-lidar_gt), 'lost': len(lidar_gt-right)}
                    for name in ('gained', 'lost'):
                        complementarity[v][name] += row_counts[v][name]
                    for g in sorted(right-lidar_gt):
                        cls = CLASSES[int(d['gt_labels'][g])-1]
                        complementarity[v]['gained_'+cls] += 1
                        if split == 'validation' and v in ('rgb_outdoor', 'finetuned_additive_lidar_first'):
                            p = matches[v][g]
                            candidates.append({'kind': 'recovered_vs_lidar', 'key': key, 'variant': v,
                                               'class': cls, 'gt_index': g, 'prediction_index': p,
                                               'score': float(d[v+'_scores'][p, 0])})
                if split == 'validation':
                    for v in RGB:
                        failures = fp_rows(d[v+'_boxes'], d[v+'_scores'], d['gt_boxes'], d['gt_labels'], matches[v])
                        for failure in failures:
                            fp_counts[v][failure['reason']] += 1
                            fp_scores[v].append(failure['score'])
                        if v == 'rgb_heads_finetuned':
                            for failure in failures:
                                candidates.append({'kind': 'false_positive', 'key': key, 'variant': v, **failure})
                    lost = set(matches['rgb_outdoor'])-set(matches['rgb_heads_finetuned'])
                    for g in sorted(lost):
                        p = matches['rgb_outdoor'][g]
                        candidates.append({'kind': 'outdoor_gt_not_detected_after_finetune', 'key': key,
                                           'variant': 'rgb_outdoor', 'gt_index': g, 'prediction_index': p,
                                           'class': CLASSES[int(d['gt_labels'][g])-1],
                                           'score': float(d['rgb_outdoor_scores'][p, 0])})
                per_frame.append({'key': key, 'vs_lidar': row_counts})
                if (j+1) % 25 == 0:
                    print('AUDIT', split, j+1, '/', count, flush=True)
            metrics = {v: {name: summarize_cached(aggregate_statistics(ss), order)
                           for name, order in (('global_confidence_sort', True), ('upstream_default_frame_order', False))}
                       for v, ss in stats.items()}
            try:
                max_difference = metric_difference(metrics, r['splits'][split]['metrics'])
            except ValueError:
                dump(output/('parity-difference-'+split+'.json'), {'actual': metrics, 'expected': r['splits'][split]['metrics']})
                raise ValueError('Independent source class AP/mAP parity failed')
            counts = {v: {field: int(sum(sum(s[c][.5][field]) if field in ('tp', 'fp') else s[c][.5][field]
                                       for s in ss for c in CLASSES)) for field in ('tp', 'fp', 'gt')}
                      for v, ss in stats.items()}
            for v, classes in r['splits'][split]['counts_at_iou_05'].items():
                if counts[v] != {f: sum(c[f] for c in classes.values()) for f in ('tp', 'fp', 'gt')}:
                    raise ValueError('Independent counts do not reproduce')
            results['splits'][split] = {'ap_parity_passed': True, 'ap_absolute_tolerance': 1e-7,
                'maximum_ap_difference': max_difference, 'metrics': metrics, 'counts': counts,
                'vs_lidar': {v: dict(c) for v, c in complementarity.items()}, 'per_frame': per_frame,
                'fp_geometry_validation': {v: dict(c) for v, c in fp_counts.items()} if split == 'validation' else None,
                'fp_score_quantiles_validation': {v: np.quantile(scores, (0, .5, .9, .99, 1)).tolist()
                                                 for v, scores in fp_scores.items() if scores}}

        coverage = {'total_images': len(inventory['cameras']), 'skipped_images': 0,
                    'class_support': inventory['class_support'], 'by_sequence': {}, 'blockers': [],
                    'eligible_labels_in_skipped_images': [0]*4}
        used_support = np.zeros(4, int)
        for row in inventory['cameras']:
            seq = row['key'].split(':')[0]
            seqrow = coverage['by_sequence'].setdefault(seq, {'images': 0, 'usable_images': 0, 'usable_frame_keys': []})
            seqrow['images'] += 1
            gt, labels = frame_cache[row['key']]
            b = row['binding']; e, k = np.array(b['E']), np.array(b['K'])
            w, h = shape_info[seq]['image_shapes_width_height'][row['camera']]
            blockers = near_plane_blockers(gt, e, k, w, h)
            if bool(blockers) != row['skipped_near_plane']:
                raise ValueError('Historical skip condition does not reproduce')
            if row['skipped_near_plane']:
                coverage['skipped_images'] += 1
                for blocker in blockers:
                    i = blocker['gt_index']
                    blocker.update(key=row['key'], camera=row['camera'], class_name=CLASSES[int(labels[i])-1])
                    blocker['source_length_width_height'] = [float(np.linalg.norm(gt[i, j]-gt[i, 0])) for j in (3, 1, 4)]
                    blocker['matches_verified_car1_dimensions'] = bool(np.allclose(
                        blocker['source_length_width_height'], (4.915, 1.937, 1.633), rtol=0, atol=1e-4))
                    coverage['blockers'].append(blocker)
                optical = gt @ e[:3, :3].T + e[:3, 3]
                front = (optical[:, :, 2] > .1).all(1)
                eligible = projected_targets(gt[front], labels[front], e, k, w, h)
                for obj in eligible:
                    if obj['class'] >= 0:
                        coverage['eligible_labels_in_skipped_images'][obj['class']] += 1
            else:
                seqrow['usable_images'] += 1
                seqrow['usable_frame_keys'].append(row['key'])
                targets = projected_targets(gt, labels, e, k, w, h)
                if sum(x['class'] >= 0 for x in targets) != row['positive_count']:
                    raise ValueError('Historical positive count does not reproduce')
                for obj in targets:
                    if obj['class'] >= 0:
                        used_support[obj['class']] += 1
        if used_support.tolist() != inventory['class_support']:
            raise ValueError('Recomputed class support differs')
        for row in coverage['by_sequence'].values():
            row['usable_frame_keys'] = sorted(set(row['usable_frame_keys']))
        coverage['usable_images'] = coverage['total_images']-coverage['skipped_images']
        coverage['epochs'] = []
        for epoch in sorted({row['epoch'] for row in training}):
            rows = [r for r in training if r['epoch'] == epoch]
            names = sorted({k for r in rows for k in r['losses']})
            coverage['epochs'].append({'epoch': epoch, 'updates': len(rows),
                'positive_images': sum(r['positive_count'] > 0 for r in rows),
                'mean_losses': {k: sum(r['losses'].get(k, 0) for r in rows)/len(rows) for k in names}})
        if len(training) != r['freeze']['updates'] or len(training) != coverage['usable_images']*r['freeze']['epochs']:
            raise ValueError('Actual training update accounting differs')
        results['training_coverage'] = coverage
        # A fixed qualitative selection: highest score per kind/class/reason,
        # then at most18 total. These are deliberately selected cases, not a sample
        # for estimating rates or selecting a threshold/model.
        selected = []
        seen = set()
        for c in sorted(candidates, key=lambda c: (-c['score'], c['key'], c['prediction_index'])):
            group = (c['kind'], c['class'], c.get('reason'), c['variant'])
            if group not in seen:
                seen.add(group); selected.append(c)
        priorities = {'recovered_vs_lidar': 0, 'outdoor_gt_not_detected_after_finetune': 1, 'false_positive': 2}
        selected.sort(key=lambda c: (priorities[c['kind']], c['class'], -c['score']))
        limited = []; per_class_fp = Counter()
        for c in selected:
            if c['kind'] == 'false_positive':
                if per_class_fp[c['class']] >= 3:
                    continue
                per_class_fp[c['class']] += 1
            limited.append(c)
        selected = limited[:24]
        results['qualitative_selection'] = selected
        results['limitations'] = [
            'Counts are GT appearances, not unique tracks. No model or policy was trained.',
            'Validation was previously inspected; this is post-hoc diagnosis, not an independent test.',
            'FP groups describe BEV overlap, not verified image background or a unique causal explanation.',
            'Near-plane blockers are geometry; identifying an ego vehicle requires source identity evidence.',
            'Labels in skipped images are offline eligibility counts, not a demonstrated better training policy.',
            'GT cuboid corner order in pinned OpenCOOD: edge0-1 width, edge0-3 length. Historical trainer used the reverse.',
            'Swapping dimensions plus pose can preserve corner geometry but changes native width/length semantics and priors.']
        dump(output/'audit.json', results)
        dump(output/'selected-cases.json', selected)
        lines = ['# RGB fine-tuning audit21685167', '',
                 'Source archive SHA256: '+receipt['source_sha256'],
                 'All9 variants: class AP@.3/.5/.7 and macro AP reproduced in BOTH orders on TRAIN400/validation200 (absolute AP tolerance1e-7; TP/FP/GT exact).', '',
                 f'Actual training: {coverage["usable_images"]}/{coverage["total_images"]} camera images; '
                 f'{coverage["skipped_images"]} skipped; {len(training)} updates over4 epochs.',
                 'Class support (Vehicle/Heavy_Vehicle/2Wheeler/Pedestrian): '+str(used_support.tolist()), '',
                 '| Variant | VAL AP@.5 (%) | TP | FP | Added GT vs LiDAR | Lost GT vs LiDAR |', '|---|---:|---:|---:|---:|---:|']
        val = results['splits']['validation']
        for v in variants:
            ap = val['metrics'][v]['global_confidence_sort']['macro_ap']['0.5']
            counts = val['counts'][v]; gains = val['vs_lidar'].get(v, {'gained': 0, 'lost': 0})
            lines.append(f'| {v} | {100*ap:.4f} | {counts["tp"]} | {counts["fp"]} | {gains["gained"]} | {gains["lost"]} |')
        lines += ['', 'The intended TRAIN400 adaptation was not executed: whole-image filtering left only59 images.',
                  'Do not attribute this result to RGB modality limits or claim that four full TRAIN400 epochs failed.',
                  'Native width/length target semantics also disagree with the pinned source corner order.',
                  'Repair/verify data preparation and native semantics before another training run. No retraining in this audit.']
        (output/'summary.md').write_text('\n'.join(lines)+'\n')
        print('\n'.join(lines), flush=True)
        return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', required=True, type=Path)
    p.add_argument('--metadata', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    audit(a.inputs, a.metadata, a.output)


if __name__ == '__main__':
    main()
