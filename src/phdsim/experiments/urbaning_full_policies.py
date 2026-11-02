"""Frozen policy evaluation on the completed full CoBEVT test inventory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from phdsim.experiments.urbaning_benchmark import freeze, REPO
from phdsim.perception.urbaning.bundle import sha256, verify_bundle


def make_plan(reference, ego_model, geometry_model, model_dir):
    ref = json.loads(Path(reference).read_text())
    if ref['status'] != 'completed' or len(ref['sequence_results_sha256']) != len(ref['plan']['test_sequences']):
        raise ValueError('Require a completed full benchmark')
    models = [json.loads(Path(p).read_text()) for p in (ego_model, geometry_model)]
    expected = ['phdsim-urbaning-joint-gain-v1', 'phdsim-urbaning-joint-gain-geometry-v1']
    detector = verify_bundle(model_dir)
    for m, schema in zip(models, expected):
        if m['schema'] != schema or m['detector'] != detector or m['request_cost'] != .05:
            raise ValueError('Unexpected frozen policy schema, detector or cost')
    # Keep planning on login standard-library-only; runtime repeats the full
    # model split guard in comparison(). Group suffixes share one recording.
    held_out = {s.split('_crossing')[0] for s in ref['plan']['test_sequences']}
    for m in models:
        used = m['train_sequences'] + m['validation_sequences']
        if held_out & {s.split('_crossing')[0] for s in used} or any('_crossing3_' in s for s in used):
            raise ValueError('Policy fitting overlaps crossing3 test recordings')
    return {'schema': 'phdsim-urbaning-full-policies-v1', 'test_sequences': ref['plan']['test_sequences'],
            'expected_frames': ref['frames'], 'reference_sha256': sha256(reference),
            'reference': str(Path(reference).resolve()), 'detector': detector,
            'models': {n: {'path': str(Path(p).resolve()), 'sha256': sha256(p)}
                       for n, p in [('gain_ego', ego_model), ('gain_geometry', geometry_model)]},
            'request_cost': .05, 'random_seeds': list(range(100)), 'entropy_thresholds': [.5, .7],
            'policy_seed': 42, 'global_sort_modes': [False, True],
            'scope': 'expanded evaluation of already frozen pilot policies; crossing3 partly inspected; no fitting'}


def checked_plan(path):
    plan = json.loads(Path(path).read_text())
    if plan['schema'] != 'phdsim-urbaning-full-policies-v1':
        raise ValueError('Unknown plan schema')
    if sha256(plan['reference']) != plan['reference_sha256']:
        raise ValueError('Benchmark reference changed')
    for m in plan['models'].values():
        if sha256(m['path']) != m['sha256']:
            raise ValueError('Frozen policy changed')
    return plan


def run_sequence(args):
    plan = checked_plan(args.plan)
    if not 0 <= args.index < len(plan['test_sequences']):
        raise ValueError('Invalid index')
    sequence = plan['test_sequences'][args.index]
    ref = Path(args.reference_root).resolve()
    out = Path(args.output).resolve() / sequence
    out.mkdir(parents=True, exist_ok=True)
    source = json.loads((ref / sequence / 'result.json').read_text())
    benchmark = json.loads(Path(plan['reference']).read_text())
    if sha256(ref / sequence / 'result.json') != benchmark['sequence_results_sha256'][sequence]:
        raise ValueError('Benchmark sequence identity changed')
    if sha256(ref / sequence / 'converted/phdsim-conversion.json') != source['conversion_sha256']:
        raise ValueError('Benchmark conversion manifest changed')
    if source['status'] != 'completed' or source['frames'] != source['dataset_frames']:
        raise ValueError('Incomplete reference sequence')
    freeze(out / 'identity.json', {'plan': plan, 'reference_result_sha256': sha256(ref / sequence / 'result.json'),
                                  'implementation_sha256': sha256(__file__)})
    cache, poses = out / 'run', out / 'poses.json'
    if not cache.exists():
        subprocess.run([sys.executable, str(REPO / 'scripts/urbaning_stage1.py'), 'run',
                        '--upstream', args.upstream, '--model-dir', args.model_dir,
                        '--data-root', str(ref / sequence / 'converted'), '--sequence', sequence,
                        '--purpose', 'evaluation', '--max-frames', '0', '--ego-id', '100000',
                        '--seed', '42', '--device', 'cpu', '--cpu-threads', str(args.cpu_threads),
                        '--output', str(cache)], check=True)
    run = json.loads((cache / 'run.json').read_text())
    if (run['status'] != 'completed' or run['frame_bounds'] != [0, source['frames']] or
            run['dataset_frames'] != source['frames'] or run['model'] != plan['detector']):
        raise ValueError('Incomplete or incompatible policy cache; preserve and rename partial run before retry')
    if not poses.exists():
        from phdsim.experiments.urbaning_geometry import export
        export(cache, args.upstream, poses)
    freeze(out / 'completed.json', {'sequence': sequence, 'frames': source['frames'],
                                   'run_sha256': sha256(cache / 'run.json'),
                                   'trace_sha256': sha256(cache / 'frames.jsonl'), 'poses_sha256': sha256(poses)})
    print('DONE ' + sequence, flush=True)


def collect(args):
    plan = checked_plan(args.plan)
    out = Path(args.output).resolve()
    runs, poses, completed = [], [], {}
    for sequence in plan['test_sequences']:
        root = out / sequence
        marker = json.loads((root / 'completed.json').read_text())
        for name, path in [('run', root / 'run/run.json'), ('trace', root / 'run/frames.jsonl'), ('poses', root / 'poses.json')]:
            if sha256(path) != marker[name + '_sha256']:
                raise ValueError('Completed cache changed: ' + sequence)
        runs.append(root / 'run')
        poses.append(root / 'poses.json')
        completed[sequence] = marker
    if sum(m['frames'] for m in completed.values()) != plan['expected_frames']:
        raise ValueError('Incomplete full test coverage')
    from phdsim.experiments.urbaning_subsets import load_runs, comparison
    report = {'status': 'completed', 'plan': plan, 'completed': completed, 'models': {}}
    for name in ('gain_ego', 'gain_geometry'):
        print('REPLAY ' + name, flush=True)
        frames, provenance = load_runs(runs, poses if name == 'gain_geometry' else None)
        if len(frames) != plan['expected_frames']:
            raise ValueError('Replay frame count mismatch')
        provenance['gain_model_sha256'] = plan['models'][name]['sha256']
        model = json.loads(Path(plan['models'][name]['path']).read_text())
        report['models'][name] = {str(mode): comparison(
            frames, provenance, plan['random_seeds'], model=model,
            entropy_thresholds=plan['entropy_thresholds'], policy_seed=plan['policy_seed'], global_sort=mode)
            for mode in plan['global_sort_modes']}
    reference = json.loads(Path(plan['reference']).read_text())
    report['all_source_delta_vs_benchmark'] = {str(mode): {
        i: report['models']['gain_ego'][str(mode)]['policies']['all']['macro_ap'][i] -
        reference['metrics_by_global_sort'][str(mode)]['macro_ap'][i] for i in ('0.3', '0.5', '0.7')}
        for mode in plan['global_sort_modes']}
    report['implementation_sha256'] = {str(p.relative_to(REPO)): sha256(p) for p in (
        Path(__file__), REPO / 'src/phdsim/experiments/urbaning_subsets.py',
        REPO / 'src/phdsim/evaluation/urbaning_cached.py')}
    freeze(out / 'full-policy-report.json', report)
    print('DONE ' + str(out / 'full-policy-report.json'), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    for name in ('reference', 'ego-model', 'geometry-model', 'model-dir', 'output'):
        p.add_argument('--' + name, required=True)
    for command in ('run', 'collect'):
        p = sub.add_parser(command)
        for name in ('plan', 'output'):
            p.add_argument('--' + name, required=True)
        if command == 'run':
            for name in ('reference-root', 'upstream', 'model-dir'):
                p.add_argument('--' + name, required=True)
            p.add_argument('--index', required=True, type=int)
            p.add_argument('--cpu-threads', type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        plan = make_plan(args.reference, args.ego_model, args.geometry_model, args.model_dir)
        freeze(args.output, plan)
        print(json.dumps(plan, indent=2))
    elif args.command == 'run':
        run_sequence(args)
    else:
        collect(args)
