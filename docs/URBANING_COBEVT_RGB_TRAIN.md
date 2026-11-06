# Frozen-CoBEVT adapter: eight-frame TRAIN memorization check

Status2026-11-06: **implemented and locally checked; no Ares adapter training
run or native accuracy result yet.** This is the next gate after reviewed
preflight21597293. It is not an independent validation experiment.

## Scope and reuse

Use exactly the same8 native TRAIN frames:1,67,133,200 from each of
`20241126_0001_crossing2_00` and `20241126_0017_crossing1_00`.
The same frames are used for optimization and diagnostic evaluation.
No validation images/predictions, crossing3, peer payloads or network queries.
Existing validation provenance headers in the original portable packet are
checked by the shared loader, not evaluated.

Reuse the reviewed Car1-only final BEV caches from
`runs/urbaning-cobevt-rgb-preflight-21597293/features`. The preflight ZIP must
match SHA256
`8608d07b6862e3288718b0e4469ccb1e983439973c5a96e845cb2263048b9429`.
Verify every BEV NPZ hash, exact keys/native associations and48 image hashes.
Reload only the official frozen classification/regression heads, not the
LiDAR backbone or inter-agent transformer. Replaying the loaded features
must agree with every cached native logit within1e-6 before optimization.
No new source download/conversion or LiDAR detector inference is needed.

## RGB representation and trainable part

Frozen ImageNet MobileNetV3-small `features[:9]`,48 channels at stride16:
six384x640 images produce6x48x24x40 spatial maps. No global average pooling,
PCA or random channel compression. Use existing official pinned weights and
the established isolated torchvision0.21.0+cpu bootstrap.

Calibrated bilinear voxel pull samples at0.2,0.8,1.5,2.5m above a ground-z
median from near TRAIN GT boxes. Average valid camera samples at each plane.
Concatenate192 feature and4 camera-count channels on the **original100x256
rectangular metric BEV**, not the earlier200x200 square. Require its cell
centers to match official anchor centers. Features are quantized to float16
when cached, then converted back to float32 consistently for fresh/resumed runs.
CNN parameters are frozen; there is no learned depth or occlusion reasoning.
The lifting remains an explicit approximation, not official camera-CoBEVT
or a BEVFusion reproduction.

Fit channel normalization on these8 TRAIN frames only, ignoring unobserved
RGB cells. Missing RGB evidence stays zero. A small residual network receives
normalized LiDAR256 + RGB196 + coordinate2 channels, projects to16 channels,
uses a3x3 convolution, then outputs256 feature corrections. It starts with
an exactly zero final layer. Corrections are bounded by one TRAIN channel
standard deviation via tanh; this is fixed a priori and limits expressiveness.
The original detection heads remain frozen but permit gradients to their input.

## Controlled variants

| Variant | Trainable input/context | Purpose |
|---|---|---|
| `original_lidar` | None; unchanged cached BEV and original heads | Actual start-point detector |
| `lidar_adapter` | LiDAR + coordinates; all RGB/count channels zero | Same-architecture/capacity adaptation control |
| `lidar_rgb_adapter` | LiDAR + aligned RGB + coordinates | Addition of RGB to this frozen detector |
| `lidar_rgb_shuffled_diagnostic` | Frozen trained RGB adapter; cyclically shifted RGB within each recording | GT-free alignment diagnostic; no refitting |

Both learned variants have identical parameter counts, initial weights,
epoch permutations and schedule. A gain over raw LiDAR alone is not solely
an RGB gain: compare aligned RGB to the trained LiDAR adapter. Both variants
always retain LiDAR. **There is no RGB-only detector in this experiment.**

## Targets, objective and evaluation

Use the pinned upstream `VoxelPostprocessor.generate_label` and
`PointPillarLoss`: class-aware anchor assignment, sigmoid focal classification
and SmoothL1 regression with the original coefficients/sine-yaw handling.
Train from all radius-filtered cached GT, not just correct LiDAR proposals;
do not require a Car1 LiDAR hit for target eligibility. Verify GT corner/center
round trips preserve BEV geometry. Report positive anchors per class/frame.
The native anchor extent can limit supervision; no GT is removed from evaluation.

Two adapters, **64 fixed epochs x8 frames =512 updates each**, batch1,
seed0, AdamW lr.001/weight decay.0001, gradient clip1, raw residual L2 penalty
.0001. No parameter sweep, early stopping or best-epoch selection. Atomic
model/optimizer/history checkpoints at each epoch permit exact epoch-boundary
resume. The output configuration includes implementation and source identities;
different code/settings require a new output directory.

Evaluate the final epoch with the **unchanged official postprocessor**, anchors,
confidence threshold, NMS and original validation-range clipping. Freshly match
all exported boxes to the original unchanged GT. Main metric remains four-class
global-confidence-sort BEV VOC mAP@IoU.5 with the same0–100m corner-radius
filter. Per-class AP and.3/.7/default-order AP stay separately reported.
If a class has no GT in this tiny sample, four-class macro mAP is explicitly
undefined; do not average fewer classes or silently replace it with F1.

Save initial/final detection loss, epoch loss components, train-only mAP,
raw prediction/GT NPZs for all4 variants, models/normalizers/config/provenance
and BEV comparison figures. Loss decrease is a trainability diagnostic,
not automatically an AP gain. Eight-frame performance proves neither
generalization nor useful fusion; the official checkpoint may have seen
these development recordings. Native camera timing offsets remain offline.

## Ares command

From the new checkout root:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_cobevt_rgb_train.sbatch
```

Uses8CPU/24GiB/**2h upper limit**, not an ETA. Reuses the existing Singularity
wrapper and official cached ImageNet weights. torchvision is installed only
into the private output dependency target if needed; no shared venv change.
No GPU allocation is assumed. Default output:
`phdsim/runs/urbaning-cobevt-rgb-adapter-train8-001`.
Repeat the same command at the same commit to resume the last full epoch;
a lock rejects concurrent writers. A completed ZIP is reused after checksum
verification. Existing preflight caches and original model remain unchanged.

The job prints cache/head parity, RGB feature progress, losses/measured step
time and final TRAIN metrics. Return
`urbaning-cobevt-rgb-adapter-train8.zip`; larger RGB caches remain on Ares.

## Local checks

Eight focused trainer checks cover rectangular lifting and missing-view masks;
strict RGB exclusion from the LiDAR control; zero-start/bounded corrections;
gradients through frozen heads without changing their weights; loss decrease;
exact interrupted-epoch resume; within-recording GT-free shuffle; unchanged
raw-GT export/missing-class AP handling; complete synthetic8-frame training,
report/model/prediction/ZIP export and completed resume. Six previous adapter/
preflight checks also pass. The complete synthetic test mocks upstream I/O,
RGB extraction and decoding; its artificial AP values are not research results.

Separately exercised the actual pinned upstream `PointPillarLoss` at native
BEV[1,256,100,256], heads32/56 and context454 channels: CPU forward/backward/
update works, loss falls across10 synthetic steps and head gradients stay
absent. Measured~.29s/step on4 local threads, excluding native I/O, decoder
and Ares variability. This is not an Ares duration estimate. Source/API review
covered the pinned target generator/postprocessor. Full native adapter training
and post-training decoding remain untested until the Ares run.
