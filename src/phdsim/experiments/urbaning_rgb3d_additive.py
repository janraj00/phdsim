"""Evaluate predeclared LiDAR-preserving fusion on cached TRAIN/validation.

No threshold search, fitting or new detector calls. Current validation has
already been inspected; this is an exploratory development comparison.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import aggregate_statistics, summarize_cached
from phdsim.experiments.urbaning_rgb3d_complementarity import (
    audit_frame, combine, describe_pair, match_frame, sha, VARIANTS)
from phdsim.perception.urbaning.rgb3d_additive import additive_fuse, OVERLAP_THRESHOLD

NEW_VARIANTS = tuple(stage+'_'+rule for stage in ('baseline', 'depth_finetuned')
                     for rule in ('additive_raw', 'additive_lidar_first'))


def new_outcomes(data):
    rows = {}
    for stage, key in [('baseline', 'baseline'), ('depth_finetuned', 'depth')]:
        for rule, first in [('additive_raw', False), ('additive_lidar_first', True)]:
            rows[stage+'_'+rule] = additive_fuse(
                data['lidar_boxes'], data['lidar_scores'],
                data['rgb_'+key+'_boxes'], data['rgb_'+key+'_scores'], lidar_first=first)
    return rows


def compare_frame(data):
    old_stats, _ = audit_frame(data)
    gt, labels = data['gt_boxes'], data['gt_labels']
    lidar = match_frame(data['lidar_boxes'], data['lidar_scores'], gt, labels)
    stats, traces, outputs = {}, {}, new_outcomes(data)
    for v, (boxes, scores, keep, decisions) in outputs.items():
        key = 'baseline' if v.startswith('baseline_') else 'depth'
        rb, rs = data['rgb_'+key+'_boxes'], data['rgb_'+key+'_scores']
        rgb = match_frame(rb, rs, gt, labels)
        fused = match_frame(boxes, scores, gt, labels)
        stats[v] = fused[0]
        trace = describe_pair(data, rb, rs, lidar, rgb, fused, keep)
        trace['rgb_candidates'] = decisions
        trace['lidar_boxes_preserved'] = len(data['lidar_boxes'])
        trace['rgb_added'] = len(keep)-len(data['lidar_boxes'])
        # describe_pair retains raw source confidences. Record changed rank
        # scores explicitly instead of presenting them as calibrated confidence.
        for row in trace['fusion_gained_objects']:
            row['evaluation_rank_score'] = float(scores[row['fusion_prediction_index'], 0])
        for row in trace['losses']:
            if row['reason'] != 'lost_lidar_retained_matching_changed':
                raise ValueError('An additive variant removed a LiDAR prediction')
        traces[v] = trace
    return {**old_stats, **stats}, traces, outputs


def metrics_from_stats(stats):
    return {v: {name: summarize_cached(aggregate_statistics(rows), glob)
                for name, glob in [('global_confidence_sort', True),
                                   ('upstream_default_frame_order', False)]}
            for v, rows in stats.items()}


def run(source, output, *, expected_counts=(400, 200)):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Use a fresh output directory')
    raw = source.read_bytes()
    source_sha = sha(raw)
    done = source.with_name('completed.json')
    if done.is_file() and json.loads(done.read_text())['sha256'] != source_sha:
        raise ValueError('Source completion checksum differs')
    output.mkdir(parents=True)
    policy = {'overlap_threshold': OVERLAP_THRESHOLD,
              'raw': 'preserve all original LiDAR boxes/scores; reject same-class RGB overlap; RGB-only NMS',
              'lidar_first': 'same boxes; rank LiDAR=.5+.5*s, RGB=.49*s; not calibrated probabilities',
              'selection': 'two fixed rules on both frozen RGB variants; no parameter or best-variant selection',
              'validation_status': 'previously inspected development recording, not independent test',
              'numpy': np.__version__, 'python': sys.version,
              'source_sha256': source_sha,
              'code_sha256': {str(p.relative_to(Path(__file__).parents[3])): sha(p.read_bytes()) for p in (
                  Path(__file__), Path(__file__).parents[1]/'perception/urbaning/rgb3d_additive.py',
                  Path(__file__).with_name('urbaning_rgb3d_complementarity.py'),
                  Path(__file__).parents[1]/'evaluation/urbaning_cached.py',
                  Path(__file__).parents[1]/'perception/urbaning/rgb3d_late.py',
                  Path(__file__).parents[3]/'scripts/urbaning_rgb3d_additive.py',
                  Path(__file__).parents[3]/'scripts/slurm/urbaning_rgb3d_additive.sbatch')}}
    # Persist the fixed comparison BEFORE replaying either split. No fitting,
    # threshold search, filtering by GT or choice of a winner is performed.
    (output/'protocol.json').write_text(json.dumps(policy, indent=2)+'\n')
    result = {'schema': 'phdsim-rgb3d-additive-v1', 'protocol': policy, 'splits': {},
              'limitations': [
                  'GT is offline evaluation only; all original evaluation GT retained.',
                  'Preserving boxes does not guarantee identical greedy GT matches or better mAP.',
                  'LiDAR-first explicitly changes ranking; any AP gain is conditional on this fixed priority rule.',
                  'Rank scores are not calibrated probabilities or transferable confidence thresholds.',
                  'An AP-preserving ranking can still add false positives and lower operating-point precision.',
                  'Counts are GT appearances, not unique tracks. No requests/bytes/latency measured.',
                  'Development data already inspected; no generalization claim or crossing3 tuning.']}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or z.testzip() is not None:
            raise ValueError('Corrupt or duplicate archive members')
        original = json.loads(z.read('report.json'))
        if original.get('schema') != 'phdsim-rgb3d-native-depth-controlled-v1':
            raise ValueError('Expected native-depth controlled source')
        for split, count in zip(('train', 'validation'), expected_counts):
            entries = sorted(n for n in names if n.startswith('frames-'+split+'/') and n.endswith('.npz'))
            if len(entries) != count:
                raise ValueError('Source frame inventory differs')
            stats = {v: [] for v in (*VARIANTS, *NEW_VARIANTS)}
            frames = []
            frame_dir = output/('frames-'+split)
            frame_dir.mkdir()
            for j, entry in enumerate(entries):
                with np.load(io.BytesIO(z.read(entry)), allow_pickle=False) as f:
                    data = {k: f[k] for k in f.files}
                fs, traces, outcomes = compare_frame(data)
                for v, row in fs.items():
                    stats[v].append(row)
                sequence, number, ego = Path(entry).stem.rsplit('_', 2)
                if not number.isdigit() or not ego.isdigit():
                    raise ValueError('Bad frame identity')
                payload = {'gt_boxes': data['gt_boxes'], 'gt_labels': data['gt_labels'],
                           'lidar_boxes': data['lidar_boxes'], 'lidar_scores': data['lidar_scores'],
                           'rgb_baseline_boxes': data['rgb_baseline_boxes'],
                           'rgb_baseline_scores': data['rgb_baseline_scores'],
                           'rgb_depth_boxes': data['rgb_depth_boxes'], 'rgb_depth_scores': data['rgb_depth_scores']}
                for v, (b, s, keep, _) in outcomes.items():
                    payload[v+'_boxes'], payload[v+'_scores'], payload[v+'_union_indices'] = b, s, keep
                path = frame_dir/Path(entry).name
                np.savez_compressed(path, **payload)
                frames.append({'key': sequence+':'+number+':'+ego, 'sequence': sequence,
                               'payload_sha256': sha(path.read_bytes()), 'variants': traces})
                if (j+1) % 25 == 0:
                    print('ADDITIVE', split, j+1, '/', count, flush=True)
            metrics = metrics_from_stats(stats)
            if {v: metrics[v] for v in VARIANTS} != original[split+'_metrics']:
                raise ValueError('Source AP parity failed; reject new comparison')
            # Independently replay ALL newly written NPZ outputs before accepting
            # their results. This does not call any fusion/selection function.
            replay = {v: [] for v in NEW_VARIANTS}
            for frame in frames:
                filename = frame['key'].replace(':', '_')+'.npz'
                with np.load(frame_dir/filename, allow_pickle=False) as f:
                    for v in NEW_VARIANTS:
                        replay[v].append(match_frame(f[v+'_boxes'], f[v+'_scores'],
                                                    f['gt_boxes'], f['gt_labels'])[0])
            if metrics_from_stats(replay) != {v: metrics[v] for v in NEW_VARIANTS}:
                raise ValueError('Independent saved-outcome AP replay failed')
            summaries = {v: combine([f['variants'][v] for f in frames]) for v in NEW_VARIANTS}
            for v, row in summaries.items():
                row['rgb_added'] = sum(f['variants'][v]['rgb_added'] for f in frames)
                row['lidar_boxes_preserved'] = sum(f['variants'][v]['lidar_boxes_preserved'] for f in frames)
                a = metrics[v]['global_confidence_sort']['macro_ap']['0.5']
                b = metrics['lidar']['global_confidence_sort']['macro_ap']['0.5']
                row['delta_vs_lidar_pp'] = None if a is None or b is None else 100*(a-b)
            by_sequence = {seq: {v: combine([f['variants'][v] for f in frames if f['sequence'] == seq])
                                 for v in NEW_VARIANTS} for seq in sorted({f['sequence'] for f in frames})}
            operating_counts = {}
            for v, ss in stats.items():
                classes = {name: {'gt': sum(s[name][.5]['gt'] for s in ss),
                                  'tp': sum(sum(s[name][.5]['tp']) for s in ss),
                                  'fp': sum(sum(s[name][.5]['fp']) for s in ss)} for name in CLASSES}
                total = {k: sum(c[k] for c in classes.values()) for k in ('gt', 'tp', 'fp')}
                operating_counts[v] = {'total': total, 'classes': classes}
            result['splits'][split] = {'frames': count, 'source_ap_reproduced': True,
                                      'saved_new_ap_reproduced': True, 'metrics': metrics,
                                      'operating_counts': operating_counts, 'variants': summaries,
                                      'by_sequence': by_sequence, 'per_frame': frames}
            print('PARITY', split, 'all5 source variants / both AP orders / new raw-output replay PASSED', flush=True)
    if sha(source.read_bytes()) != source_sha:
        raise ValueError('Source changed during replay')
    lines = ['# LiDAR-preserving additive RGB fusion',
             'Fixed .2 same-class overlap rejection; no fitting or validation parameter selection.',
             'LiDAR-first values are priority ranks, not calibrated confidence.\n']
    for split, rows in result['splits'].items():
        lines += [f'## {split}: {rows["frames"]} frames',
                  '| Variant | BEV mAP@.5 (%) | Delta vs LiDAR (pp) |', '|---|---:|---:|']
        reference = rows['metrics']['lidar']['global_confidence_sort']['macro_ap']['0.5']
        for v, m in rows['metrics'].items():
            a = m['global_confidence_sort']['macro_ap']['0.5']
            av = 'N/A' if a is None else f'{100*a:.4f}'
            delta = 'N/A' if a is None or reference is None else f'{100*(a-reference):+.4f}'
            lines.append(f'| {v} | {av} | {delta} |')
        lines += ['', '| Variant | Added RGB boxes | Additional GT vs LiDAR | Lost GT vs LiDAR | False positives |',
                  '|---|---:|---:|---:|---:|']
        lines.append(f'| lidar | 0 | 0 | 0 | {rows["operating_counts"]["lidar"]["total"]["fp"]} |')
        for v, r in rows['variants'].items():
            c = r['total']
            lines.append(f'| {v} | {r["rgb_added"]} | {c["fusion_gained"]} | {c["fusion_lost"]} | {c["fusion_fp"]} |')
        lines += ['', '| Variant | Vehicle AP@.5 (%) | Heavy_Vehicle | 2Wheeler | Pedestrian |',
                  '|---|---:|---:|---:|---:|']
        for v, m in rows['metrics'].items():
            values = [m['global_confidence_sort']['classes'][c]['ap']['0.5'] for c in CLASSES]
            lines.append('| '+v+' | '+' | '.join('N/A' if a is None else f'{100*a:.4f}' for a in values)+' |')
    lines += ['', 'Physical LiDAR boxes are preserved in both new rules. Greedy matching can still change.',
              'LiDAR-first deliberately protects ranking; interpret AP alongside added FP and per-class recovery.',
              'TRAIN/validation are separate; validation has previously been inspected. No independent test claim.']
    (output/'report.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'source-report.json').write_text(json.dumps(original, indent=2, allow_nan=False)+'\n')
    archive = output/'urbaning-rgb3d-additive.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('report.json', 'summary.md', 'protocol.json', 'source-report.json'):
            z.write(output/name, name)
        for folder in ('frames-train', 'frames-validation'):
            for p in sorted((output/folder).glob('*.npz')):
                z.write(p, str(p.relative_to(output)))
    print('\n'.join(lines), flush=True)
    print('SHA256', sha(archive.read_bytes()), 'bytes', archive.stat().st_size, flush=True)
    print('DONE:', archive, flush=True)
    return archive


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    run(a.source.resolve(), a.output.resolve())


if __name__ == '__main__':
    main()
