# Native RGB ROI-head fine-tuning

Prepared 2026-11-08 on top of ee5b8e26b88b556eff3e3dc30743ff2cd6b135eb.
The user authorized further RGB fitting after additive fusion21667369.
This experiment is implemented and locally tested with synthetic data. Native
Linux Cube R-CNN backward/gradient checks and actual training remain pending.

User-reported job21668971 failed after9m59s at an incorrect startup assertion:
the gate expected bare loss_cls, while pinned native output uses
BoxHead/loss_cls and Cube/loss_z. The guard now requires those exact keys BEFORE
backward/optimizer mutation. Synthetic tests use native names, reject missing
depth loss before updates, and verify foreground/background gate receipts.
Gate progress/actual values are printed, with returned-key diagnostics on error.
The four actual training epochs did not start. Keep this failed output and use
a fresh job-ID output on retry; native startup checks remain pending.

## Motivation

The supplied validation200 additive result preserves all LiDAR matches and
recovers110 extra GT appearances with baseline RGB,102 with depth-adapted RGB.
But it adds21943/21926 boxes and raises FP from7027 to27986/28060. With explicit
LiDAR-first ranking, mAP@.5 changes21.5380 ->22.0671/21.9834%; with original
raw scores it drops18.5275/18.1581%. Ranking protection is not evidence of good
precision. The previous adaptation fitted only the existing linear depth layer;
classification, 2D boxes, dimensions, pose and uncertainty did not learn.

## Actual scope

Train the native ROI 2D feature head, foreground/background classifier, 2D box
readout, full shared 3D feature head, center/depth/dimensions/pose readouts and
3D uncertainty. Backbone/FPN, RPN and priors stay frozen in eval mode. This is
head fine-tuning, not end-to-end image-backbone training. RPN proposals remain
image-derived; no LiDAR or annotations enter inference.

Replace11 fine outputs with the task's4 coarse outputs. Fixed initialization
uses mean existing rows for car/van, truck/bus/trailer, cyclist/motorcycle and
pedestrian, and preserves the background classifier row. Collapse class-specific
2D/3D readouts and dimension priors consistently. This mean is neither learned
nor an exact aggregation of the old probabilities. Evaluate the untrained
four-class initializer on the SAME600 frames to separate output surgery from
the subsequent training effect. The trained2Wheeler category includes all
UrbanIng2Wheeler supervision, including categories without an exact original
checkpoint counterpart.

Use pinned official native classification/2D/cuboid/uncertainty losses. The
foreground/background classifier learns from sampled RPN proposals, including
empty cameras. No BEV oracle filter, GT-based selection at inference, confidence
threshold search or final-model selection by validation is introduced.

## Supervision and geometry

TRAIN400 comprises only20241126_0001_crossing2_00 and20241126_0017_crossing1_00,
Car1, all six cameras. Derive camera centers, WHL dimensions and proper SO(3)
poses from annotated upright3D boxes and the unchanged native calibration.
Explicitly handle determinant-1 basis changes: the pose's third local axis is
the cross product of longitudinal and downward axes. Camera cuboid corner sets
and upright Car1 boxes roundtrip in tests under BOTH handednesses.

Project cuboids into each image. Front-facing boxes at least12px on both axes,
at least50% inside the image, within the existing100m support supervise
positives. Other intersecting front-facing boxes become ignore regions.
Skip an image when a near-plane-straddling cuboid intersects its field of view;
record all skips and positive support. Retain all original GT in evaluation.
Projected boxes are weak2D annotations: they are amodal and do not resolve
occlusion/visibility. This is a material limitation of the training labels.

Pinned upstream positive sampling is reused. Its empty-GT indexing failure is
handled in a narrow alternate sampler: remove proposals covered by ignore
regions and assign the remaining sampled proposals to background. Keep empty
cameras; do not silently turn the run into positive-only fitting. Fail if no
background proposal remains rather than continue with an undefined loss.

## Fixed training and controls

- Seed0; four fixed epochs across2400 TRAIN camera images, excluding declared
  near-plane skips. SGD lr1e-4, momentum.9, weight decay1e-4,100-update linear
  warmup; native128 ROI samples/image; gradient norm clipped at5.
- Fixed test resize from the official model; no augmentation or hyperparameter
  grid. Require supervision for each of the4 classes. Save each epoch and final
  head state, but evaluate only the final state. No resume is implemented.
- Disposable startup check on a real TRAIN image exercises native positive
  classification AND depth gradients, plus an artificially empty target for
  testing the background path. Discard ALL gate updates, restore initializer
  and RNG, verify frozen state and save/load prediction parity before fitting.
- Freeze and checksum the final serialized state before loading validation200
  from20241126_0004_crossing2_00. Re-evaluate TRAIN400 and then validation200;
  no crossing3, downloads, installations or new LiDAR inference.

Compare cached LiDAR, original outdoor RGB, prior depth-adapted RGB, four-class
initializer RGB and final fitted RGB. For initializer and final RGB also report
the SAME fixed additive raw-score and explicit LiDAR-first controls. Do not
select a winning fusion variant by these validation numbers. Predictions use
RGB+K only; additive fusion uses boxes/scores/classes only.

Reproduce source LiDAR/original-RGB/depth-RGB class AP@.3/.5/.7 in BOTH AP orders.
Write600 primitive outcome NPZs, then independently re-read them to reproduce
all new AP. Report class AP, macro AP and TP/FP/GT at IoU.5, TRAIN and validation
separately. LiDAR-first is source priority, not calibrated probability. Inspect
FP counts alongside AP. Two TRAIN recordings, one inspected validation recording
and one optimization seed do not establish held-out generalization.

## Run from Mac via SSH

Use a new worktree on the published fine-tuning branch. Submit:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_finetune.sbatch
```

Reuses read-only runtime21649159, outdoor model21655505 and completed source
ZIP21658632. Allocates8CPU/24GiB;24h is a scheduler ceiling, NOT an ETA. There
are up to9600 training image forwards and7200 initial/final evaluation forwards,
plus the native gate. Frozen backbone computation is repeated on CPU; this is
substantially more work than the earlier cached depth solve. Partial epoch
checkpoints are preserved if interrupted; do not claim automatic resume.

New output: `phdsim/runs/urbaning-rgb3d-finetune-JOBID`.
Logs in submit checkout: `urbaning-rgb-fit-JOBID.out/.err`.
Archive: `urbaning-rgb3d-finetune.zip`, including initialized/final heads,
training curves, support/inventory, freeze metadata, report and600 raw outputs.
Original weights, runtime and earlier experiment directories are not modified.

## Local verification

Eight focused tests cover exact coarse/background row initialization, tensor
shapes and trainable/frozen parameter boundaries, proper-pose/corner roundtrips
with either handedness, ignores and near-plane handling, TRAIN key rejection,
empty/ignore-only native sampler behavior, and a synthetic400/200 end-to-end
run with actual PyTorch SGD, fit-before-validation, all controls, source hashes,
archive integrity and independent saved-prediction AP replay. The synthetic run
uses a toy detector and one test epoch; it does NOT exercise compiled native
Cube R-CNN loss/ROIAlign/PyTorch3D. Native gate must pass on Ares before the
full experiment proceeds. Python/Bash syntax is checked locally.

See [thermal follow-up design](URBANING_THERMAL_PLAN.md).
