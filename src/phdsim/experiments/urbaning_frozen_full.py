"""Evaluate frozen regional/tree policies on existing full crossing3 caches.

No fitting, detector calls, downloads, upstream imports or threshold selection.
The development-only portable AP loader keeps its crossing3 exclusion unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets, choose_subset, matched_random_subsets, random_subset
from phdsim.decision.urbaning_regional import choose_regional_subset
from phdsim.experiments.urbaning_ap_replay import MODES, baseline_choices, dumps, metrics_both_orders, same_metrics
from phdsim.experiments.urbaning_geometry import load_sidecars
from phdsim.experiments.urbaning_subsets import _inside, digest, ensemble_summary, load_runs
from phdsim.learning.urbaning import recording_group
from phdsim.learning.urbaning_regional_gain import predict
from phdsim.learning.urbaning_regions import regional_features
from phdsim.learning.urbaning_trees import predict_tree_gains

SCHEMA = 'phdsim-urbaning-frozen-full-inputs-v1'
EXPECTED_FRAMES = 1400
SEQUENCE_FRAMES = 200
SEQUENCES = ('20241127_0009_crossing3_00', '20241127_0010_crossing3_08',
             '20241127_0010_crossing3_09', '20241127_0011_crossing3_00',
             '20241127_0012_crossing3_00', '20241127_0024_crossing3_08', '20241127_0024_crossing3_09')
MEMBERS = ('full-policy-report.json', 'tree-gain.json', 'regional-policy.json', 'regional-policy-report.json')
SEEDS = tuple(range(100))
PURE_PROBABILITIES = (.5, .75, .9)  # fixed before this replay, never selected on test


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def zip_member(path, suffix):
    with zipfile.ZipFile(path) as z:
        matches = [n for n in z.namelist() if n.split('/')[-1] == suffix]
        if len(matches) != 1:
            raise ValueError('Expected one archive member: '+suffix)
        return z.read(matches[0])


def check_models(reference, tree, regional, regional_report):
    """Header/split guard and prediction preflight before any test payload read."""
    if (reference.get('status') != 'completed' or reference['plan']['test_sequences'] != list(SEQUENCES)
            or reference['plan']['expected_frames'] != EXPECTED_FRAMES or set(reference['completed']) != set(SEQUENCES)
            or any(reference['completed'][s]['frames'] != SEQUENCE_FRAMES for s in SEQUENCES)):
        raise ValueError('Require the completed seven-sequence, 1400-frame full inventory')
    detector = reference['plan']['detector']
    if (tree.get('request_cost') != .05 or tree.get('detector') != detector
            or regional.get('schema') != 'phdsim-urbaning-regional-acquisition-v1'
            or regional.get('error_count_penalty') != 8. or regional.get('validation_selected') is not True
            or regional_report.get('status') != 'completed' or regional_report.get('detector') != detector
            or regional['dataset_manifest_sha256'] != regional_report['dataset_manifest_sha256']
            or regional['model']['dataset_manifest_sha256'] != regional['dataset_manifest_sha256']
            or regional['model'].get('profile') != 'full' or regional['model'].get('alpha') != .1):
        raise ValueError('Frozen model/detector/penalty mismatch')
    expected_train, expected_val = {'20241126_0001', '20241126_0017'}, {'20241126_0004'}
    held = {recording_group(s) for s in SEQUENCES}
    for train, val in ((tree['train_recording_groups'], tree['validation_recording_groups']),
                       (regional['model']['training_recording_groups'], regional['model']['validation_recording_groups'])):
        if (set(train) != expected_train or set(val) != expected_val
                or set(train) & set(val) or held & (set(train) | set(val))):
            raise ValueError('Frozen original-recording split mismatch')
    if ({recording_group(s) for s in tree['train_sequences']} != expected_train
            or {recording_group(s) for s in tree['validation_sequences']} != expected_val):
        raise ValueError('Tree sequence/group mismatch')
    # Exercise both deployment interfaces using only empty local detections.
    ids = ['100000', '200000', '-3']
    x, mask = regional_features(ids, .5, np.empty((0, 8, 3)), np.empty((0, 2)),
                                {'200000': np.eye(4), '-3': np.eye(4)})
    choose_regional_subset(ids, predict(regional['model'], x[None], mask[None])[0], 8.)
    choose_subset(ids, predict_tree_gains(tree, np.zeros(32)), .05)


def pack_inputs(reference_zip, tree_zip, regional_zip, output):
    contents = {name: zip_member(path, name) for name, path in zip(
        MEMBERS, (reference_zip, tree_zip, regional_zip, regional_zip))}
    check_models(*(json.loads(contents[n]) for n in MEMBERS))
    manifest = {'schema': SCHEMA, 'files': {n: sha(b) for n, b in contents.items()},
                'source_archives_sha256': {name: digest(path) for name, path in
                    [('full_report', reference_zip), ('tree_pilot', tree_zip), ('regional_policy', regional_zip)]},
                'selection': 'existing frozen full regional alpha=.1 / penalty=8; tree cost=.05; no refit',
                'seeds': list(SEEDS), 'pure_random_probabilities': list(PURE_PROBABILITIES)}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, raw in contents.items(): z.writestr(name, raw)
        z.writestr('manifest.json', dumps(manifest))
    load_inputs(output, digest(output))
    print('INPUTS', output, 'SHA256', digest(output), 'bytes', output.stat().st_size, flush=True)


def load_inputs(path, expected_sha):
    if digest(path) != expected_sha:
        raise ValueError('Frozen input archive SHA256 mismatch')
    with zipfile.ZipFile(path) as z:
        if sorted(z.namelist()) != sorted((*MEMBERS, 'manifest.json')) or z.testzip() is not None:
            raise ValueError('Unexpected or corrupt frozen input archive')
        manifest = json.loads(z.read('manifest.json'))
        if (manifest.get('schema') != SCHEMA or set(manifest['files']) != set(MEMBERS)
                or manifest.get('seeds') != list(SEEDS)
                or manifest.get('pure_random_probabilities') != list(PURE_PROBABILITIES)):
            raise ValueError('Frozen input protocol mismatch')
        contents = {name: z.read(name) for name in MEMBERS}
        if any(sha(b) != manifest['files'][n] for n, b in contents.items()):
            raise ValueError('Frozen input member SHA256 mismatch')
    values = [json.loads(contents[n]) for n in MEMBERS]
    check_models(*values)
    return (*values, manifest)


def check_caches(root, reference):
    """Identity verification only; missing caches fail, never launch inference."""
    runs, poses = [], []
    for sequence in SEQUENCES:
        directory = Path(root)/sequence
        expected = reference['completed'][sequence]
        if json.loads((directory/'completed.json').read_text()) != expected:
            raise ValueError('Completed cache marker changed: '+sequence)
        for name, path in [('run', directory/'run/run.json'), ('trace', directory/'run/frames.jsonl'),
                           ('poses', directory/'poses.json')]:
            if digest(path) != expected[name+'_sha256']:
                raise ValueError('Completed cache changed: '+sequence+' '+name)
        runs.append(directory/'run'); poses.append(directory/'poses.json')
    return runs, poses


def provenance_equal(actual, expected):
    if actual['detector'] != expected['detector']:
        raise ValueError('Detector provenance changed')
    fields = ('sequence', 'run_sha256', 'trace_sha256', 'predictions_sha256', 'geometry_sidecar_sha256')
    core = lambda p: sorted([{k: i[k] for k in fields} for i in p['inputs']], key=lambda i: i['sequence'])
    if core(actual) != core(expected):
        raise ValueError('Prediction/pose provenance changed')


def predict_choices(frames, provenance, pose_paths, tree, regional, portable_path):
    """Policies see Car1 boxes/scores and pose metadata, never GT/peer payloads."""
    sidecars = load_sidecars(pose_paths)
    evidence = {}
    for origin in provenance['inputs']:
        root = Path(origin['directory']).resolve()
        trace = root/'frames.jsonl'
        if digest(trace) != origin['trace_sha256']: raise ValueError('Trace changed during replay')
        sidecar = sidecars[origin['trace_sha256']][0]
        for row in map(json.loads, trace.read_text().splitlines()):
            evidence[row['frame_key']] = (root, origin, row, sidecar['frames'][row['frame_key']])
    choices = {'regional': [], 'tree': []}
    with Path(portable_path).open('x') as stream:
        for n, frame in enumerate(frames, 1):
            root, origin, row, transforms = evidence[frame['key']]
            path = _inside(root, row['predictions'])
            if digest(path) != origin['predictions_sha256'][row['predictions']]:
                raise ValueError('Predictions changed during replay')
            with np.load(path, allow_pickle=False) as data:
                features, mask = regional_features(frame['source_ids'], frame['ego_entropy'],
                    data['ego_boxes'], data['ego_scores'], transforms)
            gains = predict(regional['model'], features[None], mask[None])[0]
            choices['regional'].append(choose_regional_subset(frame['source_ids'], gains, regional['error_count_penalty']))
            choices['tree'].append(choose_subset(frame['source_ids'], predict_tree_gains(tree, frame['features']), tree['request_cost']))
            stream.write(dumps({'key': frame['key'], 'sequence': frame['sequence'], 'source_ids': frame['source_ids'],
                'gt_sha256': row['gt_sha256'], 'prediction_path': row['predictions'],
                'prediction_sha256': origin['predictions_sha256'][row['predictions']],
                'statistics': frame['statistics']})+'\n')
            if n % 100 == 0 or n == len(frames): print('FROZEN CHOICES', n, '/', len(frames), flush=True)
    return choices


def ensemble(frames, choices_by_seed):
    samples = {mode: [] for mode in MODES}
    for seed, choices in zip(SEEDS, choices_by_seed):
        result = metrics_both_orders(frames, choices)
        for mode in MODES: samples[mode].append(result[mode])
        if (seed+1) % 25 == 0: print('RANDOM', seed+1, '/100', flush=True)
    return {mode: ensemble_summary(rows, SEEDS) for mode, rows in samples.items()}


def score(frames, choices, reference):
    keys, ids = [f['key'] for f in frames], [f['source_ids'] for f in frames]
    if len(frames) != EXPECTED_FRAMES or len(set(keys)) != EXPECTED_FRAMES or {f['sequence'] for f in frames} != set(SEQUENCES):
        raise ValueError('Incomplete full frame coverage')
    policies = {a: baseline_choices(frames, a) for a in ACTION_ORDER}
    for label in ('gain_ego', 'gain_geometry'):
        old = reference['models'][label]['True']['policies']['learned_joint_gain']['choices']
        if set(old) != set(keys): raise ValueError('Previous policy coverage mismatch')
        policies[label] = [old[k] for k in keys]
    policies.update(choices)
    results = {name: metrics_both_orders(frames, selected) for name, selected in policies.items()}
    for mode, global_sort in MODES.items():
        for name in ACTION_ORDER:
            same_metrics(results[name][mode], reference['models']['gain_geometry'][str(global_sort)]['policies'][name])
        for label in ('gain_ego', 'gain_geometry'):
            same_metrics(results[label][mode], reference['models'][label][str(global_sort)]['policies']['learned_joint_gain'])
    print('PARITY: baselines and previous policies reproduced in both AP orders', flush=True)
    maximum = results['all']['global_confidence_sort']['peer_requests']
    for name, by_mode in results.items():
        r = by_mode['global_confidence_sort']
        print('PRIMARY', name, 'mAP@.5={:.6f}'.format(r['macro_ap']['0.5']),
              'requests='+str(r['peer_requests']),
              'saved={:.2f}%'.format(100*(1-r['peer_requests']/maximum)), flush=True)
    pure = {}
    for p in PURE_PROBABILITIES:
        print('PURE RANDOM p=', p, flush=True)
        pure[str(p)] = ensemble(frames, ([random_subset(i, k, seed, p) for i, k in zip(ids, keys)] for seed in SEEDS))
    for mode, global_sort in MODES.items():
        old = reference['models']['gain_geometry'][str(global_sort)]['independent_random_subsets_p_half']
        for seed in SEEDS: same_metrics(pure['0.5'][mode]['per_seed'][str(seed)], old['per_seed'][str(seed)])
    controls = {}
    for name in choices:
        controls[name] = {}
        for control in ('budget', 'schedule'):
            print('SECONDARY CONTROL', name, control, flush=True)
            row = ensemble(frames, (matched_random_subsets(ids, keys, choices[name], seed, control) for seed in SEEDS))
            for mode in MODES:
                expected = results[name][mode]
                for sample in row[mode]['per_seed'].values():
                    if any(sample[k] != expected[k] for k in ('peer_requests', 'request_histogram')):
                        raise ValueError('Matched random cost changed')
            controls[name][control] = row
    return results, pure, controls, {name: dict(zip(keys, actions)) for name, actions in policies.items()}


def markdown(report):
    mode = 'global_confidence_sort'
    total = report['policies']['all'][mode]['peer_requests']
    lines = ['# Frozen regional and tree: full crossing3', '',
        'Primary: four-class BEV mAP@0.5 with global confidence sorting. '
        'F1 is a secondary diagnostic. These test recordings have been inspected before; no blind-test claim.', '',
        '| Policy | mAP@0.5 (%) | Requests | Saved vs ALWAYS (%) |', '|---|---:|---:|---:|']
    def row(name, ap, requests):
        lines.append(f'| {name} | {100*ap:.4f} | {requests:.2f} | {100*(1-requests/total):.2f} |')
    for name in ('ego', 'vehicle_peer', 'infrastructure'):
        r = report['policies'][name][mode]; row(name, r['macro_ap']['0.5'], r['peer_requests'])
    for p, r in report['pure_random'].items():
        s = r[mode]['summary']; row('Pure random p='+p+' (100-seed mean)', s['map_0.5']['mean'], s['peer_requests']['mean'])
    for name in ('gain_ego', 'gain_geometry', 'regional', 'tree', 'all'):
        r = report['policies'][name][mode]; row(name, r['macro_ap']['0.5'], r['peer_requests'])
    lines += ['', 'Pure random draws each available peer independently on every frame. At p=.5 this is uniform over feasible subsets. '
        'The p values are fixed before replay. Different request budgets are not evidence of better learned selection.', '',
        'Per-class AP, both AP ordering modes, sequence-level policy metrics, F1, choices and matched controls are in report.json. '
        'Random spread describes randomization, not uncertainty over independent recordings.', '',
        'Regional is the unchanged audited linear prototype: summing its cell predictions can lose spatial binding. '
        'It chooses whole-frame partner subsets; it does not selectively transmit regions. '
        'Infra positions are site-origin proxies. Request counts do not measure bytes or latency.', '']
    return '\n'.join(lines)


def run(inputs, inputs_sha256, cache_root, output):
    reference, tree, regional, regional_report, manifest = load_inputs(inputs, inputs_sha256)
    runs, poses = check_caches(cache_root, reference)
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    print('VERIFY 1400 frozen frames and original baseline AP; no detector calls', flush=True)
    def progress(seq, n, total):
        if n % 25 == 0: print('VERIFY', seq, f'{n}/{total}', flush=True)
    frames, provenance = load_runs(runs, poses, progress=progress)
    provenance_equal(provenance, reference['models']['gain_geometry']['True']['provenance'])
    choices = predict_choices(frames, provenance, poses, tree, regional, out/'offline-statistics.jsonl')
    # Checkpoint choices before the slower random controls; safe to inspect without refitting.
    write(out/'frozen-choices.json', {'scope': 'full crossing3; already inspected', 'choices': {
        n: dict(zip([f['key'] for f in frames], c)) for n, c in choices.items()}, 'input_sha256': inputs_sha256})
    results, pure, controls, all_choices = score(frames, choices, reference)
    per_sequence = {}
    for sequence in SEQUENCES:
        indices = [i for i, f in enumerate(frames) if f['sequence'] == sequence]
        selected = [frames[i] for i in indices]
        per_sequence[sequence] = {n: metrics_both_orders(selected, [c[frames[i]['key']] for i in indices])
                                  for n, c in all_choices.items()}
    report = {'schema': 'phdsim-urbaning-frozen-full-report-v1', 'status': 'completed', 'frames': len(frames),
        'scope': 'expanded evaluation on previously inspected crossing3; no training or tuning',
        'protocol': {'primary': 'four-class global-confidence-sort BEV mAP@0.5', 'f1': 'secondary mean-frame micro F1',
                     'request_savings_denominator': results['all']['global_confidence_sort']['peer_requests'],
                     'tree_frozen_f1_cost': .05, 'regional_frozen_error_count_penalty': 8.,
                     'pure_random': 'each available peer independently with fixed p; no model choices or GT',
                     'secondary_controls': 'retrospective matched budget/schedule; not deployable independent random',
                     'policy_boundary': 'Car1 detections/entropy + available peer poses only; no GT or peer predictions'},
        'inputs_sha256': inputs_sha256, 'frozen_inputs': manifest, 'provenance': provenance,
        'policies': results, 'pure_random': pure, 'secondary_matched_controls': controls,
        'per_sequence': per_sequence, 'choices': all_choices,
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__},
        'implementation_sha256': {str(p.relative_to(Path(__file__).parents[3])): digest(p) for p in (
            Path(__file__), Path(__file__).with_name('urbaning_ap_replay.py'), Path(__file__).with_name('urbaning_subsets.py'),
            *[Path(__file__).parents[1]/p for p in ('decision/urbaning.py', 'decision/urbaning_regional.py',
              'learning/urbaning_trees.py', 'learning/urbaning_regions.py', 'learning/urbaning_regional_gain.py',
              'learning/urbaning_geometry.py', 'evaluation/urbaning_cached.py')])}}
    write(out/'report.json', report)
    (out/'RESULTS.md').write_text(markdown(report))
    write(out/'files.json', {p.name: digest(p) for p in out.iterdir() if p.is_file()})
    archive = out/'urbaning-frozen-full.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.iterdir()):
            if p != archive: z.write(p, p.name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError('Final ZIP CRC failure')
    print((out/'RESULTS.md').read_text(), flush=True)
    print('SHA256', digest(archive), 'bytes', archive.stat().st_size, flush=True)
    print('DONE:', archive, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    pack = sub.add_parser('pack-inputs')
    for field in ('reference-zip', 'tree-zip', 'regional-zip', 'output'): pack.add_argument('--'+field, required=True)
    replay = sub.add_parser('run')
    for field in ('inputs', 'inputs-sha256', 'cache-root', 'output-dir'): replay.add_argument('--'+field, required=True)
    args = parser.parse_args(argv)
    if args.command == 'pack-inputs': pack_inputs(args.reference_zip, args.tree_zip, args.regional_zip, args.output)
    else: run(args.inputs, args.inputs_sha256, args.cache_root, args.output_dir)
