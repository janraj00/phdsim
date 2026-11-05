"""CPU Car1 LiDAR/RGB proposal reranking, using immutable converted inputs.

This is late fusion of fixed proposals, not an RGB 3D detector or acquisition
policy. GT enters offline targets/evaluation only, never feature extraction.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import time
import zipfile

import numpy as np
import yaml

from phdsim.evaluation.urbaning import CLASSES, IOU_THRESHOLDS, empty_statistics
from phdsim.evaluation.urbaning_cached import (frame_statistics, aggregate_statistics,
                                             summarize_cached, _radius_mask, _polygon, polygon_iou,
                                             validate_arrays)
from phdsim.experiments.urbaning_ap_replay import load_archive

SCHEMA = 'phdsim-urbaning-rgb-late-pilot-v1'
AP_SHA = 'ce8893d439d446edf0cb328881a0b31523a138b1eed713b844f68e1da7e557c5'
PACKET_SHA = 'c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee'
UPSTREAM = 'd5766e75f985c6c566a09abfa23d3fbb32f03820'
WEIGHTS_SHA = '047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f'
CAMERAS = tuple('vehicle1_' + n + '_camera' for n in
                ('back_left', 'left', 'front_left', 'front_right', 'right', 'back_right'))
# The pinned converter stores E=R1 inv(R2) cTg gTl R3 R1. Native optical
# camera coordinates are R2 R1 E x, not E x. See docs/URBANING_RGB_PILOT.md.
R2_R1 = np.array([[0., 1., 0., 0.], [0., 0., -1., 0.],
                  [1., 0., 0., 0.], [0., 0., 0., 1.]])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    os.replace(temp, path)


def select_frames(frames, per_recording):
    """Predeclared uniform sampling by native frame key, without GT/scores."""
    from phdsim.learning.urbaning import recording_group
    groups = {}
    for frame in frames:
        groups.setdefault(recording_group(frame['sequence']), []).append(frame)
    result = []
    for group in sorted(groups):
        rows = sorted(groups[group], key=lambda f: f['key'])
        count = min(per_recording, len(rows))
        indices = np.linspace(0, len(rows) - 1, count, dtype=int)
        result.extend(rows[i] for i in indices)
    return sorted(result, key=lambda f: f['key'])


def camera_fields(path):
    """Compose only camera scalars; do not construct YAML's embedded label tags."""
    node = yaml.compose(Path(path).read_text())
    if not isinstance(node, yaml.MappingNode):
        raise ValueError('Expected converted YAML mapping')
    fields = {k.value: v for k, v in node.value}
    def numbers(n):
        if isinstance(n, yaml.SequenceNode):
            return [numbers(v) for v in n.value]
        if isinstance(n, yaml.ScalarNode):
            return float(n.value)
        raise ValueError('Only numeric camera calibration fields are accepted')
    cameras = []
    for i in range(6):
        entry = fields.get('camera' + str(i))
        if not isinstance(entry, yaml.MappingNode):
            raise ValueError('Missing Car1 camera calibration')
        values = {k.value: v for k, v in entry.value}
        e, k = (np.asarray(numbers(values[n])) for n in ('extrinsic', 'intrinsic'))
        if (e.shape != (4, 4) or k.shape != (3, 3) or not np.isfinite(e).all()
                or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0
                or not np.allclose(e[3], [0, 0, 0, 1])):
            raise ValueError('Invalid converted camera calibration')
        cameras.append((R2_R1 @ e, k))
    return cameras


def project_crop(box, extrinsic, intrinsic, width, height):
    camera = np.asarray(box) @ extrinsic[:3, :3].T + extrinsic[:3, 3]
    # Reject near-plane straddling boxes instead of inventing extreme crops.
    if np.any(camera[:, 2] <= .1):
        return None
    p = camera @ intrinsic.T
    p = p[:, :2] / p[:, 2:3]
    lo, hi = p.min(axis=0), p.max(axis=0)
    unclipped = np.maximum(hi-lo, 0).prod()
    lo = np.maximum(lo, [0, 0]); hi = np.minimum(hi, [width, height])
    size = hi-lo
    if unclipped <= 0 or np.any(size < 12):
        return None
    coverage = float(size.prod()/unclipped)
    if coverage < .5:
        return None
    area = float(size.prod()/(width*height))
    padding = .1 * size
    a = np.floor(np.maximum(lo-padding, [0, 0])).astype(int)
    b = np.ceil(np.minimum(hi+padding, [width, height])).astype(int)
    return tuple(np.r_[a, b]), area, coverage


def lidar_features(boxes, scores, selected):
    center = boxes.mean(axis=1)
    edges = np.stack([np.linalg.norm(boxes[:, j]-boxes[:, 0], axis=1)
                      for j in (1, 3, 4)], axis=1)
    confidence = np.clip(scores[:, 0], 1e-5, 1-1e-5)
    geometry = np.c_[np.log(confidence/(1-confidence)), center/100, edges/10,
                     np.linalg.norm(center[:, :2], axis=1)/100]
    projection = np.zeros((len(boxes), 9))
    for i, crop in enumerate(selected):
        if crop is not None:
            camera, _, area, coverage = crop
            projection[i, :3] = [1, area, coverage]
            projection[i, 3+camera] = 1
    return np.c_[geometry, projection]


def training_labels(boxes, scores, statistics):
    """Map original-score .5 greedy TP flags back to proposal indices."""
    target = np.full(len(boxes), np.nan)
    keep = _radius_mask(boxes)
    for class_id, name in enumerate(CLASSES, 1):
        indices = np.flatnonzero(keep & (scores[:, 1] == class_id))
        indices = indices[np.argsort(-scores[indices, 0])]
        row = statistics[name][.5]
        if not np.array_equal(scores[indices, 0], row['score']):
            raise ValueError('Original-score target alignment differs')
        target[indices] = row['tp']
    return target


class Encoder:
    """Frozen ImageNet MobileNetV3-small; only the later NumPy head is fitted."""
    def __init__(self, weights_dir, threads):
        import torch
        import torchvision
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
        if torch.__version__ != '2.6.0+cpu' or torchvision.__version__ != '0.21.0+cpu':
            raise RuntimeError('Use the pinned CPU torch2.6 / torchvision0.21 runtime')
        torch.set_num_threads(threads)
        torch.hub.set_dir(str(weights_dir))
        weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
        self.model = mobilenet_v3_small(weights=weights, progress=True).eval()
        self.model.requires_grad_(False)
        self.torch = torch
        self.weights_file = Path(weights_dir)/'checkpoints'/Path(weights.url).name
        if sha(self.weights_file.read_bytes()) != WEIGHTS_SHA:
            raise ValueError('Pretrained weights hash mismatch')
        self.identity = {'encoder': 'MobileNetV3-small IMAGENET1K_V1; frozen features + global average pool',
                         'weights_url': weights.url, 'weights_sha256': sha(self.weights_file.read_bytes()),
                         'torch': torch.__version__, 'torchvision': torchvision.__version__,
                         'input': 'RGB square-resized224, ImageNet mean/std, no augmentation'}

    def __call__(self, crops):
        import cv2
        result = []
        with self.torch.inference_mode():
            for start in range(0, len(crops), 64):
                batch = np.stack([cv2.resize(c, (224, 224)).transpose(2, 0, 1)
                                  for c in crops[start:start+64]]).astype(np.float32)/255
                batch = (batch-np.array([.485, .456, .406], dtype=np.float32)[None, :, None, None])
                batch /= np.array([.229, .224, .225], dtype=np.float32)[None, :, None, None]
                x = self.torch.from_numpy(batch)
                x = self.model.avgpool(self.model.features(x)).flatten(1)
                result.append(x.cpu().numpy())
        return np.concatenate(result) if result else np.empty((0, 576), dtype=np.float32)


def extract_frame(record, output, encoder, qa=False):
    """This function receives predictions/calibration/images only; no GT."""
    import cv2
    boxes, scores = record['boxes'], record['scores']
    yaml_path = Path(record['yaml'])
    cameras = camera_fields(yaml_path)
    paths = [yaml_path.with_name(yaml_path.stem+'_camera'+str(i)+'.png') for i in range(6)]
    sources = {str(p): sha(p.read_bytes()) for p in paths}
    identity = {'schema': SCHEMA, 'key': record['key'], 'prediction_sha256': record['prediction_sha256'],
                'yaml_sha256': sha(yaml_path.read_bytes()), 'images': sources, 'encoder': encoder.identity,
                'implementation_sha256': sha(Path(__file__).read_bytes())}
    cache_path = output/'features'/(record['key'].replace(':', '_')+'.npz')
    meta_path = cache_path.with_suffix('.json')
    if cache_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta['identity'] != identity or meta['cache_sha256'] != sha(cache_path.read_bytes()):
            raise ValueError('RGB cache provenance changed; use a new output directory')
        with np.load(cache_path, allow_pickle=False) as z:
            return {n: z[n] for n in ('lidar', 'visual', 'visible', 'camera', 'time_offsets_ms')}
    images = [cv2.imread(str(p), cv2.IMREAD_COLOR) for p in paths]
    if any(image is None for image in images):
        raise ValueError('Converted Car1 RGB image is unreadable')
    selected = []
    for box in boxes:
        candidates = []
        for i, ((e, k), image) in enumerate(zip(cameras, images)):
            projection = project_crop(box, e, k, image.shape[1], image.shape[0])
            if projection is not None:
                crop, area, coverage = projection
                candidates.append((i, crop, area, coverage))
        selected.append(max(candidates, key=lambda c: (c[2]*c[3], -c[0])) if candidates else None)
    indices = [i for i, crop in enumerate(selected) if crop is not None]
    crops = []
    for i in indices:
        cam, (x1, y1, x2, y2), _, _ = selected[i]
        crops.append(cv2.cvtColor(images[cam][y1:y2, x1:x2], cv2.COLOR_BGR2RGB))
    visual = np.zeros((len(boxes), 576), dtype=np.float32)
    if crops:
        visual[indices] = encoder(crops)
    visible = np.array([s is not None for s in selected])
    camera = np.array([-1 if s is None else s[0] for s in selected])
    native = record['native_association']
    offsets = np.array([int(Path(native['members'][name]).stem)-native['timestamp_ns']/1e6
                        for name in CAMERAS])
    result = {'lidar': lidar_features(boxes, scores, selected), 'visual': visual,
              'visible': visible, 'camera': camera, 'time_offsets_ms': offsets}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp = cache_path.with_suffix('.tmp.npz')
    np.savez_compressed(temp, **result)
    os.replace(temp, cache_path)
    write_json(meta_path, {'identity': identity, 'cache_sha256': sha(cache_path.read_bytes()),
                          'proposals': len(boxes), 'visible': int(visible.sum())})
    if qa:
        qa_dir = output/'projection-qa'; qa_dir.mkdir(exist_ok=True)
        prefix = record['key'].replace(':', '_')
        for ci, image in enumerate(images):
            canvas = image.copy()
            for i in indices:
                cam, rect, _, _ = selected[i]
                if cam == ci:
                    x1, y1, x2, y2 = rect
                    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 255), 2)
                    cv2.putText(canvas, str(i)+':c'+str(int(scores[i, 1])), (x1, max(16, y1)),
                                cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1)
            cv2.imwrite(str(qa_dir/(prefix+'_camera'+str(ci)+'.jpg')), canvas)
        for j, crop in enumerate(crops[:12]):
            cv2.imwrite(str(qa_dir/(prefix+'_crop'+str(j)+'.jpg')), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    return result


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x, -35, 35)))


def fit_head(x, labels, classes, raw_scores, l2=.1):
    """Fixed residual logistic objective; normalization and fit on train only."""
    mean, scale = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-6)
    design = np.c_[np.ones(len(x)), (x-mean)/scale]
    raw = np.clip(raw_scores, 1e-5, 1-1e-5)
    offset = np.log(raw/(1-raw))
    models = {}
    for c in range(1, 5):
        keep = (classes == c) & np.isfinite(labels)
        target = labels[keep]
        support = {'positive': int((target == 1).sum()), 'negative': int((target == 0).sum())}
        if min(support.values()) < 5:
            models[str(c)] = {'fallback': 'original_score; fewer than5 train positives or negatives', **support}
            continue
        a = design[keep]; o = offset[keep]; w = np.zeros(design.shape[1])
        penalty = np.r_[.01, np.full(x.shape[1], l2)]
        def loss(v):
            z = o+a@v
            return np.mean(np.logaddexp(0, z)-target*z)+.5*np.dot(penalty*v, v)
        for _ in range(40):
            p = sigmoid(o+a@w)
            gradient = a.T@(p-target)/len(a)+penalty*w
            hessian = (a.T*(p*(1-p)))@a/len(a)+np.diag(penalty)
            step = np.linalg.solve(hessian, gradient)
            old = loss(w); rate = 1.
            while rate > 1e-6 and loss(w-rate*step) > old:
                rate *= .5
            w -= rate*step
            if np.max(np.abs(rate*step)) < 1e-7:
                break
        models[str(c)] = {'coefficients': w.tolist(), **support}
    return {'mean': mean.tolist(), 'scale': scale.tolist(), 'classes': models,
            'l2': l2, 'intercept_l2': .01, 'objective': 'mean BCE + ridge; original logit offset',
            'target': 'offline original-score greedy same-class BEV TP at IoU0.5'}


def predict_head(model, x, classes, raw_scores):
    design = np.c_[np.ones(len(x)), (x-np.asarray(model['mean']))/np.asarray(model['scale'])]
    raw = np.clip(raw_scores, 1e-5, 1-1e-5)
    result = np.asarray(raw_scores, dtype=np.float64).copy()
    for c in range(1, 5):
        row = model['classes'][str(c)]
        if 'coefficients' in row:
            selected = classes == c
            result[selected] = sigmoid(np.log(raw[selected]/(1-raw[selected]))+
                                       design[selected]@np.asarray(row['coefficients']))
    return result


def pca_fit(visual, visible, dimensions=16):
    valid = visual[visible].astype(np.float64)
    if len(valid) < 2:
        raise ValueError('Too few visible RGB proposals to fit the pilot')
    mean = valid.mean(axis=0)
    _, _, components = np.linalg.svd(valid-mean, full_matrices=False)
    return {'mean': mean.tolist(), 'components': components[:min(dimensions, len(valid)-1)].tolist()}


def pca_apply(model, visual, visible):
    result = (visual-np.asarray(model['mean']))@np.asarray(model['components']).T
    result[~visible] = 0
    return result


def shuffled_visual(visual, visible, classes, seed=0):
    """GT-free diagnostic, preserving class and unavailable-image mask."""
    result = visual.copy(); rng = np.random.default_rng(seed)
    for c in range(1, 5):
        indices = np.flatnonzero(visible & (classes == c))
        result[indices] = visual[rng.permutation(indices)]
    return result


def read_inputs(base, output, train_per_recording, validation_per_recording):
    packet = base.parent/'inputs'/'urbaning-gap-acquisition-inputs-001.zip'
    if sha(packet.read_bytes()) != PACKET_SHA:
        raise ValueError('Original portable input packet hash differs')
    with zipfile.ZipFile(packet) as z:
        ap = z.read('ap-export.zip')
    if sha(ap) != AP_SHA:
        raise ValueError('AP export hash differs')
    ap_path = output/'ap-export.zip'; ap_path.write_bytes(ap)
    splits, manifest = load_archive(ap_path)
    records = {}; provenance = {}
    for split, count in (('train', train_per_recording), ('validation', validation_per_recording)):
        chosen = select_frames(splits[split], count)
        sources = manifest['splits'][split]['provenance']['inputs']
        by_sequence = {}
        for source in sources:
            directory = Path(source['directory'])
            if (sha((directory/'run.json').read_bytes()) != source['run_sha256']
                    or sha((directory/'frames.jsonl').read_bytes()) != source['trace_sha256']):
                raise ValueError('Original run provenance changed')
            by_sequence[source['sequence']] = (source, {r['frame_key']: r for r in
                map(json.loads, (directory/'frames.jsonl').read_text().splitlines())})
        records[split] = []
        for frame in chosen:
            binding = manifest['splits'][split]['frame_bindings'][frame['key']]
            source, trace = by_sequence[frame['sequence']]
            row = trace[frame['key']]
            if row['native_association'] != frame['native_association']:
                raise ValueError('Native association differs')
            pred = Path(source['directory'])/row['predictions']
            if row['predictions'] != binding['prediction_path'] or sha(pred.read_bytes()) != binding['prediction_sha256']:
                raise ValueError('Original predictions changed')
            with np.load(pred, allow_pickle=False) as z:
                boxes, scores = z['ego_boxes'], z['ego_scores']
                gt_boxes, gt_labels = z['gt_boxes'], z['gt_labels']
            if sha(gt_boxes.tobytes()+gt_labels.tobytes()) != binding['gt_sha256']:
                raise ValueError('GT binding differs')
            yaml_source = row['source_files']['100000']['yaml']
            yaml_path = Path(yaml_source['path'])
            if sha(yaml_path.read_bytes()) != yaml_source['sha256']:
                raise ValueError('Converted source YAML changed')
            conversion = json.loads((yaml_path.parents[2]/'phdsim-conversion.json').read_text())
            if (conversion['converter_commit'] != UPSTREAM or conversion['sequence'] != frame['sequence']
                    or conversion['sync_by_frame'][row['source_frame_id']] != frame['native_association']):
                raise ValueError('Pinned converter/native image binding differs')
            camera_fields(yaml_path)
            for i, name in enumerate(CAMERAS):
                if not frame['native_association']['members'].get(name):
                    raise ValueError('Incomplete original Car1 RGB association')
                if not yaml_path.with_name(yaml_path.stem+'_camera'+str(i)+'.png').is_file():
                    raise FileNotFoundError('Missing converted RGB; do not start detector/conversion again: '+str(yaml_path))
            records[split].append({'key': frame['key'], 'sequence': frame['sequence'],
                'prediction_sha256': binding['prediction_sha256'], 'native_association': frame['native_association'],
                'yaml': str(yaml_path), 'boxes': boxes, 'scores': scores, 'gt_boxes': gt_boxes,
                'gt_labels': gt_labels, 'baseline_statistics': frame['statistics']['ego']})
        provenance[split] = {'frames': len(chosen), 'keys': [f['key'] for f in chosen],
            'available_frames_before_sampling': len(splits[split]), 'source_runs': sources}
    return records, provenance


def prepare_matching(record):
    """Offline reusable IoU matrices; GT never reaches the RGB/head inputs."""
    boxes, scores = record['boxes'], record['scores']
    truth, labels = record['gt_boxes'], record['gt_labels']
    validate_arrays(boxes, scores[:, 1], scores[:, 0])
    validate_arrays(truth, labels)
    pred_keep, gt_keep = _radius_mask(boxes), _radius_mask(truth)
    result = {}
    for c, name in enumerate(CLASSES, 1):
        indices = np.flatnonzero(pred_keep & (scores[:, 1] == c))
        a = [_polygon(b) for b in boxes[indices]]
        b = [_polygon(t) for t in truth[gt_keep & (labels == c)]]
        overlap = np.asarray([[polygon_iou(p, t) for t in b] for p in a], dtype=np.float32).reshape(len(a), len(b))
        result[name] = (indices, overlap)
    return result


def rematch(prepared, confidence):
    result = empty_statistics()
    for name in CLASSES:
        indices, overlap = prepared[name]
        order = np.argsort(-confidence[indices])
        scores = confidence[indices][order].tolist()
        for threshold in IOU_THRESHOLDS:
            remaining = list(range(overlap.shape[1])); tp = []
            for row in overlap[order]:
                best = int(np.argmax(row[remaining])) if remaining else None
                matched = best is not None and row[remaining[best]] >= threshold
                tp.append(int(matched))
                if matched:
                    remaining.pop(best)
            result[name][threshold] = {'gt': overlap.shape[1], 'tp': tp,
                                      'fp': [1-v for v in tp], 'score': scores}
    return result


def evaluate(records, confidence, prepared=None):
    statistics = []
    if prepared is None:
        prepared = [prepare_matching(r) for r in records]
    for frame, new_confidence in zip(prepared, confidence):
        # Recompute matching: fixed TP labels cannot be reused after reranking.
        statistics.append(rematch(frame, new_confidence))
    total = aggregate_statistics(statistics)
    return {'global_confidence_sort': summarize_cached(total, True),
            'upstream_default_frame_order': summarize_cached(total, False)}


def print_table(metrics):
    print('| Variant, same sampled Car1 frames | BEV mAP@0.5 (%) | Delta vs original (pp) |', flush=True)
    print('|---|---:|---:|', flush=True)
    baseline = metrics['original_lidar']['global_confidence_sort']['macro_ap']['0.5']
    for name, value in metrics.items():
        ap = value['global_confidence_sort']['macro_ap']['0.5']
        a = 'undefined: missing GT class' if ap is None else f'{ap*100:.4f}'
        delta = 'undefined' if ap is None or baseline is None else f'{(ap-baseline)*100:+.4f}'
        print(f'| {name} | {a} | {delta} |', flush=True)


def run(base, output, train_count=60, validation_count=60, encoder=None):
    if np.__version__ != '1.26.4':
        raise RuntimeError('NumPy1.26.4 is required for historical AP tie parity')
    output.mkdir(parents=True, exist_ok=True)
    configuration = {'schema': SCHEMA, 'base': str(base), 'train_per_recording': train_count,
                     'validation_per_recording': validation_count, 'ap_sha256': AP_SHA,
                     'implementation_sha256': sha(Path(__file__).read_bytes())}
    state = output/'configuration.json'
    if state.exists() and json.loads(state.read_text()) != configuration:
        raise ValueError('Resume configuration changed; use a new output directory')
    write_json(state, configuration)
    if (output/'completed.json').exists():
        receipt = json.loads((output/'completed.json').read_text())
        if sha((output/'urbaning-rgb-pilot.zip').read_bytes()) != receipt['sha256']:
            raise ValueError('Completed output changed')
        print('REUSE completed:', output/'urbaning-rgb-pilot.zip', flush=True)
        return
    print('PREFLIGHT original predictions, converted Car1 RGB/calibration, recording split; no detector', flush=True)
    records, provenance = read_inputs(base, output, train_count, validation_count)
    write_json(output/'inputs.json', provenance)
    print('SAMPLED', {s: len(r) for s, r in records.items()}, flush=True)
    # Check baseline parity on precisely the sampled validation frames before RGB work.
    prepared = []
    for i, record in enumerate(records['validation']):
        prepared.append(prepare_matching(record))
        if (i+1) % 10 == 0:
            print('CACHE validation BEV IoU', i+1, '/', len(records['validation']), flush=True)
    original = evaluate(records['validation'], [r['scores'][:, 0] for r in records['validation']], prepared)
    reference = summarize_cached(aggregate_statistics([r['baseline_statistics'] for r in records['validation']]))
    for name in CLASSES:
        if original['global_confidence_sort']['classes'][name] != reference['classes'][name]:
            raise ValueError('Raw-box baseline fails historical AP parity')
    write_json(output/'baseline.json', original)
    if encoder is None:
        encoder = Encoder(output/'weights', int(os.environ.get('SLURM_CPUS_PER_TASK', '4')))
    extracted = {}; started = time.monotonic(); completed = 0
    total = sum(map(len, records.values()))
    for split in ('train', 'validation'):
        extracted[split] = []
        for i, record in enumerate(records[split]):
            # Offline GT deliberately omitted from the feature-extractor input.
            runtime_record = {k: record[k] for k in ('key', 'prediction_sha256', 'native_association', 'yaml', 'boxes', 'scores')}
            value = extract_frame(runtime_record, output, encoder, qa=i == 0)
            extracted[split].append(value); completed += 1
            if completed % 5 == 0 or completed == 1:
                seconds = time.monotonic()-started
                print(f'RGB {completed}/{total}: {record["key"]}; crops={int(value["visible"].sum())}/{len(value["visible"])}; '
                      f'mean={seconds/completed:.2f}s/frame; estimated remaining={seconds/completed*(total-completed)/60:.1f}min', flush=True)
    def joined(split, field):
        return np.concatenate([r[field] for r in extracted[split]])
    tr_x, va_x = (joined(s, 'lidar') for s in ('train', 'validation'))
    tr_v, va_v = (joined(s, 'visual') for s in ('train', 'validation'))
    tr_mask, va_mask = (joined(s, 'visible') for s in ('train', 'validation'))
    tr_score = np.concatenate([r['scores'] for r in records['train']])
    va_score = np.concatenate([r['scores'] for r in records['validation']])
    targets = np.concatenate([training_labels(r['boxes'], r['scores'], r['baseline_statistics']) for r in records['train']])
    print('FIT fixed residual logistic heads; train-only PCA16/normalization; no validation search', flush=True)
    pca = pca_fit(tr_v, tr_mask)
    tr_rgb = pca_apply(pca, tr_v, tr_mask); va_rgb = pca_apply(pca, va_v, va_mask)
    lidar = fit_head(tr_x, targets, tr_score[:, 1], tr_score[:, 0])
    fusion = fit_head(np.c_[tr_x, tr_rgb], targets, tr_score[:, 1], tr_score[:, 0])
    models = {'schema': SCHEMA, 'pca': pca, 'lidar_head': lidar, 'fusion_head': fusion,
              'encoder': encoder.identity, 'fit_split': 'train only; no crossing3 access'}
    write_json(output/'model.json', models)
    predictions = {
        'lidar_recalibrated': predict_head(lidar, va_x, va_score[:, 1], va_score[:, 0]),
        'lidar_rgb': predict_head(fusion, np.c_[va_x, va_rgb], va_score[:, 1], va_score[:, 0]),
        'lidar_rgb_shuffled_diagnostic': predict_head(fusion, np.c_[va_x, shuffled_visual(va_rgb, va_mask, va_score[:, 1])],
                                                    va_score[:, 1], va_score[:, 0])}
    boundaries = np.cumsum([len(r['boxes']) for r in records['validation']])[:-1]
    metrics = {'original_lidar': original}
    for name, scores in predictions.items():
        print('EVALUATE', name, 'fresh greedy BEV matching', flush=True)
        metrics[name] = evaluate(records['validation'], np.split(scores, boundaries), prepared)
    report = {'schema': SCHEMA, 'status': 'completed', 'scope': 'development pilot; existing proposals only, zero peer requests',
              'frames': {s: len(r) for s, r in records.items()}, 'metrics': metrics,
              'visibility': {s: {'proposals': int(sum(len(r['visible']) for r in v)),
                                 'with_usable_rgb': int(sum(r['visible'].sum() for r in v)),
                                 'native_camera_offset_ms_min': float(min(r['time_offsets_ms'].min() for r in v)),
                                 'native_camera_offset_ms_max': float(max(r['time_offsets_ms'].max() for r in v))}
                             for s, v in extracted.items()},
              'elapsed_rgb_and_fit_seconds': time.monotonic()-started, 'encoder': encoder.identity,
              'limitations': ['No new 3D boxes, class or box-coordinate changes; recall ceiling remains fixed.',
                  'Offline native camera associations may occur after anchor time; no online causal claim.',
                  'No acquisition policy fitting, no crossing3, no blind generalization or full BEV fusion claim.',
                  'LiDAR-only control also receives projection availability/geometry; only RGB content differs.',
                  'Fixed sampled frames: do not compare these AP values directly with historical full200/full1400.',
                  'Frozen ImageNet features; a negative pilot does not rule out trainable feature-level fusion.',
                  'Shuffle is one fixed-seed diagnostic, not a significance test.'],
              'protocol': {'primary': 'four-class BEV mAP@0.5, global confidence sort; fresh matching after rescoring',
                           'secondary': 'per-class AP@0.3/0.5/0.7, frame-order AP',
                           'train_target': 'binary original-score greedy BEV TP@0.5; surrogate, not AP loss',
                           'selection': 'none: fixed PCA16, ridge0.1, min5 examples per target value, shuffle seed0'}}
    write_json(output/'report.json', report)
    print_table(metrics)
    baseline = metrics['original_lidar']['global_confidence_sort']['macro_ap']['0.5']
    lines = ['# Car1 LiDAR + RGB: CPU late-fusion pilot', '',
             f'Train: {len(records["train"])} frames; validation: {len(records["validation"])} frames. Zero partner queries.', '',
             '| Variant | BEV mAP@0.5 (%) | Change vs original (pp) |', '|---|---:|---:|']
    for name, m in metrics.items():
        ap = m['global_confidence_sort']['macro_ap']['0.5']
        lines.append(f'| {name} | '+('undefined' if ap is None else f'{100*ap:.4f}')+' | '+
                     ('undefined' if ap is None or baseline is None else f'{100*(ap-baseline):+.4f}')+' |')
    lines += ['', '## Per-class AP@0.5 (%)', '', '| Variant | '+' | '.join(CLASSES)+' |', '|---|'+'---:|'*4]
    for name, m in metrics.items():
        values = [m['global_confidence_sort']['classes'][c]['ap']['0.5'] for c in CLASSES]
        lines.append('| '+name+' | '+' | '.join('undefined' if x is None else f'{100*x:.4f}' for x in values)+' |')
    lines += ['', *report['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    qa_files = sorted((output/'projection-qa').glob('*.jpg'))
    gallery = '<!doctype html><meta charset="utf-8"><title>Car1 RGB pilot</title><style>body{font:16px sans-serif;max-width:1100px;margin:auto}img{max-width:100%}pre{white-space:pre-wrap}</style>'
    gallery += '<h1>Car1 RGB projection QA</h1><p>Yellow rectangles are selected LiDAR proposal crops; no GT is used for choosing views.</p>'
    gallery += '<pre>'+html.escape('\n'.join(lines))+'</pre>'
    gallery += ''.join('<h3>'+html.escape(p.name)+'</h3><img src="projection-qa/'+p.name+'">' for p in qa_files)
    (output/'index.html').write_text(gallery)
    bundle = output/'urbaning-rgb-pilot.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('report.json', 'model.json', 'inputs.json', 'configuration.json', 'summary.md', 'index.html', 'baseline.json'):
            z.write(output/name, name)
        for p in qa_files:
            z.write(p, p.relative_to(output))
        # Feature cache and ImageNet weights stay on Ares; keep downloadable results small.
    receipt = {'sha256': sha(bundle.read_bytes()), 'bytes': bundle.stat().st_size}
    write_json(output/'completed.json', receipt)
    print('SHA256', receipt['sha256'], 'bytes', receipt['bytes'], flush=True)
    print('DONE:', bundle, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--train-per-recording', type=int, default=60)
    parser.add_argument('--validation-per-recording', type=int, default=60)
    args = parser.parse_args(argv)
    if min(args.train_per_recording, args.validation_per_recording) < 1:
        parser.error('Frame counts must be positive')
    run(args.base.resolve(), args.output_dir.resolve(), args.train_per_recording, args.validation_per_recording)


if __name__ == '__main__':
    main()
