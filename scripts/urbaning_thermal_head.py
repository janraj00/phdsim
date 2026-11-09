"""One-epoch thermal ROI-head pilot with a fixed 4,000-proposal frozen RPN."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

TRAIN_SEQUENCES = ('20241126_0001_crossing2_00', '20241126_0017_crossing1_00')
VALIDATION_SEQUENCE = '20241126_0004_crossing2_00'
CLASS_NAMES = ('Vehicle', 'Heavy_Vehicle', '2Wheeler', 'Pedestrian')
RPN_BUDGET = 4000
EPOCHS = 1
LEARNING_RATE = 1e-4
SCHEMA = 'phdsim-urbaning-thermal-roi-head-pilot-v1'
VARIANTS = ('lidar', 'thermal_initialized', 'thermal_finetuned',
            'initialized_additive_raw', 'initialized_additive_lidar_first',
            'finetuned_additive_raw', 'finetuned_additive_lidar_first')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


def save_npz(path, **arrays):
    temp = Path(path).with_suffix('.partial')
    with temp.open('wb') as f:
        import numpy as np
        np.savez_compressed(f, **arrays)
    os.replace(temp, path)


def load_sequence(root, sequence, cache):
    from phdsim.datasets.urbaning.archive import sequence_directory
    if sequence not in cache:
        directory = sequence_directory(root, sequence)
        calibration = json.loads((directory/'calibration.json').read_text())
        streams = sorted(k for k in calibration if k.endswith('_thermal_camera'))
        if not streams:
            raise ValueError(f'No calibrated thermal cameras in {sequence}')
        cache[sequence] = {'directory': directory, 'calibration': calibration,
                           'streams': streams, 'vehicle_lidar_to_global': None}
    return cache[sequence]


def transforms_for_record(seq, members):
    import numpy as np
    state_name = members.get('vehicle1_state')
    if not state_name:
        raise ValueError('Association lacks vehicle1_state')
    state = json.loads((seq['directory']/'vehicle1_state'/state_name).read_text())
    gTv = np.asarray(state['gTv'], dtype=np.float64)
    vTl = np.asarray(seq['calibration']['vehicle1_middle_lidar']['extrinsics']['vTl'], dtype=np.float64)
    if gTv.shape != (4, 4) or vTl.shape != (4, 4):
        raise ValueError('Invalid vehicle/LiDAR transform')
    gTl = gTv @ vTl
    return {stream: np.asarray(seq['calibration'][stream]['extrinsics']['cTg'], dtype=np.float64) @ gTl
            for stream in seq['streams'] if stream in members and members[stream]}


def camera_model(seq, stream, filename, cache):
    import cv2
    import numpy as np
    from phdsim.datasets.urbaning.geometry import rectified_image
    key = (seq['directory'].name, stream)
    if key not in cache:
        path = seq['directory']/stream/filename
        raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise ValueError('Unreadable thermal image: '+str(path))
        image, intrinsic = rectified_image(raw, seq['calibration'][stream]['intrinsics'])
        cache[key] = (intrinsic, image.shape[:2])
    return cache[key]


def read_thermal(seq, stream, filename, model_cache):
    import cv2
    import numpy as np
    from phdsim.datasets.urbaning.geometry import rectified_image
    intrinsic, shape = camera_model(seq, stream, filename, model_cache)
    path = seq['directory']/stream/filename
    raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if raw is None:
        raise ValueError('Unreadable thermal image: '+str(path))
    image, actual_k = rectified_image(raw, seq['calibration'][stream]['intrinsics'])
    if image.shape != shape or not np.array_equal(actual_k, intrinsic):
        raise ValueError('Thermal rectification changed within a stream')
    return np.repeat(image[:, :, None], 3, axis=2), intrinsic


def rpn_limits(model, budget=RPN_BUDGET):
    rpn = model.proposal_generator
    if (not isinstance(getattr(rpn, 'pre_nms_topk', None), dict) or
            not isinstance(getattr(rpn, 'post_nms_topk', None), dict) or
            False not in rpn.pre_nms_topk or False not in rpn.post_nms_topk):
        raise TypeError('Pinned RPN lacks the expected Detectron2 test proposal limits')
    old = {'pre': int(rpn.pre_nms_topk[False]), 'post': int(rpn.post_nms_topk[False])}
    rpn.pre_nms_topk[False] = max(old['pre'], budget)
    rpn.post_nms_topk[False] = budget
    return old


def snapshot_hash(model, frozen_only=False):
    h = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        if frozen_only and key.startswith(('roi_heads.box_head.', 'roi_heads.box_predictor.', 'roi_heads.cube_head.')):
            continue
        h.update(key.encode()); h.update(value.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def optimizer_for(detector):
    import torch
    return torch.optim.SGD([p for p in detector.model.parameters() if p.requires_grad],
                           lr=LEARNING_RATE, momentum=.9, weight_decay=1e-4)


def update(detector, inputs, optimizer, required_losses=()):
    import torch
    optimizer.zero_grad(set_to_none=True)
    losses = detector.losses(inputs)
    missing = sorted(set(required_losses)-set(losses))
    if missing:
        raise ValueError(f'Missing required native losses {missing}; returned {sorted(losses)}')
    total = sum(losses.values())
    if not total.requires_grad:
        raise ValueError('Native thermal loss has no training graph')
    total.backward()
    params = [p for p in detector.model.parameters() if p.requires_grad]
    if not any(p.grad is not None and bool((p.grad != 0).any()) for p in params):
        raise ValueError('No native ROI-head gradients from thermal input')
    norm = torch.nn.utils.clip_grad_norm_(params, 5., error_if_nonfinite=True)
    optimizer.step()
    return {k: float(v.detach()) for k, v in losses.items()}, float(norm)


def find_data_root(base, explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).resolve())
    else:
        base = Path(base).resolve()
        candidates.extend((base.parent/'data'/'urbaning-v2x', base.parent/'inputs'/'urbaning-v2x',
                           base/'data'/'urbaning-v2x', base/'inputs'/'urbaning-v2x',
                           base.parent.parent/'data'/'urbaning-v2x'))
    required = (*TRAIN_SEQUENCES, VALIDATION_SEQUENCE)
    for root in candidates:
        if all((root/'extracted'/s/'extraction.json').is_file() for s in required):
            return root
    raise FileNotFoundError('Need extracted thermal data for both TRAIN sequences and validation; checked: '
                            + ', '.join(str(p) for p in candidates))


def preflight(train, root, sequence_cache, camera_cache, projected_targets):
    import numpy as np
    rows, items = [], []
    support = np.zeros(4, dtype=np.int64)
    ignored = np.zeros(4, dtype=np.int64)
    offsets = []
    for record in train:
        if record['sequence'] not in TRAIN_SEQUENCES:
            raise ValueError('TRAIN key came from an undeclared sequence: '+record['key'])
        seq = load_sequence(root, record['sequence'], sequence_cache)
        members = record['native_association']['members']
        transforms = transforms_for_record(seq, members)
        if not transforms:
            raise ValueError('No associated thermal cameras: '+record['key'])
        for stream in seq['streams']:
            filename = members.get(stream)
            if not filename:
                continue
            intrinsic, (height, width) = camera_model(seq, stream, filename, camera_cache)
            rows2d = projected_targets(record['gt_boxes'], record['gt_labels'], transforms[stream],
                                       intrinsic, width, height)
            positive_counts = np.zeros(4, dtype=np.int64)
            ignore_counts = np.zeros(4, dtype=np.int64)
            for target in rows2d:
                if target['class'] >= 0:
                    positive_counts[target['class']] += 1
                    support[target['class']] += 1
                else:
                    label = int(record['gt_labels'][target['gt_index']])-1
                    ignore_counts[label] += 1
                    ignored[label] += 1
            offset = int(Path(filename).stem)-record['native_association']['timestamp_ns']/1e6
            offsets.append(offset)
            items.append({'record': record, 'sequence': seq, 'stream': stream,
                          'filename': filename, 'intrinsic': intrinsic, 'E': transforms[stream],
                          'targets': rows2d, 'offset_ms': offset})
            rows.append({'key': record['key'], 'stream': stream, 'offset_ms': offset,
                         'positive_by_class': positive_counts.tolist(),
                         'ignore_by_class': ignore_counts.tolist()})
    if np.any(support < 20):
        raise ValueError('Insufficient projected TRAIN support per class: '+str(support.tolist()))
    return items, {'cameras': rows, 'class_support': support.tolist(),
                   'near_plane_and_small_ignore_counts': ignored.tolist(),
                   'mean_abs_capture_offset_ms': float(np.mean(np.abs(offsets)))}


def native_gate(detector, items, output):
    import torch
    from detectron2.utils.events import EventStorage
    from phdsim.perception.urbaning.rgb3d_finetune import NoUsableBackgroundProposals
    original = detector.trainable_state()
    frozen = snapshot_hash(detector.model, True)
    rng = torch.get_rng_state()
    example = None
    events = []
    for item in items:
        if not any(t['class'] >= 0 for t in item['targets']):
            continue
        image, intrinsic = read_thermal(item['sequence'], item['stream'], item['filename'], {})
        inputs = detector.training_input(image, intrinsic, item['targets'])
        optimizer = optimizer_for(detector)
        with EventStorage():
            try:
                losses, norm = update(detector, inputs, optimizer,
                                      ('BoxHead/loss_cls', 'Cube/loss_z'))
            except NoUsableBackgroundProposals:
                detector.load_trainable(original)
                torch.set_rng_state(rng)
                continue
        if losses['Cube/loss_z'] <= 0:
            detector.load_trainable(original)
            torch.set_rng_state(rng)
            continue
        example = (image, intrinsic, inputs, losses, norm, item)
        break
    if example is None:
        raise ValueError('Thermal native gate found no positive ROI/depth update')
    image, intrinsic, inputs, losses, norm, item = example
    print('THERMAL NATIVE GATE positive', item['record']['key'], item['stream'],
          'targets', sum(t['class'] >= 0 for t in item['targets']), flush=True)
    print('THERMAL NATIVE GATE positive losses', json.dumps(losses, sort_keys=True), flush=True)
    events.append({'kind': 'positive', 'key': item['record']['key'], 'stream': item['stream'],
                   'losses': losses, 'gradient_norm': norm})
    with EventStorage():
        bg_losses, bg_norm = update(detector, detector.training_input(image, intrinsic, []),
                                    optimizer_for(detector), ('BoxHead/loss_cls',))
    print('THERMAL NATIVE GATE background losses', json.dumps(bg_losses, sort_keys=True), flush=True)
    events.append({'kind': 'empty_labels', 'losses': bg_losses, 'gradient_norm': bg_norm})
    if snapshot_hash(detector.model, True) != frozen:
        raise ValueError('Frozen parameters changed in thermal gate')
    detector.load_trainable(original)
    torch.set_rng_state(rng)
    for key, value in detector.trainable_state().items():
        if not torch.equal(value, original[key]):
            raise ValueError('Thermal gate failed to restore initializer')
    before = detector.predict(image, intrinsic)
    path = output/'models'/'thermal-gate-roundtrip.pt'
    torch.save(original, path)
    detector.load_trainable(torch.load(path, map_location='cpu', weights_only=True))
    after = detector.predict(image, intrinsic)
    for key in before:
        import numpy as np
        np.testing.assert_array_equal(before[key], after[key])
    write_json(output/'native-gate.json', {'passed': True, 'updates_discarded': True,
               'frozen_parameters_unchanged': True,
               'rpn_pre_nms_topk': detector.model.proposal_generator.pre_nms_topk[False],
               'rpn_post_nms_topk': detector.model.proposal_generator.post_nms_topk[False],
               'events': events})
    print('THERMAL NATIVE GATE PASSED: positive/depth + empty/background gradients; save/load parity', flush=True)


def predict_thermal(detector, record, root, sequence_cache, camera_cache, upright_boxes, classwise_nms):
    import numpy as np
    seq = load_sequence(root, record['sequence'], sequence_cache)
    members = record['native_association']['members']
    transforms = transforms_for_record(seq, members)
    boxes, scores = [], []
    associated_streams = [stream for stream in seq['streams'] if members.get(stream)]
    if not associated_streams:
        raise ValueError('No associated thermal cameras for prediction: '+record['key'])
    for stream in associated_streams:
        filename = members.get(stream)
        if not filename:
            continue
        image, intrinsic = read_thermal(seq, stream, filename, camera_cache)
        pred = detector.predict(image, intrinsic)
        boxes.append(upright_boxes(pred['centers'], pred['dimensions'], pred['rotations'], transforms[stream]))
        scores.append(np.c_[pred['scores'], pred['classes']+1])
    if len(boxes) != len(associated_streams):
        raise ValueError('Incomplete thermal prediction set for '+record['key'])
    all_boxes, all_scores = np.concatenate(boxes), np.concatenate(scores)
    keep = classwise_nms(all_boxes, all_scores, .2)
    return all_boxes[keep], all_scores[keep], len(all_boxes)


def statistics_metrics(frame_stats):
    from phdsim.evaluation.urbaning_cached import aggregate_statistics, summarize_cached
    total = aggregate_statistics(frame_stats)
    return {name: summarize_cached(total, order) for name, order in
            (('global_confidence_sort', True), ('upstream_default_frame_order', False))}


def counts_iou05(frame_stats):
    from phdsim.evaluation.urbaning import CLASSES
    from phdsim.evaluation.urbaning_cached import aggregate_statistics
    total = aggregate_statistics(frame_stats)
    return {name: {'tp': int(sum(total[name][.5]['tp'])),
                   'fp': int(sum(total[name][.5]['fp'])), 'gt': int(total[name][.5]['gt'])}
            for name in CLASSES}


def evaluate_split(records, split, stage, detector, root, sequence_cache, camera_cache,
                   output, upright_boxes, classwise_nms, additive_fuse, source_report):
    import numpy as np
    from phdsim.evaluation.urbaning_cached import frame_statistics
    folder = output/f'frames-{split}-{stage}'
    folder.mkdir()
    if stage == 'initialized':
        active_variants = ('lidar', 'thermal_initialized',
                           'initialized_additive_raw', 'initialized_additive_lidar_first')
    elif stage == 'finetuned':
        active_variants = ('lidar', 'thermal_finetuned',
                           'finetuned_additive_raw', 'finetuned_additive_lidar_first')
    else:
        raise ValueError('Unknown thermal evaluation stage: '+stage)
    stats = {v: [] for v in active_variants}
    frame_rows = []
    for index, record in enumerate(records):
        thermal_boxes, thermal_scores, raw_count = predict_thermal(
            detector, record, root, sequence_cache, camera_cache, upright_boxes, classwise_nms)
        outputs = {'lidar': (record['boxes'], record['scores'])}
        thermal_name = 'thermal_'+stage
        outputs[thermal_name] = (thermal_boxes, thermal_scores)
        for prefix in (('initialized',) if stage == 'initialized' else ('finetuned',)):
            for suffix, first in (('raw', False), ('lidar_first', True)):
                b, s, _, _ = additive_fuse(record['boxes'], record['scores'], thermal_boxes,
                                            thermal_scores, lidar_first=first)
                outputs[prefix+'_additive_'+suffix] = (b, s)
        payload = {'gt_boxes': record['gt_boxes'], 'gt_labels': record['gt_labels'],
                   'thermal_raw_count': np.asarray([raw_count], dtype=np.int64)}
        for variant, (boxes, scores) in outputs.items():
            if variant not in stats:
                continue
            payload[variant+'_boxes'], payload[variant+'_scores'] = boxes, scores
            stats[variant].append(frame_statistics(boxes, scores, record['gt_boxes'], record['gt_labels']))
        path = folder/(record['key'].replace(':', '_')+'.npz')
        save_npz(path, **payload)
        frame_rows.append({'key': record['key'], 'sha256': sha(path.read_bytes()),
                           'thermal_raw_boxes': raw_count, 'thermal_nms_boxes': len(thermal_boxes)})
        if (index+1) % 10 == 0:
            print('EVAL', split, stage, index+1, '/', len(records), flush=True)
    metrics = {variant: statistics_metrics(rows) for variant, rows in stats.items()}
    baseline = source_report[split+'_metrics']['lidar']
    if metrics['lidar'] != baseline:
        raise ValueError('Cached LiDAR AP does not reproduce for '+split)
    # Independently replay the written predictions before trusting the summary.
    replay = {variant: [] for variant in stats}
    for row in frame_rows:
        path = folder/(row['key'].replace(':', '_')+'.npz')
        if sha(path.read_bytes()) != row['sha256']:
            raise ValueError('Thermal prediction payload changed')
        with np.load(path, allow_pickle=False) as archive:
            for variant in stats:
                replay[variant].append(frame_statistics(archive[variant+'_boxes'], archive[variant+'_scores'],
                                                        archive['gt_boxes'], archive['gt_labels']))
    replay_metrics = {variant: statistics_metrics(rows) for variant, rows in replay.items()}
    if replay_metrics != metrics:
        raise ValueError('Independent saved prediction AP replay differs')
    counts = {variant: counts_iou05(rows) for variant, rows in stats.items()}
    return {'metrics': metrics, 'counts_at_iou_05': counts, 'frames': frame_rows,
            'source_lidar_ap_reproduced': True, 'saved_prediction_ap_reproduced': True}


def run(args):
    import cv2
    import numpy as np
    import torch
    from detectron2.utils.events import EventStorage
    from phdsim.datasets.urbaning.geometry import rectified_image
    from phdsim.experiments.urbaning_rgb3d_finetune import read_inputs, source_archive, update
    from phdsim.perception.urbaning.rgb3d_additive import additive_fuse
    from phdsim.perception.urbaning.rgb3d_finetune import (
        FineTuneDetector, GROUPS, LEARNING_RATE as _RGB_LR, NoUsableBackgroundProposals,
        projected_targets)
    from phdsim.perception.urbaning.rgb3d_late import (
        OUTDOOR_ASSETS, classwise_nms, upright_boxes)
    from phdsim.evaluation.urbaning_cached import frame_statistics

    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use fresh output; thermal training resume is not implemented')
    output.mkdir(parents=True, exist_ok=True)
    for name in ('models', 'train-loader', 'validation-loader'):
        (output/name).mkdir()
    root = find_data_root(args.base, args.data_root)
    for sequence in (*TRAIN_SEQUENCES, VALIDATION_SEQUENCE):
        if not (root/'extracted'/sequence/'extraction.json').is_file():
            raise FileNotFoundError('Required thermal sequence is not extracted: '+sequence)
    for name, expected in OUTDOOR_ASSETS.items():
        if sha((args.model_dir/name).read_bytes()) != expected:
            raise ValueError('Official outdoor model asset changed: '+name)
    runtime_sha = sha((args.runtime/'ready.json').read_bytes())
    source_zip, source_report, source_sha = source_archive(args.source)
    train_rows, train_provenance = read_inputs(args.base, output/'train-loader', 200, 0)
    train = train_rows['train']
    if len(train) != 400 or any(r['sequence'] not in TRAIN_SEQUENCES for r in train):
        raise ValueError('Expected TRAIN400 from the declared two sequences only')
    for record in train:
        parts = record['key'].split(':')
        if len(parts) != 3 or parts[2] != '100000':
            raise ValueError('Unexpected TRAIN key: '+record['key'])
    sequence_cache, camera_cache = {}, {}
    items, inventory = preflight(train, root, sequence_cache, camera_cache, projected_targets)
    write_json(output/'train-inventory.json', inventory)
    print('THERMAL TRAIN SUPPORT', json.dumps(inventory['class_support']), flush=True)
    if min(inventory['class_support']) < 20:
        raise ValueError('Too little projected thermal TRAIN support')
    detector = FineTuneDetector(args.model_dir, args.threads)
    model = detector.model.eval()
    default_rpn = rpn_limits(model, RPN_BUDGET)
    initial = detector.trainable_state()
    torch.save(initial, output/'models/initialized-heads.pt')
    frozen_sha = snapshot_hash(model, True)
    protocol = {'schema': SCHEMA, 'source_sha256': source_sha, 'runtime_sha256': runtime_sha,
                'official_assets': OUTDOOR_ASSETS, 'train_provenance': train_provenance['train'],
                'train_sequences': list(TRAIN_SEQUENCES), 'validation_sequence': VALIDATION_SEQUENCE,
                'epochs': EPOCHS, 'train_camera_views': len(items), 'seed': 0,
                'optimizer': 'SGD momentum=.9 weight_decay=.0001', 'lr': LEARNING_RATE,
                'warmup_updates': 100, 'gradient_clip_norm': 5., 'roi_samples_per_image': 128,
                'rpn_frozen': True, 'rpn_proposal_limits_test': {'pre_nms_topk': max(default_rpn['pre'], RPN_BUDGET),
                                                                  'post_nms_topk': RPN_BUDGET},
                'initialized_control': 'fixed mean of official fine-class rows into four classes',
                'trainable': ['native box_head', 'native box_predictor', 'native cube_head'],
                'frozen': ['backbone/FPN', 'RPN', 'priors'],
                'supervision': 'projected 3D GT; weak 2D boxes; per-object small/truncated/near-plane ignores',
                'validation': 'load only after final one-epoch state is saved and frozen',
                'selection': 'one fixed TRAIN epoch; no validation tuning; crossing3 excluded',
                'validation_claim': 'development comparison only; not an independent test'}
    write_json(output/'protocol.json', protocol)
    native_gate(detector, items, output)
    frozen_sha = snapshot_hash(model, True)
    optimizer = optimizer_for(detector)
    skipped = 0
    step = 0
    history = []
    with (EventStorage() as storage, (output/'training.jsonl').open('w') as log,
          (output/'skipped-updates.jsonl').open('w') as skiplog):
        order = np.random.default_rng(0).permutation(len(items))
        for position in order:
            item = items[position]
            image, intrinsic = read_thermal(item['sequence'], item['stream'], item['filename'], camera_cache)
            for group in optimizer.param_groups:
                group['lr'] = LEARNING_RATE*min(1., (step+1)/100)
            try:
                losses, norm = update(detector, detector.training_input(image, intrinsic, item['targets']),
                                      optimizer)
            except NoUsableBackgroundProposals as exc:
                skipped += 1
                skiplog.write(json.dumps({'key': item['record']['key'], 'stream': item['stream'],
                                          'reason': str(exc)})+'\n')
                continue
            step += 1
            entry = {'step': step, 'key': item['record']['key'], 'stream': item['stream'],
                     'positive_count': sum(t['class'] >= 0 for t in item['targets']),
                     'losses': losses, 'gradient_norm': norm}
            log.write(json.dumps(entry, allow_nan=False)+'\n')
            storage.step()
            if step % 100 == 0:
                log.flush(); skiplog.flush()
                print('THERMAL TRAIN updates', step, 'loss', sum(losses.values()), flush=True)
    if step < 100:
        raise ValueError('Too few successful thermal ROI updates: '+str(step))
    final_path = output/'models/final-heads.pt'
    final_state = detector.trainable_state()
    torch.save(final_state, final_path)
    if snapshot_hash(model, True) != frozen_sha:
        raise ValueError('Frozen backbone/FPN/RPN changed during thermal training')
    freeze = {'model_sha256': sha(final_path.read_bytes()), 'updates': step, 'skipped_updates': skipped,
              'epochs': EPOCHS, 'validation_loaded': False, 'frozen_state_sha256': frozen_sha,
              'rpn_limits': protocol['rpn_proposal_limits_test']}
    write_json(output/'models/freeze.json', freeze)

    # The only validation sequence is crossing2_00. Load it after final checkpoint/freeze.
    val_rows, val_provenance = read_inputs(args.base, output/'validation-loader', 0, 200)
    validation = val_rows['validation']
    if len(validation) != 200 or any(r['sequence'] != VALIDATION_SEQUENCE for r in validation):
        raise ValueError('Unexpected thermal validation split/sequence')
    trained = torch.load(final_path, map_location='cpu', weights_only=True)
    detector.load_trainable(initial)
    validation_initial = evaluate_split(validation, 'validation', 'initialized', detector, root,
                                        sequence_cache, camera_cache, output, upright_boxes, classwise_nms,
                                        additive_fuse, source_report)
    detector.load_trainable(trained)
    train_final = evaluate_split(train, 'train', 'finetuned', detector, root, sequence_cache,
                                 camera_cache, output, upright_boxes, classwise_nms,
                                 additive_fuse, source_report)
    validation_final = evaluate_split(validation, 'validation', 'finetuned', detector, root,
                                      sequence_cache, camera_cache, output, upright_boxes, classwise_nms,
                                      additive_fuse, source_report)
    if (sha(final_path.read_bytes()) != freeze['model_sha256'] or
            snapshot_hash(model, True) != frozen_sha or
            sha((args.runtime/'ready.json').read_bytes()) != runtime_sha or sha(args.source.read_bytes()) != source_sha):
        raise ValueError('Thermal frozen model/runtime/source changed')
    report = {'schema': SCHEMA, 'protocol': protocol, 'freeze': freeze,
              'splits': {'train_finetuned': train_final,
                         'validation_initialized': validation_initial,
                         'validation_finetuned': validation_final},
              'validation_provenance': val_provenance['validation'],
              'limitations': ['Single fixed epoch and one seed; pilot only',
                  'Thermal detections use grayscale replicated to three channels',
                  'Training labels are projected 3D boxes with occlusion/visibility ambiguity',
                  'Validation crossing2_00 is development data previously inspected, not independent test',
                  'No crossing3, no learned communication/acquisition policy',
                  'LiDAR-first changes ranking and is not a calibrated score']}
    write_json(output/'report.json', report)
    lines = ['# UrbanIng thermal ROI-head pilot', '',
             '| Variant | TRAIN mAP@.5 (%) | Validation mAP@.5 (%) |', '|---|---:|---:|']
    train_metrics = train_final['metrics']
    init_metrics = validation_initial['metrics']
    val_metrics = validation_final['metrics']
    for variant in VARIANTS:
        train_value = train_metrics.get(variant, {}).get('global_confidence_sort', {}).get('macro_ap', {}).get('0.5')
        val_source = init_metrics if variant.startswith('initialized') or variant == 'thermal_initialized' else val_metrics
        val_value = val_source.get(variant, {}).get('global_confidence_sort', {}).get('macro_ap', {}).get('0.5')
        if variant == 'lidar':
            val_value = val_metrics['lidar']['global_confidence_sort']['macro_ap']['0.5']
        fmt = lambda v: 'N/A' if v is None else f'{100*v:.4f}'
        lines.append(f'| {variant} | {fmt(train_value)} | {fmt(val_value)} |')
    lines += ['', 'Per-class AP and TP/FP/GT counts: `report.json`.',
              'One TRAIN epoch; native thermal input; frozen RPN at fixed 4,000 proposals.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    archive = output/'urbaning-thermal-head-pilot.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('protocol.json', 'train-inventory.json', 'native-gate.json', 'training.jsonl',
                     'skipped-updates.jsonl', 'report.json', 'summary.md', 'models/initialized-heads.pt',
                     'models/final-heads.pt', 'models/freeze.json'):
            z.write(output/name, name)
        for folder in ('frames-train-finetuned', 'frames-validation-initialized',
                       'frames-validation-finetuned'):
            for path in sorted((output/folder).glob('*.npz')):
                z.write(path, str(path.relative_to(output)))
    write_json(output/'completed.json', {'sha256': sha(archive.read_bytes()),
                                         'model_sha256': freeze['model_sha256']})
    print('\n'.join(lines), flush=True)
    print('SHA256', sha(archive.read_bytes()), 'bytes', archive.stat().st_size, flush=True)
    print('DONE:', archive, flush=True)
    source_zip.close()
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'runtime', 'model-dir', 'source', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--activated', action='store_true')
    args = parser.parse_args()
    if not args.activated or os.environ.get('PYTHONHASHSEED') != '0':
        spec = importlib.util.spec_from_file_location('rgb3d_runtime', ROOT/'scripts/urbaning_rgb3d_late.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        _, env = module.reuse(args.runtime.resolve())
        env.update({'PYTHONHASHSEED': '0', 'MPLCONFIGDIR': str(args.output.resolve()/'matplotlib-cache'),
                    'OMP_NUM_THREADS': str(args.threads), 'MKL_NUM_THREADS': str(args.threads)})
        command = [sys.executable, '-u', str(Path(__file__).resolve()), *sys.argv[1:]]
        if not args.activated:
            command.append('--activated')
        os.execve(sys.executable, command, env)
    run(args)


if __name__ == '__main__':
    main()
