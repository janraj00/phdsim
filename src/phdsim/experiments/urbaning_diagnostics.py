"""Offline analysis of frozen full-test policies; never trains or runs a detector."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from phdsim.decision.urbaning import available_subsets, matched_random_subsets, choose_subset
from phdsim.experiments.urbaning_benchmark import freeze, REPO
from phdsim.experiments.urbaning_full_policies import checked_plan
from phdsim.experiments.urbaning_subsets import load_runs, evaluate, ensemble_summary
from phdsim.learning.urbaning import predict_gains, HEADS, recording_group, assert_unseen_recordings
from phdsim.perception.urbaning.bundle import sha256


def availability(frame):
    options = available_subsets(frame['source_ids'])
    car2, infra = 'vehicle_peer' in options, 'infrastructure' in options
    return 'both' if car2 and infra else 'car2_only' if car2 else 'infra_only' if infra else 'none'


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {'n': 0}
    return {'n': len(values), 'mean': float(values.mean()), 'median': float(np.median(values)),
            'q10': float(np.quantile(values, .1)), 'q90': float(np.quantile(values, .9)),
            'positive_fraction': float(np.mean(values > 1e-12)),
            'negative_fraction': float(np.mean(values < -1e-12)),
            'neutral_fraction': float(np.mean(np.abs(values) <= 1e-12))}


def marginal_gains(frames, cost):
    edges = [('car2_over_ego', 'vehicle_peer', 'ego', 1),
             ('infra_over_ego', 'infrastructure', 'ego', 1),
             ('car2_given_infra', 'all', 'infrastructure', 1),
             ('infra_given_car2', 'all', 'vehicle_peer', 1),
             ('both_over_ego', 'all', 'ego', 2)]
    result = {}
    for label, end, start, pulls in edges:
        values = [f['quality'][end] - f['quality'][start] for f in frames
                  if end in f['quality'] and start in f['quality']]
        result[label] = distribution(values)
        if values:
            result[label].update(additional_requests=pulls,
                                 above_frozen_cost_fraction=float(np.mean(np.asarray(values) > cost * pulls)))
    synergy = [f['quality']['all'] - f['quality']['vehicle_peer'] -
               f['quality']['infrastructure'] + f['quality']['ego'] for f in frames if 'all' in f['quality']]
    result['joint_synergy_not_assumed_additive'] = distribution(synergy)
    return result


def prediction_errors(predicted, observed):
    p, y = np.asarray(predicted, float), np.asarray(observed, float)
    if not len(p):
        return {'n': 0}
    error = p - y
    # Correlation is undefined when either series is constant.
    corr = float(np.corrcoef(p, y)[0, 1]) if np.std(p) > 1e-12 and np.std(y) > 1e-12 else None
    return {'n': len(p), 'mae': float(np.abs(error).mean()),
            'rmse': float(np.sqrt(np.square(error).mean())), 'bias_predicted_minus_observed': float(error.mean()),
            'pearson': corr, 'predicted_gain': distribution(p), 'observed_gain': distribution(y)}


def diagnose_model(frames, model, choices):
    if not frames or len(frames) != len(choices):
        raise ValueError('Missing or inconsistent choices')
    cost = model['request_cost']
    examples = []
    predicted, observed = {a: [] for a in HEADS}, {a: [] for a in HEADS}
    regrets, selected_gains, missed, choices_from_model = [], [], [], []
    for f, action in zip(frames, choices):
        gains = predict_gains(model, f['features'])
        choices_from_model.append(choose_subset(f['source_ids'], gains, cost))
        options = available_subsets(f['source_ids'])
        utilities = {a: q - f['quality']['ego'] - cost * (len(options[a]) - 1) for a, q in f['quality'].items()}
        regret = max(utilities.values()) - utilities[action]
        regrets.append(regret)
        examples.append({'frame_key': f['key'], 'availability': availability(f), 'chosen': action,
                         'hindsight_best': max(utilities, key=utilities.get), 'utility_regret': regret,
                         'predicted_gains': {a: gains[a] for a in gains if a in options},
                         'actual_f1': f['quality']})
        selected_gains.append(utilities[action])
        missed.append(action == 'ego' and max(utilities.values()) > 1e-12)
        for head in HEADS:
            if head in f['quality']:
                predicted[head].append(gains[head])
                observed[head].append(f['quality'][head] - f['quality']['ego'])
    if choices_from_model != choices:
        raise ValueError('Frozen model does not reproduce saved choices')
    return {'gain_heads': {a: prediction_errors(predicted[a], observed[a]) for a in HEADS},
            'largest_utility_mistakes': sorted(examples, key=lambda x: (-x['utility_regret'], x['frame_key']))[:10],
            'utility_regret_vs_hindsight': distribution(regrets),
            'chosen_net_gain_vs_ego': distribution(selected_gains),
            'chosen_worse_utility_than_ego_fraction': float(np.mean(np.asarray(selected_gains) < -1e-12)),
            'missed_positive_utility_when_not_querying_fraction': float(np.mean(missed))}


def compact_comparison(frames, choices, cost, seeds, with_random):
    # choices are sliced from the frozen full-test report, never tuned here.
    result = {'frames': len(frames), 'availability': dict(Counter(map(availability, frames))),
              'metrics_by_global_sort': {}}
    ids, keys = [f['source_ids'] for f in frames], [f['key'] for f in frames]
    reference = choices['learned_joint_gain']
    controls = {mode: [matched_random_subsets(ids, keys, reference, seed, mode) for seed in seeds]
                for mode in ('schedule', 'budget')} if with_random else {}
    for sort in (False, True):
        metrics = {name: evaluate(frames, actions, cost, global_sort=sort) for name, actions in choices.items()}
        oracle = [choose_subset(f['source_ids'], {a: q - f['quality']['ego'] for a, q in f['quality'].items()}, cost)
                  for f in frames]
        metrics['hindsight_f1_utility_not_deployable'] = evaluate(frames, oracle, cost, global_sort=sort)
        random = {}
        for mode, actions in controls.items():
            samples = [evaluate(frames, c, cost, global_sort=sort) for c in actions]
            expected = metrics['learned_joint_gain']['peer_requests']
            if any(s['peer_requests'] != expected or s['request_histogram'] != metrics['learned_joint_gain']['request_histogram'] for s in samples):
                raise ValueError('Conditional random budget mismatch')
            random[mode] = ensemble_summary(samples, seeds)['summary']
        result['metrics_by_global_sort'][str(sort)] = {'policies': metrics, 'random_controls': random}
    return result


def analyze(frames, model, saved, seeds):
    assert_unseen_recordings(model, sorted({f['sequence'] for f in frames}))
    keys = [f['key'] for f in frames]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate replay keys')
    for sort in ('False', 'True'):
        for name, p in saved[sort]['policies'].items():
            if set(p['choices']) != set(keys):
                raise ValueError('Saved policy coverage differs from caches')
            if p['choices'] != saved['True']['policies'][name]['choices']:
                raise ValueError('AP ordering changed policy choices')
    choices = {n: [p['choices'][k] for k in keys] for n, p in saved['True']['policies'].items()}
    # Verify the analysis environment reproduces the saved full aggregate before slicing.
    for sort in (False, True):
        for name, actions in choices.items():
            score = evaluate(frames, actions, model['request_cost'], global_sort=sort)
            expected = saved[str(sort)]['policies'][name]
            for i, ap in score['macro_ap'].items():
                if ap is None or expected['macro_ap'][i] is None or abs(ap - expected['macro_ap'][i]) > 1e-7:
                    raise ValueError('Analysis AP differs from frozen full report')
            for field in ('peer_requests', 'mean_frame_f1', 'mean_frame_utility'):
                if abs(score[field] - expected[field]) > 1e-10:
                    raise ValueError('Analysis changed frozen policy outcomes')
    result = {'availability': {}, 'recordings': {}, 'marginal_f1_gains': marginal_gains(frames, model['request_cost']),
              'prediction_diagnostics': diagnose_model(frames, model, choices['learned_joint_gain'])}
    for category in ('none', 'car2_only', 'infra_only', 'both'):
        indices = [i for i, f in enumerate(frames) if availability(f) == category]
        if not indices:
            result['availability'][category] = {'frames': 0}
            continue
        selected = [frames[i] for i in indices]
        result['availability'][category] = compact_comparison(selected,
            {n: [c[i] for i in indices] for n, c in choices.items()}, model['request_cost'], seeds, True)
        result['availability'][category]['prediction_diagnostics'] = diagnose_model(
            selected, model, [choices['learned_joint_gain'][i] for i in indices])
    for recording in sorted({recording_group(f['sequence']) for f in frames}):
        indices = [i for i, f in enumerate(frames) if recording_group(f['sequence']) == recording]
        selected = [frames[i] for i in indices]
        result['recordings'][recording] = compact_comparison(selected,
            {n: [c[i] for i in indices] for n, c in choices.items()}, model['request_cost'], seeds, False)
        result['recordings'][recording].update(sequences=sorted({f['sequence'] for f in selected}),
            marginal_f1_gains=marginal_gains(selected, model['request_cost']),
            prediction_diagnostics=diagnose_model(selected, model, [choices['learned_joint_gain'][i] for i in indices]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Completed urbaning-full-policies output')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError('Preserve existing diagnostics; choose a new output')
    root = Path(args.root).resolve()
    plan = checked_plan(root / 'plan.json')
    full = json.loads((root / 'full-policy-report.json').read_text())
    if full['status'] != 'completed' or full['plan'] != plan:
        raise ValueError('Require the completed matching full-policy report')
    runs, poses = [], []
    for seq in plan['test_sequences']:
        folder = root / seq
        marker = full['completed'][seq]
        for key, path in [('run', folder / 'run/run.json'), ('trace', folder / 'run/frames.jsonl'), ('poses', folder / 'poses.json')]:
            if sha256(path) != marker[key + '_sha256']:
                raise ValueError('Completed source identity changed')
        runs.append(folder / 'run')
        poses.append(folder / 'poses.json')
    report = {'status': 'completed', 'scope': 'post-hoc descriptive offline diagnostics; no training/tuning/inference',
              'full_report_sha256': sha256(root / 'full-policy-report.json'), 'plan': plan, 'models': {},
              'interpretation': {'gains': 'paired changes in frame micro F1 at BEV IoU .5, not AP gains',
                  'conditional_random': 're-randomized within each availability stratum with exact matched budget/histogram',
                  'independence': 'segments of one original recording are grouped; frames are temporally correlated',
                  'oracle': 'GT-assisted F1-utility reference only; not deployable or an AP upper bound',
                  'cost': 'frozen .05 per peer bundle; no measured network costs; no cost sweep'}}
    for name in ('gain_ego', 'gain_geometry'):
        print('ANALYZE ' + name, flush=True)
        frames, provenance = load_runs(runs, poses if name == 'gain_geometry' else None)
        if len(frames) != plan['expected_frames'] or provenance['detector'] != plan['detector']:
            raise ValueError('Full-test coverage or detector mismatch')
        model = json.loads(Path(plan['models'][name]['path']).read_text())
        if full['models'][name]['True']['provenance']['gain_model_sha256'] != plan['models'][name]['sha256']:
            raise ValueError('Saved report policy differs from frozen plan')
        report['models'][name] = analyze(frames, model, full['models'][name], plan['random_seeds'])
        report['models'][name]['provenance'] = provenance
    report['implementation_sha256'] = {str(p.relative_to(REPO)): sha256(p) for p in (
        Path(__file__), REPO / 'src/phdsim/evaluation/urbaning_cached.py', REPO / 'src/phdsim/experiments/urbaning_subsets.py')}
    freeze(args.output, report)
    print('DONE ' + args.output, flush=True)


if __name__ == '__main__':
    main()
