"""Replay a CPU-BEV export and diagnose its decoder, without training.

Oracle outputs use validation GT and are strictly offline representation checks.
They are not detector results and must not be used to select hyperparameters.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import (
    _radius_mask, aggregate_statistics, frame_statistics, summarize_cached,
)
from phdsim.perception.urbaning.bev_cpu import decode, geometry, targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.export
    report = json.loads((root / 'report.json').read_text())
    priors = json.loads((root / 'train-only-priors.json').read_text())
    config = json.loads((root / 'configuration.json').read_text())
    assert report['status'] == 'completed'
    grid = config['grid']
    result = {'purpose': __doc__, 'numpy': np.__version__, 'modes': {},
              'oracle_decoder_checks': {}, 'frames': report['frames']}
    source_root = Path(__file__).resolve().parents[1] / 'src/phdsim'
    result['verified_source_sha256'] = {}
    for name, relative in [('urbaning_bev_cpu.py', 'experiments/urbaning_bev_cpu.py'),
                           ('bev_cpu.py', 'perception/urbaning/bev_cpu.py'),
                           ('urbaning_rgb_pilot.py', 'experiments/urbaning_rgb_pilot.py')]:
        digest = hashlib.sha256((source_root / relative).read_bytes()).hexdigest()
        assert digest == config['code'][name], 'Source differs from original run: ' + name
        result['verified_source_sha256'][name] = digest
    truths = {}
    for mode in ('rgb', 'lidar', 'rgb_lidar'):
        stats = []
        diagnostics = {name: {'predictions': 0, 'gt': 0, 'center_distances_m': [],
                             'gt_centers_with_prediction_within_1m': 0,
                             'pred_edge_a_m': [], 'pred_edge_b_m': []}
                       for name in CLASSES}
        files = sorted((root / (mode + '-predictions')).glob('*.npz'))
        assert len(files) == report['frames']['validation']
        if mode != 'rgb':
            assert set(path.name for path in files) == set(truths), 'Frame keys differ'
        for index, path in enumerate(files):
            with np.load(path, allow_pickle=False) as data:
                boxes, scores = data['boxes'], data['scores']
                gt, labels = data['gt_boxes'], data['gt_labels']
                digest = hashlib.sha256(gt.tobytes() + labels.tobytes()).hexdigest()
                if mode == 'rgb':
                    truths[path.name] = (gt.copy(), labels.copy(), digest)
                else:
                    assert digest == truths[path.name][2], 'GT differs across modalities'
                stats.append(frame_statistics(boxes, scores, gt, labels))
                boxes, scores = boxes[_radius_mask(boxes)], scores[_radius_mask(boxes)]
                gt, labels = gt[_radius_mask(gt)], labels[_radius_mask(gt)]
                for c, name in enumerate(CLASSES, 1):
                    pred = boxes[scores[:, 1] == c]
                    truth = gt[labels == c]
                    row = diagnostics[name]
                    row['predictions'] += len(pred); row['gt'] += len(truth)
                    for box in pred:
                        _, a, b, _, _ = geometry(box)
                        row['pred_edge_a_m'].append(a); row['pred_edge_b_m'].append(b)
                    if len(pred) and len(truth):
                        distance = np.linalg.norm(pred.mean(1)[:, None, :2] - truth.mean(1)[None, :, :2], axis=2)
                        row['center_distances_m'].extend(distance.min(1).tolist())
                        row['gt_centers_with_prediction_within_1m'] += int((distance.min(0) < 1).sum())
            if (index + 1) % 50 == 0:
                print(f'REPLAY {mode} {index+1}/{len(files)}', flush=True)
        combined = aggregate_statistics(stats)
        summaries = {}
        max_error = 0.
        for order, global_sort in [('global_confidence_sort', True), ('upstream_default_frame_order', False)]:
            summary = summarize_cached(combined, global_sort)
            expected = report['validation'][mode][order]
            for name in CLASSES:
                assert summary['classes'][name]['ground_truth_count'] == expected['classes'][name]['ground_truth_count']
                for t in ('0.3', '0.5', '0.7'):
                    max_error = max(max_error, abs(summary['classes'][name]['ap'][t] - expected['classes'][name]['ap'][t]))
            for t in ('0.3', '0.5', '0.7'):
                max_error = max(max_error, abs(summary['macro_ap'][t] - expected['macro_ap'][t]))
            summaries[order] = summary
        assert max_error < 1e-12, max_error
        for name, row in diagnostics.items():
            for key in ('center_distances_m', 'pred_edge_a_m', 'pred_edge_b_m'):
                values = row.pop(key)
                row[key + '_quantiles_10_50_90'] = np.quantile(values, [.1, .5, .9]).tolist() if values else None
            row['true_positives_iou05'] = sum(combined[name][.5]['tp'])
            row['recall_iou05'] = row['true_positives_iou05'] / row['gt']
        result['modes'][mode] = {'max_class_ap_absolute_error': max_error,
                                 'metrics': summaries, 'diagnostics': diagnostics}
    # Fill exact target regressions and heat peaks from GT. This tests the
    # target/decoder path, including peak suppression, clipping, top-k and NMS.
    # It does NOT test calibration, feature extraction, visibility or learning.
    for label, topk, nms in [('original_decoder', 40, .2), ('relaxed_cap_and_nms', 500, 1.)]:
        stats = []; counts = {'radius_gt': 0, 'outside_center_grid': 0, 'same_class_cell_collisions': 0}
        for index, (key, (gt, labels, _)) in enumerate(sorted(truths.items())):
            target = targets(gt, labels, priors, grid)
            heat = torch.logit(target['heat'].clamp(1e-7, 1-1e-7))
            regression = torch.zeros((1, 4, 8, grid['size'], grid['size']))
            if len(target['locations']):
                c, y, x = target['locations'].T
                regression[0, c, :, y, x] = target['regression']
            boxes, scores = decode((heat, regression), priors, grid, topk=topk, nms_iou=nms)
            stats.append(frame_statistics(boxes, scores, gt, labels))
            for field in counts: counts[field] += target['statistics'][field]
            if (index + 1) % 50 == 0:
                print(f'OFFLINE GT DECODER {label} {index+1}/{len(truths)}', flush=True)
        combined = aggregate_statistics(stats)
        result['oracle_decoder_checks'][label] = {
            'NOT_A_MODEL_RESULT': True, 'topk': topk, 'nms_iou': nms,
            'target_counts': counts, 'metrics': summarize_cached(combined),
            'recall_iou05': {name: sum(combined[name][.5]['tp']) / combined[name][.5]['gt'] for name in CLASSES}}
    result['not_checked'] = ['Native RGB/LiDAR feature alignment: input feature caches absent from archive',
                             'Training diagnostic AP: training predictions absent from archive',
                             'Independent test/generalization: validation was previously inspected']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(args.output, flush=True)


if __name__ == '__main__':
    torch.set_num_threads(2)
    main()
