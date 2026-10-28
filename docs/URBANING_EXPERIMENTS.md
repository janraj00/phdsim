# UrbanIng-V2X experiment status

The current study uses the authors' frozen **LiDAR CoBEVT** detector for
cooperative object detection and offline selective acquisition. Outputs are
3D boxes with classes and scores; the reported metric uses **BEV polygon IoU**.
RGB and thermal cameras are not inputs to this stage.

## Task and naming

At each evaluated timestamp, **Car1** detects and localizes objects in a fixed
evaluation region using Car1.LiDAR and any selected partner sources. All variants
use the same all-source ground truth for that frame. The acquisition question
is whether to request Car2, Infra, both or neither before seeing their observations.

| Name in this study | Official source ID | Stage 1 input |
|---|---|---|
| Car1 | `100000` | `Car1.LiDAR` |
| Car2 | `200000` | `Car2.LiDAR` |
| Infra | `-1` for the recorded crossing1 sequence | `Infra.LiDAR`, the bundled roadside clouds |

Car1 and Car2 are fixed platform names; the agent performing detection is a
separate role. This pilot evaluates Car1 only. Other crossings use site IDs
`-2` or `-3`. Infra is one site-level source in this adapter, not one physical
pole or one camera. Code action identifiers are mapped in the
[stage 1 protocol](URBANING_STAGE1.md).

This study is separate from [PST900 / PSTNet segmentation](PSTNET_EXPERIMENTS.md);
their mIoU numbers are not UrbanIng detection results. Return to the
[experiment index](EXPERIMENTS.md) for the repository overview.

## UrbanIng CoBEVT CPU smoke evaluation — 2026-10-23

The frozen official `CoBEVT_SIS_1_2_vs_3` checkpoint completed real-data offline
evaluation on 20 frames of `20241126_0017_crossing1_00`, with **Car1** (vehicle
`100000`) performing the detection task. The native release 1.0 sequence was
downloaded and verified; the unchanged
official converter processed two bounded source views. Execution used Linux
x86_64, Python 3.12.14, CPU PyTorch 2.6.0 and two model threads. The model was not
retrained. See [protocol, dependencies and commands](URBANING_STAGE1.md).

Frames 1–10 contain only Car1 and Infra within the upstream 70m range.
Vehicle-class AP at BEV IoU 0.5 was **43.16%** for Car1.LiDAR and **91.99%** for
Car1.LiDAR + Infra.LiDAR. There were no annotated 2Wheelers in this window, so four-class
macro AP is undefined and reported as null.

Frames 101–110 have all three sources available. Each row below uses the same
ground truth: 726 Vehicle, 31 Heavy_Vehicle, 19 2Wheeler and 100 Pedestrian
object annotations across frames. These are not counts of distinct tracks.

| Sources / policy (LiDAR only) | BEV mAP @ IoU 0.5, four classes | Vehicle AP @ IoU 0.5 | Peer requests/frame |
|---|---:|---:|---:|
| Car1 | 24.76% | 56.77% | 0 |
| Car1 + Car2 | 36.14% | 73.88% | 1 |
| Car1 + Infra | 47.53% | 81.16% | 1 |
| Car1 + Car2 + Infra | 53.21% | 90.81% | 2 |
| Car1 + one randomly selected partner | 42.04% | 77.20% | 1 |
| Car1 with entropy gate, threshold 0.5 | 42.04% | 77.20% | 1 |

The example entropy threshold requested one peer in every evaluated frame;
its outcome therefore equals random-one-peer here. This is **not evidence of an
effective adaptive stopping policy**. In the middle window, choosing one partner
halves request count relative to all sources, but no byte or latency saving was
measured. 2Wheeler AP remains weak even with cooperation.

These are **diagnostic results on one crossing1 recording**, not a held-out
benchmark, significance test or paper reproduction. The checkpoint's held-out
crossing is crossing3, which was not used. Threshold calibration, matched-budget
controls, recording-level evaluation, both ego vehicles, full test aggregation,
GPU execution and online replay remain follow-up work.

Local artifacts: `runs/urbaning-stage1-cpu-smoke-001/` and
`runs/urbaning-stage1-cpu-mid10-001/`. Each has configuration/provenance, native
associations, source hashes, per-action predictions, shared GT and metrics.
Raw data, model weights and run artifacts remain outside Git.

## Local run ledger

| Directory under `runs/` | Purpose |
|---|---|
| `urbaning-stage1-cpu-smoke-001/` | Frozen CoBEVT, crossing1 frames 1–10, Car1, CPU |
| `urbaning-stage1-cpu-mid10-001/` | Frozen CoBEVT, crossing1 frames 101–110, Car1, CPU |

`runs/` is local and Git-ignored. These artifacts record the completed pilot;
their availability on a particular machine must be checked separately.
