# Native RGB depth-head adaptation on CPU

Prepared 2026-11-07. This is an implemented experiment to run, not an achieved
accuracy gain. It fine-tunes an existing Cube R-CNN layer; no new BEV adapter or
learned fusion network is added.

## Motivation and current result

User-reported Ares21655505 completed the official outdoor checkpoint comparison
on the same8 TRAIN frames: RGB6.935736% (general checkpoint4.097309%), late
fusion27.024288% (general29.228132%), original LiDAR29.149123%. The source
outdoor ZIP has not been read locally; these numbers are user-reported. Better
standalone RGB did not improve the uncalibrated raw-score fusion rule. Do not
claim a modality improvement from this small already-inspected sample.

Earlier locally replayed GT-dependent error-factor controls on the general
model isolated substantial depth/localization error. They were diagnostics,
not deployable results or evidence that a trained head will reach those values.

## What is trained

Use the same official outdoor DLA34 checkpoint and private compiled CPU runtime.
Freeze image backbone/FPN/RPN, 2D detection, shared1024-dimensional RGB feature
generator, 2D center offsets, dimensions, pose and uncertainty/confidence.
Train only original `roi_heads.cube_head.bbox_3D_center_depth`: a1024-to-11
linear layer. At most11,275 existing scalar parameters change; categories with
fewer than32 positive TRAIN camera-object associations keep their original rows.
This is partial supervised RGB adaptation, not end-to-end detector training.

The official model predicts direct depth in virtual focal space. Capture the
EXACT input/output of its native depth layer; keep original-resolution K and
predicted center pixels. Check per-camera virtual-to-metric scaling against
the actual detector's decoded optical depth. For inference, multiply the learned
native-depth change by this scale and displace the original center along its
predicted camera ray. Sizes/poses/classes/scores remain unchanged. No LiDAR
values, proposals, detections or GT enter this operation.

Offline TRAIN supervision associates predicted2D boxes with projected GT by
same coarse class and greedy image IoU>=.5. Require all GT vertices in front,
clipped projected width/height>=12px and the existing100m corner-radius support.
Read native image shape, without assuming every source resolution. Target is
the optical-camera depth of the annotated3D object center. Image associations
can be ambiguous in occlusion; repeated views/frames are not independent tracks.

Fit fixed weighted ridge around pretrained weights in TRAIN-standardized feature
coordinates. Feature penalty10, intercept penalty1, standard-deviation floor
1e-4; mean-normalized inverse-square target-depth weights with a1-virtual-unit
floor. No penalty search, PCA, extra input features, iterative checkpoint
selection or validation tuning. Fold normalization/corrections algebraically
into the ORIGINAL layer's float32 weight/bias tensors. Save ordinary PyTorch
state dictionaries usable with native `load_state_dict(strict=True)`.

## Order and guards

1. Verify source outdoor assets and completed21655505 pilot. Its model identity,
   fixed8 TRAIN keys, GT/LiDAR arrays, native camera hashes/K/extrinsics/times
   must bind to the existing source packet. Record pilot archive SHA256 before
   fitting; the worker checks the reported6.935736% baseline.
2. Run a native TRAIN8 startup gate before full extraction: capture depth
   features, replay the original8 AP in BOTH modes, and temporarily perturb the
   ORIGINAL layer's bias. A real full detector forward must match cached-head
   replay; restore the original layer exactly and discard the perturbation.
3. Extract six-camera RGB features for400 TRAIN frames from0001 crossing2 and
   0017 crossing1. No new LiDAR inference. Fit the existing depth readout using
   TRAIN targets only, save the model/support/normalization-folded state and
   freeze its checksum.
4. Verify the ACTUAL fitted readout against a full native detector forward on a
   TRAIN example. Restore the original feature-extraction model before continuing.
5. Only after freeze, load200 development-validation records from0004 crossing2.
   Extract frozen features once and evaluate the already frozen trained head.
   No crossing3. The portable input packet contains both splits and its source
   engineering metadata may be checked earlier, but validation records never
   enter readout fitting or parameter selection.
6. Independently read written outcome NPZs to compute class AP@.3/.5/.7 and
   macro AP, global sorting primary and upstream ordering secondary. Check frozen
   model/runtime/source-weight hashes afterward. Keep all original GT at eval.

Compare on identical records:

- Cached original Car1 LiDAR.
- Frozen outdoor Car1 RGB.
- Same RGB with its native depth layer adapted.
- LiDAR + frozen RGB under the original union/NMS rule.
- LiDAR + adapted RGB under that SAME rule.

Report TRAIN and validation separately, with per-class AP and native fine-class
fit support. Offline depth MAE on the same image-matched observations is a
component diagnostic, not a replacement for mAP. Confidence calibration remains
unchanged; better depth need not improve naive late fusion. No new2D proposals
means this fit cannot recover objects the2D detector never proposed.

Two TRAIN recordings and one previously inspected validation recording are
limited development evidence, not a blind test or equal-training modality
ranking. The official LiDAR checkpoint has different training data/pretraining.

## Run and outputs

Existing source runtime21649159 and outdoor model/pilot21655505 are reused
read-only, with no install, download or compilation. Use a fresh checkout and:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_depth.sbatch
```

8CPU/24GiB,4h scheduler ceiling, not a completion estimate. Progress prints
native startup checks, TRAIN feature extraction, freeze, validation and replay.
The main compute is3600 frozen RGB image forwards; readout fitting is a small
deterministic linear solve. Do not quote the8-frame pilot time as a full-run ETA.

Default output: `phdsim/runs/urbaning-rgb3d-depth-JOBID`. NPZ+JSON camera caches
bind image/calibration/time/head/code hashes; verified entries are reused on an
interrupted retry with the SAME output argument. Resume rejects changed sources,
protocol, incomplete final cache pairs or corrupted payloads. A process lock
prevents simultaneous writers. A completed output is hash-verified and reused.

The source runtime/weights and previous pilot outputs are preserved. Original
and trained head states, freeze metadata, summary, all600 raw primitive outcome
files and feature receipts enter `urbaning-rgb3d-depth-controlled.zip`. Large RGB
features stay on Ares and are excluded from the download. Fusion is reproducible
from the primitive LiDAR/RGB arrays and fixed NMS rule.

## Validation before native submission

Four focused tests cover train-only fitting, forbidden validation keys, unchanged
unsupported rows, ray/scaling/no-op replay,2D supervision and an end-to-end
synthetic400-TRAIN/200-validation pipeline. The pipeline asserts fit occurs once
before validation, source data/weights remain unchanged, archive AP outcomes,
verified completed reuse and rejection of corrupt caches. Eight earlier RGB3D
tests also pass. Actual official outdoor native CPU forward verifies captured
1024-feature/virtual-depth parity and both a bias perturbation and a nontrivial
fitted readout against the ORIGINAL model; original head restored afterward.
The fitted-readout numerical test uses synthetic targets, not UrbanIng accuracy.
No controlled native training/validation result has run here.
