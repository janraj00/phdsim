# Car1 independent RGB3D detector and decision-level fusion

Prepared 2026-11-07. This is a small engineering pilot, not a completed native
UrbanIng result. It replaces adapter fitting with a frozen independent RGB
detector and fixed decision-level fusion. Acquisition and multi-agent fusion
are not changed.

## Method

Use official **Cube R-CNN DLA34 / Omni3D** weights. The model predicts 3D cuboids
from an RGB image and its camera intrinsics. It does not consume LiDAR points,
LiDAR proposals, depth, GT boxes or partner predictions. It is a monocular
external pretrained model, not an UrbanIng RGB benchmark reproduction.

References:

- https://github.com/facebookresearch/omni3d
- https://github.com/facebookresearch/omni3d/blob/main/MODEL_ZOO.md
- https://openaccess.thecvf.com/content/CVPR2023/html/Brazil_Omni3D_A_Large_Benchmark_and_Model_for_3D_Object_Detection_in_CVPR_2023_paper.html

Pin Omni3D to `778bd0210e5e1b584cc52daeba57cae3a3ee8c4e`, Detectron2 to
`247691a1c292654867deb35cabb27f18d75a1363`, and PyTorch3D to
`75ebeeaea0908c5527e7b1e305fbc7681382db47` (0.7.8). Exact hashes of the official
383,344,642-byte checkpoint, complete config and category metadata are checked
before loading. Use the official architecture/config and strict state checking
(allow only documented omitted pixel normalization buffers). Do not use the
official demo's hard-coded `.cuda()` call or guessed camera intrinsics.

For each image, apply the official resize, retain the unmodified original K
and original image dimensions as the official model expects. Use the reviewed
native-optical camera transform from `camera_fields`, including its converter
axis correction. Export camera-space predicted corners unchanged. For the
existing upright-box BEV evaluator, transform the predicted center to Car1,
project the object's predicted local length axis into BEV and construct an
upright W/H/L cuboid. This is an explicit roll/pitch-discarding approximation,
not a GT-based correction; inspect raw camera projections and resulting BEV.

Class mapping follows the official UrbanIng coarse groups:

| Cube class | UrbanIng group |
|---|---|
| car, van | Vehicle |
| truck, bus, trailer | Heavy_Vehicle |
| cyclist, motorcycle | 2Wheeler |
| pedestrian | Pedestrian |

Other categories remain in the raw export but do not enter four-class fusion.
Do not silently equate an unoccupied bicycle with a Cyclist. There is no exact
checkpoint category for E-Scooter, OtherVehicle or OtherPedestrian. Retain ALL
original GT during evaluation: the category coverage mismatch is a limitation,
not grounds for filtering difficult GT away.

Six independent camera outputs are transformed into Car1 coordinates and merged
with classwise hard BEV NMS at predeclared IoU .2. Late fusion is the union of
those detections and cached original Car1 LiDAR boxes followed by the same NMS.
Keep original confidence values, with no fitted calibration, score averaging,
threshold sweep or box-coordinate averaging. RGB-only new objects can survive.
Because detector scores are not calibrated against each other, this is an
initial transparent fusion baseline, not an optimal fusion rule.

## Small pilot and outputs

Four uniformly selected frames per existing TRAIN recording (0001 crossing2 and
0017 crossing1), eight frames total, six cameras each. Selection uses frame
keys, not GT, scores or a successful example. Zero validation/crossing3 access,
new fitting, LiDAR backbone inference or peer requests. Existing checked source
packet and original cached predictions are read, not modified.

Compare original LiDAR, LiDAR with the new NMS alone (postprocessing control),
independent RGB and LiDAR+RGB late fusion. Keep the same original all-source GT
and evaluator: BEV VOC AP at .3/.5/.7, global sorting primary, upstream frame
order secondary. Four-class macro is N/A when a class has no GT. Eight TRAIN
frames are an engineering diagnostic, never held-out accuracy evidence.

Export raw per-camera 2D/3D predictions, category scores/poses, K/extrinsics,
image hashes and native association/times; raw per-frame fused detections and
GT; original-source hashes; per-class AP in both orders; 48 camera projection
images and eight three-panel BEV figures. Displayed predictions use score>=.25;
metrics retain official ROI threshold .01 and are not evaluated on that display
subset. The BEV display window is not an evaluation range change. Retain native
offsets offline, without motion compensation or online availability claims.

## Run on Ares

Local checks passed: four focused geometry/NMS/export tests including the full
synthetic48-camera/eight-frame export, Python and shell syntax, and an actual
unchanged official-weight CPU inference on an upstream demo image. That forward
returned49 finite3D detections. Its approximate .94s time on a480x640 image and
four local CPU threads is a startup check, not an Ares/native-camera ETA or an
UrbanIng accuracy result. CPU extensions were compiled from the pinned original
sources; an unavailable default compiler/linker was corrected to GCC/G++.

Submit from the new checkout; the submitter is not an SSH client. Existing
`phdsim`, converted sources, input packet, CPU venv and container remain in their
original locations. Use:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_late.sbatch
```

The job allocates 8 CPUs / 24 GiB, with a 4-hour scheduler ceiling, not an ETA.
It builds isolated CPU Detectron2/PyTorch3D extensions with two compiler workers
and installs private torchvision0.21.0+cpu. No pip operation modifies the shared
venv. Existing torch2.6.0+cpu / NumPy1.26.4 and other tested perception packages
are required. Compiler/toolchain errors must stop before detector execution.

Default output:
`phdsim/runs/urbaning-rgb3d-late-JOBID/run/urbaning-rgb3d-late-train8.zip`.
The sibling `runtime` holds external source/build files, dependencies and
weights, excluded from the result ZIP and Git. Use a fresh output if interrupted;
this initial small runner deliberately does not overwrite or silently resume
an incompletely built runtime or a previous scientific output.

Review projection/metric depth and category coverage first. Only after that gate
should a fixed development comparison be prepared, then an independent test.
External pretrained LiDAR and RGB models have different training data; their
standalone numbers are not a controlled same-training modality ablation.

## Why this follows the adapter diagnosis

The supplied completed train-eval ZIP has been read locally and passed CRC.
Across three seeds, original LiDAR / LiDAR adapter / RGB adapter have TRAIN400
mAP24.3129/31.5907/34.0658% and development-validation200
21.6500/18.0014/17.6987%. RGB-minus-LiDAR-adapter validation deltas are
-.6918/-.7340/+.5175pp. Mean class AP for those three variants on validation:
Vehicle48.4287/47.5242/47.9692, Heavy_Vehicle20.1936/7.6690/10.4115,
2Wheeler14.9675/13.8680/9.4055, Pedestrian3.0102/2.9446/3.0086%.
The adapters improve both TRAIN recordings but generalize poorly on the one
inspected validation recording. This does not prove RGB is inherently harmful
or uniquely identify the cause. Preserve all original models and results.
