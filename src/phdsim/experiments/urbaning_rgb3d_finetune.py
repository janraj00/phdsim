"""Native four-class RGB head fitting: TRAIN400, then frozen validation200."""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import time
import zipfile

import numpy as np

from phdsim.perception.urbaning.rgb3d_late import OUTDOOR_ASSETS, CLASS_MAP, upright_boxes, classwise_nms
from phdsim.perception.urbaning.rgb3d_additive import additive_fuse
from phdsim.perception.urbaning.rgb3d_finetune import (
    FineTuneDetector, projected_targets, train_key, GROUPS, EPOCHS, LEARNING_RATE,
    NoUsableBackgroundProposals)
from phdsim.evaluation.urbaning_cached import frame_statistics, aggregate_statistics, summarize_cached

SCHEMA = 'phdsim-rgb3d-four-class-heads-v1'
VARIANTS = ('lidar', 'rgb_outdoor', 'rgb_depth', 'rgb_coarse_initialized', 'rgb_heads_finetuned',
            'initialized_additive_raw', 'initialized_additive_lidar_first',
            'finetuned_additive_raw', 'finetuned_additive_lidar_first')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


def save_npz(path, **arrays):
    temp = path.with_suffix('.partial')
    with temp.open('wb') as f:
        np.savez_compressed(f, **arrays)
    os.replace(temp, path)


def read_inputs(*args):
    from phdsim.experiments.urbaning_rgb_pilot import read_inputs as implementation
    return implementation(*args)


def camera_fields(path):
    from phdsim.experiments.urbaning_rgb_pilot import camera_fields as implementation
    return implementation(path)


def source_archive(path):
    raw = path.read_bytes()
    done = path.with_name('completed.json')
    if not done.is_file() or json.loads(done.read_text())['sha256'] != sha(raw):
        raise ValueError('Need completed checksum-verified depth source21658632')
    z = zipfile.ZipFile(io.BytesIO(raw))
    if len(z.namelist()) != len(set(z.namelist())) or z.testzip() is not None:
        raise ValueError('Corrupt/duplicate source archive')
    report = json.loads(z.read('report.json'))
    if report['schema'] != 'phdsim-rgb3d-native-depth-controlled-v1':
        raise ValueError('Unexpected source experiment')
    for split, count in (('train', 400), ('validation', 200)):
        if len([n for n in z.namelist() if n.startswith('frames-'+split+'/') and n.endswith('.npz')]) != count:
            raise ValueError('Source frame inventory differs')
    return z, report, sha(raw)


def camera(record, index):
    import cv2
    path = Path(record['yaml']).with_name(Path(record['yaml']).stem+f'_camera{index}.png')
    raw = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Unreadable native RGB image')
    e, k = camera_fields(record['yaml'])[index]
    binding = {'image_sha256': sha(raw), 'E': e.tolist(), 'K': k.tolist(),
               'native_association': record['native_association'],
               'gt_sha256': sha(record['gt_boxes'].tobytes()+record['gt_labels'].tobytes())}
    return image, e, k, binding


def snapshot_hash(model, frozen_only=False):
    h = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        if frozen_only and key.startswith(('roi_heads.box_head.', 'roi_heads.box_predictor.', 'roi_heads.cube_head.')):
            continue
        h.update(key.encode()); h.update(value.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def update(detector, inputs, optimizer, *, required_losses=()):
    import torch
    optimizer.zero_grad(set_to_none=True)
    losses = detector.losses(inputs)
    missing = sorted(set(required_losses)-set(losses))
    if missing:
        raise ValueError(f'Missing required native losses {missing}; returned {sorted(losses)}')
    total = sum(losses.values())
    if not total.requires_grad:
        raise ValueError('Native losses have no training graph')
    total.backward()
    parameters = [p for p in detector.model.parameters() if p.requires_grad]
    if not any(p.grad is not None and bool((p.grad != 0).any()) for p in parameters):
        raise ValueError('No actual native-head gradients')
    norm = torch.nn.utils.clip_grad_norm_(parameters, 5., error_if_nonfinite=True)
    optimizer.step()
    return {k: float(v.detach()) for k, v in losses.items()}, float(norm)


def native_gate(detector, train, output):
    """Disposable positive and background backward checks before full fitting."""
    import torch
    from detectron2.utils.events import EventStorage
    original = detector.trainable_state()
    frozen = snapshot_hash(detector.model, True)
    optimizer = torch.optim.SGD([p for p in detector.model.parameters() if p.requires_grad], lr=LEARNING_RATE)
    rng = torch.get_rng_state()
    events = []
    example = None
    with EventStorage():
        for record in train:
            for index in range(6):
                image, e, k, _ = camera(record, index)
                rows = projected_targets(record['gt_boxes'], record['gt_labels'], e, k, image.shape[1], image.shape[0])
                if rows is None or not any(r['class'] >= 0 for r in rows):
                    continue
                print('NATIVE GATE positive', record['key'], 'camera', index,
                      'targets', sum(r['class'] >= 0 for r in rows), flush=True)
                try:
                    losses, norm = update(detector, detector.training_input(image, k, rows), optimizer,
                                          required_losses=('BoxHead/loss_cls', 'Cube/loss_z'))
                except ValueError as exc:
                    write_json(output/'native-gate.json', {'passed': False, 'stage': 'positive',
                                                          'key': record['key'], 'camera': index, 'error': str(exc)})
                    raise
                print('NATIVE GATE positive losses', json.dumps(losses, sort_keys=True), flush=True)
                events.append({'kind': 'positive', 'key': record['key'], 'camera': index,
                               'losses': losses, 'gradient_norm': norm})
                example = image, k
                break
            if example is not None:
                break
        if example is None:
            raise ValueError('No positive native training example')
        # Deliberately empty synthetic labels on a real image exercise the
        # empty-GT implementation only. ALL resulting parameter changes are discarded.
        image, k = example
        losses, norm = update(detector, detector.training_input(image, k, []), optimizer,
                              required_losses=('BoxHead/loss_cls',))
        print('NATIVE GATE background losses', json.dumps(losses, sort_keys=True), flush=True)
        events.append({'kind': 'disposable_empty_labels', 'losses': losses, 'gradient_norm': norm})
    if snapshot_hash(detector.model, True) != frozen:
        raise ValueError('Frozen parameters/buffers changed during gate')
    if not any(not torch.equal(original[k], v) for k, v in detector.trainable_state().items()):
        raise ValueError('No actual native-head update')
    detector.load_trainable(original)
    torch.set_rng_state(rng)
    for key, value in detector.trainable_state().items():
        if not torch.equal(value, original[key]):
            raise ValueError('Disposable gate failed to restore initializer')
    # Save/load parity on an actual detector forward, not just tensor shapes.
    before = detector.predict(image, k)
    path = output/'models/gate-roundtrip.pt'
    torch.save(original, path)
    detector.load_trainable(torch.load(path, weights_only=True, map_location='cpu'))
    after = detector.predict(image, k)
    for key in before:
        np.testing.assert_array_equal(before[key], after[key])
    write_json(output/'native-gate.json', {'passed': True, 'updates_discarded': True,
                                          'frozen_parameters_unchanged': True, 'events': events})
    print('NATIVE GATE PASSED: positive + empty-image gradients, frozen-state guard, save/load prediction parity', flush=True)


def run(base, runtime, model_dir, source, output, threads, gate_only=False):
    import torch
    from detectron2.utils.events import EventStorage
    output = Path(output)
    forbidden = [Path(runtime).resolve(), Path(model_dir).resolve(), Path(source).parent.resolve()]
    if any(output.resolve() == p or output.resolve().is_relative_to(p) for p in forbidden):
        raise ValueError('Output must be separate from all source artifacts')
    output.mkdir(parents=True, exist_ok=True)
    with (output/'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output/'protocol.json').exists():
            raise ValueError('Use a fresh output; training resumes are not implemented')
        for folder in ('models', 'train-loader', 'validation-loader', 'frames-train', 'frames-validation'):
            (output/folder).mkdir()
        started = time.monotonic()
        for name, expected in OUTDOOR_ASSETS.items():
            if sha((model_dir/name).read_bytes()) != expected:
                raise ValueError('Official source weights/config changed')
        runtime_sha = sha((runtime/'ready.json').read_bytes())
        z, old_report, source_sha = source_archive(source)
        records, provenance = read_inputs(base, output/'train-loader', 200, 0)
        train = records['train']
        if len(train) != 400 or records['validation']:
            raise ValueError('Need TRAIN400 only before fitting')
        for record in train:
            train_key(record['key'])
        code_paths = [Path(__file__), Path(__file__).parents[1]/'perception/urbaning/rgb3d_finetune.py',
                      Path(__file__).parents[3]/'scripts/urbaning_rgb3d_finetune.py',
                      Path(__file__).parents[3]/'scripts/slurm/urbaning_rgb3d_finetune.sbatch']
        protocol = {'schema': SCHEMA, 'source_sha256': source_sha, 'runtime_sha256': runtime_sha,
                    'official_assets': OUTDOOR_ASSETS, 'train_provenance': provenance,
                    'epochs': EPOCHS, 'optimizer': 'SGD momentum=.9 weight_decay=.0001',
                    'lr': LEARNING_RATE, 'warmup_updates': 100, 'gradient_clip_norm': 5., 'seed': 0,
                    'roi_samples_per_image': 128, 'threads': threads, 'gate_only': gate_only,
                    'coarse_initialization_groups': GROUPS, 'initializer': 'fixed mean of existing category rows',
                    'trainable': ['native box_head', 'native box_predictor', 'native cube_head'],
                    'frozen': ['backbone/FPN', 'RPN', 'priors'],
                    'supervision': 'projected 3D GT; weak 2D boxes, no visibility labels; per-object ignore small/truncated/near-plane-straddling boxes',
                    'selection': 'fixed final four epochs; no validation fitting/selection; no crossing3',
                    'code': {str(p.relative_to(Path(__file__).parents[3])): sha(p.read_bytes()) for p in code_paths}}
        write_json(output/'protocol.json', protocol)
        detector = FineTuneDetector(model_dir, threads)
        initial = detector.trainable_state()
        frozen_sha = snapshot_hash(detector.model, True)
        torch.save(initial, output/'models/initialized-heads.pt')
        native_gate(detector, train, output)
        if gate_only:
            print('GATE ONLY DONE; full experiment not started:', output, flush=True)
            return output

        inventory = []
        support = np.zeros(4, int)
        for record in train:
            for index in range(6):
                image, e, k, binding = camera(record, index)
                rows = projected_targets(record['gt_boxes'], record['gt_labels'], e, k, image.shape[1], image.shape[0])
                for r in rows:
                    if r['class'] >= 0:
                        support[r['class']] += 1
                inventory.append({'key': record['key'], 'camera': index, 'binding': binding,
                                  'near_plane_ignore_count': sum(r['near_plane_ignore'] for r in rows),
                                  'positive_count': sum(r['class'] >= 0 for r in rows)})
        if np.any(support == 0):
            raise ValueError('At least one coarse class has no TRAIN supervision')
        write_json(output/'train-inventory.json', {'cameras': inventory, 'class_support': support.tolist()})
        bykey = {r['key']: r for r in train}
        optimizer = torch.optim.SGD([p for p in detector.model.parameters() if p.requires_grad],
                                    lr=LEARNING_RATE, momentum=.9, weight_decay=1e-4)
        history = []
        step = 0
        skipped_no_background = 0
        with (EventStorage() as storage,
              (output/'training.jsonl').open('w') as log,
              (output/'skipped-updates.jsonl').open('w') as skipped_log):
            for epoch in range(EPOCHS):
                order = np.random.default_rng(epoch).permutation(len(inventory))
                for position in order:
                    row = inventory[position]
                    record, index = bykey[row['key']], row['camera']
                    image, e, k, binding = camera(record, index)
                    if binding != row['binding']:
                        raise ValueError('TRAIN image/calibration/GT changed')
                    targets = projected_targets(record['gt_boxes'], record['gt_labels'], e, k, image.shape[1], image.shape[0])
                    for group in optimizer.param_groups:
                        group['lr'] = LEARNING_RATE*min(1., (step+1)/100)
                    try:
                        losses, norm = update(detector, detector.training_input(image, k, targets), optimizer)
                    except NoUsableBackgroundProposals as exc:
                        skipped_no_background += 1
                        skipped_log.write(json.dumps({'epoch': epoch+1, 'key': row['key'],
                                                      'camera': index, 'reason': str(exc)})+'\n')
                        continue
                    step += 1
                    entry = {'step': step, 'epoch': epoch+1, 'key': row['key'], 'camera': index,
                             'positive_count': row['positive_count'], 'losses': losses, 'gradient_norm': norm}
                    log.write(json.dumps(entry, allow_nan=False)+'\n')
                    storage.step()
                    if step % 100 == 0:
                        log.flush()
                        skipped_log.flush()
                        print('TRAIN', epoch+1, '/', EPOCHS, 'updates', step, 'loss', sum(losses.values()), flush=True)
                skipped_log.flush()
                torch.save(detector.trainable_state(), output/f'models/epoch-{epoch+1}.pt')
                history.append({'epoch': epoch+1, 'updates': step,
                                'skipped_no_background_total': skipped_no_background})
                if snapshot_hash(detector.model, True) != frozen_sha:
                    raise ValueError('Frozen backbone/RPN/priors changed')
        trained = detector.trainable_state()
        final_path = output/'models/final-heads.pt'
        torch.save(trained, final_path)
        written = torch.load(final_path, map_location='cpu', weights_only=True)
        if set(written) != set(trained) or any(not torch.equal(written[k], trained[k]) for k in trained):
            raise ValueError('Saved final head state differs from fitted state')
        trained = written
        freeze = {'model_sha256': sha(final_path.read_bytes()), 'updates': step,
                  'epochs': EPOCHS, 'validation_loaded': False, 'history': history,
                  'protocol_sha256': digest(protocol), 'class_support': support.tolist()}
        write_json(output/'models/freeze.json', freeze)
        print('FROZEN four-class RGB heads BEFORE loading validation', freeze['model_sha256'], flush=True)

        def evaluate(rows, split):
            stats = {v: [] for v in VARIANTS}
            old_stats = {v: [] for v in ('lidar', 'rgb_baseline', 'rgb_depth_finetuned')}
            frame_rows = []
            for j, record in enumerate(rows):
                filename = record['key'].replace(':', '_')+'.npz'
                with np.load(io.BytesIO(z.read('frames-'+split+'/'+filename)), allow_pickle=False) as f:
                    old = {k: f[k].copy() for k in f.files}
                for a, b in (('boxes', 'lidar_boxes'), ('scores', 'lidar_scores'),
                             ('gt_boxes', 'gt_boxes'), ('gt_labels', 'gt_labels')):
                    np.testing.assert_array_equal(record[a], old[b])
                outputs = {'lidar': (old['lidar_boxes'], old['lidar_scores']),
                           'rgb_outdoor': (old['rgb_baseline_boxes'], old['rgb_baseline_scores']),
                           'rgb_depth': (old['rgb_depth_boxes'], old['rgb_depth_scores'])}
                prepared = [camera(record, i) for i in range(6)]
                for stage, state in (('initialized', initial), ('finetuned', trained)):
                    detector.load_trainable(state)
                    bs, ss = [], []
                    for image, e, k, _ in prepared:
                        pred = detector.predict(image, k)
                        boxes = upright_boxes(pred['centers'], pred['dimensions'], pred['rotations'], e)
                        scores = np.c_[pred['scores'], pred['classes']+1]
                        bs.append(boxes); ss.append(scores)
                    boxes, scores = np.concatenate(bs), np.concatenate(ss)
                    keep = classwise_nms(boxes, scores, .2)
                    boxes, scores = boxes[keep], scores[keep]
                    outputs['rgb_coarse_initialized' if stage == 'initialized' else 'rgb_heads_finetuned'] = boxes, scores
                    for name, first in (('raw', False), ('lidar_first', True)):
                        b, s, _, _ = additive_fuse(record['boxes'], record['scores'], boxes, scores, lidar_first=first)
                        outputs[stage+'_additive_'+name] = b, s
                payload = {'gt_boxes': record['gt_boxes'], 'gt_labels': record['gt_labels']}
                for v, (b, s) in outputs.items():
                    payload[v+'_boxes'], payload[v+'_scores'] = b, s
                    stats[v].append(frame_statistics(b, s, record['gt_boxes'], record['gt_labels']))
                for v, alias in (('lidar', 'lidar'), ('rgb_baseline', 'rgb_outdoor'), ('rgb_depth_finetuned', 'rgb_depth')):
                    old_stats[v].append(stats[alias][-1])
                path = output/('frames-'+split)/filename
                save_npz(path, **payload)
                frame_rows.append({'key': record['key'], 'sha256': sha(path.read_bytes()),
                                   'cameras': [p[3] for p in prepared]})
                if (j+1) % 10 == 0:
                    print('EVAL', split, j+1, '/', len(rows), flush=True)
            def metrics(rows):
                total = aggregate_statistics(rows)
                return {name: summarize_cached(total, order) for name, order in
                        (('global_confidence_sort', True), ('upstream_default_frame_order', False))}
            result = {v: metrics(s) for v, s in stats.items()}
            for v, ss in old_stats.items():
                if metrics(ss) != old_report[split+'_metrics'][v]:
                    raise ValueError('Source baseline AP does not reproduce')
            replay = {v: [] for v in VARIANTS}
            for frame in frame_rows:
                path = output/('frames-'+split)/(frame['key'].replace(':', '_')+'.npz')
                if sha(path.read_bytes()) != frame['sha256']:
                    raise ValueError('Changed saved prediction payload')
                with np.load(path, allow_pickle=False) as f:
                    for v in VARIANTS:
                        replay[v].append(frame_statistics(f[v+'_boxes'], f[v+'_scores'], f['gt_boxes'], f['gt_labels']))
            if {v: metrics(s) for v, s in replay.items()} != result:
                raise ValueError('Independent AP replay differs')
            counts = {}
            for v, ss in replay.items():
                total = aggregate_statistics(ss)
                counts[v] = {c: {k: int(sum(total[c][.5][k])) if k in ('tp', 'fp') else int(total[c][.5][k])
                                 for k in ('tp', 'fp', 'gt')} for c in total}
            return {'metrics': result, 'counts_at_iou_05': counts, 'frames': frame_rows,
                    'source_ap_reproduced': True, 'saved_prediction_ap_reproduced': True}

        results = {'train': evaluate(train, 'train')}
        records, val_provenance = read_inputs(base, output/'validation-loader', 0, 200)
        validation = records['validation']
        if len(validation) != 200 or records['train'] or any(r['sequence'] != '20241126_0004_crossing2_00' for r in validation):
            raise ValueError('Unexpected development validation recording')
        results['validation'] = evaluate(validation, 'validation')
        if (sha(final_path.read_bytes()) != freeze['model_sha256']
                or snapshot_hash(detector.model, True) != frozen_sha
                or sha(source.read_bytes()) != source_sha
                or sha((runtime/'ready.json').read_bytes()) != runtime_sha):
            raise ValueError('Frozen model or sources changed')
        for name, expected in OUTDOOR_ASSETS.items():
            if sha((model_dir/name).read_bytes()) != expected:
                raise ValueError('Source weights changed')
        report = {'schema': SCHEMA, 'protocol': protocol, 'freeze': freeze, 'splits': results,
                  'validation_provenance': val_provenance, 'seconds': time.monotonic()-started,
                  'limitations': ['Four-class output surgery requires initialized-control comparison',
                      'Only ROI heads train; image backbone/FPN/RPN stay frozen; not end-to-end training',
                      'Projected cuboids are weak 2D supervision, including occlusion ambiguity',
                      'Two TRAIN recordings, one previously inspected development-validation recording',
                      'No crossing3 or independent test; single seed; no acquisition/communication claim',
                      'LiDAR-first is source-priority ranking, not calibrated confidence; inspect FP too']}
        write_json(output/'report.json', report)
        lines = ['# Four-class RGB head fine-tuning', '', '| Variant | TRAIN mAP@.5 (%) | Validation mAP@.5 (%) |', '|---|---:|---:|']
        for v in VARIANTS:
            values = [results[s]['metrics'][v]['global_confidence_sort']['macro_ap']['0.5'] for s in ('train', 'validation')]
            lines.append('| '+v+' | '+' | '.join('N/A' if a is None else f'{100*a:.4f}' for a in values)+' |')
        lines += ['', 'Class AP@.3/.5/.7, FP/TP counts and replayable predictions: report.json.',
                  'Projected-GT supervision; frozen backbone/RPN; final-only development comparison.']
        (output/'summary.md').write_text('\n'.join(lines)+'\n')
        archive = output/'urbaning-rgb3d-finetune.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in ('protocol.json', 'report.json', 'summary.md', 'native-gate.json', 'train-inventory.json', 'training.jsonl',
                         'models/initialized-heads.pt', 'models/final-heads.pt', 'models/freeze.json',
                         'skipped-updates.jsonl'):
                bundle.write(output/name, name)
            for split in ('train', 'validation'):
                for path in sorted((output/('frames-'+split)).glob('*.npz')):
                    bundle.write(path, str(path.relative_to(output)))
        write_json(output/'completed.json', {'sha256': sha(archive.read_bytes()), 'model_sha256': freeze['model_sha256']})
        z.close()
        print('\n'.join(lines), flush=True)
        print('SHA256', sha(archive.read_bytes()), 'bytes', archive.stat().st_size, flush=True)
        print('DONE:', archive, flush=True)
        return archive
