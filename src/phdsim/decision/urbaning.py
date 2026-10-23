"""LiDAR acquisition baselines using ego evidence and public source IDs only."""

import hashlib
import math


def action_subsets(source_ids):
    """Stable paired baselines; unavailable peer categories fall back to ego.

    Source IDs follow the pinned UrbanIng converter: two cars and one bundled
    infrastructure site. They do not denote individual roadside sensors.
    """
    ids = tuple(str(value) for value in source_ids)
    if not ids or ids[0] not in ('100000', '200000') or len(ids) > 3 or len(set(ids)) != len(ids):
        raise ValueError('Expected vehicle ego and at most two distinct partners')
    if any(value not in ('100000', '200000', '-1', '-2', '-3') for value in ids):
        raise ValueError('Unknown source ID')
    vehicle = tuple(i for i in range(1, len(ids)) if int(ids[i]) > 0)
    infrastructure = tuple(i for i in range(1, len(ids)) if int(ids[i]) < 0)
    if len(vehicle) > 1 or len(infrastructure) > 1:
        raise ValueError('Expected at most one partner of each category')
    return {'ego': (0,), 'vehicle_peer': (0,) + vehicle,
            'infrastructure': (0,) + infrastructure, 'all': tuple(range(len(ids)))}


def choose_one_peer(source_ids, frame_key, seed, ego_uncertainty=None, threshold=None):
    """Always-one random baseline, or uncertainty-gated acquisition of one peer.

    A deterministic hash avoids dependence on run order and Python hash seeds.
    No labels, peer predictions or counterfactual gains enter this interface.
    """
    actions = action_subsets(source_ids)
    if threshold is not None:
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('Entropy threshold must be in [0,1]')
        if ego_uncertainty is None or not math.isfinite(ego_uncertainty) or not 0 <= ego_uncertainty <= 1:
            raise ValueError('Finite ego entropy in [0,1] is required')
        if ego_uncertainty <= threshold:
            return 'ego'
    candidates = [name for name in ('vehicle_peer', 'infrastructure') if len(actions[name]) == 2]
    if not candidates:
        return 'ego'
    number = int.from_bytes(hashlib.sha256((str(seed) + ':' + frame_key).encode()).digest()[:8], 'big')
    return candidates[number % len(candidates)]
