# Official outdoor Cube R-CNN: paired TRAIN8 development check

Prepared 2026-11-07 after the user requested improving RGB detection. This is a
change of official pretrained checkpoint, not UrbanIng fine-tuning, a new
adapter, an acquisition policy or evidence of an improvement before execution.

## Completed baseline and diagnosis

Ares21653482 completed the original Omni3D DLA34 pilot. Supplied archive:
`urbaning-rgb3d-late-train8.zip`,9,421,563bytes, SHA256
`9166540676ab7629f9426bfc1a45f968f5da9f2162507389885e461ebc64d4ad`.
CRC passed. Local review independently reconstructed all48 raw RGB outputs'
upright conversion, six-camera merging and late fusion; all frame arrays match
exactly. All four variants' class/macro AP at .3/.5/.7 reproduce exactly in both
ordering modes under NumPy1.26.4.48 calibration determinants are -1 within
1.6e-15, maximum orthogonality error1.6e-15. This validates numerical basis
consistency, not exhaustive physical camera calibration.

Primary BEV VOC AP@.5/global-confidence-sort percentages:

| Variant | Vehicle | Heavy_Vehicle | 2Wheeler | Pedestrian | mAP |
|---|---:|---:|---:|---:|---:|
| Original LiDAR / LiDAR NMS control |53.8975|18.6104|25.7143|18.3743|29.1491|
| RGB, general Omni3D checkpoint |5.5743|8.5069|0|2.3080|4.0973|
| LiDAR+RGB, fixed union/NMS |51.8322|22.2680|25.0000|17.8124|29.2281|

There are350/24/5/54 GT appearances by class, not independent object tracks.
At IoU .5, LiDAR has226 matched GT appearances; RGB40; late fusion227.
RGB matches5 GT appearances missed by LiDAR. Fusion gains5 but loses4 old
matches; all four original LiDAR predictions were removed by NMS. An example:
LiDAR confidence .2056 / GT IoU .6000 is suppressed by RGB confidence .4099 /
GT IoU .4473. Confidence values are not calibrated across models. The outdoor
comparison retains this exact fusion rule to isolate checkpoint choice.

Representative camera projections and first-frame BEV plots at both sites were
reviewed, plus camera2 across all8 frames. Image-space alignment is plausible;
3D position/size errors and missed objects remain. No claim that every camera
or annotation has been physically audited.

An offline error-factor diagnostic matched194 camera-object observations by
same coarse class and greedy projected-GT image IoU>=.5. Use native1920x1080,
all GT vertices in front, projected clipped dimensions>=12px, existing RGB
scores/config unchanged. Observations can repeat objects across cameras.
Replace only a matched prediction's geometry, then rerun identical camera NMS
and AP with all original GT retained:

| Offline GT-dependent control | RGB mAP@.5 (%) |
|---|---:|
| Unchanged |4.0973|
| Correct optical depth, retain predicted camera ray/size/pose |15.2056|
| Correct BEV center |19.7628|
| Correct horizontal dimensions |4.6712|
| Correct BEV heading |4.0973|
| Correct complete box for those image-matched observations |22.0324|

These are **GT-assisted error-isolation diagnostics**, never deployable results,
learned gains, independent tests or guaranteed achievable performance. They
motivate addressing depth/localization before more fusion-rule tuning.

## Paired official checkpoint comparison

Authors release general, indoor-only and outdoor-only checkpoints:
https://github.com/facebookresearch/omni3d/blob/main/MODEL_ZOO.md

Keep DLA34 and the already compiled runtime. Download the official outdoor
config/weights/category metadata into the NEW output; preserve the old model.
The outdoor classifier has11 categories rather than50; category-to-four-class
mapping and all GT remain unchanged. No fine-tuning, threshold sweeps, score
recalibration or fusion-rule change. Verify classifier size against metadata.

Official outdoor asset SHA256:

- config: `feaad164338cc8fd083bf8aa995d551e762cf9d49b580e68ae335b40ebd912b5`
- metadata: `1c62db8f91b0b501fea8b44f55b28905c69b1706d7e4dd9fb1429e61c989b758`
- checkpoint: `9dfc68c564a31e5e0e893b913574863af05ee0200b58f91173bbc088f31e8e2d`

An outdoor run requires the hash-pinned completed21653482 archive. Before model
inference, verify identical8 frame keys, original LiDAR/GT arrays and all48
image hashes, K, optical extrinsics and native time associations. Independently
replay every original-reference variant/class/AP order. Include original
reference metrics in report.json and print paired RGB and fusion deltas.

Use the same four frames from each TRAIN recording, no validation or crossing3.
This is an inspected development comparison. Selecting a future starting model
using these8 frames is not a blind test. The external RGB/LiDAR pretraining
datasets differ, so this does not rank modalities under equal training.

## Ares command

Submit from the new outdoor checkout:

```bash
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
RUNTIME="$WORK/phdsim/runs/urbaning-rgb3d-late-21649159/runtime"
REFERENCE="$WORK/phdsim/runs/urbaning-rgb3d-late-21653482/run/urbaning-rgb3d-late-train8.zip"
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_late.sbatch \
  "" "$RUNTIME" outdoor "$REFERENCE"
```

Existing runtime/model remain read-only; no install or compilation. New model
assets are about378MB.8CPU/24GiB,4h scheduler ceiling, not an ETA. Scientific
output: `phdsim/runs/urbaning-rgb3d-late-JOBID/run/urbaning-rgb3d-outdoor-train8.zip`.
Reuse the ordinary urbaning-rgb3d-late-JOBID logs from this checkout.

Local checks: official outdoor model loaded strictly and ran on CPU with finite
3D outputs; blank image with zero detections handled. Eight focused tests pass,
including a full paired synthetic export and rejection of changed source images.
Python and shell syntax checked. No outdoor UrbanIng result has run here.

## Following step, not implemented by this job

If the released outdoor model remains weak, prepare actual UrbanIng adaptation
with400 TRAIN /200 separate development-validation frames and unchanged
baseline, using only RGB at inference. A CPU-focused option is fine-tuning the
existing `bbox_3D_center_depth` layer from frozen RGB ROI features, with fixed
protocol and held-out evaluation; do not label this as training the whole
detector. Its features/targets, decoding parity and recording split must be
verified before fitting. Do not substitute an eight-frame fit for that test or
claim that the offline GT-depth diagnostic predicts the trained outcome.
