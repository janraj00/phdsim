# Thermal as an infrastructure observation

Design only,2026-11-08. No thermal detector/fusion training is implemented or
submitted by this change. The current RGB fine-tuning experiment stays separate.

## Physical source and useful first comparison

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
