# Controlled Car1 LiDAR/RGB adapter development experiment

Status2026-11-06: implemented and locally checked; **not submitted or completed
on Ares yet**. This follows the user's reported TRAIN8 run21599501, not a claim
that the observed training gain generalizes.

## Question and fixed comparison

Does aligned Car1 RGB help the frozen official CoBEVT detector on a separate
development recording, beyond an equally trainable LiDAR-only adapter?
The primary difference is **LiDAR+RGB adapter minus LiDAR adapter**, with the
original unchanged LiDAR detector also reported. Primary evaluation remains
four-class BEV VOC mAP@IoU.5, global confidence sorting and the original0–100m
corner-radius filter. Preserve per-class AP, IoU.3/.7 and the upstream frame-order
AP separately. There is no F1 substitution or acquisition policy in this test.

| Variant | Training input | Validation input | Role |
|---|---|---|---|
| `original_lidar` | None | Original Car1 LiDAR BEV, frozen heads | Unchanged reference |
| `lidar_adapter` | LiDAR + coordinates; ALL RGB/count channels zero | Same | Same-capacity adaptation control |
| `lidar_rgb_adapter` | LiDAR + aligned RGB + coordinates | Same | Primary RGB variant |
| `lidar_rgb_shuffled_train_control` | LiDAR + RGB from another TRAIN frame | ALIGNED validation RGB | Check useful training correspondence |
| `lidar_rgb_shuffled_eval_diagnostic` | No additional fitting; use aligned-trained model | RGB from another validation frame | Offline dependence/alignment diagnostic |

The shuffled-training control receives exactly the same aligned validation
inputs as the aligned-trained model. Its training RGB is a fixed half-recording
cyclic rotation of sorted frame keys. This is GT/score-free and stays within
each original recording. The evaluation diagnostic independently rotates ONLY
the validation recording. With200 frames the donor is100 frame positions away;
this avoids the near-identical neighboring-frame shuffle. It still does not
guarantee unrelated scene content or prove semantic understanding.

## Fixed data and schedule

| Split | Sequence | Frames |
|---|---|---:|
| TRAIN | `20241126_0001_crossing2_00` | 200 |
| TRAIN | `20241126_0017_crossing1_00` | 200 |
| Development validation | `20241126_0004_crossing2_00` | 200 |

Assert disjoint original recording IDs, unique frame keys, exact counts and no
crossing3. Reuse the existing hash-bound portable input packet, native source
associations, converted calibration, point payloads and unchanged cached GT.
The validation recording has been inspected in previous experiments; this is
**not a new blind test**. The official checkpoint may have seen these development
recordings. Incremental adapter comparison remains paired on the same frozen
detector, but cannot establish independence of the pretrained backbone.

Three paired optimization seeds:0,1,2. Every trainable mode gets **32 fixed
epochs x400 frames=12800 updates**;115200 updates across9 models. Final epoch
only: no validation sweep, early stopping, best-checkpoint choice, ensemble or
changing the schedule after seeing a seed's validation result. The TRAIN8
memorization check used64 epochs on8 frames; this is a separately frozen
full-development schedule, not an extension of its fitted models.

Same architecture/capacity, initialization, epoch frame order, loss, optimizer
and update count within each seed. Verify matching initial state hashes and
parameter counts. Retain the TRAIN8 bounded zero-start residual architecture
(13952 trainable parameters at454 context channels), frozen original32/56 heads,
actual upstream anchor targets/focal+regression loss, AdamW.001/weight decay.0001,
gradient clip1 and raw-residual penalty.0001. All GT remains in evaluation,
including LiDAR misses. All learned variants retain LiDAR; no RGB-only claim.

## Features and resource use

Reuse eight SHA-verified reviewed native TRAIN BEV caches. For the other592
frames run one frozen Car1-only native backbone/fusion forward per frame and
cache its final256x100x256 BEV. Each new forward uses a deterministic per-key
NumPy/Python/torch seed; the reviewed eight retain their original preprocessing.
Native point sampling can therefore differ from historical full-run order.
**Use this experiment's shared reloaded-feature baseline**, not the21.5380%
historical Car1 result as if exact equality were established.

Restore channels-last memory layout after lossless float32 LiDAR loading.
Check cached/native logits, unchanged native decoding, GT matching and both AP
orders per frame using the existing audited guard. Record hashes/strides/errors.
Do not overwrite the reviewed preflight, source payloads or old trained models.

Frozen ImageNet MobileNet stride16 spatial maps are lifted onto the original
rectangular grid with the existing calibrated four-height approximation.
Ground-z prior and all normalization are learned from TRAIN only. RGB is cached
as float16 and consistently converted to float32; reject non-finite quantization.
Missing RGB evidence stays zero. Save TRAIN anchor targets once; validation GT
is used only for source checks/offline parity and final detection evaluation.

Streaming training keeps only two decoded feature frames cached in Python,
computes one context at a time and reads targets on demand. It does not hold
all400 normalized contexts in RAM. Approximate additional cache is30GB before
filesystem/compression effects; the download ZIP excludes these large caches.
Use8CPU/24GiB per worker, maximum two concurrent feature workers or seed workers.
No GPU or shared-venv change. Wall-time limits are ceilings, not ETAs; logs print
measured extraction progress and per-model optimization speed.

## Stages, checks and restart

One submit command creates an `afterok` dependency chain:

1. Inventory/source checks and TRAIN ground prior; private torchvision bootstrap.
2. Native startup gate on two TRAIN frames: one reviewed reuse and one new
   native forward, RGB lifting, target serialization, zero-start parity,
   three disposable one-update adapter probes and original decoder. Gate-only
   weights/normalization are discarded; its feature caches are reusable.
3. Three sequence feature tasks, at most two concurrently.
4. Streaming TRAIN-only normalization and fixed training shuffle manifest.
5. Three seed tasks, at most two concurrently. Each fits all3 models, writes
   final checksums/freeze receipt, THEN loads validation records/features for
   evaluation. Source/GT may already have been used by engineering parity
   checks, but no validation statistic enters fitting or normalization.
6. Independent raw-prediction AP replay and aggregation/ZIP export.

Per-stage/index locks reject concurrent writers. Feature manifests verify
source/config/hash bindings. Model and optimizer checkpoints every100 updates
and each epoch resume the same frame order; configuration/source drift fails
instead of silently reusing old artifacts. Completed seeds and archives are
verified/reused. Preserve the same detached checkout/output for a restart;
use a fresh output if numerical code or settings change.

Run from the new controlled checkout:

```bash
bash scripts/slurm/submit_urbaning_cobevt_rgb_controlled.sh
```

Default output:
`/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-cobevt-rgb-controlled-001`.
All logs are in its `logs/` subdirectory. The submitter prints the inventory,
gate, feature-array, normalization, fit-array and report job IDs. The inventory,
gate, features, normalization, seed and collector ceilings are respectively
30min/1h/24h/2h/48h/2h. Failure prevents dependent computation from starting.

## Outputs and interpretation

Return `urbaning-cobevt-rgb-controlled.zip`: protocol/inventory, TRAIN-only
normalizers, shuffle mapping, freeze/source receipts, all9 final adapters,
training curves, raw prediction/GT NPZs for all5 validation variants and all3
seeds, per-class AP and both AP orders, mean/SD and the three paired RGB-minus-
LiDAR-adapter deltas. The collector verifies identical frame/GT bindings,
frozen model/normalizer hashes and baseline metrics across seeds, then independently
replays AP from every exported prediction file before publishing the report.

Seed SD measures optimization variability; it is **not** a confidence interval
over independent recordings. Do not pool predictions across seeds as an ensemble.
One development validation recording cannot settle cross-site generalization.
Fixed sparse lifting still has depth/occlusion ambiguity; native camera time
offsets remain offline metadata. A future crossing3 evaluation needs a separately
frozen protocol; this job never accesses crossing3.

## Local verification

Nine new controlled tests pass, including a native-size feature/head/lifting/
cache round trip with mocked dataset I/O/encoder, new-vs-reviewed cache paths,
cache reuse without backbone calls, TRAIN-only streaming-normalizer parity,
half-recording shuffle, bounded cache/corruption rejection, exact mid-epoch
resume and matching initial weights, discarded startup-probe state, full
three-seed freeze/held-out-evaluation/export/replay/reuse with synthetic outcomes,
and fake-Slurm dependency/concurrency validation. The13 trainer and6 previous
adapter/preflight checks also pass (28 total). Existing bootstrap has3 separate
child-process regression checks and actual pinned RGB-encoder startup coverage.
Synthetic perfect AP in tests is never a research result.

Additionally exercised this new optimizer at the full1x256x100x256 channels-last
shape with the actual pinned upstream PointPillarLoss: two CPU updates passed,
frozen head gradients stayed absent; approximately.30s for the first update on
four local threads. This excludes native source I/O and is not an Ares ETA.
Real Ares native sequence extraction/400-frame fitting remains pending.
