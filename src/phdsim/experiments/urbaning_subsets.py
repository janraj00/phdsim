"""Fit joint subset gains on separate recordings and replay cached outcomes.

All GT and unrequested outcomes remain in this offline experiment layer. Policy
functions receive only explicit ego evidence, availability and predicted gains.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from phdsim.decision.urbaning import (
    ACTION_ORDER, action_subsets, available_subsets, choose_one_peer, choose_subset,
    matched_random_subsets, random_subset)
from phdsim.evaluation.urbaning_cached import (
    aggregate_statistics, frame_f1, frame_statistics, summarize_cached)
from phdsim.learning.urbaning import (
    HEADS, assert_unseen_recordings, choose_learned_subset, ego_features,
    fit_joint_gain, recording_group)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Cache payload leaves its run directory')
    return path


def load_runs(directories, geometry_sidecars=None):
    if geometry_sidecars is not None:
        from phdsim.experiments.urbaning_geometry import load_sidecars
        geometry = load_sidecars(geometry_sidecars)
        used_geometry = set()
    frames, manifests, keys = [], [], set()
    detector = None
    for directory in directories:
        root = Path(directory).resolve()
        run = json.loads((root / 'run.json').read_text())
        if run.get('schema') != 'phdsim-urbaning-stage1-v1' or run.get('status') != 'completed':
            raise ValueError('Expected a completed stage 1 run')
        identity = run['model']
        if detector is not None and identity != detector:
            raise ValueError('All caches must use the same frozen detector')
        detector = identity
        sequence = run['arguments']['sequence']
        recording_group(sequence)
        original = json.loads((root / 'metrics.json').read_text())
        rows = [json.loads(line) for line in (root / 'frames.jsonl').read_text().splitlines()]
        current, payloads = [], {}
        sidecar = None
        if geometry_sidecars is not None:
            trace_hash = digest(root / 'frames.jsonl')
            if trace_hash not in geometry:
                raise ValueError('Missing trace-bound geometry sidecar')
            sidecar, sidecar_hash = geometry[trace_hash]
            used_geometry.add(trace_hash)
            if set(sidecar['frames']) != {r['frame_key'] for r in rows}:
                raise ValueError('Geometry frame coverage mismatch')
        for row in rows:
            key, ids = row['frame_key'], row['sources']['included_ids']
            expected_key = '{}:{}:{}'.format(sequence, row['source_frame_id'], run['arguments']['ego_id'])
            if key != expected_key or key in keys or str(ids[0]) != str(run['arguments']['ego_id']):
                raise ValueError('Duplicate or inconsistent native frame identity')
            keys.add(key)
            options = available_subsets(ids)
            path = _inside(root, row['predictions'])
            payloads[row['predictions']] = digest(path)
            with np.load(path, allow_pickle=False) as data:
                gt, labels = data['gt_boxes'], data['gt_labels']
                if hashlib.sha256(gt.tobytes() + labels.tobytes()).hexdigest() != row['gt_sha256']:
                    raise ValueError('Cached GT fingerprint mismatch')
                statistics = {name: frame_statistics(data[name + '_boxes'], data[name + '_scores'], gt, labels)
                              for name in options}
                # Reject inconsistent fallback aliases rather than double-counting them.
                for name, indices in action_subsets(ids).items():
                    canonical = next(n for n, v in options.items() if v == indices)
                    for field in ('boxes', 'scores'):
                        if not np.array_equal(data[name + '_' + field], data[canonical + '_' + field]):
                            raise ValueError('Fallback cache outcomes disagree')
                features = ego_features(ids, row['ego_entropy_bits'], data['ego_scores'])
                if sidecar is not None:
                    from phdsim.learning.urbaning_geometry import geometry_features
                    features = geometry_features(ids, row['ego_entropy_bits'], data['ego_scores'],
                                                 data['ego_boxes'], sidecar['frames'][key])
            frame = {'key': key, 'sequence': sequence, 'source_ids': ids,
                     'native_association': row.get('native_association'),
                     'ego_entropy': row['ego_entropy_bits'], 'features': features,
                     'statistics': statistics, 'quality': {n: frame_f1(s) for n, s in statistics.items()}}
            if sidecar is not None:
                from phdsim.learning.urbaning_geometry import SCHEMA as GEOMETRY_SCHEMA
                frame['feature_schema'] = GEOMETRY_SCHEMA
            current.append(frame)
        if not current:
            raise ValueError('Empty cache')
        # Independent cached evaluator must reproduce every original fixed baseline.
        for action in ACTION_ORDER:
            selected = [next(n for n, v in available_subsets(f['source_ids']).items()
                             if v == action_subsets(f['source_ids'])[action]) for f in current]
            measured = evaluate(current, selected, 0.)
            for name, expected in original[action]['classes'].items():
                actual = measured['classes'][name]
                if expected['ground_truth_count'] != actual['ground_truth_count']:
                    raise ValueError('Cached evaluator changed GT support')
                for iou, value in expected['ap'].items():
                    observed = actual['ap'][iou]
                    if (value is None) != (observed is None) or (
                            value is not None and abs(value - observed) > 1e-7):
                        raise ValueError('Cached evaluator does not reproduce stage 1 AP')
        manifests.append({'directory': str(root), 'sequence': sequence,
                          'run_sha256': digest(root / 'run.json'),
                          'trace_sha256': digest(root / 'frames.jsonl'), 'predictions_sha256': payloads})
        if sidecar is not None:
            manifests[-1]['geometry_sidecar_sha256'] = sidecar_hash
            manifests[-1]['geometry_metadata_assumption'] = sidecar['metadata_assumption']
        frames.extend(current)
    if geometry_sidecars is not None and used_geometry != set(geometry):
        raise ValueError('Unused geometry sidecars')
    if not frames:
        raise ValueError('At least one cache is required')
    return sorted(frames, key=lambda f: f['key']), {'detector': detector, 'inputs': manifests}


def evaluate(frames, choices, cost):
    if not frames or len(frames) != len(choices) or not math.isfinite(cost) or cost < 0:
        raise ValueError('Invalid evaluation inputs')
    counts = [len(available_subsets(f['source_ids'])[a]) - 1 for f, a in zip(frames, choices)]
    qualities = [f['quality'][a] for f, a in zip(frames, choices)]
    result = summarize_cached(aggregate_statistics(f['statistics'][a] for f, a in zip(frames, choices)))
    result.update(frames=len(frames), peer_requests=sum(counts),
                  mean_peer_requests=float(np.mean(counts)),
                  request_histogram={str(k): counts.count(k) for k in range(3)},
                  action_histogram=dict(Counter(choices)), mean_frame_f1=float(np.mean(qualities)),
                  mean_frame_utility=float(np.mean(qualities) - cost * np.mean(counts)))
    return result


def _sequence_set(frames):
    return sorted({f['sequence'] for f in frames})


def fit(train, validation, alphas, cost):
    if not math.isfinite(cost) or cost < 0:
        raise ValueError('Request cost must be predeclared and nonnegative')
    train_sequences, val_sequences = _sequence_set(train), _sequence_set(validation)
    train_groups = {recording_group(s) for s in train_sequences}
    val_groups = {recording_group(s) for s in val_sequences}
    if train_groups & val_groups or any('crossing3' in s for s in train_sequences + val_sequences):
        raise ValueError('Use disjoint original train/validation recordings outside crossing3')
    from phdsim.learning.urbaning import SCHEMA as EGO_SCHEMA
    schemas = {f.get('feature_schema', EGO_SCHEMA) for f in train + validation}
    if len(schemas) != 1:
        raise ValueError('Training and validation feature schemas differ')
    schema = schemas.pop()
    x = np.asarray([f['features'] for f in train])
    targets = [[f['quality'].get(a, f['quality']['ego']) - f['quality']['ego'] for a in HEADS] for f in train]
    masks = [[a in f['quality'] for a in HEADS] for f in train]
    candidates = []
    for alpha in sorted(set(alphas)):
        model = fit_joint_gain(x, targets, masks, alpha, train_sequences, schema=schema)
        model['request_cost'] = cost
        from phdsim.learning.urbaning import predict_gains
        choices = [choose_subset(f['source_ids'], predict_gains(model, f['features']), cost) for f in validation]
        score = evaluate(validation, choices, cost)
        candidates.append((score['mean_frame_utility'], -alpha, model, score))
    if not candidates:
        raise ValueError('At least one regularization value is required')
    _, _, model, score = max(candidates, key=lambda c: c[:2])
    model.update(validation_sequences=val_sequences, validation_recording_groups=sorted(val_groups),
                 validation_metrics=score, selection_rule='maximum validation mean frame F1 minus cost * pulls',
                 training_frames=len(train), validation_frames=len(validation))
    return model


def comparison(frames, provenance, seeds, model=None, diagnostic_cost=None, entropy_thresholds=(.5, .7), policy_seed=42):
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError('Predeclare distinct random seeds')
    low, high = entropy_thresholds
    if not 0 <= low <= high <= 1:
        raise ValueError('Expected ordered entropy thresholds in [0,1]')
    cost = model['request_cost'] if model is not None else diagnostic_cost
    if cost is None or not math.isfinite(cost) or cost < 0:
        raise ValueError('A frozen request cost is required')
    if model is None and any('crossing3' in s for s in _sequence_set(frames)):
        raise ValueError('Reserve crossing3 for a frozen, validated policy')
    ids, keys = [f['source_ids'] for f in frames], [f['key'] for f in frames]
    policies = {}
    for action in ACTION_ORDER:
        policies[action] = [next(n for n, indices in available_subsets(f['source_ids']).items()
                                 if indices == action_subsets(f['source_ids'])[action]) for f in frames]
    # A deliberately simple deployable rule spanning the full subset space.
    policies['entropy_subsets'] = ['ego' if f['ego_entropy'] <= low else
                                  (next(reversed(available_subsets(f['source_ids'])))
                                   if f['ego_entropy'] > high else
                                   choose_one_peer(f['source_ids'], f['key'], policy_seed)) for f in frames]
    if model is not None:
        from phdsim.learning.urbaning import predict_gains
        from phdsim.learning.urbaning import SCHEMA as EGO_SCHEMA
        if any(f.get('feature_schema', EGO_SCHEMA) != model['schema'] for f in frames):
            raise ValueError('Evaluation feature schema differs from frozen model')
        assert_unseen_recordings(model, _sequence_set(frames))
        if model.get('detector') != provenance['detector']:
            raise ValueError('Gain model was fitted for a different detector')
        policies['learned_joint_gain'] = [choose_subset(f['source_ids'], predict_gains(model, f['features']), cost)
                                          for f in frames]
    # Uses test labels: offline reference only, never a candidate deployable policy.
    hindsight = [choose_subset(f['source_ids'], {a: q - f['quality']['ego']
                                                for a, q in f['quality'].items()}, cost) for f in frames]
    report = {'schema': 'phdsim-urbaning-subsets-v1', 'status': 'completed',
              'scope': 'cached offline replay; no online acquisition or network measurement',
              'training_surrogate': 'frame micro F1 at BEV IoU .5, not per-frame AP',
              'request_cost': cost, 'entropy_thresholds': list(entropy_thresholds), 'seeds': seeds,
              'policy_seed': policy_seed,
              'provenance': provenance, 'policies': {}, 'random_controls': {},
              'hindsight_f1_reference_not_deployable': evaluate(frames, hindsight, cost),
              'hindsight_choices': dict(zip(keys, hindsight))}
    for name, choices in policies.items():
        report['policies'][name] = evaluate(frames, choices, cost)
        report['policies'][name]['choices'] = dict(zip(keys, choices))
    for name in ('entropy_subsets', 'learned_joint_gain'):
        if name not in policies:
            continue
        controls = {}
        for mode in ('schedule', 'budget'):
            samples = [evaluate(frames, matched_random_subsets(ids, keys, policies[name], seed, mode), cost)
                       for seed in seeds]
            controls[mode] = ensemble_summary(samples, seeds)
        report['random_controls'][name] = controls
    # The same controls also quantify the offline F1 reference's advantage; no
    # claim about a trained policy is inferred from this privileged comparison.
    report['hindsight_random_controls'] = {mode: ensemble_summary([
        evaluate(frames, matched_random_subsets(ids, keys, hindsight, seed, mode), cost) for seed in seeds], seeds)
        for mode in ('schedule', 'budget')}
    report['independent_random_subsets_p_half'] = ensemble_summary([
        evaluate(frames, [random_subset(f['source_ids'], f['key'], seed) for f in frames], cost) for seed in seeds], seeds)
    report['native_associations'] = {f['key']: f['native_association'] for f in frames}
    return report


def ensemble_summary(samples, seeds):
    fields = {'map_0.5': lambda s: s['macro_ap']['0.5'],
              'mean_frame_f1': lambda s: s['mean_frame_f1'],
              'mean_frame_utility': lambda s: s['mean_frame_utility'],
              'peer_requests': lambda s: s['peer_requests']}
    summary = {}
    for field, extract in fields.items():
        values = [extract(s) for s in samples]
        summary[field] = None if None in values else {
            'mean': float(np.mean(values)), 'std': float(np.std(values)),
            'min': float(min(values)), 'max': float(max(values))}
    return {'summary': summary, 'per_seed': {str(seed): sample for seed, sample in zip(seeds, samples)},
            'interpretation': 'Randomization spread only; not a confidence interval over recordings'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    train = sub.add_parser('fit', help='Fit on train recordings; select alpha on separate validation recordings')
    train.add_argument('--train-runs', nargs='+', required=True)
    train.add_argument('--validation-runs', nargs='+', required=True)
    train.add_argument('--alphas', nargs='+', type=float, default=[.1, 1., 10.])
    train.add_argument('--request-cost', type=float, required=True)
    train.add_argument('--output', required=True)
    replay = sub.add_parser('compare', help='Replay saved counterfactual outcomes; no detector required')
    replay.add_argument('--runs', nargs='+', required=True)
    replay.add_argument('--model', help='Frozen joint-gain model; its cost is retained')
    replay.add_argument('--diagnostic-cost', type=float, help='Required without model; exploratory reference only')
    replay.add_argument('--random-seeds', type=int, nargs='+', default=list(range(100)))
    replay.add_argument('--entropy-thresholds', type=float, nargs=2, default=[.5, .7])
    replay.add_argument('--policy-seed', type=int, default=42)
    replay.add_argument('--output', required=True)
    train.add_argument('--train-geometry', nargs='+', help='Pose sidecars, one per training run')
    train.add_argument('--validation-geometry', nargs='+', help='Pose sidecars, one per validation run')
    replay.add_argument('--geometry', nargs='+', help='Pose sidecars, one per evaluation run')
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError('Use a new output file')
    if args.command == 'fit':
        train_frames, train_provenance = load_runs(args.train_runs, args.train_geometry)
        val_frames, val_provenance = load_runs(args.validation_runs, args.validation_geometry)
        if train_provenance['detector'] != val_provenance['detector']:
            raise ValueError('Training/validation detectors differ')
        result = fit(train_frames, val_frames, args.alphas, args.request_cost)
        result.update(detector=train_provenance['detector'],
                      provenance={'train': train_provenance, 'validation': val_provenance})
    else:
        if args.model and args.diagnostic_cost is not None:
            raise ValueError('Do not replace the cost frozen in a gain model')
        frames, provenance = load_runs(args.runs, args.geometry)
        model = json.loads(Path(args.model).read_text()) if args.model else None
        if args.model:
            provenance['gain_model_sha256'] = digest(args.model)
        result = comparison(frames, provenance, args.random_seeds, model,
                            args.diagnostic_cost, args.entropy_thresholds, args.policy_seed)
    result['implementation_sha256'] = {str(p.relative_to(Path(__file__).resolve().parents[1])): digest(p)
                                       for p in (Path(__file__),
                                                 Path(__file__).resolve().parents[1] / 'decision/urbaning.py',
                                                 Path(__file__).resolve().parents[1] / 'learning/urbaning.py',
                                                 Path(__file__).resolve().parents[1] / 'evaluation/urbaning_cached.py')}
    if (args.command == 'fit' and args.train_geometry) or (args.command == 'compare' and args.geometry):
        for relative in ('learning/urbaning_geometry.py', 'experiments/urbaning_geometry.py'):
            path = Path(__file__).resolve().parents[1] / relative
            result['implementation_sha256'][relative] = digest(path)
    write_json(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
