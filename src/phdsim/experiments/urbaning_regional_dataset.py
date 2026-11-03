"""Build fixed-grid Car1 inputs and offline spatial targets from frozen caches.

No learning, detector inference, upstream imports, installs or network access.
GT and counterfactual perception are confined to the target builder and audits.
"""

import argparse
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets
from phdsim.evaluation.urbaning import CLASSES
from phdsim.experiments.urbaning_frame_inspection import audit_frame
from phdsim.experiments.urbaning_geometry import load_sidecars
from phdsim.experiments.urbaning_subsets import _inside, digest, load_runs, write_json
from phdsim.learning.urbaning import recording_group
from phdsim.learning.urbaning_regions import (
    CELL_COUNT, CELL_SIZE, FEATURES, LOW_SCORE, MAX_XY, MIN_XY, OVERFLOW,
    SCHEMA, SIDE, SPATIAL_CELLS, assign_cells, cell_centers, regional_features)

STATS = ('tp', 'fp', 'fn')


def validate_split_headers(train_runs, validation_runs):
    groups, sequences = {}, {}
    for split, paths in (('train', train_runs), ('validation', validation_runs)):
        if not paths:
            raise ValueError('Both training and validation recordings are required')
        sequences[split] = []
        for path in paths:
            run = json.loads((Path(path) / 'run.json').read_text())
            sequence = run['arguments']['sequence']
            recording_group(sequence)
            if 'crossing3' in sequence or str(run['arguments']['ego_id']) != '100000':
                raise ValueError('Regional development uses Car1 crossing1/2 only; crossing3 is rejected')
            sequences[split].append(sequence)
        if len(set(sequences[split])) != len(sequences[split]):
            raise ValueError('Duplicate input sequence')
        groups[split] = sorted({recording_group(s) for s in sequences[split]})
    if set(groups['train']) & set(groups['validation']):
        raise ValueError('Training and validation overlap an original recording')
    return groups


def regional_targets(data, audit):
    """Globally match first, then assign TP/FN by GT center and FP by pred center.

This conserves counts across cell boundaries. No per-cell rematching or F1
averaging is performed. Overflow retains all eligible out-of-grid instances.
Unavailable canonical actions have -1 counts/recoveries/losses and zero deltas;
their explicit availability mask is mandatory for any future training.
"""
    gt = np.asarray(data['gt_boxes'])
    labels = np.asarray(data['gt_labels'], dtype=int) - 1
    gt_cells = assign_cells(gt[:, :4, :2].mean(axis=1))
    counts = np.full((CELL_COUNT, 4, 4, 3), -1, dtype=np.int32)
    recovered = np.full((CELL_COUNT, 4, 4), -1, dtype=np.int32)
    lost = np.full_like(recovered, -1)
    gt_counts = np.zeros((CELL_COUNT, 4), dtype=np.int32)
    retained = np.array(audit['outcomes']['ego']['gt_indices_considered'], dtype=int)
    np.add.at(gt_counts, (gt_cells[retained], labels[retained]), 1)
    available = np.array([a in audit['outcomes'] for a in ACTION_ORDER], dtype=bool)
    for j, action in enumerate(ACTION_ORDER):
        if not available[j]:
            continue
        result = audit['outcomes'][action]
        counts[:, j], recovered[:, j], lost[:, j] = 0, 0, 0
        for stat, ids in (('tp', result['matched_gt_indices']), ('fn', result['missed_gt_indices'])):
            indices = np.array(ids, dtype=int)
            np.add.at(counts[:, j, :, STATS.index(stat)], (gt_cells[indices], labels[indices]), 1)
        false = np.array(result['false_positive_indices'], dtype=int)
        boxes = np.asarray(data[action + '_boxes'])
        scores = np.asarray(data[action + '_scores'])
        false_cells = assign_cells(boxes[false, :4, :2].mean(axis=1))
        np.add.at(counts[:, j, :, 1], (false_cells, scores[false, 1].astype(int) - 1), 1)
        for output, field in ((recovered, 'recovered_vs_ego_gt_indices'), (lost, 'lost_vs_ego_gt_indices')):
            indices = np.array(result[field], dtype=int)
            np.add.at(output[:, j], (gt_cells[indices], labels[indices]), 1)
        # These invariants make the regional targets a partition of the exact
        # frozen evaluator's outcomes, including boxes straddling grid edges.
        if not np.array_equal(counts[:, j, :, 0] + counts[:, j, :, 2], gt_counts):
            raise ValueError('Regional GT support differs between actions')
        total = counts[:, j].sum(axis=(0, 1))
        if not np.array_equal(total, [result[s] for s in STATS]):
            raise ValueError('Regional counts do not conserve full-frame matching')
        tp, fp, fn = map(int, total)
        f1 = 2*tp / (2*tp + fp + fn) if 2*tp + fp + fn else 1.
        if abs(f1 - result['f1']) > 1e-12:
            raise ValueError('Summed regional counts changed frame F1')
    deltas = np.zeros_like(counts)
    for j in np.flatnonzero(available):
        deltas[:, j] = counts[:, j] - counts[:, 0]
        if not np.array_equal(deltas[:, j, :, 0], recovered[:, j] - lost[:, j]):
            raise ValueError('TP deltas disagree with recovered/lost GT identities')
    return {'counts': counts, 'delta_vs_ego': deltas, 'recovered_gt': recovered,
            'lost_gt': lost, 'gt_counts': gt_counts, 'available': available}


def sequence_summary(inputs, targets):
    result = {'frames': len(inputs), 'cells_per_frame': CELL_COUNT,
              'car1_empty_spatial_cell_fraction': float(np.mean(inputs[:, :SPATIAL_CELLS, FEATURES.index('ego_empty')])),
              'actions': {}}
    for j, action in enumerate(ACTION_ORDER):
        mask = targets['available'][:, j]
        if not mask.any():
            result['actions'][action] = {'available_frames': 0}
            continue
        counts = targets['counts'][mask, :, j]
        delta = targets['delta_vs_ego'][mask, :, j]
        # This is an additive descriptive error-reduction target, not AP/F1 or
        # a newly chosen acquisition utility. Negative values denote harm.
        gain = -delta[:, :SPATIAL_CELLS, :, 1:].sum(axis=(2, 3))
        result['actions'][action] = {
            'available_frames': int(mask.sum()),
            'total_counts': dict(zip(STATS, map(int, counts.sum(axis=(0, 1, 2))))),
            'overflow_counts': dict(zip(STATS, map(int, counts[:, OVERFLOW].sum(axis=(0, 1))))),
            'spatial_error_reduction_cells': {'positive': int((gain > 0).sum()),
                                            'zero': int((gain == 0).sum()), 'negative': int((gain < 0).sum())},
            'recovered_gt': int(targets['recovered_gt'][mask, :, j].sum()),
            'lost_gt': int(targets['lost_gt'][mask, :, j].sum())}
    return result


def plot_example(x, target, poses, key, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    try:
        extent = (MIN_XY, MAX_XY, MIN_XY, MAX_XY)
        local = x[:SPATIAL_CELLS, FEATURES.index('ego_low_count_over_10')] * 10
        image = axes[0, 0].imshow(local.reshape(SIDE, SIDE).T, origin='lower', extent=extent,
                                  cmap='Blues', interpolation='nearest', vmin=0)
        axes[0, 0].set_title('Before query: count of Car1 detections with score < 0.5')
        fig.colorbar(image, ax=axes[0, 0], shrink=.7)
        gains = -target['delta_vs_ego'][:SPATIAL_CELLS, :, :, 1:].sum(axis=(2, 3))
        vmax = max(1., float(np.abs(gains).max()))
        for j, (ax, action) in enumerate(zip(axes.ravel()[1:], ACTION_ORDER[1:]), 1):
            if target['available'][j]:
                im = ax.imshow(gains[:, j].reshape(SIDE, SIDE).T, origin='lower', extent=extent,
                               cmap='RdBu', interpolation='nearest', vmin=-vmax, vmax=vmax)
                fig.colorbar(im, ax=ax, shrink=.7)
                ax.set_title('Offline target: {}\nFP + FN reduction vs Car1'.format(action))
            else:
                ax.set_title(action + ': unavailable (no target)')
        for ax in axes.ravel():
            ax.scatter(0, 0, color='black', marker='*', s=70)
            for identity, matrix in poses.items():
                position = np.asarray(matrix)[:2, 3]
                ax.scatter(*position, marker='^' if int(identity) > 0 else 's', s=35,
                           color='#2f7b34' if int(identity) > 0 else '#8d36a8')
            ax.set(xlim=(MIN_XY, MAX_XY), ylim=(MIN_XY, MAX_XY),
                   xlabel='Car1 frame x [m]', ylabel='Car1 frame y [m]')
            ax.set_aspect('equal')
        fig.suptitle(key + '\n10m fixed cells; blue target = fewer errors, red = more errors; no visibility map', fontsize=11)
        fig.text(.5, .02, 'Blank local cells mean no low-score detection, not observed free space. '
                 'GT targets are offline only. Overflow is saved separately. Infra marker = site origin proxy.',
                 ha='center', fontsize=8)
        fig.tight_layout(rect=(0, .05, 1, .93)); fig.savefig(output, dpi=140)
    finally:
        plt.close(fig)
    from PIL import Image
    with Image.open(output) as image:
        image.verify()


def export_sequence(run_path, pose_path, dest, split):
    root = Path(run_path).resolve()
    def progress(sequence, n, total):
        if n % 25 == 0 or n == total:
            print('VERIFY {} {}/{}'.format(sequence, n, total), flush=True)
    frames, provenance = load_runs([root], [pose_path], progress=progress)
    trace = root / 'frames.jsonl'
    trace_hash = provenance['inputs'][0]['trace_sha256']
    if digest(trace) != trace_hash:
        raise ValueError('Trace changed during verification')
    sidecar, sidecar_hash = load_sidecars([pose_path])[trace_hash]
    if sidecar_hash != provenance['inputs'][0]['geometry_sidecar_sha256']:
        raise ValueError('Pose sidecar changed during verification')
    rows = {r['frame_key']: r for r in map(json.loads, trace.read_text().splitlines())}
    sequence = frames[0]['sequence']
    folder = dest / split / sequence
    folder.mkdir(parents=True)
    inputs, masks, labels, metadata = [], [], [], []
    example_index = next((i for i, f in enumerate(frames) if rows[f['key']]['source_frame_id'] == '000161'), len(frames)//2)
    for i, frame in enumerate(frames):
        row = rows[frame['key']]
        payload = _inside(root, row['predictions'])
        expected = provenance['inputs'][0]['predictions_sha256'][row['predictions']]
        if digest(payload) != expected:
            raise ValueError('Prediction cache changed during export')
        poses = sidecar['frames'][frame['key']]
        with np.load(payload, allow_pickle=False) as data:
            # The feature builder receives no GT or peer detections.
            x, available = regional_features(frame['source_ids'], frame['ego_entropy'],
                                             data['ego_boxes'], data['ego_scores'], poses)
            audit = audit_frame(frame, data)
            target = regional_targets(data, audit)
        if not np.array_equal(available, target['available']):
            raise ValueError('Feature/target action availability mismatch')
        inputs.append(x); masks.append(available); labels.append(target)
        metadata.append({'frame_key': frame['key'], 'sequence': sequence, 'recording_group': recording_group(sequence),
                         'source_ids': frame['source_ids'], 'native_association': frame['native_association'],
                         'payload_sha256': expected, 'gt_sha256': row['gt_sha256']})
        if split == 'validation' and i == example_index:
            plot_example(x, target, poses, frame['key'], folder / 'regional-example.png')
        if (i + 1) % 25 == 0 or i + 1 == len(frames):
            print('REGIONS {} {}/{}'.format(sequence, i + 1, len(frames)), flush=True)
    x = np.stack(inputs)
    target = {k: np.stack([label[k] for label in labels]) for k in labels[0]}
    keys = np.array([f['key'] for f in frames], dtype=str)
    np.savez_compressed(folder / 'inputs.npz', features=x, available=np.stack(masks),
                        frame_keys=keys, cell_centers=cell_centers().astype(np.float32))
    np.savez_compressed(folder / 'offline-targets.npz', **target, frame_keys=keys)
    with (folder / 'frames.jsonl').open('x') as stream:
        for record in metadata:
            stream.write(json.dumps(record, allow_nan=False) + '\n')
    summary = sequence_summary(x, target)
    write_json(folder / 'summary.json', summary)
    print('DONE SEQUENCE', sequence, flush=True)
    return {'split': split, 'sequence': sequence, 'provenance': provenance, 'summary': summary,
            'files': {str(p.relative_to(dest)): digest(p) for p in sorted(folder.iterdir()) if p.is_file()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-runs', nargs='+', required=True)
    parser.add_argument('--validation-runs', nargs='+', required=True)
    parser.add_argument('--train-geometry', nargs='+', required=True)
    parser.add_argument('--validation-geometry', nargs='+', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    out = Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError('Preserve existing data; select a new regional output directory')
    groups = validate_split_headers(args.train_runs, args.validation_runs)
    for paths, poses in ((args.train_runs, args.train_geometry), (args.validation_runs, args.validation_geometry)):
        if len(paths) != len(poses):
            raise ValueError('Provide one pose sidecar per input recording')
        for path in paths:
            if out.is_relative_to(Path(path).resolve()):
                raise ValueError('Regional output must be outside immutable input caches')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: F401
    out.mkdir(parents=True)
    results, detector = [], None
    for split, paths, poses in (('train', args.train_runs, args.train_geometry),
                                ('validation', args.validation_runs, args.validation_geometry)):
        for path, pose in zip(paths, poses):
            result = export_sequence(path, pose, out, split)
            identity = result['provenance']['detector']
            if detector is not None and identity != detector:
                raise ValueError('Regional caches use different frozen detectors')
            detector = identity; results.append(result)
    code = subprocess.run(['git', '-C', str(Path(__file__).resolve().parents[3]), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()
    report = {'schema': SCHEMA, 'status': 'completed', 'scope': 'dataset export only; no policy fitted or evaluated',
              'code_commit': code, 'features': list(FEATURES), 'feature_count': len(FEATURES),
              'actions': list(ACTION_ORDER), 'classes': list(CLASSES), 'count_order': list(STATS),
              'grid': {'cell_size_m': CELL_SIZE, 'min_xy': MIN_XY, 'max_xy_exclusive': MAX_XY,
                       'shape': [SIDE, SIDE], 'spatial_cells': SPATIAL_CELLS, 'overflow_cell': OVERFLOW,
                       'assignment': 'ix * ny + iy by box BEV centroid; explicit overflow, no clipping/discard'},
              'recording_groups': groups, 'detector': detector, 'sequences': results,
              'frames': {s: sum(r['summary']['frames'] for r in results if r['split'] == s)
                         for s in ('train', 'validation')},
              'runtime': {'numpy': np.__version__, 'matplotlib': matplotlib.__version__},
              'semantics': {'delta_vs_ego': 'action count minus ego count, separately for TP/FP/FN and each class',
                            'recovered_gt': 'matched by action but missed by ego; assigned by GT center',
                            'lost_gt': 'matched by ego but missed by action; assigned by GT center',
                            'unavailable': 'mask false; counts/recovered/lost are -1 and deltas zero; never train on these',
                            'cost': '.05 per requested peer/frame in the existing protocol, never per cell',
                            'aggregation': 'sum counts over cells/classes before frame F1; never average cell F1'},
              'limitations': ['Cells and neighboring frames are correlated, not independent training recordings.',
                              'Targets describe whole-frame fusion actions, not ROI-only requests or spatial mixtures of actions.',
                              'No-detection cells are not evidence of observed free space or known uncertainty.',
                              'No raw point clouds, visibility/occlusion maps, RGB or thermal are used.',
                              'Infra geometry is a bundled site-origin proxy; pre-query pose sharing is assumed.',
                              'Native associations are preserved, not certified as causal online observations.',
                              'GT and peer perception occur only in offline labels/audits, not input features.']}
    write_json(out / 'regional-dataset-report.json', report)
    (out / 'README.txt').write_text(
        'Regional dataset only: no trained policy results.\n'
        'inputs.npz contains Car1 evidence and assumed metadata only.\n'
        'offline-targets.npz contains GT-derived supervision; apply the availability mask.\n'
        'Array order: frames, cells, [actions], [classes], [TP/FP/FN].\n'
        '400 fixed 10m cells plus one explicit overflow cell. All cells are retained.\n'
        'Cells are correlated samples; split by original recording, not by cell/frame.\n'
        'Do not sum/average local F1 or charge the communication cost per cell.\n')
    files = sorted(p for p in out.rglob('*') if p.is_file())
    with zipfile.ZipFile(out / 'urbaning-regional-dataset.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(path.relative_to(out)))
    print('DONE:', out / 'urbaning-regional-dataset.zip', flush=True)


if __name__ == '__main__':
    main()
