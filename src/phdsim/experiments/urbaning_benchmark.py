"""Full SIS 1/2 vs 3 CoBEVT reference; separate from policy replay."""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from phdsim.perception.urbaning.bundle import sha256, verify_bundle
from phdsim.experiments.urbaning_stage1 import prepare_upstream, load_model, write_json, doctor

REPO = Path(__file__).resolve().parents[3]
CLASSES = ('Vehicle', 'Heavy_Vehicle', '2Wheeler', 'Pedestrian')
IOUS = (0.3, 0.5, 0.7)


def make_plan(metadata):
    from phdsim.datasets.urbaning.source import SEQUENCE_PATTERN, sequence_files
    version = metadata['data']['latestVersion']
    if (version['versionNumber'], version.get('versionMinorNumber', 0)) != (1, 0):
        raise ValueError('Expected dataset release 1.0')
    names = sorted({f['dataFile']['filename'].removesuffix('.7z.001')
                    for f in version['files'] if f['dataFile']['filename'].endswith('.7z.001')})
    if not names or any(not SEQUENCE_PATTERN.fullmatch(n) for n in names):
        raise ValueError('Missing or invalid sequence inventory')
    # Official SIS holds out ALL sequences of crossing3; no random sampling.
    test = [n for n in names if '_crossing3_' in n]
    if not test:
        raise ValueError('No crossing3 test sequences')
    return {'schema': 'phdsim-urbaning-benchmark-v1', 'dataset_version': '1.0',
            'test_sequences': test, 'source_sequences': names,
            'download_bytes_including_repeated_support': sum(
                i['bytes'] for n in test for i in sequence_files(metadata, n)),
            'frames': 'all source synchronization anchors; no frame cap',
            'ego': 'upstream default first vehicle (no specific_ego_id override)',
            'policy': 'all available collaborators; upstream intermediate inference',
            'global_sort_modes': [False, True], 'seed': 42}


def freeze(path, value):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('Frozen plan changed: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            json.dump(value, handle, indent=2)
            handle.write('\n')


def empty_stats():
    return {c: {str(i): {'tp': [], 'fp': [], 'gt': 0, 'score': []} for i in IOUS} for c in CLASSES}


def merge_stats(reports):
    result = empty_stats()
    for report in reports:
        for c in CLASSES:
            for i in map(str, IOUS):
                src, dst = report[c][i], result[c][i]
                dst['gt'] += src['gt']
                for k in ('tp', 'fp', 'score'):
                    dst[k].extend(src[k])
    return result


def summarize(stats, global_sort, calculate_ap):
    result = {}
    for c in CLASSES:
        converted = {float(i): v for i, v in copy.deepcopy(stats[c]).items()}
        result[c] = {str(i): float(calculate_ap(converted, i, global_sort)[0]) for i in IOUS}
    return {'classes': result, 'macro_ap': {str(i): sum(result[c][str(i)] for c in CLASSES) / 4 for i in IOUS}}


def validate_complete(plan, records):
    if [r['sequence'] for r in records] != plan['test_sequences']:
        raise ValueError('Missing, duplicate or unordered test sequences')
    for r in records:
        if r['status'] != 'completed' or r['frames'] != r['dataset_frames'] or r['frames'] < 1:
            raise ValueError('Incomplete sequence: ' + r['sequence'])
        if r['plan'] != plan:
            raise ValueError('Sequence belongs to another frozen plan')


def run_sequence(args):
    from phdsim.datasets.urbaning.source import fetch_sequence
    from phdsim.datasets.urbaning.archive import extract_sequence
    from phdsim.datasets.urbaning.opencood import create_source_view
    plan = json.loads(Path(args.plan).read_text())
    sequence = plan['test_sequences'][args.index]
    root, output = Path(args.data_root).resolve(), Path(args.output).resolve()
    if sha256(root / 'source/dataverse-dataset.json') != plan['metadata_sha256']:
        raise ValueError('Dataset inventory changed')
    out = output / sequence
    out.mkdir(parents=True, exist_ok=True)
    identity = {'plan': plan, 'detector': verify_bundle(args.model_dir),
                'implementation_sha256': {str(p.relative_to(REPO)): sha256(p) for p in (
                    Path(__file__), REPO / 'src/phdsim/evaluation/urbaning.py',
                    REPO / 'scripts/urbaning_convert.py')}}
    freeze(out / 'identity.json', identity)
    completed = out / 'result.json'
    if completed.exists():
        saved = json.loads(completed.read_text())
        if (saved['plan'] != plan or saved['sequence'] != sequence or
                saved['status'] != 'completed' or saved['frames'] != saved['dataset_frames'] or saved['frames'] < 1):
            raise ValueError('Incomplete or incompatible saved sequence')
        if saved['statistics_sha256'] != sha256(out / 'statistics.json'):
            raise ValueError('Completed statistics changed')
        print('REUSE ' + sequence, flush=True)
        return
    environment = doctor(args.upstream, args.model_dir, 'cpu')
    if not environment['ready']:
        raise RuntimeError(json.dumps(environment, indent=2))
    fetch_sequence(root, sequence)
    extract_sequence(root, sequence)
    view, converted = out / 'view', out / 'converted'
    if not view.exists():
        create_source_view(root, sequence, view)
    record = json.loads((view / 'phdsim-conversion.json').read_text())
    if record['sequence'] != sequence or record['max_frames'] is not None or record['start_frame'] != 0:
        raise ValueError('Benchmark requires an uncapped source view')
    if not converted.exists():
        subprocess.run([sys.executable, str(REPO / 'scripts/urbaning_convert.py'),
                        '--upstream', args.upstream, '--source-view', str(view), '--output', str(converted)], check=True)
    manifest = json.loads((converted / 'phdsim-conversion.json').read_text())
    if manifest['sequence'] != sequence or manifest['max_frames'] is not None or manifest['start_frame'] != 0:
        raise ValueError('Partial or capped conversion; preserve it and retry in a fresh output')
    prepare_upstream(args.upstream)
    import numpy as np
    import torch
    from opencood.data_utils.datasets import build_dataset
    from opencood.tools.train_utils import to_device
    from opencood.tools.inference_utils import inference_intermediate_fusion
    from opencood.utils import eval_utils
    from phdsim.evaluation.urbaning import accumulate, empty_statistics
    random.seed(plan['seed'])
    np.random.seed(plan['seed'])
    torch.manual_seed(plan['seed'])
    torch.set_num_threads(args.cpu_threads)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    model, config = load_model(args.model_dir, torch.device('cpu'))
    config['validate_dir'] = str(converted)
    # Preserve all released settings, including the upstream default ego choice.
    dataset = build_dataset(config, visualize=False, train=False, specific_scenario=sequence)
    if len(dataset) != len(record['sync_by_frame']):
        raise ValueError('Converted frame coverage differs from source synchronization anchors')
    stats = empty_statistics()
    run_record = {'status': 'running', 'sequence': sequence, 'plan': plan,
                  'detector': identity['detector'], 'effective_config': config,
                  'dataset_frames': len(dataset), 'frames': 0,
                  'python': sys.version, 'torch': torch.__version__, 'numpy': np.__version__,
                  'environment': environment,
                  'implementation_sha256': identity['implementation_sha256']}
    write_json(out / 'run.json', run_record)
    with torch.no_grad():
        for index in range(len(dataset)):
            item = dataset[index]
            batch = to_device(dataset.collate_batch_test([item]), torch.device('cpu'))
            boxes, scores, gt, labels = inference_intermediate_fusion(batch, model, dataset)
            if boxes is None:
                boxes, scores = gt.new_empty((0, 8, 3)), gt.new_empty((0, 2))
            accumulate(stats, boxes, scores, gt, labels)
            print(f'{sequence} {index + 1}/{len(dataset)}', flush=True)
    serializable = {c: {str(i): s for i, s in v.items()} for c, v in stats.items()}
    write_json(out / 'statistics.json', serializable)
    run_record.update(status='completed', frames=len(dataset),
                      statistics_sha256=sha256(out / 'statistics.json'),
                      conversion_sha256=sha256(converted / 'phdsim-conversion.json'),
                      metrics={str(mode): summarize(serializable, mode, eval_utils.calculate_ap) for mode in (False, True)})
    write_json(completed, run_record)
    write_json(out / 'run.json', run_record)


def collect(args):
    plan = json.loads(Path(args.plan).read_text())
    output = Path(args.output)
    records = [json.loads((output / s / 'result.json').read_text()) for s in plan['test_sequences']]
    validate_complete(plan, records)
    for r in records:
        if r['detector'] != verify_bundle(args.model_dir):
            raise ValueError('Different detector identity')
        if sha256(output / r['sequence'] / 'statistics.json') != r['statistics_sha256']:
            raise ValueError('Statistics changed')
    if len({json.dumps(r['implementation_sha256'], sort_keys=True) for r in records}) != 1:
        raise ValueError('Mixed inference implementations')
    prepare_upstream(args.upstream)
    from opencood.utils import eval_utils
    stats = merge_stats([json.loads((output / s / 'statistics.json').read_text()) for s in plan['test_sequences']])
    import yaml
    reference = yaml.safe_load((Path(args.model_dir) / 'eval_3d_det.yaml').read_text())
    expected = {c: {str(i): reference[c]['0-100'][f'ap_{i}'] for i in IOUS} for c in CLASSES}
    modes = {str(mode): summarize(stats, mode, eval_utils.calculate_ap) for mode in (False, True)}
    for v in modes.values():
        v['delta_vs_release'] = {c: {str(i): v['classes'][c][str(i)] - expected[c][str(i)] for i in IOUS} for c in CLASSES}
    report = {'status': 'completed', 'scope': 'full crossing3; all-source frozen CoBEVT reference; no policy fit',
              'plan': plan, 'frames': sum(r['frames'] for r in records), 'metrics_by_global_sort': modes,
              'release_reference_ap': expected,
              'warning': 'Not a claimed reproduction until class-wise deltas and configuration are reviewed',
              'sequence_results_sha256': {s: sha256(output / s / 'result.json') for s in plan['test_sequences']}}
    freeze(output / 'benchmark-report.json', report)
    print(json.dumps(report, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--metadata', required=True)
    p.add_argument('--output', required=True)
    for name in ('run', 'collect'):
        p = sub.add_parser(name)
        for arg in ('plan', 'upstream', 'model-dir', 'output'):
            p.add_argument('--' + arg, required=True)
        if name == 'run':
            p.add_argument('--data-root', required=True)
            p.add_argument('--index', type=int, required=True)
            p.add_argument('--cpu-threads', type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        plan = make_plan(json.loads(Path(args.metadata).read_text()))
        plan['metadata_sha256'] = sha256(args.metadata)
        freeze(args.output, plan)
        print(json.dumps(plan, indent=2))
    elif args.command == 'run':
        plan = json.loads(Path(args.plan).read_text())
        if not 0 <= args.index < len(plan['test_sequences']) or args.cpu_threads < 1:
            raise ValueError('Invalid sequence index or thread count')
        run_sequence(args)
    else:
        collect(args)
