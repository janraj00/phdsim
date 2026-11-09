# Thermal as an infrastructure observation

Thermal detector/fusion training remains unimplemented; the current RGB fitting
stays separate.

## Local label-projection audit (2026-11-08)

A read-only audit on the locally available TRAIN sequence
`20241126_0017_crossing1_00` found 1,200 associated thermal views (six cameras,
200 anchors), with annotation labels on every anchor. Camera captures are
+8..+41 ms from their anchors (median +20 ms). After rectification, 3D labels
projected with at least 12 pixels on each axis and at least 50% of their area
inside the image gave `[21395, 959, 306, 2591]` positive per-view appearances
for Vehicle/Heavy_Vehicle/2Wheeler/Pedestrian, and `[3365, 8, 33, 786]`
near-plane-straddling per-view boxes to ignore. Counts duplicate the same object
across cameras and time; they are support appearances, not unique objects.

This verifies useful label coverage on one crossing1 TRAIN sequence only. It
does not measure frozen-RPN proposal recall or detector performance and says
nothing yet about crossing2 transfer. Thermal data availability at the Ares
data root still needs confirmation. Before spending on training, run a sampled
native frozen-RPN recall gate against projected thermal boxes. Stop if proposals
rarely cover positives. If it passes, use a one-epoch, four-class native-head
pilot, then compare thermal-only with fixed LiDAR-first fusion on the same
development frames. Preserve the actual thermal capture offsets and make no
independent-test claim.

## Frozen-RPN gate prepared (2026-11-09)

The desktop SSH environment could not resolve `ares.cyfronet.pl`, so the Ares
filesystem could not be inspected here and no job was submitted. Prepared
`scripts/urbaning_thermal_rpn_gate.py` plus
`scripts/slurm/urbaning_thermal_rpn_gate.sbatch` to check the frozen official
outdoor RPN on twelve uniform TRAIN anchors from the confirmed crossing1 sequence
(up to72 camera views). It uses the existing immutable Car1 source packet for
frame/GT bindings, raw associated thermal images and calibration, and the
revised per-object near-plane ignore rule. It records per-class proposal recall
at IoU .3/.5/.7 and native capture offsets; no weights are updated and no
validation data is loaded. The fixed pass gates require at least five sampled
positive GT boxes in every class, macro recall >=.25 at IoU .3 and >=.10 at IoU
.5. These thresholds are a stop/go criterion for this pilot, not a benchmark
result. Ares auto-detects the extracted source under the expected
`data/` or `inputs/` roots; override with `URBANING_DATA_ROOT` if needed. If the
gate fails, stop before training. If it passes, prepare a separate one-epoch
training job with explicit thermal-only and LiDAR-first controls.

First submission21694006 failed in10s before data access: the entry point did
not prepend this checkout's `src/`, so the runtime imported an older installed
`phdsim` package and could not find the RGB fine-tuning reader. The retry
entry point now adds its own checkout source first. The startup echo now also
matches the actual twelve-anchor, one-sequence sample. No model/data processing
occurred in the failed job; retry with fresh output.

Retry21694226 found `/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/data/urbaning-v2x`
and loaded the source records, then failed at `ModuleNotFoundError: detectron2`
after3m06s. The gate had not activated the verified private CPU runtime.
Following entrypoint now mirrors the fine-tuning script's read-only `reuse()`
bootstrap for runtime21649159 and receives its path from Slurm. This performs no
installation/build and does not modify the runtime. No thermal images were
inferred in21694226; retry with a new worktree and output.

Retry21694349 activated the verified runtime and found the Ares data root, then
stopped before thermal image inference on a missing local NumPy import in the
vehicle/LiDAR transform helper. Added that import; no model forward occurred.
Keep its output and use a new worktree/output for the retry.

## Physical source and useful first comparison

## Frozen RGB-RPN result (2026-11-09)

Gate21694685 reached its planned diagnostic and returned status2 for STOP. On
the sampled crossing1 thermal views, macro proposal recall was14.17% at IoU.3,
4.48% at.5 and0.78% at.7 (required25% and10% at.3/.5). Per-class IoU.5:
Vehicle4.13% (25/605), Heavy_Vehicle12.20% (5/41), 2Wheeler0% (0/5; too few
samples for a strong class claim), Pedestrian1.59% (1/63). The RGB-pretrained,
frozen RPN misses most thermal GT boxes. Do not train only ROI heads on this
proposal set. The result is not evidence that thermal itself is useless.

Next low-cost diagnostic is implemented in the same entry point: sweep the
configured RPN test limits plus post-NMS budgets2,000 and4,000 (pre-NMS is raised
to at least the selected budget) on the exact same sampled views. It reports
per-class recall without changing weights or loading validation. If a larger
budget recovers GT, evaluate that fixed budget on more TRAIN-only thermal views.
If recall stays low, consider a trainable-RPN pilot only after confirming a
separate recording-level thermal validation set and checking actual RPN
gradients/loss in a native startup gate. Do not reuse crossing1 frames for
validation or claim generalization from this single local sequence.

Budget sweep21694751 raised macro recall from14.17/4.48/0.78% at IoU.3/.5/.7
configured default to22.05/9.47/2.89% at post-NMS4000, still just below the
fixed gates. At4000, IoU.5 recall was Vehicle7.27% (44/605),
Heavy_Vehicle19.51% (8/41), Pedestrian11.11% (7/63), and 2Wheeler0/5. The
increase is meaningful but leaves most GT without a proposal. The next diagnostic
should use a larger uniform TRAIN-only sample at fixed4000, then confirm that a
separate recording-level thermal evaluation source exists before considering any
trainable-RPN pilot. Prepared an expanded read-only gate on48 uniform TRAIN
anchors with configured and post-NMS4000 settings; it records which source
sequences are extracted. No training is justified by the prior sweep alone.

UrbanIng vehicles carry RGB cameras and LiDAR; thermal cameras are on fixed
infrastructure. Thermal and vehicle RGB therefore do not form pixel-aligned
RGB/thermal pairs. Use source camera calibration, vehicle pose and native capture
time to move infrastructure evidence into Car1's frame. Do not resize a thermal
image onto an unrelated RGB view or assume a shared viewpoint.

References: [authors' setup](https://thi-ad.github.io/urbaning/) and
[native dataset/devkit](https://github.com/thi-ad/UrbanIng-V2X).

The existing inspected thermal payload is8-bit grayscale640x480 JPEG; treat it
as image intensity, not measured Celsius. Confirm per-recording image shapes,
available sensors, calibration paths and annotation support before selecting a
model. A grayscale image repeated over three input channels is an input-format
adaptation, not proof that an RGB-pretrained detector works on thermal data.

## Proposed first architecture

1. Train a thermal2D detector on the declared TRAIN recordings, using thermal
   images and projected labels with explicit ignore/visibility limitations.
   Keep every sensor/view of an original recording in the same split. A matching
   camera format does not license reusing PST900 segmentation weights as an
   UrbanIng detection result. Choose and record a suitable detector/checkpoint
   and its provenance after the data inventory.
2. Use time-associated infrastructure LiDAR returns inside the thermal2D support
   to establish3D location/proposals. Resolve foreground/background association
   explicitly; a median of all points in the rectangle is not a verified object
   depth. If support is insufficient, retain a thermal2D observation instead of
   inventing metric depth. Do not claim this hybrid is thermal-only3D detection.
3. Transform resulting predictions and source capture times into Car1's frame.
   First test offline detection benefit, then add peer-request costs, transferred
   bytes and delivery timing under the existing acquisition protocol.

Thermal can also rescore or classify existing infrastructure LiDAR proposals.
That narrower alternative avoids monocular3D depth but cannot recover objects
for which LiDAR never produced a proposal. Keep it labeled separately from
independent thermal2D proposals followed by LiDAR-assisted localization.

## Controls required to attribute improvement

For identical evaluation frames, GT and source availability compare:

- Car1 LiDAR.
- Car1 LiDAR + infrastructure LiDAR under the existing protocol.
- The same infrastructure LiDAR augmented by thermal evidence.
- Car1 RGB adaptation and optional RGB+thermal as separately labeled extensions.

The primary thermal contribution is the paired difference between the SAME
infrastructure-LiDAR inputs with and without thermal. Otherwise an improvement
over Car1 may simply be due to the extra infrastructure LiDAR/viewpoint.

Report per-class AP and FP/TP, especially Pedestrian and2Wheeler, plus recovered
GT appearances and lost LiDAR matches. These classes motivate the experiment;
benefit is a hypothesis, not established by sensor type. Do not promise a night
advantage without usable recordings at those conditions.

Before online acquisition, check image age, clock association and image/point
availability relative to decision time. Motion can invalidate apparent alignment;
native timestamp differences must be preserved and any compensation documented.
Thermal image transmission and LiDAR transmission are distinct payload costs.

The existing development validation has been inspected repeatedly. Use it for
diagnosis, and reserve additional recording-level data for a final frozen
comparison; do not silently tune on the historical crossing3 evaluations.
