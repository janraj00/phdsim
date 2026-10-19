"""CPU RGB pilot: full network fine-tuning, weighted CE, validation-only choice."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from torch import nn
import torchvision

from phdsim.datasets.pst900.segmentation import load_frames
from phdsim.artifacts import write_json_atomic as _write
from phdsim.evaluation.segmentation import confusion_matrix, segmentation_metrics
from phdsim.perception.pstnet.rgb import PstRgb
from .data import make_rgb_plan, load_rgb_samples, class_weights


def _save_weights(model, path):
    temporary = path.with_suffix('.pth.partial')
    torch.save(model.state_dict(), temporary)
    temporary.replace(path)


@torch.inference_mode()
def evaluate(model, samples, weights):
    model.eval()
    matrix = np.zeros((5, 5), dtype=np.int64)
    numerator, denominator = 0., 0.
    for sample in samples:
        logits, reference = model(sample['rgb']), sample['mask']
        numerator += float(nn.functional.cross_entropy(logits, reference, weight=weights, reduction='sum'))
        denominator += float(weights[reference].sum())
        matrix += confusion_matrix(logits.argmax(1)[0].numpy(), reference[0].numpy())
    metrics = segmentation_metrics(matrix)
    metrics['weighted_cross_entropy'] = numerator / denominator
    metrics['foreground_mean_iou'] = float(np.mean(list(metrics['class_iou'].values())[1:]))
    metrics['predicted_class_pixels'] = matrix.sum(0).tolist()
    return metrics


def background_baseline(samples):
    matrix = sum((confusion_matrix(np.zeros_like(s['mask'][0].numpy()), s['mask'][0].numpy()) for s in samples),
                 start=np.zeros((5, 5), dtype=np.int64))
    return segmentation_metrics(matrix)


def fit_epoch(model, samples, optimizer, weights, config, epoch):
    model.train()
    generator = torch.Generator().manual_seed(config.seed + epoch)
    order = torch.randperm(len(samples), generator=generator).tolist()
    total_loss, gradient_norms = 0., []
    for step, index in enumerate(order, 1):
        sample = samples[index]
        optimizer.zero_grad(set_to_none=True)
        logits = model(sample['rgb'])
        loss = nn.functional.cross_entropy(logits, sample['mask'], weight=weights)
        if not torch.isfinite(loss):
            raise ValueError('Non-finite RGB training loss')
        loss.backward()
        norm = nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip, error_if_nonfinite=True)
        optimizer.step()
        total_loss += float(loss.detach())
        gradient_norms.append(float(norm))
        if step % 8 == 0 or step == len(samples):
            print(f'RGB pilot epoch {epoch}/{config.epochs}, step {step}/{len(samples)}, loss={total_loss/step:.4f}', flush=True)
    return {'mean_step_loss': total_loss / len(samples), 'mean_gradient_norm_before_clip': float(np.mean(gradient_norms))}


def train_rgb_pilot(manifest, output, model_directory, config, *, pretrained_path=None):
    """Retrain the architecture, not reproduce unavailable author checkpoints."""
    output, model_directory = Path(output).resolve(), Path(model_directory).resolve()
    for directory in (output, model_directory):
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f'Pilot destination is not empty: {directory}')
    torch.set_num_threads(config.cpu_threads)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(config.seed)
    frames = load_frames(manifest, verify=False)
    train_frames, validation_frames, plan = make_rgb_plan(frames, config)
    train, held = load_rgb_samples(train_frames), load_rgb_samples(validation_frames)
    weights, counts = class_weights(train)
    if pretrained_path is None:
        pretrained_path = Path(torch.hub.get_dir()) / 'checkpoints' / 'resnet18-f37072fd.pth'
    pretrained_path = Path(pretrained_path)
    initialization_sha = sha256(pretrained_path.read_bytes()).hexdigest()
    if initialization_sha != 'f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec':
        raise ValueError('Expected official torchvision ResNet18 ImageNet V1 initialization')
    model = PstRgb(3, 5)
    model.base_model.load_state_dict(torch.load(pretrained_path, map_location='cpu', weights_only=True), strict=True)
    encoder_ids = {id(p) for p in model.base_model.parameters()}
    optimizer = torch.optim.AdamW([
        {'params': list(model.base_model.parameters()), 'lr': config.encoder_learning_rate},
        {'params': [p for p in model.parameters() if id(p) not in encoder_ids], 'lr': config.decoder_learning_rate},
    ], weight_decay=config.weight_decay)
    for directory in (output, model_directory):
        directory.mkdir(parents=True, exist_ok=True)
    metadata = {'schema': 'phdsim-pstnet-rgb-training-v1', 'config': asdict(config), 'plan': plan,
                'manifest_sha256': sha256(Path(manifest).read_bytes()).hexdigest(),
                'architecture_commit': '47bbf0133b29e05c7a087b71fb27e8cd8c092ec8',
                'initialization': {'encoder': 'torchvision ResNet18 ImageNet V1', 'sha256': initialization_sha,
                                   'decoder': 'seeded random initialization'},
                'training': 'own pilot; optimizer and learning rates are our choices; no claim of identical author training',
                'preprocessing': 'authors RGB /255, bilinear 640x360, nearest class masks, no augmentation',
                'loss': 'weighted cross entropy; w_c=1/ln(1.02+train_pixel_frequency_c)',
                'class_weights': weights.tolist(), 'train_class_pixel_counts': counts,
                'batch_size': 1, 'selection': 'highest global validation five-class mIoU, including epoch zero',
                'runtime': {'torch': torch.__version__, 'torchvision': torchvision.__version__, 'device': 'cpu'},
                'model_directory': str(model_directory),
                'validation_background_baseline': background_baseline(held),
                'status': 'running'}
    _write(output / 'training.json', metadata)
    _write(output / 'plan.json', plan)
    print(f'RGB pilot: {len(train)} train, {len(held)} validation; original test and acquisition families unused', flush=True)
    start = perf_counter()
    history = [{'epoch': 0, 'train': evaluate(model, train, weights), 'validation': evaluate(model, held, weights)}]
    print(f"RGB pilot epoch 0: train mIoU={history[0]['train']['miou']:.4f}, validation mIoU={history[0]['validation']['miou']:.4f}", flush=True)
    with torch.inference_mode():
        initial_predictions = {s['frame'].frame_id: model(s['rgb']).argmax(1)[0].numpy().astype(np.uint8)
                               for s in held[:6]}
    best_epoch, best_score = 0, history[0]['validation']['miou']
    best_path = model_directory / 'model_best.pth'
    _save_weights(model, best_path)
    metadata.update({'history': history, 'selected_epoch': best_epoch, 'elapsed_seconds': perf_counter() - start})
    _write(output / 'training.json', metadata)
    for epoch in range(1, config.epochs + 1):
        epoch_start = perf_counter()
        optimization = fit_epoch(model, train, optimizer, weights, config, epoch)
        entry = {'epoch': epoch, 'optimization': optimization,
                 'train': evaluate(model, train, weights), 'validation': evaluate(model, held, weights),
                 'seconds': perf_counter() - epoch_start}
        history.append(entry)
        score = entry['validation']['miou']
        if score > best_score:
            best_score, best_epoch = score, epoch
            _save_weights(model, best_path)
        _save_weights(model, model_directory / 'model_last.pth')
        metadata.update({'history': history, 'selected_epoch': best_epoch, 'elapsed_seconds': perf_counter() - start})
        _write(output / 'training.json', metadata)
        print(f"RGB pilot epoch {epoch}: train mIoU={entry['train']['miou']:.4f}, validation mIoU={score:.4f}, foreground IoU={entry['validation']['foreground_mean_iou']:.4f}; selected epoch={best_epoch}", flush=True)
    model.load_state_dict(torch.load(best_path, map_location='cpu', weights_only=True), strict=True)
    model.eval()
    metadata.update({'status': 'complete', 'history': history, 'selected_epoch': best_epoch,
                     'selected_train': evaluate(model, train, weights), 'selected_validation': evaluate(model, held, weights),
                     'elapsed_seconds': perf_counter() - start,
                     'checkpoint': {'path': str(best_path), 'sha256': sha256(best_path.read_bytes()).hexdigest()},
                     'test_evaluated': False, 'fusion_trained': False, 'acquisition_trained': False})
    _write(output / 'training.json', metadata)
    _write(model_directory / 'training_provenance.json', metadata)
    from .report import write_report
    write_report(output, metadata, held[:6], initial_predictions, model)
    return metadata
