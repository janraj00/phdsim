# Proposal-independent Car1 BEV detection on CPU

Completed Ares run **21594614**, audited 2026-11-06. The prototype produced
poor detection results; it is not a validated multimodal baseline.

## Completed run and offline audit

Source commit: `8e83d2cbd027c5ee0efadb9ac4778e8611eaa18b`. Supplied ZIP
SHA256 `698dd3e9619d10daf2c6c426650cda2eac51143604e888742bce2913d8c28152`,
11,205,878 bytes, valid CRC. All three recorded source hashes match. Internal
feature/training/evaluation timer is1217.10s; full scheduler elapsed was not
provided. No new training or detector calls were made during this audit.

Primary metric remains four-class BEV VOC mAP@IoU.5, global confidence sort,
historical0–100m corner-radius filter. Percent values:

| Model | Reported training diagnostic,40 frames | Validation,200 frames |
|---|---:|---:|
| RGB | 2.8140 | 0.5490 |
| LiDAR | 16.8878 | 2.7615 |
| RGB+LiDAR | 16.1355 | 1.5882 |
| Separately pretrained CoBEVT reference | Not provided | 21.5380 |

The training column is a final-model diagnostic on a different40-frame sample,
not an epoch curve or a matched train/validation comparison. Training predictions
are absent from the ZIP; these training AP numbers were not independently
replayed. Decreasing training loss and this gap do not identify a cause.

The audit replays all600 exported validation NPZs (200 per mode), checks common
frame keys and byte-identical GT, and freshly matches each model's boxes.
All class AP and macro AP at.3/.5/.7, in both ordering modes, reproduce exactly
with NumPy1.26.4. This is recomputation with the existing metric implementation,
not an independently implemented second evaluator. CoBEVT raw predictions are
not included, so its external-reference number is not replayed in this audit.

### What is failing in the learned predictions

LiDAR-only at the original fixed decode settings, on all200 validation frames:

| Class | GT instances | Predictions after radius filter | Correct matches atIoU.5 |
|---|---:|---:|---:|
| Vehicle | 12241 | 7872 | 1972 |
| Heavy_Vehicle | 249 | 6557 | 0 |
| 2Wheeler | 289 | 7793 | 13 |
| Pedestrian | 2158 | 7907 | 22 |

These are per-frame instances, not unique objects. Counts use the fixed.05
confidence threshold; they are not new primary metrics. The median distance
from a predicted Vehicle center to the nearest same-class GT center is1.47m
for LiDAR,1.97m for fusion and4.14m for RGB. This one-way nearest-center
diagnostic permits duplicate associations and is not detection recall.
Many predictions are misplaced or unsupported, especially for minority classes.
The archive alone cannot determine whether errors originate in features,
projection, optimization or generalization.

### Offline GT target/decode diagnostic — NOT a model result

To check whether the box representation/decoder itself could explain the very
low AP, insert exact validation-GT heat peaks and regression targets into the
existing decoder. No model features or predictions are used in this check.
Every original GT stays in evaluation, including cell collisions.

| GT-assisted diagnostic | BEV mAP@.5 (%) | Vehicle recall (%) | Pedestrian recall (%) |
|---|---:|---:|---:|
| Original top40/class and NMS.2 | 88.9273 | 63.5406 | 92.1687 |
| Relaxed cap500/class and NMS1 | 98.0422 | 100.0000 | 92.1687 |

Both Heavy_Vehicle and2Wheeler recall are100% in these checks. There are14937
radius-filtered validation GT,0 outside-grid target centers,169 same-class
cell collisions; the pedestrian recall deficit matches those169 collisions.
Original training target collisions were29/22763, a separate count.

The default cap40/class is inadequate for an average61.2 Vehicle GT/frame,
and NMS can also discard correct nearby boxes. The relaxed row jointly changes
cap/NMS: it does not isolate their separate effects. Because all exact target
peaks have equal score, the capped oracle selection follows deterministic cell
order rather than an optimal ranking. These are attainable outputs for this
GT-assisted construction, not a general AP upper bound or deployable results.

The representation can decode accurate geometry when supplied correct targets;
therefore neither coarse cells nor these decode limits alone explain0–3% model
mAP. This does not validate native image/point alignment: input BEV feature
caches and native payloads are absent from the archive. Do not change the saved
model, reported protocol or primary metric based on this diagnostic.

### Next gate before larger training

Use a tiny fixed set of native TRAIN frames: inspect point/image/GT alignment
and feature occupancy, then train and evaluate on those exact frames to test
memorization. This is a training sanity check, not a validation improvement
claim. Export per-class AP, heat/box losses, predictions and overlays. Only
after that succeeds should larger training or architecture changes be assessed.
No new job is prepared/submitted by this audit; all original models are retained.

Reproduce the archive audit from the matching source version:

```bash
PYTHONPATH=src python scripts/audit_urbaning_bev_cpu.py \
  /path/to/extracted/urbaning-bev-cpu \
  --output /path/to/audit.json
```

It requires the existing pinned CPU torch/NumPy runtime; the audit does not
install packages, train, read crossing3 or use a GPU.


## What this measures

Train three small Car1 detectors that produce new box centers, sizes, heights
and orientations. They are independent of CoBEVT proposals and scores:

| Model | Actual input to the learned model |
|---|---|
| `rgb` | Six RGB camera feature maps lifted through calibration; point channels zeroed |
| `lidar` | Three geometry-only point-grid channels from Car1; RGB channels zeroed |
| `rgb_lidar` | Both input groups |
| `cobevt_lidar_reference` | Historical cached CoBEVT ego-only results; separately trained external reference |

The three prototype heads have the same architecture, number of parameters,
initial weights, frame order, optimizer and fixed8-epoch schedule. Only the
modality gate differs. The RGB encoder is pretrained on ImageNet and frozen;
the point encoder is a classical grid descriptor. Thus this is a comparison
within this specified prototype, not a universal ranking of sensor modalities.
The old pretrained CoBEVT may have seen these development recordings and uses
different training data and a different architecture. Its number is context,
not the controlled modality ablation.

**The previous CPU RGB scorer is a separate experiment.** Its26 positive two-
wheeler examples were correct LiDAR proposals, not the entire training GT.
The original400 training frames contain these radius-filtered GT instances:
Vehicle18196,Heavy_Vehicle1258,2Wheeler389,Pedestrian2920. This new model learns
from all train GT, including objects without a correct LiDAR proposal. Counts
are frame instances, not independent physical objects.

## Small architecture, explicit approximations

Frozen torchvision0.21.0+cpu MobileNetV3-small IMAGENET1K_V1 spatial features,
input384x640 RGB with ImageNet normalization. Project576 channels to16 with a
fixed PCG64-seed0 normal matrix divided bysqrt576, without fitting to labels.
Use calibrated bilinear sampling from six images at four heights above a
train-only median ground-z prior:0.2,0.8,1.5,2.5m. Average valid camera samples,
concatenate height slices and geometric camera-count masks. Grid:200x200 over
[-110,110]m in each converted Car1 axis, **1.1m cells**. This covers the previous
0–100m corner-radius evaluation region without tightening its GT mask.

The voxel-pull idea is motivated by
[Simple-BEV](https://simple-bev.github.io/), whose official task/model is not
reproduced here. This implementation and the small box head are new prototype
code. It is also **not BEVFusion**, and does not claim to reproduce either
paper's results. Depth/occlusion remain ambiguous; the frozen encoder,16-channel
compression, four height planes and coarse cells can limit accuracy.

For LiDAR, read only Car1's hashed converted uncompressed PCD. Build log point
count, maximum height and mean height per cell, with a fixed vertical range
[-1,+6]m above the learned ground prior. No intensity, peer point clouds,
peer predictions or GT enters these runtime features. A small reader handles
the pinned converter's binary/ASCII PCD without importing Open3D. RGB-only
predictions are numerically invariant to changes in LiDAR values; vice versa
for LiDAR-only. Input feature caches store both arrays for the three-model
experiment, but the selected head receives only its allowed arrays plus zeros
for the other modality and shared x/y coordinate channels.

The head uses1x1 projection to24 channels, two3x3 convolutions, GroupNorm/SiLU,
four center heatmaps and class-specific8-value box regression. Train from all
radius-filtered GT: Gaussian center heatmaps/focal loss and SmoothL1 residual
box regression around train-only per-class size/z/orientation priors. No GT
box or LiDAR proposal determines a prediction's location at inference.

Multiple same-class GT centers in one cell cannot all be represented: retain
first target deterministically and report collisions; **do not remove any GT
from evaluation**. Outside-grid target centers are also counted without
removing their GT at evaluation. These model limits must remain visible.
Decode fixed local maxima, score>=.05, at most40 candidates per class, same-
class oriented BEV NMS atIoU.2. No threshold search on validation.

## Data, training and evaluation

Reuse the exact existing immutable train/validation payloads, rectified images,
calibration and original AP-export provenance. No new dataset download or
conversion. Verify run/trace/GT/prediction/YAML hashes, converter commit and
native image association through the existing loader. Separately verify Car1
PCD bytes against the original trace. Cache each frame's BEV features with
image/point/calibration/encoder/code/ground-prior identities and its own hash.
Native camera associations remain offline and can be-1..+45ms from anchor.

- Train400: `20241126_0001_crossing2_00`, `20241126_0017_crossing1_00`.
- Development validation200: `20241126_0004_crossing2_00`.
- No crossing3 access. The validation has already been inspected repeatedly;
  it is not a new blind test. Two train recordings limit generalization.
- Train-only priors/targets; no validation model selection or early stopping.
- Fixed8 epochs per model, batch1, seed0, AdamW lr.001/weight decay.0001,
  gradient norm clipping10, same epoch permutations for all modalities.
- Final epoch is evaluated, not the best observed validation epoch.
- Additional training diagnostic:20 uniformly selected frames per training
  recording,40 total. This is not model selection.

Primary: the same four-class **BEV polygon VOC mAP@IoU0.5, global confidence
sort**, with the historical0–100m corner-radius filter. Class AP at.3/.5/.7
and historical frame-order AP are separate diagnostics. Every model's new
boxes are matched to the unchanged GT; old TP flags are not reused.
Save raw per-frame predictions+GT in the result ZIP to permit independent AP
recomputation later. No peer queries, ROI transmissions or uncertainty claim.

## Ares execution and cost

Confirmed on2026-11-05: `plgkgacq-cpu` only,25000CPU-hours granted,
406.21 consumed; no GPU allocation. Keep this experiment on CPU.

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_bev_cpu.sbatch
```

Default output: `$WORK/phdsim/runs/urbaning-bev-cpu-001`.
Eight CPU cores,24GiB RAM,6h upper limit (at most48 allocated CPU-hours,
not an expected duration). Reuse the existing container/wrapper and isolated
pinned torchvision bootstrap. Existing official ImageNet weights are read from
`runs/urbaning-rgb-pilot-001/weights`, with the same full weight hash check.
No shared venv edits or GPU dependencies are introduced.

Feature arrays for600 frames are roughly3.3GB uncompressed, plus metadata,
models and result files. Request at least8GiB free filesystem space; filesystem
free space is not a check of the group's storage quota. Sources stay intact.
At runtime cache arrays are kept in RAM; the24GiB allocation includes head/CNN
and evaluator overhead. There is no reuse of the old proposal-crop features:
these are different, full-image spatial features.

Local measured compatibility smoke on4 CPU threads: six synthetic1080p images
resized384x640, frozen encoder and voxel lifting took~0.49s; a200x200 training
step took~0.067s over10 updates. These numbers exclude Ares filesystem I/O,
queue, native-data variation and full evaluation. They are not an Ares wall-
time promise. The job prints measured feature extraction and per-model training
rates/ETA. Completed native Ares results and timing are recorded above.

Atomic feature caches and a locked stable output directory allow resume.
Checkpoints save model, optimizer, deterministic epoch/frame cursor, loss sums
and history every50 updates and each epoch. Interrupted optimization was tested
to reproduce uninterrupted final weights/history exactly. Configuration/code
changes require a new output; old models are retained. Completed output ZIP
receipts are checked before returning on a completed rerun.

Outputs: `summary.md`, `report.json`, train-only priors/support, training-loss
history, three final models,200 prediction/GT NPZs per variant and three BEV
plots comparing all models with the old external CoBEVT reference. Feature
cache stays on Ares and is excluded from `urbaning-bev-cpu.zip`.

## Validation performed before submission

Eleven focused tests passed: oracle box-target/decode roundtrip at varied yaw
and four classes; unchanged existing BEV matching; calibrated bilinear lifting
and view masking; modality isolation; point-grid clipping/empty bins; hashed
PCD decoding; GT-free feature extraction/cache integrity; collision accounting;
synthetic overfit with no old LiDAR proposals; final and mid-epoch checkpoint
resume; synthetic full three-model fit/evaluation/export/completed resume.
Actual pinned frozen RGB weights and full-size CPU feature/training operations
were exercised locally. Shell syntax and Python compilation passed. No native
UrbanIng RGB training run or successful AP result is claimed before Ares.
