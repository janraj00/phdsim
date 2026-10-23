"""Frozen CoBEVT inputs, independent of labels and acquisition decisions."""

import math


def subset_inputs(ego_batch, indices):
    """Select agent voxels and compact their indices for upstream record_len.

    Returns ONLY model inputs. Ground truth, peer labels and full-frame metadata
    are deliberately not reachable through this dictionary. Batch size is one.
    Each action reuses the exact same preprocessed voxels, without resampling.
    """
    import torch

    count = ego_batch['record_len']
    indices = tuple(indices)
    if count.numel() != 1 or not indices or indices[0] != 0:
        raise ValueError('One frame with ego at index zero is required')
    if len(indices) != len(set(indices)) or any(i < 0 or i >= int(count.item()) for i in indices):
        raise ValueError('Invalid or duplicate source indices')
    lidar = ego_batch['processed_lidar']
    coordinates = lidar['voxel_coords']
    if coordinates.ndim != 2 or coordinates.shape[1] != 4:
        raise ValueError('Expected voxel coordinates [agent,z,y,x]')
    selected = {name: [] for name in ('voxel_features', 'voxel_coords', 'voxel_num_points')}
    for new_index, old_index in enumerate(indices):
        mask = coordinates[:, 0] == old_index
        if not bool(mask.any()):
            raise ValueError('Source has no in-range voxels; upstream scatter cannot represent it')
        for name in selected:
            value = lidar[name][mask].clone()
            if name == 'voxel_coords':
                value[:, 0] = new_index
            selected[name].append(value)
    if sum(len(part) for part in selected['voxel_coords']) < 2:
        raise ValueError('Upstream PillarVFE squeezes singleton voxel dimensions; at least two voxels required')
    return {'processed_lidar': {name: torch.cat(parts) for name, parts in selected.items()},
            'record_len': count.new_tensor([len(indices)])}


def ego_entropy(logits, top_k=100):
    """Mean Bernoulli entropy of the top-k ego anchor confidence values, in bits.

    This is an uncalibrated acquisition heuristic, not detection error probability.
    Confidence follows the upstream maximum over four sigmoid class outputs.
    """
    import torch

    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != 32 or top_k <= 0:
        raise ValueError('Expected released CoBEVT classification output [1,32,H,W]')
    confidence = logits.permute(0, 2, 3, 1).reshape(-1, 4).sigmoid().max(dim=-1).values
    probability = confidence.topk(min(top_k, confidence.numel())).values.clamp(1e-7, 1 - 1e-7)
    value = (-(probability * probability.log2() +
               (1 - probability) * (1 - probability).log2())).mean().item()
    if not math.isfinite(value):
        raise ValueError('Non-finite ego uncertainty')
    return value
