"""Train/validation-only regional feature ablations on a verified exported ZIP.

No detector calls, raw observations, network access or crossing3 reads.
These regressions predict whole-frame fusion's local FP+FN reduction, not a
visibility map, ROI query outcome, AP/F1 gain or communication policy.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import time
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets
from phdsim.evaluation.urbaning import CLASSES
from phdsim.learning.urbaning import recording_group
from phdsim.learning.urbaning_regions import FEATURES, SCHEMA, cell_centers
from phdsim.learning.urbaning_regional_gain import HEADS, PROFILES, fit_candidates, predict, validate_inputs


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def validate_headers(manifest):
    """Reject held-out recordings and overlap before any NPZ is opened."""
    if (manifest.get('schema') != SCHEMA or manifest.get('status') != 'completed'
            or manifest.get('features') != list(FEATURES)
            or manifest.get('actions') != list(ACTION_ORDER)
            or manifest.get('classes') != list(CLASSES)
            or manifest.get('count_order') != ['tp', 'fp', 'fn']):
        raise ValueError('Unsupported dataset schema or ordered feature/target contract')
    grid = manifest['grid']
    expected = {'cell_size_m': 10., 'min_xy': -100., 'max_xy_exclusive': 100.,
                'shape': [20, 20], 'spatial_cells': 400, 'overflow_cell': 400}
    if any(grid.get(k) != v for k, v in expected.items()):
        raise ValueError('Unsupported regional grid')
    groups = {'train': set(), 'validation': set()}
    sequences = set()
    for row in manifest['sequences']:
        seq, split = row['sequence'], row['split']
        if split not in groups or 'crossing3' in seq or seq in sequences:
            raise ValueError('Crossing3, duplicate sequence or invalid split')
        groups[split].add(recording_group(seq)); sequences.add(seq)
    if not all(groups.values()) or groups['train'] & groups['validation']:
        raise ValueError('Empty split or original-recording overlap')
    if {k: sorted(v) for k, v in groups.items()} != manifest['recording_groups']:
        raise ValueError('Recording group manifest mismatch')


def validate_arrays(inputs, labels, metadata, sequence):
    if set(inputs) != {'features', 'available', 'frame_keys', 'cell_centers'}:
        raise ValueError('Runtime input allowlist mismatch')
    if set(labels) != {'counts', 'delta_vs_ego', 'recovered_gt', 'lost_gt', 'gt_counts', 'available', 'frame_keys'}:
        raise ValueError('Offline target schema mismatch')
    x, mask = validate_inputs(inputs['features'], inputs['available'])
    n = len(x)
    if not n or len(metadata) != n or not np.array_equal(inputs['cell_centers'], cell_centers()):
        raise ValueError('Grid or frame metadata mismatch')
    keys = inputs['frame_keys']
    if (keys.shape != (n,) or len(set(keys.tolist())) != n
            or not np.array_equal(keys, labels['frame_keys'])
            or not np.array_equal(mask, labels['available'])):
        raise ValueError('Target/input keys or masks differ')
    expected = {'counts': (n, 401, 4, 4, 3), 'delta_vs_ego': (n, 401, 4, 4, 3),
                'recovered_gt': (n, 401, 4, 4), 'lost_gt': (n, 401, 4, 4), 'gt_counts': (n, 401, 4)}
    for name, shape in expected.items():
        a = labels[name]
        if a.shape != shape or not np.issubdtype(a.dtype, np.integer) or not np.isfinite(a).all():
            raise ValueError('Invalid count tensor: ' + name)
    if (labels['gt_counts'] < 0).any():
        raise ValueError('Negative GT support')
    for i, row in enumerate(metadata):
        if (row['sequence'] != sequence or row['recording_group'] != recording_group(sequence)
                or row['frame_key'] != keys[i] or not keys[i].startswith(sequence + ':')
                or not keys[i].endswith(':100000')):
            raise ValueError('Frame identity mismatch')
        allowed = available_subsets(row['source_ids'])
        if not np.array_equal(mask[i], [a in allowed for a in ACTION_ORDER]):
            raise ValueError('Source identity/availability mismatch')
    c, d, gt = labels['counts'], labels['delta_vs_ego'], labels['gt_counts']
    for j in range(4):
        ok = mask[:, j]
        if ((c[ok, :, j] < 0).any() or (c[~ok, :, j] != -1).any()
                or (d[~ok, :, j] != 0).any()
                or not np.array_equal(c[ok, :, j] - c[ok, :, 0], d[ok, :, j])
                or not np.array_equal(c[ok, :, j, :, 0] + c[ok, :, j, :, 2], gt[ok])):
            raise ValueError('Count conservation, deltas or unavailable sentinel mismatch')
        for name in ('recovered_gt', 'lost_gt'):
            a = labels[name]
            if (a[ok, :, j] < 0).any() or (a[~ok, :, j] != -1).any():
                raise ValueError('Recovery/loss sentinel mismatch')
        if not np.array_equal(d[ok, :, j, :, 0], labels['recovered_gt'][ok, :, j] - labels['lost_gt'][ok, :, j]):
            raise ValueError('Recovery/loss identities disagree with TP deltas')
    gain = -(d[:, :, 1:, :, 1].astype(float) + d[:, :, 1:, :, 2])
    return {'features': x, 'available': mask, 'gain': gain, 'frame_keys': keys}


def load_dataset(path):
    result = {'train': [], 'validation': []}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP members')
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError('Unsafe ZIP path')
        raw_manifest = archive.read('regional-dataset-report.json')
        manifest = json.loads(raw_manifest)
        validate_headers(manifest)
        for row in manifest['sequences']:
            split, seq = row['split'], row['sequence']
            prefix = split + '/' + seq + '/'
            required = {prefix + n for n in ('inputs.npz', 'offline-targets.npz', 'frames.jsonl')}
            if not required <= row['files'].keys():
                raise ValueError('Missing file hash bindings')
            for name, expected in row['files'].items():
                if not name.startswith(prefix) or sha(archive.read(name)) != expected:
                    raise ValueError('File path or SHA256 mismatch: ' + name)
            arrays = []
            for filename in ('inputs.npz', 'offline-targets.npz'):
                with np.load(io.BytesIO(archive.read(prefix + filename)), allow_pickle=False) as data:
                    arrays.append({k: data[k] for k in data.files})
            metadata = [json.loads(s) for s in archive.read(prefix + 'frames.jsonl').decode().splitlines()]
            result[split].append(validate_arrays(*arrays, metadata, seq))
            print('VERIFIED', split, seq, len(metadata), 'frames', flush=True)
    joined = {split: {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
              for split, rows in result.items()}
    if {s: len(d['features']) for s, d in joined.items()} != manifest['frames']:
        raise ValueError('Manifest frame count mismatch')
    return joined, manifest, sha(raw_manifest)


def metrics(prediction, truth, available, features=None):
    """All-cell selection score plus offline strata to expose sparse-label failure."""
    heads, mse = {}, []
    strata_mse = {name: [] for name in ('changed', 'positive', 'negative', 'neutral')}
    for j, action in enumerate(HEADS):
        valid = available[:, j+1]
        p, y = prediction[valid, :, j], truth[valid, :, j]
        classes = {}
        for c, name in enumerate(CLASSES):
            a, b = p[:, :, c].ravel(), y[:, :, c].ravel()
            strata = {}
            for group, keep in (('all', np.ones(len(b), bool)), ('changed', b != 0),
                                ('positive', b > 0), ('negative', b < 0), ('neutral', b == 0)):
                err = a[keep] - b[keep]
                strata[group] = {'cells': len(err), 'mse': float(np.mean(err**2)) if len(err) else None,
                                 'mae': float(np.mean(np.abs(err))) if len(err) else None}
            classes[name] = strata
            if len(b): mse.append(strata['all']['mse'])
            for group in strata_mse:
                if strata[group]['cells']:
                    strata_mse[group].append(strata[group]['mse'])
        # Ranking sums signed class gains; excludes only nonspatial overflow.
        actual, score = y[:, :400].sum(axis=2), p[:, :400].sum(axis=2)
        order = np.argsort(-score, axis=1, kind='stable')[:, :10]
        picked = np.take_along_axis(actual, order, axis=1).sum(axis=1)
        upper = np.sort(actual, axis=1)[:, -10:].sum(axis=1)
        ranking = {'k': 10, 'mean_actual_gain_in_top10': float(picked.mean()) if len(picked) else None,
                   'random_top10_expected_gain': float((actual.sum(axis=1)*10/400).mean()) if len(actual) else None,
                   'gt_top10_reference': float(upper.mean()) if len(upper) else None}
        evidence = {}
        if features is not None:
            empty = features[valid, :400, FEATURES.index('ego_empty')] > .5
            actual, score = y[:, :400].sum(axis=2), p[:, :400].sum(axis=2)
            for name, keep in (('car1_empty', empty), ('car1_nonempty', ~empty)):
                a, b = score[keep], actual[keep]
                positive, negative = b > 0, b < 0
                evidence[name] = {'cells': len(b), 'mse_total_class_gain': float(np.mean((a-b)**2)) if len(b) else None,
                                  'actual_positive_cells': int(positive.sum()), 'actual_negative_cells': int(negative.sum()),
                                  'mean_prediction_on_actual_positive': float(a[positive].mean()) if positive.any() else None,
                                  'mean_prediction_on_actual_negative': float(a[negative].mean()) if negative.any() else None}
        heads[action] = {'available_frames': int(valid.sum()), 'classes': classes, 'ranking': ranking,
                         'prequery_evidence_strata': evidence}
    return {'macro_mse': float(np.mean(mse)),
            'stratum_macro_mse': {k: float(np.mean(v)) if v else None for k, v in strata_mse.items()}, 'heads': heads}


def plot_example(data, prediction, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    keys = data['frame_keys'].tolist()
    i = next((i for i, k in enumerate(keys) if ':000161:' in k), len(keys)//2)
    values = [data['gain'][i, :400].sum(axis=-1), prediction[i, :400].sum(axis=-1)]
    limit = max(1., max(float(np.abs(v).max()) for v in values))
    fig, axes = plt.subplots(2, 3, figsize=(12, 8), layout='constrained')
    try:
        for row, title in enumerate(('Offline actual reduction (GT)', 'Predicted before query')):
            for j, action in enumerate(HEADS):
                ax = axes[row, j]
                if data['available'][i, j+1]:
                    im = ax.imshow(values[row][:, j].reshape(20, 20).T, origin='lower',
                                   extent=(-100, 100, -100, 100), cmap='RdBu', vmin=-limit, vmax=limit)
                ax.set(title=title + '\n' + action, xlabel='Car1 x [m]', ylabel='Car1 y [m]')
                ax.scatter(0, 0, marker='*', color='black', s=35)
        fig.colorbar(im, ax=axes.ravel().tolist(), shrink=.65, label='FP + FN reduction vs Car1')
        fig.suptitle(keys[i] + '\nBlue: fewer errors; red: more errors. Whole-frame fusion outcomes; no visibility map.')
        fig.savefig(output, dpi=140)
    finally:
        plt.close(fig)
    with Image.open(output) as image:
        image.verify()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    out = Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError('Preserve previous results; choose a new output directory')
    started = time.monotonic()
    data, manifest, manifest_hash = load_dataset(args.dataset)
    train, val = data['train'], data['validation']
    out.mkdir(parents=True)
    models_dir = out / 'models'; models_dir.mkdir()
    reports, choices, candidates, saved_predictions = {}, {}, {}, {}
    zero = np.zeros_like(val['gain'])
    mean = zero.copy()
    for j in range(3):
        prior = train['gain'][train['available'][:, j+1], :, j].mean(axis=(0, 1))
        mean[:, :, j] = prior
    for name, p in (('zero', zero), ('train_mean', mean)):
        reports[name] = metrics(p, val['gain'], val['available'], val['features'])
    for profile in PROFILES:
        print('FIT', profile, len(PROFILES[profile]), 'features', flush=True)
        fitted = fit_candidates(train['features'], train['available'], train['gain'], profile)
        scored = []
        for model in fitted:
            p = predict(model, val['features'], val['available'])
            report = metrics(p, val['gain'], val['available'], val['features'])
            scored.append((model, report, p))
            print('VALIDATION', profile, 'alpha', model['alpha'], 'MSE', report['macro_mse'], flush=True)
        model, report, p = min(scored, key=lambda row: row[1]['macro_mse'])
        model.update({'dataset_manifest_sha256': manifest_hash,
                      'training_recording_groups': manifest['recording_groups']['train'],
                      'validation_recording_groups': manifest['recording_groups']['validation'],
                      'classes': list(CLASSES), 'selection': 'validation macro MSE over available action/class heads'})
        write_json(models_dir / (profile + '.json'), model)
        choices[profile] = model['alpha']; reports[profile] = report
        candidates[profile] = [{'alpha': m['alpha'], 'validation_macro_mse': r['macro_mse']} for m, r, _ in scored]
        saved_predictions[profile] = p
    best = min(PROFILES, key=lambda p: reports[p]['macro_mse'])
    plot_example(val, saved_predictions[best], out / 'validation-example.png')
    np.savez_compressed(out / 'validation-predictions.npz', **saved_predictions,
                        available=val['available'], frame_keys=val['frame_keys'])
    source_paths = [Path(__file__), Path(__file__).parents[1] / 'learning' / 'urbaning_regional_gain.py',
                    Path(__file__).parents[1] / 'learning' / 'urbaning_regions.py']
    report = {'schema': 'phdsim-urbaning-regional-learning-v1', 'status': 'completed',
              'scope': 'Validation-selected regional regression and feature ablation; no acquisition policy evaluation',
              'dataset_sha256': sha(Path(args.dataset).read_bytes()), 'dataset_manifest_sha256': manifest_hash,
              'recording_groups': manifest['recording_groups'], 'frames': manifest['frames'],
              'runtime': {'python': platform.python_version(), 'numpy': np.__version__},
              'source_sha256': {p.name: sha(p.read_bytes()) for p in source_paths},
              'elapsed_seconds': time.monotonic()-started, 'profiles': {p: [FEATURES[i] for i in ids] for p, ids in PROFILES.items()},
              'target': '-(delta_FP + delta_FN), separately by class; positive = fewer errors',
              'loss': 'mean squared error per available action/class; alpha L2 penalty, intercept unpenalized',
              'selection': 'fixed alpha grid (.01,.1,1); lowest validation macro MSE; first wins exact ties',
              'selected_alphas': choices, 'selected_profile': best, 'candidates': candidates, 'validation': reports,
              'limitations': manifest['limitations'] + [
                  'Only two original training recordings and one already-inspected validation recording; no independent test result.',
                  'All 401 cells included; sparse unchanged targets make all-cell MSE alone insufficient.',
                  'Top10 is a region-ranking diagnostic, not an actual acquisition/communication policy or cost-matched partner random baseline.',
                  'No AP, F1, request count, utility, calibrated uncertainty or visibility improvement is measured.']}
    write_json(out / 'regional-learning-report.json', report)
    lines = ['# Regional learning: development validation only', '',
             'Target: signed reduction of FP + FN per region, peer action and class. No acquisition policy evaluated.', '',
             '| Features | Count | Selected alpha | Validation macro MSE |', '|---|---:|---:|---:|']
    for name, r in reports.items():
        lines.append('| {} | {} | {} | {:.6f} |'.format(name, len(PROFILES.get(name, ())), choices.get(name, '-'), r['macro_mse']))
    lines += ['', 'Selected profile: **{}**. All choices are development results on one validation recording.'.format(best), '',
              'Lower MSE is better. See the JSON for changed/positive/negative/neutral strata, per-class errors and region ranking.', '',
              'Changed-cell macro MSE: zero {:.6f}, selected {:.6f}. Negative-gain macro MSE: zero {:.6f}, selected {:.6f}.'.format(
                  reports['zero']['stratum_macro_mse']['changed'], reports[best]['stratum_macro_mse']['changed'],
                  reports['zero']['stratum_macro_mse']['negative'], reports[best]['stratum_macro_mse']['negative']), '',
              'A lower overall error need not imply better recognition of harmful partners. The JSON separately reports empty Car1 regions: these are central to the information-deficit goal.', '',
              'Fixed example: validation frame 161 if present; it is not selected by model performance.', '',
              'Reproduce from the matching Git revision:', '```bash',
              'OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 python scripts/urbaning_regional_learning.py --dataset /path/urbaning-regional-dataset.zip --output-dir /new/output', '```', '',
              'No detector, raw LiDAR, peer payload or crossing3 test data is loaded. Model inference accepts only the 46-feature input contract and public availability.', '',
              'Cells are correlated; 400 frames are two original training recordings, not 160,400 independent samples.']
    (out / 'README.md').write_text('\n'.join(lines) + '\n')
    bundle = out / 'urbaning-regional-learning.zip'
    with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file() and path != bundle:
                archive.write(path, path.relative_to(out))
    print('DONE:', bundle, flush=True)


if __name__ == '__main__':
    main()
