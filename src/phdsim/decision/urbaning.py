"""LiDAR acquisition baselines using ego evidence and public source IDs only."""

import hashlib
import math
import random

ACTION_ORDER = ('ego', 'vehicle_peer', 'infrastructure', 'all')


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


def available_subsets(source_ids):
    """Canonical feasible actions, with duplicate fallback subsets removed."""
    actions = action_subsets(source_ids)
    result, seen = {}, set()
    for name in ACTION_ORDER:
        indices = actions[name]
        if indices not in seen:
            result[name] = indices
            seen.add(indices)
    return result


def _rng(seed, *parts):
    # Local PRNG; neither process hash randomization nor caller order matters.
    key = repr((seed,) + parts).encode('utf-8')
    return random.Random(int.from_bytes(hashlib.sha256(key).digest(), 'big'))


def choose_subset(source_ids, predicted_gains, request_cost=0.):
    """Choose a jointly scored subset; the score of both is not a sum.

    Gains are predicted changes in frame detection F1 relative to ego. A tie
    prefers fewer requests, then the canonical action order. The caller supplies
    predictions from local evidence, never measured counterfactual outcomes.
    """
    if not math.isfinite(request_cost) or request_cost < 0:
        raise ValueError('Request cost must be finite and nonnegative')
    actions = available_subsets(source_ids)
    rows = []
    for name, indices in actions.items():
        gain = 0. if name == 'ego' else predicted_gains.get(name)
        if gain is None or not math.isfinite(gain):
            raise ValueError('A finite joint gain prediction is required for ' + name)
        cost = len(indices) - 1
        rows.append((-(gain - request_cost * cost), cost, ACTION_ORDER.index(name), name))
    return min(rows)[-1]


def random_subset(source_ids, frame_key, seed, probability=0.5):
    """Independently request each available partner with probability p.

    At p=0.5 all four subsets are equally likely when both partners are present;
    with one partner both feasible subsets are equally likely. Thus random has
    the same action space as the learned policy, including zero and two pulls.
    """
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Probability must be in [0,1]')
    actions = available_subsets(source_ids)
    ids = tuple(str(value) for value in source_ids)
    selected = (0,) + tuple(i for i in range(1, len(ids))
                           if _rng(seed, 'subset', frame_key, ids[i]).random() < probability)
    return next(name for name, indices in actions.items() if indices == selected)


def matched_random_subsets(source_ids, frame_keys, reference_choices, seed, mode):
    """Offline randomized control matched exactly to a policy's pull counts.

    schedule: same number of partners on each frame, random partner identity.
    budget: permute those counts within receiver/feasible-action strata, then
    randomize partner identity. This preserves the complete 0/1/2 histogram and
    total pulls while testing timing and identity. These retrospective controls
    are not deployable policies and receive no labels or quality scores.
    """
    if mode not in ('schedule', 'budget'):
        raise ValueError('Unknown matching mode')
    if not len(source_ids) == len(frame_keys) == len(reference_choices):
        raise ValueError('Mismatched control inputs')
    if len(set(frame_keys)) != len(frame_keys):
        raise ValueError('Frame keys must be unique')
    actions = [available_subsets(ids) for ids in source_ids]
    counts, groups = [], {}
    for i, (ids, options, choice) in enumerate(zip(source_ids, actions, reference_choices)):
        if choice not in options:
            raise ValueError('Reference action is unavailable')
        counts.append(len(options[choice]) - 1)
        group = (str(ids[0]), tuple(options))
        groups.setdefault(group, []).append(i)
    if mode == 'budget':
        for group, indices in sorted(groups.items()):
            indices.sort(key=lambda i: frame_keys[i])
            values = [counts[i] for i in indices]
            _rng(seed, 'budget', group).shuffle(values)
            for i, value in zip(indices, values):
                counts[i] = value
    result = []
    for key, options, count in zip(frame_keys, actions, counts):
        candidates = [name for name, indices in options.items() if len(indices) - 1 == count]
        result.append(_rng(seed, 'partner', key).choice(candidates))
    return result
