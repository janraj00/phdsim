"""Versioned review of the existing pilot, retaining the original test frames."""

from collections import Counter
import json
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image

from phdsim.datasets import ObservationPool, PoolRecord, digest, prepare_pool, read_lines, write_json, write_lines


def recording_family(sequence_id: str) -> str:
    match = re.fullmatch(r"\d+_bag(\d+)[a-z]*", sequence_id)
    if not match:
        raise ValueError(f"Not a PST900 recording: {sequence_id}")
    return f"bag{int(match.group(1))}"


def reviewed_split(record: PoolRecord, survivor_pixels: int, validation_bags: tuple[int, ...]):
    if survivor_pixels == 1:
        return None  # Quarantine, never silently relabel the frame.
    family = recording_family(record.sequence_id)
    if record.split == "test":
        return "test"
    return "validation" if family in {f"bag{bag}" for bag in validation_bags} else "train"


def prepare_reviewed_pool(source: str | Path, output: str | Path, validation_bags=(1, 7, 11)) -> ObservationPool:
    pool = ObservationPool(source)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Reviewed pool already exists: {output}")
    annotations = {r["target"]["id"]: r for r in read_lines(pool.root / "annotations.jsonl")}
    labels = pool.read_labels()
    source_hashes = {name: digest(pool.root / name) for name in ("pool.json", "observations.jsonl", "labels.jsonl", "annotations.jsonl")}
    survivor_counts = {}
    for target_id, row in annotations.items():
        path = pool._local_path(row["mask_path"])
        if digest(path) != row["mask_sha256"]:
            raise ValueError("Source mask fingerprint mismatch")
        with Image.open(path) as image:
            survivor_counts[target_id] = int(np.sum(np.asarray(image) == 4))
    records, included, excluded = [], {}, {}
    for row in pool.records:
        count = survivor_counts[row.target.id]
        if labels[row.target] != int(count > 0):
            raise ValueError("Original task labels differ from masks")
        split = reviewed_split(row, count, tuple(validation_bags))
        if split is None:
            excluded[row.target.id] = {"target": {"kind": row.target.kind, "id": row.target.id},
                                      "original_label": labels[row.target], "original_split": row.split,
                                      "survivor_pixels": count, "mask_sha256": annotations[row.target.id]["mask_sha256"],
                                      "reason": "single class-4 pixel; quarantined pending semantic annotation review"}
            continue
        data = row.to_dict()
        data["split"] = split
        data["payload"]["path"] = str(pool.payload_path(row))
        for key in ("calibration_ref", "pose_ref"):
            if data[key] is not None:
                data[key] = str(pool._local_path(data[key]))
        records.append(data)
        included[row.target] = split
    for split in ("train", "validation"):
        if {labels[t] for t, s in included.items() if s == split} != {0, 1}:
            raise ValueError(f"Reviewed {split} must contain both classes")
    if {r.observation_id for r in pool.records if r.split == "test"} != {r["observation_id"] for r in records if r["split"] == "test"}:
        raise ValueError("Review would alter test membership; stop for explicit review")
    families = {s: {recording_family(r["sequence_id"]) for r in records if r["split"] == s}
                for s in ("train", "validation", "test")}
    if any(families[a] & families[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("A recording family crosses splits")
    adapter = output.parent / (output.name + "_input")
    adapter.mkdir(parents=True, exist_ok=True)
    write_lines(adapter / "observations.jsonl", records)
    write_lines(adapter / "labels.jsonl", ({"target": {"kind": t.kind, "id": t.id}, "label": labels[t]} for t in included))
    result = prepare_pool(adapter / "observations.jsonl", output,
                          dataset_id=f"pst900-pilot-reviewed-{len(included)}",
                          dataset_version="review-v1-bags-" + "-".join(str(bag) for bag in validation_bags),
                          labels=adapter / "labels.jsonl")
    (output / "annotations").mkdir()
    kept = []
    for target in included:
        row = annotations[target.id]
        source_mask = pool._local_path(row["mask_path"])
        destination = output / row["mask_path"]
        if not destination.exists():
            shutil.copyfile(source_mask, destination)
        kept.append(row)
    write_lines(output / "annotations.jsonl", kept)
    write_lines(output / "quarantine.jsonl", excluded.values())
    splits = {t.id: split for t, split in included.items()}
    write_lines(output / "provenance.jsonl", ({**row, "original_pool_split": row["split"], "split": splits[row["target_id"]]}
                for row in read_lines(pool.root / "provenance.jsonl") if row["target_id"] in splits))
    balance = {s: dict(Counter(str(labels[t]) for t, split in included.items() if split == s))
               for s in families}
    write_json(output / "review.json", {
        "source_pool": str(pool.root), "source_pool_fingerprint": pool.fingerprint,
        "source_sha256": source_hashes, "validation_bags": list(validation_bags),
        "selection_basis": "development recording families and class counts only; no model scores or test labels",
        "test_membership": "unchanged; previously inspected diagnostic test, not a fresh confirmatory set",
        "task": "any class-4 pixel; suspicious one-pixel annotations quarantined rather than relabeled",
        "excluded_targets": list(excluded), "split_class_counts": balance,
        "recording_families": {s: sorted(v) for s, v in families.items()},
    })
    source_info = json.loads((pool.root / "dataset.json").read_text(encoding="utf-8"))
    write_json(output / "dataset.json", {**source_info,
        "frames": len(included), "observations": len(records), "binary_label_counts": balance,
        "selection": "source pilot with one-pixel annotations quarantined; whole recording families 1,7,11 reserved for validation",
        "validation_sequences": sorted({r["sequence_id"] for r in records if r["split"] == "validation"}),
        "review": "review.json", "quarantine": "quarantine.jsonl", "test_status": "previously inspected diagnostic test",
        "pool_file_counts": {"metadata": 8, "image_pngs": len(list((output / 'assets').glob('*.png'))),
                             "mask_pngs": len(list((output / 'annotations').glob('*.png'))),
                             "observation_rows": len(records), "label_rows": len(included), "mask_reference_rows": len(kept)},
    })
    result.manifest["task"] = pool.manifest["task"]
    result.manifest["review"] = "review.json"
    write_json(output / "pool.json", result.manifest)
    if any(digest(pool.root / name) != value for name, value in source_hashes.items()):
        raise ValueError("Source pool changed during preparation")
    print({"reviewed_observations": len(result.records), "quarantined_frames": len(excluded), "splits": balance}, flush=True)
    return result
