# Data contracts and preprocessing

Observation preparation and allocation are separate stages. Reference masks are
offline supervision, not observations owned by an agent.

The [25-dataset compatibility audit and proposed v2 contract](DATASET_AUDIT.md)
documents limitations of the current format, required extensions and a proposed
Cyfronet/Parquet storage architecture. It is a design proposal; the contracts
below describe the implemented v1 workflows.

[UrbanIng-V2X](URBANING.md) now has a separate experimental real-sequence
inspection catalog with portable asset keys, native sample times, source
association memberships and offline 3D annotations. It does not change the
existing replay contracts or implement the final general v2 schema.

## Source data and current segmentation manifest

The available PST900 archive contains **885 complete frame triplets**:
597 original training frames and 288 original test frames. Each triplet contains
one RGB PNG, one aligned thermal PNG, and one class-index mask. Logically this is
**1,770 observation images and 885 reference masks**, or 2,655 PNG references.
The paper describes 894 pairs; the adapter records the discrepancy rather than
inventing missing frames.

Native images are 1280 x 720. Thermal is aligned 8-bit AGC imagery, not temperature
in degrees. Registration is supplied by the dataset authors. Class IDs are:

| ID | Meaning |
|---|---|
| 0 | Background |
| 1 | Fire extinguisher |
| 2 | Backpack |
| 3 | Hand drill |
| 4 | Survivor / Rescue Randy |

`datasets/pst900/segmentation.py` prepares one `segmentation/manifest.json` with
885 records and no agent assignment. Each record has:

| Field | Meaning |
|---|---|
| `frame_id` | Original split and filename, uniquely identifying a frame |
| `split` | Original `train` or `test` |
| `sequence_id` | Recording sequence, including any suffix |
| `tick` | Source frame number, not an invented physical timestamp |
| `assets.rgb` | RGB `path`, `sha256`, and `bytes` |
| `assets.thermal` | Thermal `path`, `sha256`, and `bytes` |
| `assets.labels` | Offline class-mask `path`, `sha256`, and `bytes` |
| `mirror` | Download identity, source comparison and channel-extraction provenance |

The pinned mirror stores an RGB/thermal pair in RGBA: channels 0-2 are RGB and
channel 3 is thermal. Splitting these channels is lossless, although PNG encoding
and byte size can change. Every mask must match its original ZIP entry's size and
CRC32. Available original RGB/thermal images are additionally compared pixel by
pixel. Mirror-only image pixels have not all been independently checked against
original downloads.

Download caches can contain originals, RGBA mirror files, split PNGs and duplicate
mask bytes. Their physical file count is therefore greater than the logical
experiment input count. Transfer accounting uses the PNG actually delivered.

## Preprocessing A: canonical observation pool

The generic `datasets/pool.py` contract is independent of PST900 and agent identity.
The historical 400-pair presence pilot creates **800 observation records**, 400
binary labels and 400 reference-mask records. An observation row is:

```json
{
  "observation_id": "frame-0007-rgb",
  "sequence_id": "31_bag1a",
  "tick": 7,
  "target": {"kind": "frame", "id": "frame-0007"},
  "split": "train",
  "stream_id": "pst900-rgb",
  "modality": "rgb",
  "payload": {
    "path": "assets/<sha256>.png",
    "format": "rgb-png-v1",
    "sha256": "<64 hexadecimal digits>"
  },
  "capture_time_ns": null,
  "calibration_ref": null,
  "pose_ref": null
}
```

`stream_id` is a source stream, not an agent. `payload` identifies immutable local
bytes. `target` links corresponding observations. Optional physical timestamps,
poses and calibration parameters remain null when not imported.

The source presence pool has six description files: `pool.json`,
`observations.jsonl`, `labels.jsonl`, `annotations.jsonl`, `provenance.jsonl`,
and `dataset.json`. Assets are deduplicated by SHA256. The retained source pool
contains 800 image PNGs, 342 unique mask PNGs and those six files: 1,148 physical
files, while still describing 400 mask references.

For presence, a binary label is 1 when the mask contains any class-4 pixel.
The reviewed pool quarantines one single-pixel case, yielding **399 pairs / 798
observations**. This review does not change the full segmentation benchmark.
Mask paths, hashes and class-pixel counts remain separate offline references.

## Preprocessing B: agent and tick allocation

`datasets/allocation.py` creates one `schedule.json`; it does not create more image
files. Agent settings specify modality, source streams and a per-agent maximum.
`partition` assigns each observation once; `replicate` explicitly allows sharing.
Unused observations are recorded; missing images are not duplicated or shifted
to another tick to meet a limit.

The old presence test uses 160 RGB assignments and 160 thermal assignments:
320 assignments across 160 frames. Its remaining observations belong to fitting
and validation. The PSTNet experiment currently uses fixed paired RGB and thermal
owners rather than the full general allocator.

## Model preprocessing and outputs

PSTNet RGB is resized bilinearly to 640 x 360 and divided by 255, without ImageNet
normalization. Masks use nearest-neighbor resize. When requested, thermal is
resized and its zero-valued holes are filled with OpenCV INPAINT_NS, radius 10,
before division by 255. Stored source images remain unchanged.

The historical presence CNN instead uses 384 x 216 and ImageNet normalization.
These are separate model-input contracts.

Presence replay stores configuration, model identity, summary, example, report,
CSV predictions and optional decision/delivery/transfer/experience JSONL traces.
Disabling traces changes output file counts. Segmentation training stores its
plan, training history, checkpoint identity, curves and fixed validation examples.
Replay logs refer to original image files instead of copying them at every tick.
