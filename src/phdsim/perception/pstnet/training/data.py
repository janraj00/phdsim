"""Family-disjoint pilot selection without looking at masks or test images."""

from collections import defaultdict
from hashlib import sha256
import numpy as np
import torch

from phdsim.datasets.pst900.review import recording_family
from phdsim.perception.pstnet.input import rgb_tensor, reference_mask


def _sample_by_family(frames, count, seed):
    groups = defaultdict(list)
    for frame in frames:
        groups[recording_family(frame.sequence_id)].append(frame)
    if count > len(frames) or count < len(groups):
        raise ValueError('Pilot count must cover every family and fit available frames')
    key = lambda value: sha256(f'pstnet-rgb-pilot:{seed}:{value}'.encode()).hexdigest()
    queues = {g: sorted(rows, key=lambda f: key(f.frame_id)) for g, rows in groups.items()}
    selected = []
    while len(selected) < count:
        for group in sorted(groups, key=key):
            if queues[group] and len(selected) < count:
                selected.append(queues[group].pop(0))
    return tuple(selected)


def make_rgb_plan(frames, config):
    original_train = tuple(f for f in frames if f.split == 'train')
    families = {recording_family(f.sequence_id) for f in original_train}
    validation, acquisition = set(config.validation_families), set(config.acquisition_families)
    if not validation | acquisition <= families:
        raise ValueError('Configured held-out families are absent from original train')
    train_candidates = tuple(f for f in original_train if recording_family(f.sequence_id) not in validation | acquisition)
    validation_candidates = tuple(f for f in original_train if recording_family(f.sequence_id) in validation)
    train = _sample_by_family(train_candidates, config.train_frames, config.seed)
    held = _sample_by_family(validation_candidates, config.validation_frames, config.seed)
    plan = {'schema': 'phdsim-pstnet-rgb-plan-v1',
            'selection': 'SHA256 ordering, round-robin recording families; no mask/model-dependent selection',
            'train_frame_ids': [f.frame_id for f in train], 'validation_frame_ids': [f.frame_id for f in held],
            'train_families': sorted({recording_family(f.sequence_id) for f in train}),
            'validation_families': sorted(validation), 'acquisition_reserved_families': sorted(acquisition),
            'acquisition_reserved_frames': sum(recording_family(f.sequence_id) in acquisition for f in original_train),
            'official_test_frames_unused': sum(f.split == 'test' for f in frames),
            'unused_vision_train_frames': len(train_candidates) - len(train),
            'unused_validation_frames': len(validation_candidates) - len(held)}
    return train, held, plan


def load_rgb_samples(frames):
    """Read only selected RGB images and labels; never thermal or official test."""
    if any(f.split != 'train' for f in frames):
        raise ValueError('RGB pilot can use original train frames only')
    return tuple({'frame': f, 'rgb': rgb_tensor(f.rgb_path, f.rgb_sha256),
                  'mask': torch.from_numpy(reference_mask(f.mask_path, f.mask_sha256)).long().unsqueeze(0)}
                 for f in frames)


def class_weights(samples):
    """Inverse log-frequency weighting from TRAIN masks only (Paszke scheme)."""
    counts = sum((torch.bincount(s['mask'].flatten(), minlength=5).numpy() for s in samples),
                 start=np.zeros(5, dtype=np.int64))
    if not len(samples) or (counts == 0).any():
        raise ValueError('Pilot training selection must contain pixels from every class')
    frequency = counts / counts.sum()
    weights = 1 / np.log(1.02 + frequency)
    return torch.tensor(weights, dtype=torch.float32), counts.tolist()
