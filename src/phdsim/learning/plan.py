"""Separate recording families before training; never select by test scores."""

from hashlib import sha256
from math import ceil

from phdsim.datasets.pst900.review import recording_family


def make_plan(pool, seed=42, meta_fraction=0.3):
    if not 0 < meta_fraction < 1:
        raise ValueError("meta_fraction must be between zero and one")
    groups = {split: {recording_family(r.sequence_id) for r in pool.records if r.split == split}
              for split in ("train", "validation", "test")}
    if any(groups[a] & groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Recording families must not cross splits")
    order = sorted(groups["train"], key=lambda g: sha256(f"acquisition-v1:{seed}:{g}".encode()).hexdigest())
    count = ceil(len(order) * meta_fraction)
    if count < 3 or count >= len(order):
        raise ValueError("Need at least three meta families and remaining CNN training families")
    meta = set(order[:count])
    roles = {"cnn_train": groups["train"] - meta, "meta_train": meta,
             "cnn_validation": groups["validation"], "test": groups["test"]}
    sequences = {role: sorted({r.sequence_id for r in pool.records if recording_family(r.sequence_id) in families})
                 for role, families in roles.items()}
    return {"schema": "phdsim-learning-plan-v1", "pool_fingerprint": pool.fingerprint,
            "seed": seed, "meta_fraction": meta_fraction,
            "selection": "SHA256 order of train recording families; no labels or model scores",
            "recording_families": {k: sorted(v) for k, v in roles.items()}, "sequences": sequences,
            "frames": {role: len({r.target for r in pool.records if r.sequence_id in names})
                       for role, names in sequences.items()},
            "test_status": "previously inspected diagnostic test; never used to fit or select models"}
