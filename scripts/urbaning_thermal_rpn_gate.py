"""Cheap frozen-RPN recall gate for projected UrbanIng thermal boxes."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from phdsim.datasets.urbaning.archive import sequence_directory
from phdsim.datasets.urbaning.geometry import rectified_image
from phdsim.experiments.urbaning_rgb3d_finetune import read_inputs
from phdsim.perception.urbaning.rgb3d_finetune import FineTuneDetector, projected_targets

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
    if sequence not in cache:
        directory = sequence_directory(root, sequence)
        calibration = json.loads((directory/'calibration.json').read_text())
        cache[sequence] = (directory, calibration)
    return cache[sequence]


def vehicle_lidar_to_global(directory, calibration, members):
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
    import torch

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
    totals = {c: {str(t): [0, 0] for t in IOU_THRESHOLDS} for c in range(4)}
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
            proposals, _ = model.proposal_generator(batch, features, None)
            proposal_boxes = proposals[0].proposal_boxes.tensor.detach().cpu().numpy()
            gt_boxes = inputs['instances'].gt_boxes.tensor.detach().cpu().numpy()
            gt_classes = inputs['instances'].gt_classes.detach().cpu().numpy()
            keep = gt_classes >= 0
            recalls = proposal_recall(proposal_boxes, gt_boxes[keep])
            names = [CLASSES[int(c)] for c in gt_classes[keep]]
            for j, name in enumerate(names):
                class_id = CLASSES.index(name)
                for threshold in IOU_THRESHOLDS:
                    hit = recalls[str(threshold)][j]
                    totals[class_id][str(threshold)][0] += hit
                    totals[class_id][str(threshold)][1] += 1
            anchor_ms = record['native_association']['timestamp_ns']/1e6
            offset_ms = int(Path(filename).stem)-anchor_ms
            proposal_rows.append({'key': record['key'], 'stream': stream, 'offset_ms': offset_ms,
                                  'positive_count': int(keep.sum()), 'proposal_count': len(proposal_boxes),
                                  'recall': {str(t): float(np.mean(v)) if v else None
                                             for t, v in recalls.items()}})
            seen += 1
        print('THERMAL GATE FRAME', record['key'], 'usable_views', seen, flush=True)
    if not proposal_rows:
        raise ValueError('No positive thermal views reached frozen RPN gate')
    metrics = {}
    for class_id, name in enumerate(CLASSES):
        metrics[name] = {threshold: {'hits': hit, 'gt': count,
                         'recall': hit/count if count else None}
                         for threshold, (hit, count) in totals[class_id].items()}
    macro = {threshold: float(np.mean([metrics[n][threshold]['recall'] for n in CLASSES
                                       if metrics[n][threshold]['recall'] is not None]))
             for threshold in map(str, IOU_THRESHOLDS)}
    # Frozen RPN boxes are the only localization candidates in this pilot.
    # Proceed only when the RGB-pretrained RPN covers enough thermal GT to fit.
    class_support_ok = all(totals[c]['0.5'][1] >= 5 for c in range(4))
    passed = class_support_ok and macro['0.3'] >= .25 and macro['0.5'] >= .10
    report = {'schema': 'phdsim-urbaning-thermal-frozen-rpn-gate-v1', 'passed': passed,
              'decision_rule': {'min_gt_per_class': 5, 'macro_recall_iou_0.3_min': .25,
                                'macro_recall_iou_0.5_min': .10},
              'sample_per_sequence': SAMPLE_PER_SEQUENCE, 'sampled_frames': [r['key'] for r in selected],
              'data_root': str(root), 'train_provenance': provenance['train'],
              'metrics': metrics, 'macro_recall': macro, 'views': proposal_rows,
              'mean_abs_capture_offset_ms': float(np.mean([abs(r['offset_ms']) for r in proposal_rows]))}
    (output/'rpn-gate.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print('THERMAL RPN RECALL', json.dumps({'macro': macro, 'per_class': metrics}, sort_keys=True), flush=True)
    print('THERMAL RPN GATE', 'PASSED' if passed else 'STOP: frozen proposal coverage too low', flush=True)
    print('DONE:', output, flush=True)
    return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == '__main__':
    main()
