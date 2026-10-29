"""Prepare/follow a frozen recording-level experiment; default prints commands.

Run with a prepared Linux CoBEVT environment. Each successful subprocess has a
completion marker; failed conversion/inference outputs are retained, never
silently overwritten. This orchestrates existing verified components.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def validate_protocol(plan):
    if plan.get('schema') != 'phdsim-urbaning-recording-experiment-v1':
        raise ValueError('Unknown protocol schema')
    groups = set()
    for split in ('train', 'validation', 'test'):
        sequences = plan[split]
        if not sequences:
            raise ValueError('Every split requires a recording')
        for sequence in sequences:
            match = re.fullmatch(r'(2024\d{4}_\d{4})_crossing([123])_\d{2}', sequence)
            if not match or match.group(1) in groups:
                raise ValueError('Invalid or overlapping recording identity')
            groups.add(match.group(1))
            if (split == 'test') != (match.group(2) == '3'):
                raise ValueError('Reserve crossing3 for final testing')
    if (plan['ego_id'] not in (100000, 200000) or type(plan['frames_per_sequence']) is not int or
            plan['frames_per_sequence'] < 1 or not math.isfinite(plan['request_cost']) or
            plan['request_cost'] < 0 or not plan['alphas'] or
            any(not math.isfinite(a) or a <= 0 for a in plan['alphas']) or
            not plan['random_seeds'] or len(set(plan['random_seeds'])) != len(plan['random_seeds'])):
        raise ValueError('Invalid frozen experiment settings')


def build_steps(plan, python, upstream, data_root, model_dir, output, threads, fetch):
    validate_protocol(plan)
    if threads < 1:
        raise ValueError('CPU threads must be positive')
    python = str(Path(python).absolute())
    upstream, data_root, model_dir, output = map(lambda p: Path(p).absolute(),
                                                (upstream, data_root, model_dir, output))
    stage1 = [python, str(REPO / 'scripts/urbaning_stage1.py')]
    cli = [python, '-c', 'import sys; from phdsim.cli import main; main(sys.argv[1:])', 'urbaning']
    steps = [('model', stage1 + ['fetch', '--model-dir', str(model_dir)], model_dir / 'best_model.pth'),
             ('doctor', stage1 + ['doctor', '--upstream', str(upstream), '--model-dir', str(model_dir),
                                  '--device', 'cpu'], model_dir / 'best_model.pth')]
    runs = {split: [] for split in ('train', 'validation', 'test')}
    test_steps = []
    for split in runs:
        target = test_steps if split == 'test' else steps
        for sequence in plan[split]:
            prefix = split + '-' + sequence
            view, converted, run = output / 'views' / sequence, output / 'converted' / sequence, output / 'runs' / sequence
            if fetch:
                target.append((prefix + '-fetch', cli + ['fetch', '--root', str(data_root), '--sequence', sequence],
                              data_root / 'source' / (sequence + '-download.json')))
            target.extend([
                (prefix + '-extract', cli + ['extract', '--root', str(data_root), '--sequence', sequence],
                 data_root / 'extracted' / sequence / 'extraction.json'),
                (prefix + '-view', cli + ['opencood-view', '--root', str(data_root), '--sequence', sequence,
                                         '--max-frames', str(plan['frames_per_sequence']), '--output', str(view)],
                 view / 'phdsim-conversion.json'),
                (prefix + '-convert', [python, str(REPO / 'scripts/urbaning_convert.py'),
                                       '--upstream', str(upstream), '--source-view', str(view), '--output', str(converted)],
                 converted / 'phdsim-conversion.json'),
                (prefix + '-infer', stage1 + ['run', '--upstream', str(upstream), '--model-dir', str(model_dir),
                                              '--data-root', str(converted), '--sequence', sequence,
                                              '--purpose', 'evaluation' if split == 'test' else 'smoke',
                                              '--max-frames', str(plan['frames_per_sequence']),
                                              '--ego-id', str(plan['ego_id']), '--seed', '42',
                                              '--device', 'cpu', '--cpu-threads', str(threads), '--output', str(run)],
                 run / 'metrics.json')])
            runs[split].append(str(run))
    gain_model = output / 'joint-gain.json'
    subset = [python, str(REPO / 'scripts/urbaning_subsets.py')]
    steps.append(('fit', subset + ['fit', '--train-runs'] + runs['train'] + ['--validation-runs'] + runs['validation'] +
                  ['--request-cost', str(plan['request_cost']), '--alphas'] + list(map(str, plan['alphas'])) +
                  ['--output', str(gain_model)], gain_model))
    # Freeze policy fitting/selection before collecting or evaluating test data.
    steps.extend(test_steps)
    report = output / 'test-report.json'
    steps.append(('test', subset + ['compare', '--runs'] + runs['test'] + ['--model', str(gain_model),
                  '--random-seeds'] + list(map(str, plan['random_seeds'])) + ['--output', str(report)], report))
    return steps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', default=str(REPO / 'configs/urbaning/joint_gain_recordings.json'))
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--model-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cpu-threads', type=int, default=8)
    parser.add_argument('--fetch', action='store_true', help='Download missing native sequences with the verified importer')
    parser.add_argument('--execute', action='store_true', help='Execute; otherwise only print the complete frozen command list')
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.protocol).read_text())
    steps = build_steps(plan, args.python, args.upstream, args.data_root, args.model_dir,
                        args.output, args.cpu_threads, args.fetch)
    if not args.execute:
        for name, command, artifact in steps:
            print(name + ': ' + shlex.join(command))
        return
    output = Path(args.output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    snapshot = {'protocol': plan, 'steps': [{'name': n, 'argv': c, 'artifact': str(a)} for n, c, a in steps]}
    snapshot_file = output / 'experiment-plan.json'
    if snapshot_file.exists() and json.loads(snapshot_file.read_text()) != snapshot:
        raise ValueError('Experiment plan changed; use a new output directory')
    snapshot_file.write_text(json.dumps(snapshot, indent=2) + '\n')
    (output / 'completed').mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(REPO / 'src') + (os.pathsep + environment['PYTHONPATH'] if environment.get('PYTHONPATH') else '')
    for name, command, artifact in steps:
        if name.endswith('-extract'):
            sequence = name.rsplit('-', 1)[0].split('-', 1)[1]
            manifest = Path(args.data_root) / 'source' / (sequence + '-download.json')
            if json.loads(manifest.read_text())['dataset_version'] != plan['dataset_version']:
                raise ValueError('Dataset release differs from the frozen protocol')
        marker = output / 'completed' / (name + '.json')
        if marker.exists():
            if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != json.loads(marker.read_text())['sha256']:
                raise ValueError('A completed stage artifact changed: ' + name)
            print('REUSE ' + name, flush=True)
            continue
        print('START ' + name, flush=True)
        subprocess.run(command, cwd=REPO, env=environment, check=True)
        if name.endswith('-fetch'):
            if json.loads(artifact.read_text())['dataset_version'] != plan['dataset_version']:
                raise ValueError('Dataset release differs from the frozen protocol')
        if not artifact.is_file():
            raise ValueError('Stage did not produce its declared artifact: ' + name)
        marker.write_text(json.dumps({'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}) + '\n')
        print('DONE ' + name, flush=True)


if __name__ == '__main__':
    main()
