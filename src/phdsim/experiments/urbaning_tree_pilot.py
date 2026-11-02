"""Validation-only ridge/tree comparison on existing geometry caches.

The protocol fixes cost, features and a small candidate grid before execution.
No detector inference, upstream import, download or crossing3 replay is provided.
"""

import argparse
import json
from pathlib import Path
import platform
import subprocess
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, action_subsets, available_subsets, choose_subset, matched_random_subsets
from phdsim.experiments.urbaning_subsets import digest, ensemble_summary, evaluate, load_runs, write_json
from phdsim.learning.urbaning import HEADS, fit_joint_gain, predict_gains, recording_group
from phdsim.learning.urbaning_geometry import FEATURES, SCHEMA as FEATURE_SCHEMA
from phdsim.learning.urbaning_trees import fit_tree_gain, predict_tree_gains

COST = .05
RIDGE_ALPHAS = (.1, 1., 10.)
TREE_GRID = tuple({'max_depth': depth, 'min_samples_leaf': leaf,
                   'n_estimators': 100, 'learning_rate': .05, 'seed': 42}
                  for depth in (1, 2) for leaf in (10, 20))
SEEDS = tuple(range(100))


def validate_splits(train_sequences, validation_sequences):
    train, validation = set(train_sequences), set(validation_sequences)
    if not train or not validation or any('crossing3' in s for s in train | validation):
        raise ValueError('Nonempty crossing1/2 train and validation splits are required; no crossing3')
    train_groups = {recording_group(s) for s in train}
    val_groups = {recording_group(s) for s in validation}
    if train_groups & val_groups:
        raise ValueError('Training and validation must use disjoint original recordings')
    return sorted(train_groups), sorted(val_groups)


def read_split_headers(train_runs, validation_runs):
    # Reject accidental test paths from run headers before opening any predictions.
    def identities(paths):
        return [json.loads((Path(p) / 'run.json').read_text())['arguments']['sequence'] for p in paths]
    validate_splits(identities(train_runs), identities(validation_runs))


def policy_choices(model, frames, predictor):
    return [choose_subset(f['source_ids'], predictor(model, f['features']), COST) for f in frames]


def utility_metrics(frames, choices):
    counts = [len(available_subsets(f['source_ids'])[a]) - 1 for f, a in zip(frames, choices)]
    f1 = float(np.mean([f['quality'][a] for f, a in zip(frames, choices)]))
    return {'mean_frame_f1': f1, 'peer_requests': sum(counts),
            'mean_frame_utility': f1 - COST * float(np.mean(counts))}


def choose_candidate(candidates):
    # Predeclared ties: fewer requests, then earlier candidate in the fixed grid.
    return max(range(len(candidates)), key=lambda i: (
        candidates[i]['validation']['mean_frame_utility'],
        -candidates[i]['validation']['peer_requests'], -i))


def constant_choices(frames, action):
    result = []
    for f in frames:
        subset = action_subsets(f['source_ids'])[action]
        result.append(next(a for a, s in available_subsets(f['source_ids']).items() if s == subset))
    return result


def select_models(train, validation):
    train_sequences = sorted({f['sequence'] for f in train})
    val_sequences = sorted({f['sequence'] for f in validation})
    _, val_groups = validate_splits(train_sequences, val_sequences)
    if any(f.get('feature_schema') != FEATURE_SCHEMA for f in train + validation):
        raise ValueError('Both learners require the exact same 32 geometry features')
    keys = [f['key'] for f in train + validation]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate frame identities')
    x = np.asarray([f['features'] for f in train])
    y = [[f['quality'].get(a, f['quality']['ego']) - f['quality']['ego'] for a in HEADS] for f in train]
    mask = [[a in f['quality'] for a in HEADS] for f in train]
    selected, grid_reports = {}, {}
    for family in ('ridge', 'tree'):
        models, candidates = [], []
        parameters = [{'alpha': a} for a in RIDGE_ALPHAS] if family == 'ridge' else TREE_GRID
        for index, params in enumerate(parameters):
            if family == 'ridge':
                model = fit_joint_gain(x, y, mask, params['alpha'], train_sequences, schema=FEATURE_SCHEMA)
                predictor = predict_gains
            else:
                model = fit_tree_gain(x, y, mask, train_sequences, FEATURE_SCHEMA, **params)
                predictor = predict_tree_gains
            choices = policy_choices(model, validation, predictor)
            metrics = utility_metrics(validation, choices)
            candidates.append({'index': index, 'parameters': params, 'validation': metrics})
            model.update(request_cost=COST, validation_sequences=val_sequences,
                         validation_recording_groups=val_groups, training_frames=len(train),
                         validation_frames=len(validation), validation_selection=metrics,
                         selection_rule='maximum validation utility; tie fewer requests, then fixed grid order')
            models.append(model)
            print(f'{family} candidate {index}: utility={metrics["mean_frame_utility"]:.6f}, '
                  f'F1={metrics["mean_frame_f1"]:.6f}, requests={metrics["peer_requests"]}', flush=True)
        best = choose_candidate(candidates)
        selected[family] = models[best]
        grid_reports[family] = {'candidates': candidates, 'selected_index': best}
    return selected, grid_reports


def validation_report(train, validation, models, grids, seeds=SEEDS):
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError('Distinct random seeds are required')
    validate_splits([f['sequence'] for f in train], [f['sequence'] for f in validation])
    policies = {a: constant_choices(validation, a) for a in ACTION_ORDER}
    policies['ridge'] = policy_choices(models['ridge'], validation, predict_gains)
    policies['tree'] = policy_choices(models['tree'], validation, predict_tree_gains)
    ranked = [{'validation': utility_metrics(validation, policies[a])} for a in ACTION_ORDER]
    best_constant = ACTION_ORDER[choose_candidate(ranked)]
    report = {'schema': 'phdsim-urbaning-tree-pilot-v1', 'status': 'completed',
              'scope': 'development validation only; selected on these same validation labels, not independent test evidence',
              'protocol': {'feature_schema': FEATURE_SCHEMA, 'features': list(FEATURES),
                           'request_cost': COST, 'target': 'frame micro F1 at BEV IoU .5 gain over ego',
                           'selection_metric': 'mean frame F1 minus .05 * mean peer requests',
                           'ridge_alphas': list(RIDGE_ALPHAS), 'tree_grid': list(TREE_GRID),
                           'tie_rule': 'fewer validation requests, then fixed candidate order',
                           'random_seeds': list(seeds), 'test_access': False},
              'splits': {'train_sequences': sorted({f['sequence'] for f in train}),
                         'validation_sequences': sorted({f['sequence'] for f in validation}),
                         'training_frames': len(train), 'validation_frames': len(validation)},
              'grids': grids, 'selected_constant': best_constant,
              'validation_policies': {}, 'random_controls': {}, 'gain_errors': {}}
    keys, ids = [f['key'] for f in validation], [f['source_ids'] for f in validation]
    for name, choices in policies.items():
        report['validation_policies'][name] = {
            'global_confidence_sort': evaluate(validation, choices, COST, global_sort=True),
            'upstream_default_order': evaluate(validation, choices, COST, global_sort=False),
            'choices': dict(zip(keys, choices))}
    # The constant baseline competes on utility, not on a test-selected AP score.
    eligible = [best_constant, 'ridge', 'tree']
    values = [{'validation': utility_metrics(validation, policies[n])} for n in eligible]
    report['validation_selected_policy'] = eligible[choose_candidate(values)]
    for name, predictor in (('ridge', predict_gains), ('tree', predict_tree_gains)):
        report['gain_errors'][name] = {}
        predictions = [predictor(models[name], f['features']) for f in validation]
        for action in HEADS:
            errors = [p[action] - (f['quality'][action] - f['quality']['ego'])
                      for p, f in zip(predictions, validation) if action in f['quality']]
            report['gain_errors'][name][action] = None if not errors else {
                'n': len(errors), 'mae': float(np.mean(np.abs(errors))),
                'rmse': float(np.sqrt(np.mean(np.square(errors)))), 'bias': float(np.mean(errors))}
        report['random_controls'][name] = {}
        for mode in ('schedule', 'budget'):
            samples = [evaluate(validation, matched_random_subsets(ids, keys, policies[name], seed, mode), COST)
                       for seed in seeds]
            report['random_controls'][name][mode] = ensemble_summary(samples, seeds)
    report['limitations'] = [
        'One temporally correlated validation recording; candidate selection is optimistic on this recording.',
        'Crossing3 was previously inspected in other experiments; this pilot never reads it.',
        'Low-score detection summaries cannot describe every missed or occluded object.',
        'Native time associations and pose metadata are not a validated causal online protocol.',
        'Cost counts bundled peer requests, not measured bytes or network latency.']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-runs', nargs='+', required=True)
    parser.add_argument('--validation-runs', nargs='+', required=True)
    parser.add_argument('--train-geometry', nargs='+', required=True)
    parser.add_argument('--validation-geometry', nargs='+', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    out = Path(args.output_dir)
    if out.exists():
        raise FileExistsError('Use a fresh pilot directory; existing results are preserved')
    read_split_headers(args.train_runs, args.validation_runs)
    try:
        import sklearn
        from sklearn.ensemble import GradientBoostingRegressor  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Pilot dependency import failed: {}: {}. Use scripts/urbaning_tree_env.py '
                           'for isolated dependencies; do not alter the shared venv.'
                           .format(type(exc).__name__, exc)) from exc
    out.mkdir(parents=True)
    code = subprocess.run(['git', '-C', str(Path(__file__).resolve().parents[3]), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()
    write_json(out / 'pilot-state.json', {'status': 'running', 'code_commit': code,
                                        'arguments': vars(args), 'request_cost': COST})
    print('LOAD verified training caches and existing pose sidecars (no inference)', flush=True)
    train, train_provenance = load_runs(args.train_runs, args.train_geometry)
    print('LOAD verified validation cache (no crossing3 access)', flush=True)
    validation, val_provenance = load_runs(args.validation_runs, args.validation_geometry)
    if train_provenance['detector'] != val_provenance['detector']:
        raise ValueError('Training and validation detector fingerprints differ')
    models, grids = select_models(train, validation)
    for name, model in models.items():
        model.update(detector=train_provenance['detector'],
                     provenance={'train': train_provenance, 'validation': val_provenance})
        write_json(out / (name + '-gain.json'), model)
    print('VALIDATION replay and 100 matched random seeds; no detector calls', flush=True)
    report = validation_report(train, validation, models, grids)
    report.update(code_commit=code, provenance={'train': train_provenance, 'validation': val_provenance},
                  runtime={'python': platform.python_version(), 'numpy': np.__version__,
                           'scikit_learn': sklearn.__version__,
                           'numpy_file': np.__file__, 'scikit_learn_file': sklearn.__file__},
                  models={n: {'file': n + '-gain.json', 'sha256': digest(out / (n + '-gain.json'))}
                          for n in models})
    write_json(out / 'validation-report.json', report)
    with zipfile.ZipFile(out / 'urbaning-tree-pilot.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ('validation-report.json', 'ridge-gain.json', 'tree-gain.json'):
            archive.write(out / name, name)
    write_json(out / 'completed.json', {'status': 'completed', 'report_sha256': digest(out / 'validation-report.json')})
    print('VALIDATION ONLY: policy / F1 / utility / requests', flush=True)
    for name, value in report['validation_policies'].items():
        m = value['global_confidence_sort']
        print(f'{name}: {m["mean_frame_f1"]:.6f} / {m["mean_frame_utility"]:.6f} / {m["peer_requests"]}', flush=True)
    print('Best constant:', report['selected_constant'], flush=True)
    print('Validation selection:', report['validation_selected_policy'], flush=True)
    print('DONE:', out / 'urbaning-tree-pilot.zip', flush=True)


if __name__ == '__main__':
    main()
