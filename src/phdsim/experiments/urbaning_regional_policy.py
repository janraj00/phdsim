"""Validation-only whole-frame replay of a frozen regional predictor.

Counts suffice for F1 and requests, not AP. AP can subsequently be computed
from the original caches using the saved frozen frame choices, without fitting.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, action_subsets, available_subsets, matched_random_subsets
from phdsim.decision.urbaning_regional import ERROR_COSTS, choose_regional_subset
from phdsim.experiments.urbaning_regional_learning import load_dataset
from phdsim.learning.urbaning_regional_gain import predict

COST = .05
SEEDS = tuple(range(100))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def evaluate(counts, source_ids, choices):
    if len(counts) != len(choices) or len(source_ids) != len(choices) or not len(counts):
        raise ValueError('Unaligned replay arrays')
    selected, requests = [], []
    for c, ids, action in zip(counts, source_ids, choices):
        options = available_subsets(ids)
        if action not in options:
            raise ValueError('Unavailable replay action')
        requests.append(len(options[action])-1)
        row = c[ACTION_ORDER.index(action)]
        if row.shape != (4, 3) or (row < 0).any():
            raise ValueError('Invalid aggregated target counts')
        selected.append(row)
    per_frame = np.asarray(selected).sum(axis=1)
    tp, fp, fn = per_frame.T
    den = 2*tp+fp+fn
    f1 = np.divide(2*tp, den, out=np.ones(len(tp), float), where=den != 0)
    total = per_frame.sum(axis=0)
    micro = 2*total[0]/(2*total[0]+total[1]+total[2]) if total.sum() else 1.
    return {'frames': len(choices), 'mean_frame_f1': float(f1.mean()), 'micro_f1_all_frames': float(micro),
            'mean_frame_utility': float(f1.mean()-COST*np.mean(requests)), 'peer_requests': sum(requests),
            'request_histogram': {str(n): requests.count(n) for n in range(3)},
            'action_histogram': dict(Counter(choices)), 'map_0.5': None,
            'map_status': 'Requires per-detection confidences/TP flags from original caches; counts cannot determine AP'}


def controls(counts, ids, keys, reference):
    result = {}
    reference_score = evaluate(counts, ids, reference)
    for mode in ('budget', 'schedule'):
        samples, schedules = [], []
        for seed in SEEDS:
            choices = matched_random_subsets(ids, keys, reference, seed, mode)
            sample = evaluate(counts, ids, choices)
            samples.append(sample); schedules.append(tuple(choices))
            if (sample['peer_requests'] != reference_score['peer_requests']
                    or sample['request_histogram'] != reference_score['request_histogram']):
                raise ValueError('Random budget mismatch')
        fields = ('mean_frame_f1', 'mean_frame_utility', 'peer_requests')
        result[mode] = {'summary': {field: {'mean': float(np.mean([r[field] for r in samples])),
                                          'min': float(min(r[field] for r in samples)),
                                          'max': float(max(r[field] for r in samples)),
                                          'std': float(np.std([r[field] for r in samples]))} for field in fields},
                        'per_seed': {str(seed): row for seed, row in zip(SEEDS, samples)},
                        'unique_choice_sequences': len(set(schedules)),
                        'mean_changed_frames_vs_policy': float(np.mean([sum(a != b for a, b in zip(s, reference)) for s in schedules])),
                        'interpretation': 'Offline randomized control with identical pull histogram within feasibility strata; spread is not a recording confidence interval'}
    return result


def load_validation(path, data, manifest):
    """Use only labels whose hashes/identities passed load_dataset validation."""
    rows, source_ids = [], []
    with zipfile.ZipFile(path) as archive:
        for sequence in manifest['sequences']:
            if sequence['split'] != 'validation': continue
            prefix = 'validation/' + sequence['sequence'] + '/'
            import io
            payload, trace = archive.read(prefix + 'offline-targets.npz'), archive.read(prefix + 'frames.jsonl')
            for name, raw in (('offline-targets.npz', payload), ('frames.jsonl', trace)):
                if hashlib.sha256(raw).hexdigest() != sequence['files'][prefix + name]:
                    raise ValueError('Regional dataset changed since verification')
            with np.load(io.BytesIO(payload), allow_pickle=False) as labels:
                rows.append(labels['counts'].sum(axis=1))
            source_ids.extend(r['source_ids'] for r in map(json.loads, trace.decode().splitlines()))
    counts = np.concatenate(rows)
    if len(counts) != len(data['features']): raise ValueError('Validation counts alignment failed')
    return counts, source_ids


def prior_comparison(path, manifest, counts, ids, keys):
    """Verify the previous pilot used exactly these payloads before comparison."""
    with zipfile.ZipFile(path) as archive:
        previous = json.loads(archive.read('validation-report.json'))
    provenance = previous['provenance']['validation']
    now = [r['provenance'] for r in manifest['sequences'] if r['split'] == 'validation']
    inputs = [r for p in now for r in p['inputs']]
    if (provenance['detector'] != manifest['detector'] or provenance['inputs'] != inputs):
        raise ValueError('Prior pilot uses different validation provenance')
    result = {}
    for name, old in previous['validation_policies'].items():
        if set(old['choices']) != set(keys): raise ValueError('Prior pilot frame coverage differs')
        measured = evaluate(counts, ids, [old['choices'][k] for k in keys])
        original = old['global_confidence_sort']
        for field in ('mean_frame_f1', 'mean_frame_utility', 'peer_requests'):
            if abs(measured[field]-original[field]) > 1e-12:
                raise ValueError('Regional replay does not reproduce previous pilot ' + field)
        measured['map_0.5'] = original['macro_ap']['0.5']
        measured['map_status'] = 'Previously computed global-confidence-sort AP on the identical verified caches'
        if name in ('ridge', 'tree'): result['previous_' + name] = measured
    return result


def plot_tradeoff(candidates, policies, random_controls, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    fig, ax = plt.subplots(figsize=(8, 5), layout='constrained')
    try:
        ax.plot([r['peer_requests'] for _, r, _ in candidates],
                [100*r['mean_frame_f1'] for _, r, _ in candidates], 'o-', color='#1d6585', label='Regional penalty grid')
        for name, label, marker, color in (('all', 'ALWAYS', 's', '#555555'),
                                           ('regional', 'Selected regional', '*', '#d56b1c'),
                                           ('previous_ridge', 'Previous ridge', 'D', '#6d3a9b')):
            if name in policies:
                r = policies[name]
                ax.scatter(r['peer_requests'], 100*r['mean_frame_f1'], s=100 if marker=='*' else 40,
                           marker=marker, color=color, label=label, zorder=4)
        control = random_controls['budget']['summary']['mean_frame_f1']
        ax.errorbar(policies['regional']['peer_requests'], 100*control['mean'],
                    yerr=[[100*(control['mean']-control['min'])], [100*(control['max']-control['mean'])]],
                    fmt='x', color='#b12236', capsize=4, label='Same-budget random: mean and min/max')
        ax.set(xlabel='Peer requests over 200 validation frames', ylabel='Mean frame F1 [%]',
               title='Regional acquisition: validation only\nPenalty selected on this recording; no independent test')
        ax.grid(alpha=.2); ax.legend(loc='lower right', fontsize=8)
        fig.savefig(output, dpi=150)
    finally:
        plt.close(fig)
    with Image.open(output) as image: image.verify()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--prior-pilot', help='Optional previous tree-pilot ZIP for provenance-checked comparison')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    out = Path(args.output_dir).resolve()
    if out.exists(): raise FileExistsError('Preserve existing results; select a new output directory')
    data, manifest, manifest_hash = load_dataset(args.dataset)
    model = json.loads(Path(args.model).read_text())
    if (model.get('profile') != 'full' or model.get('dataset_manifest_sha256') != manifest_hash
            or model.get('training_recording_groups') != manifest['recording_groups']['train']
            or model.get('validation_recording_groups') != manifest['recording_groups']['validation']):
        raise ValueError('Use the previously selected full regional model with its exact dataset')
    val = data['validation']
    predictions = predict(model, val['features'], val['available'])
    counts, ids = load_validation(args.dataset, val, manifest)
    keys = val['frame_keys'].tolist()
    candidates = []
    for error_cost in ERROR_COSTS:
        choices = [choose_regional_subset(i, p, error_cost) for i, p in zip(ids, predictions)]
        score = evaluate(counts, ids, choices)
        candidates.append((error_cost, score, choices))
        print('CANDIDATE', error_cost, 'F1', score['mean_frame_f1'], 'requests', score['peer_requests'],
              'utility', score['mean_frame_utility'], flush=True)
    index = max(range(len(candidates)), key=lambda i: (candidates[i][1]['mean_frame_utility'],
                                                     -candidates[i][1]['peer_requests'], -i))
    error_cost, selected, choices = candidates[index]
    policies = {}
    for action in ACTION_ORDER:
        baseline = [next(a for a, subset in available_subsets(i).items() if subset == action_subsets(i)[action]) for i in ids]
        policies[action] = evaluate(counts, ids, baseline)
    policies['regional'] = selected
    if args.prior_pilot:
        policies.update(prior_comparison(args.prior_pilot, manifest, counts, ids, keys))
    always = policies['all']['peer_requests']
    for row in policies.values():
        row['saved_requests_vs_always'] = always-row['peer_requests']
        row['saved_fraction_vs_always'] = (always-row['peer_requests'])/always if always else 0.
    print('REPLAY 100 budget and 100 schedule controls; selected penalty frozen', flush=True)
    randomized = controls(counts, ids, keys, choices)
    for row in randomized.values():
        row['policy_exceeds_random_f1_draws'] = sum(selected['mean_frame_f1'] > sample['mean_frame_f1']
                                                   for sample in row['per_seed'].values())
    report = {'schema': 'phdsim-urbaning-regional-policy-v1', 'status': 'completed',
              'scope': 'Development validation selection and replay on 200 crossing2 frames; no independent test',
              'protocol': {'request_cost_f1_units': COST, 'error_count_penalty_grid': list(ERROR_COSTS),
                           'selected_error_count_penalty': error_cost, 'seeds': list(SEEDS),
                           'aggregation': 'signed sum over all 401 cells and four classes; one whole-frame subset',
                           'selection': 'max validation mean frame F1 - .05*mean requests; tie fewer requests then grid order',
                           'profile': 'previously selected full, frozen coefficients and alpha',
                           'random_budget': 'shuffle 0/1/2 counts within feasible-action strata, then choose partner identity',
                           'random_schedule': 'keep 0/1/2 count on each frame; randomize partner identity only'},
              'dataset_manifest_sha256': manifest_hash, 'model_sha256': hashlib.sha256(Path(args.model).read_bytes()).hexdigest(),
              'prior_pilot_sha256': hashlib.sha256(Path(args.prior_pilot).read_bytes()).hexdigest() if args.prior_pilot else None,
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), Path(__file__).parents[1]/'decision'/'urbaning_regional.py')},
              'recording_groups': manifest['recording_groups'], 'detector': manifest['detector'],
              'validation_provenance': [r['provenance'] for r in manifest['sequences'] if r['split'] == 'validation'],
              'frame_keys': keys, 'source_ids': ids, 'choices': dict(zip(keys, choices)),
              'candidates': [{'error_count_penalty': c, 'metrics': s} for c, s, _ in candidates],
              'policies': policies, 'random_controls': randomized,
              'limitations': ['Validation has been inspected and used for model/penalty selection; not held-out evidence.',
                              'Error-count penalty and .05 F1 cost have different units; they are not equated.',
                              'Requests are simulated peer/frame counts, not measured bytes, latency or sensor power.',
                              'Whole-frame fusion outcomes only; no mixing regional actions or per-cell charges.',
                              'No AP from TP/FP/FN counts. Frozen choices can be replayed against original cached detections.']}
    out.mkdir(parents=True)
    plot_tradeoff(candidates, policies, randomized, out/'requests-vs-f1.png')
    write_json(out/'regional-policy-report.json', report)
    write_json(out/'regional-policy.json', {'schema': 'phdsim-urbaning-regional-acquisition-v1',
                                          'error_count_penalty': error_cost, 'validation_selected': True,
                                          'model': model, 'dataset_manifest_sha256': manifest_hash})
    lines = ['# Regional acquisition replay — validation only', '',
             '| Policy | Mean frame F1 | Requests | Saved vs ALWAYS |', '|---|---:|---:|---:|']
    for name, row in policies.items():
        lines.append('| {} | {:.4f}% | {} | {:.2f}% |'.format(name, 100*row['mean_frame_f1'], row['peer_requests'], 100*row['saved_fraction_vs_always']))
    lines += ['', 'Selected penalty: {} predicted FP+FN errors per peer/frame. Selection utility uses .05 F1 units per request.'.format(error_cost), '',
              'Random controls use exactly the regional policy request budget and feasible actions; see the JSON for 100 draws per control.', '',
              '| Random control | F1 mean | F1 min–max | Requests |', '|---|---:|---:|---:|']
    for name, control in randomized.items():
        f = control['summary']['mean_frame_f1']
        lines.append('| {} | {:.4f}% | {:.4f}–{:.4f}% | {} |'.format(name, 100*f['mean'], 100*f['min'], 100*f['max'], selected['peer_requests']))
    lines += ['', '| Error-count penalty | F1 | Requests | Saved vs ALWAYS |', '|---|---:|---:|---:|']
    for c, score, _ in candidates:
        lines.append('| {} | {:.4f}% | {} | {:.2f}% |'.format(c, 100*score['mean_frame_f1'], score['peer_requests'], 100*(always-score['peer_requests'])/always if always else 0.))
    lines += ['',
              'Code entry point: scripts/urbaning_regional_policy.py. Supply --dataset, --model and a new --output-dir; --prior-pilot is optional.', '',
              'mAP is unavailable from counts. This is validation-selected development evidence, not a crossing3 test result.']
    (out/'README.md').write_text('\n'.join(lines)+'\n')
    bundle = out/'urbaning-regional-policy.zip'
    with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(out.iterdir()):
            if p != bundle: archive.write(p, p.name)
    print('DONE:', bundle, flush=True)


if __name__ == '__main__': main()
