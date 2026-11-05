# Proposal-independent Car1 BEV detection on CPU

Prepared 2026-11-05 after the user explicitly asked to keep working on CPU
while a GPU grant is unavailable. **No Ares result or submission yet.**

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
rates/ETA. Actual native Ares performance and detection AP remain unmeasured.

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
