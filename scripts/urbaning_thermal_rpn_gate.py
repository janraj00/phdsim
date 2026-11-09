"""Cheap frozen-RPN proposal-budget sweep for projected thermal boxes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

CLASSES = ('Vehicle', 'Heavy_Vehicle', '2Wheeler', 'Pedestrian')
GATE_SEQUENCE = '20241126_0017_crossing1_00'
SAMPLE_PER_SEQUENCE = 12
IOU_THRESHOLDS = (.3, .5, .7)


def find_data_root(base, explicit=None):
    if explicit:
        root = Path(explicit).resolve()
        if not (root/'extracted'/GATE_SEQUENCE/'extraction.json').is_file():
            raise FileNotFoundError('Explicit UrbanIng root lacks the required extraction: '+str(root))
        return root
    base = Path(base).resolve()
    candidates = (base.parent/'data'/'urbaning-v2x', base.parent/'inputs'/'urbaning-v2x',
                  base/'data'/'urbaning-v2x', base/'inputs'/'urbaning-v2x',
                  base.parent.parent/'data'/'urbaning-v2x')
    for root in candidates:
        if (root/'extracted'/GATE_SEQUENCE/'extraction.json').is_file():
            return root
    raise FileNotFoundError('No UrbanIng data root contains the crossing1 TRAIN extraction marker; checked: '
                            + ', '.join(str(p) for p in candidates))


def load_sequence(root, sequence, cache):
    from phdsim.datasets.urbaning.archive import sequence_directory
    if sequence not in cache:
        directory = sequence_directory(root, sequence)
        calibration = json.loads((directory/'calibration.json').read_text())
        cache[sequence] = (directory, calibration)
    return cache[sequence]


def vehicle_lidar_to_global(directory, calibration, members):
    import numpy as np
    state_name = members.get('vehicle1_state')
    if not state_name:
        raise ValueError('Thermal association is missing vehicle1_state')
    state = json.loads((directory/'vehicle1_state'/state_name).read_text())
    gTv = np.asarray(state['gTv'], dtype=np.float64)
    vTl = np.asarray(calibration['vehicle1_middle_lidar']['extrinsics']['vTl'], dtype=np.float64)
    if gTv.shape != (4, 4) or vTl.shape != (4, 4):
        raise ValueError('Invalid vehicle/LiDAR transform')
    return gTv @ vTl


def proposal_recall(proposals, targets):
    import numpy as np
    if len(targets) == 0:
        return {str(t): [] for t in IOU_THRESHOLDS}
    if len(proposals) == 0:
        return {str(t): [0]*len(targets) for t in IOU_THRESHOLDS}
    lo = np.maximum(proposals[:, None, :2], targets[None, :, :2])
    hi = np.minimum(proposals[:, None, 2:], targets[None, :, 2:])
    inter = np.maximum(hi-lo, 0).prod(axis=2)
    pa = np.maximum(proposals[:, 2:]-proposals[:, :2], 0).prod(axis=1)
    ga = np.maximum(targets[:, 2:]-targets[:, :2], 0).prod(axis=1)
    iou = inter/np.maximum(pa[:, None]+ga[None, :]-inter, 1e-9)
    return {str(t): (iou.max(axis=0) >= t).astype(int).tolist() for t in IOU_THRESHOLDS}


def run(args):
    import cv2
    import numpy as np
    import torch
    from phdsim.datasets.urbaning.geometry import rectified_image
    from phdsim.experiments.urbaning_rgb3d_finetune import read_inputs
    from phdsim.perception.urbaning.rgb3d_finetune import FineTuneDetector, projected_targets

    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Gate output must be a fresh empty directory')
    output.mkdir(parents=True, exist_ok=True)
    for folder in ('loader',):
        (output/folder).mkdir()
    root = find_data_root(args.base, args.data_root)
    print('THERMAL DATA ROOT', root, flush=True)
    records, provenance = read_inputs(args.base, output/'loader', 200, 0)
    train = records['train']
    selected = []
    for sequence in (GATE_SEQUENCE,):
        rows = sorted((r for r in train if r['sequence'] == sequence), key=lambda r: r['key'])
        if len(rows) < SAMPLE_PER_SEQUENCE:
            raise ValueError('Too few declared TRAIN frames for thermal gate: '+sequence)
        indices = np.linspace(0, len(rows)-1, SAMPLE_PER_SEQUENCE, dtype=int)
        selected.extend(rows[i] for i in indices)

    detector = FineTuneDetector(args.model_dir, args.threads)
    model = detector.model.eval()
    proposal_rows = []
    sequence_cache = {}
    rpn = model.proposal_generator
    if (not isinstance(getattr(rpn, 'pre_nms_topk', None), dict) or
            not isinstance(getattr(rpn, 'post_nms_topk', None), dict) or False not in rpn.pre_nms_topk or
            False not in rpn.post_nms_topk):
        raise TypeError('Pinned RPN does not expose Detectron2 test proposal budgets')
    default_pre = int(rpn.pre_nms_topk[False])
    default_post = int(rpn.post_nms_topk[False])
    settings = [('configured', default_pre, default_post)]
    settings += [(f'post-{budget}', max(default_pre, budget), budget) for budget in (2000, 4000)]
    totals = {key: {c: {str(t): [0, 0] for t in IOU_THRESHOLDS} for c in range(4)}
              for key, _, _ in settings}
    torch.set_grad_enabled(False)
    for record in selected:
        sequence = record['sequence']
        directory, calibration = load_sequence(root, sequence, sequence_cache)
        members = record['native_association']['members']
        gTl = vehicle_lidar_to_global(directory, calibration, members)
        streams = sorted(k for k in calibration if k.endswith('_thermal_camera'))
        seen = 0
        for stream in streams:
            filename = members.get(stream)
            if not filename:
                continue
            path = directory/stream/filename
            raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if raw is None:
                raise ValueError('Unreadable associated thermal image: '+str(path))
            image, intrinsic = rectified_image(raw, calibration[stream]['intrinsics'])
            bgr = np.repeat(image[:, :, None], 3, axis=2)
            cTg = np.asarray(calibration[stream]['extrinsics']['cTg'], dtype=np.float64)
            cTl = cTg @ gTl
            rows = projected_targets(record['gt_boxes'], record['gt_labels'], cTl, intrinsic,
                                      image.shape[1], image.shape[0])
            positive = [r for r in rows if r['class'] >= 0]
            if not positive:
                continue
            inputs = detector.training_input(bgr, intrinsic, rows)
            batch = model.preprocess_image([inputs])
            features = model.backbone(batch.tensor)
            gt_boxes = inputs['instances'].gt_boxes.tensor.detach().cpu().numpy()
            gt_classes = inputs['instances'].gt_classes.detach().cpu().numpy()
            keep = gt_classes >= 0
            names = [CLASSES[int(c)] for c in gt_classes[keep]]
            by_budget = {}
            for key, pre_nms, post_nms in settings:
                rpn.pre_nms_topk[False] = pre_nms
                rpn.post_nms_topk[False] = post_nms
                proposals, _ = model.proposal_generator(batch, features, None)
                proposal_boxes = proposals[0].proposal_boxes.tensor.detach().cpu().numpy()
                recalls = proposal_recall(proposal_boxes, gt_boxes[keep])
                for j, name in enumerate(names):
                    class_id = CLASSES.index(name)
                    for threshold in IOU_THRESHOLDS:
                        hit = recalls[str(threshold)][j]
                        totals[key][class_id][str(threshold)][0] += hit
                        totals[key][class_id][str(threshold)][1] += 1
                by_budget[key] = {'proposal_count': len(proposal_boxes),
                                  'recall': {str(t): float(np.mean(v)) if v else None
                                             for t, v in recalls.items()}}
            rpn.pre_nms_topk[False] = default_pre
            rpn.post_nms_topk[False] = default_post
            anchor_ms = record['native_association']['timestamp_ns']/1e6
            offset_ms = int(Path(filename).stem)-anchor_ms
            proposal_rows.append({'key': record['key'], 'stream': stream, 'offset_ms': offset_ms,
                                  'positive_count': int(keep.sum()), 'budgets': by_budget})
            seen += 1
        print('THERMAL GATE FRAME', record['key'], 'usable_views', seen, flush=True)
    if not proposal_rows:
        raise ValueError('No positive thermal views reached frozen RPN gate')
    metrics, macro = {}, {}
    for key, _, _ in settings:
        metrics[key] = {}
        for class_id, name in enumerate(CLASSES):
            metrics[key][name] = {threshold: {'hits': hit, 'gt': count,
                                    'recall': hit/count if count else None}
                                  for threshold, (hit, count) in totals[key][class_id].items()}
        macro[key] = {threshold: float(np.mean([metrics[key][n][threshold]['recall'] for n in CLASSES
                                                if metrics[key][n][threshold]['recall'] is not None]))
                      for threshold in map(str, IOU_THRESHOLDS)}
    report = {'schema': 'phdsim-urbaning-thermal-rpn-budget-sweep-v1',
              'default_limits': {'pre_nms_topk': default_pre, 'post_nms_topk': default_post},
              'sweep_settings': [{'name': key, 'pre_nms_topk': pre, 'post_nms_topk': post}
                                 for key, pre, post in settings],
              'sample_per_sequence': SAMPLE_PER_SEQUENCE, 'sampled_frames': [r['key'] for r in selected],
              'data_root': str(root), 'train_provenance': provenance['train'],
              'metrics': metrics, 'macro_recall': macro, 'views': proposal_rows,
              'mean_abs_capture_offset_ms': float(np.mean([abs(r['offset_ms']) for r in proposal_rows]))}
    (output/'rpn-budget-sweep.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    for key in macro:
        print('THERMAL RPN BUDGET', key, json.dumps({'macro': macro[key],
              'per_class': metrics[key]}, sort_keys=True), flush=True)
    print('THERMAL RPN BUDGET SWEEP DONE', flush=True)
    print('DONE:', output, flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    for name in ('base', 'runtime', 'model-dir', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--activated', action='store_true')
    args = parser.parse_args()
    if not args.activated or os.environ.get('PYTHONHASHSEED') != '0':
        spec = importlib.util.spec_from_file_location('rgb3d_runtime', ROOT/'scripts/urbaning_rgb3d_late.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _, env = module.reuse(args.runtime.resolve())
        env.update({'PYTHONHASHSEED': '0', 'MPLCONFIGDIR': str(args.output.resolve()/'matplotlib-cache'),
                    'OMP_NUM_THREADS': str(args.threads), 'MKL_NUM_THREADS': str(args.threads)})
        command = [sys.executable, '-u', str(Path(__file__).resolve()), *sys.argv[1:]]
        if not args.activated:
            command.append('--activated')
        os.execve(sys.executable, command, env)
    raise SystemExit(run(args))


if __name__ == '__main__':
    main()
