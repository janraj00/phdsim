"""Offline paired LiDAR ablation. Compatible with the separate upstream Python 3.9 env."""

import argparse
import hashlib
import importlib
from importlib import metadata
import inspect
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from phdsim.decision.urbaning import action_subsets, choose_one_peer
from phdsim.perception.urbaning.bundle import UPSTREAM_COMMIT, fetch_bundle, load_config, sha256, verify_bundle


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare_upstream(directory):
    directory = Path(directory).resolve()
    revision = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != UPSTREAM_COMMIT:
        raise ValueError('Checkout must be pinned to ' + UPSTREAM_COMMIT)
    subprocess.run(['git', '-C', str(directory), 'diff', '--exit-code', 'HEAD', '--'], check=True,
                   stdout=subprocess.DEVNULL)
    sys.path.insert(0, str(directory / 'opencood'))
    module = importlib.import_module('opencood')
    if Path(module.__file__).resolve().parent != directory / 'opencood' / 'opencood':
        raise ValueError('A different opencood installation is already imported')
    return revision


def doctor(upstream, model_dir, device='cuda'):
    report = {'ready': False, 'python': sys.version, 'requested_device': device, 'errors': []}
    report['packages'] = {}
    for package in ('numpy', 'torch', 'spconv', 'spconv-cu113', 'spconv-cu120', 'cumm',
                    'einops', 'PyYAML', 'shapely', 'open3d'):
        try:
            report['packages'][package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    for name, check in (
        ('upstream_commit', lambda: prepare_upstream(upstream)),
        ('model', lambda: verify_bundle(model_dir)),
    ):
        try:
            report[name] = check()
        except Exception as error:
            report['errors'].append(name + ': ' + str(error))
    try:
        import torch
        report.update(torch=torch.__version__, cuda=torch.version.cuda,
                      cuda_available=torch.cuda.is_available())
        if device == 'cuda' and not torch.cuda.is_available():
            report['errors'].append('CUDA GPU unavailable; explicitly select --device cpu for a CPU smoke run')
        elif device == 'cuda':
            report['gpu'] = torch.cuda.get_device_name(0)
        for name in ('spconv', 'opencood.data_utils.datasets', 'opencood.utils.eval_utils'):
            try:
                importlib.import_module(name)
            except Exception as error:
                report['errors'].append(name + ': ' + str(error))
    except ImportError as error:
        report['errors'].append(str(error))
    report['ready'] = not report['errors']
    return report


def load_model(model_dir, device):
    import torch
    from opencood.models.lidar.point_pillar_cobevt import PointPillarCoBEVT

    config = load_config(model_dir)
    model = PointPillarCoBEVT(config['model']['args'])
    # PyTorch 1.12 lacks weights_only. Its fallback is restricted to the exact
    # hash-verified official release, never arbitrary user checkpoint files.
    options = {'weights_only': True} if 'weights_only' in inspect.signature(torch.load).parameters else {}
    state = torch.load(Path(model_dir) / 'best_model.pth', map_location='cpu', **options)
    model.load_state_dict(state, strict=True)
    model.requires_grad_(False)
    return model.to(device).eval(), config


def validate_selection(sequence, purpose, max_frames, start, ego_id):
    from phdsim.datasets.urbaning.source import SEQUENCE_PATTERN

    if not SEQUENCE_PATTERN.fullmatch(sequence) or start < 0 or max_frames < 0:
        raise ValueError('Invalid sequence or frame bounds')
    if ego_id not in (100000, 200000):
        raise ValueError('Ego must be one of the two recorded vehicles')
    if purpose == 'smoke' and ('crossing3' in sequence or max_frames == 0):
        raise ValueError('Smoke runs must be bounded and use crossing1/2; reserve crossing3 for evaluation')
    if purpose == 'evaluation' and 'crossing3' not in sequence:
        raise ValueError('The released SIS checkpoint holds out crossing3')


def capture_sources(dataset, index):
    """Capture the source order from the very same retrieval used to make voxels."""
    from opencood.data_utils.datasets import COM_RANGE

    original = dataset.retrieve_base_data
    captured = {}

    def retrieve(*args, **kwargs):
        data = original(*args, **kwargs)
        ego = next(value for value in data.values() if value['ego'])
        position = ego['params']['lidar_pose']
        captured['all_ids'] = list(data)
        captured['included_ids'] = [key for key, value in data.items() if math.hypot(
            value['params']['lidar_pose'][0] - position[0],
            value['params']['lidar_pose'][1] - position[1]) <= COM_RANGE]
        return data

    dataset.retrieve_base_data = retrieve
    try:
        item = dataset[index]
    finally:
        dataset.retrieve_base_data = original
    if item['ego']['cav_num'] != len(captured['included_ids']):
        raise ValueError('Captured source order disagrees with upstream fusion input')
    return item, captured


def run(args):
    import numpy as np
    import torch
    from phdsim.evaluation.urbaning import accumulate, empty_statistics, summarize
    from phdsim.perception.urbaning.cobevt import ego_entropy, subset_inputs

    validate_selection(args.sequence, args.purpose, args.max_frames, args.start, args.ego_id)
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('Set PYTHONHASHSEED=0 before Python starts, or use scripts/urbaning_stage1.py')
    if not 0 <= args.seed < 2 ** 32:
        raise ValueError('Seed must be in [0,2**32)')
    if args.entropy_threshold is not None and (not math.isfinite(args.entropy_threshold) or
                                             not 0 <= args.entropy_threshold <= 1):
        raise ValueError('Entropy threshold must be in [0,1]')
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError('Use a new output directory: ' + str(output))
    environment = doctor(args.upstream, args.model_dir, args.device)
    if not environment['ready']:
        raise RuntimeError(json.dumps(environment, indent=2))
    from opencood.data_utils.datasets import build_dataset
    from opencood.tools.train_utils import to_device

    # Reproducible within this environment; hardware/driver identities are saved.
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.device == 'cuda':
        torch.cuda.manual_seed_all(args.seed)
    else:
        if args.cpu_threads < 1:
            raise ValueError('CPU threads must be positive')
        torch.set_num_threads(args.cpu_threads)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    device = torch.device('cuda:0' if args.device == 'cuda' else 'cpu')
    model, config = load_model(args.model_dir, device)
    config['validate_dir'] = str(Path(args.data_root).resolve())
    config['train_params']['specific_ego_id'] = args.ego_id
    if not (Path(args.data_root) / args.sequence).is_dir():
        raise FileNotFoundError('Missing converted sequence: ' + str(Path(args.data_root) / args.sequence))
    # Keep architectural max_cav=3 and the upstream mask, even for ego-only.
    dataset = build_dataset(config, visualize=False, train=False, specific_scenario=args.sequence)
    if args.start >= len(dataset):
        raise ValueError('Start frame exceeds the sequence length')
    end = min(len(dataset), args.start + args.max_frames) if args.max_frames else len(dataset)
    output.mkdir(parents=True)
    (output / 'predictions').mkdir()
    provenance = {'schema': 'phdsim-urbaning-stage1-v1', 'status': 'running',
                  'arguments': vars(args), 'environment': environment,
                  'model': verify_bundle(args.model_dir), 'effective_config': config,
                  'frame_bounds': [args.start, end], 'dataset_frames': len(dataset),
                  'protocol': 'offline counterfactual; fixed all-source GT; frozen model; no online transmission',
                  'python_hash_seed': os.environ.get('PYTHONHASHSEED'),
                  'implementation_sha256': {name: sha256(Path(__file__).resolve().parents[1] / name)
                                            for name in ('experiments/urbaning_stage1.py', 'decision/urbaning.py',
                                                         'evaluation/urbaning.py', 'perception/urbaning/cobevt.py',
                                                         'perception/urbaning/bundle.py')}}
    write_json(output / 'run.json', provenance)
    statistics, requests, fallback_count = {}, {}, {}
    source_manifest = Path(args.data_root) / 'phdsim-conversion.json'
    conversion = json.loads(source_manifest.read_text()) if source_manifest.is_file() else None
    if conversion:
        write_json(output / 'conversion-source.json', conversion)
    try:
        with (output / 'frames.jsonl').open('x', encoding='utf-8') as trace, torch.no_grad():
            for index in range(args.start, end):
                item, sources = capture_sources(dataset, index)
                batch = to_device(dataset.collate_batch_test([item]), device)
                scene, timestamp_index = dataset.retrieve_by_idx(index)
                timestamp = dataset.return_timestamp_key(scene, timestamp_index)
                frame_key = args.sequence + ':' + timestamp + ':' + str(args.ego_id)
                source_files = {key: {name: {'path': scene[key][timestamp][name],
                                            'sha256': sha256(scene[key][timestamp][name])}
                                      for name in ('yaml', 'lidar')} for key in sources['all_ids']}
                ids = sources['included_ids']
                actions = action_subsets(ids)
                # This GT object is computed once, outside the action loop.
                gt_boxes, gt_labels = dataset.post_processor.generate_gt_bbx(batch, gt_range=dataset.gt_range)
                gt_digest = hashlib.sha256(gt_boxes.cpu().numpy().tobytes() +
                                           gt_labels.cpu().numpy().tobytes()).hexdigest()
                frame_file = 'predictions/{:06d}.npz'.format(index)
                arrays = {'gt_boxes': gt_boxes.cpu().numpy(), 'gt_labels': gt_labels.cpu().numpy()}
                predictions, timings = {}, {}
                uncertainty = None
                for name, indices in actions.items():
                    if indices not in predictions:
                        inputs = subset_inputs(batch['ego'], indices)
                        if args.device == 'cuda':
                            torch.cuda.synchronize()
                        started = time.perf_counter()
                        result = model(inputs)
                        if args.device == 'cuda':
                            torch.cuda.synchronize()
                        elapsed = 1000 * (time.perf_counter() - started)
                        if not all(bool(value.isfinite().all()) for value in result.values()):
                            raise ValueError('Non-finite model output for ' + name)
                        if name == 'ego':
                            uncertainty = ego_entropy(result['psm'])
                        boxes, scores = dataset.post_processor.post_process(batch, {'ego': result},
                                                                           gt_range=dataset.gt_range)
                        if boxes is None:
                            boxes = gt_boxes.new_empty((0, 8, 3))
                            scores = gt_boxes.new_empty((0, 2))
                        predictions[indices] = (boxes, scores)
                        timings[indices] = elapsed
                    boxes, scores = predictions[indices]
                    arrays[name + '_boxes'] = boxes.cpu().numpy()
                    arrays[name + '_scores'] = scores.cpu().numpy()
                selected = {'random_one_peer': choose_one_peer(ids, frame_key, args.seed)}
                if args.entropy_threshold is not None:
                    selected['entropy_gate'] = choose_one_peer(ids, frame_key, args.seed,
                                                               uncertainty, args.entropy_threshold)
                executed = dict(actions)
                executed.update({name: actions[choice] for name, choice in selected.items()})
                for name, indices in executed.items():
                    statistics.setdefault(name, empty_statistics())
                    requests[name] = requests.get(name, 0) + len(indices) - 1
                    fallback_count[name] = fallback_count.get(name, 0) + int(
                        name in ('vehicle_peer', 'infrastructure') and len(indices) == 1)
                    accumulate(statistics[name], *predictions[indices], gt_boxes, gt_labels)
                np.savez_compressed(output / frame_file, **arrays)
                native = None
                if conversion and conversion['sequence'] == args.sequence:
                    native = conversion.get('sync_by_frame', {}).get(timestamp)
                row = {'frame_key': frame_key, 'frame_index': index, 'source_frame_id': timestamp,
                       'native_association': native, 'sources': sources, 'source_files': source_files,
                       'gt_sha256': gt_digest, 'gt_count': len(gt_labels), 'predictions': frame_file,
                       'ego_entropy_bits': uncertainty, 'policy_choices': selected,
                       'actions': {name: {'source_ids': [ids[i] for i in indices],
                                          'peer_requests': len(indices) - 1,
                                          'model_forward_ms': timings[indices]}
                                   for name, indices in executed.items()}}
                trace.write(json.dumps(row, allow_nan=False) + '\n')
                trace.flush()
                print('{}/{} frame={} sources={} entropy={:.3f}'.format(
                    index - args.start + 1, end - args.start, timestamp, ids, uncertainty), flush=True)
        report = {name: {**summarize(values), 'frames': end - args.start,
                         'peer_requests': requests[name],
                         'mean_peer_requests': requests[name] / (end - args.start),
                         'unavailable_peer_fallback_frames': fallback_count[name]}
                  for name, values in statistics.items()}
        write_json(output / 'metrics.json', report)
        provenance['status'] = 'completed'
    except Exception as error:
        provenance.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        write_json(output / 'run.json', provenance)
    return str(output)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='phdsim urbaning cobevt')
    subparsers = parser.add_subparsers(dest='command', required=True)
    fetch = subparsers.add_parser('fetch', help='Fetch/verify the pinned official model bundle')
    fetch.add_argument('--model-dir', default='models/urbaning/CoBEVT_SIS_1_2_vs_3')
    fetch.add_argument('--archive', help='Use an existing archive instead of downloading')
    check = subparsers.add_parser('doctor', help='Report source/model/dependency/device readiness')
    execute = subparsers.add_parser('run', help='Run a paired offline comparison on one sequence')
    for command in (check, execute):
        command.add_argument('--upstream', required=True)
        command.add_argument('--model-dir', default='models/urbaning/CoBEVT_SIS_1_2_vs_3')
        command.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    execute.add_argument('--data-root', required=True, help='Converted OpenCOOD root containing sequence directories')
    execute.add_argument('--sequence', required=True)
    execute.add_argument('--purpose', choices=('smoke', 'evaluation'), default='smoke')
    execute.add_argument('--max-frames', type=int, default=10, help='0 means all remaining frames; evaluation only')
    execute.add_argument('--start', type=int, default=0)
    execute.add_argument('--ego-id', type=int, choices=(100000, 200000), default=100000)
    execute.add_argument('--seed', type=int, default=42)
    execute.add_argument('--cpu-threads', type=int, default=2)
    execute.add_argument('--entropy-threshold', type=float, help='Optional fixed ego entropy gate [0,1]; never tune on test')
    execute.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'fetch':
        value = fetch_bundle(args.model_dir, args.archive)
    elif args.command == 'doctor':
        value = doctor(args.upstream, args.model_dir, args.device)
    else:
        value = run(args)
    print(json.dumps(value, indent=2))
    if args.command == 'doctor' and not value['ready']:
        raise SystemExit(2)
