# Car1 LiDAR + RGB: CPU late-fusion pilot

Status: prepared and locally checked on 2026-11-05; **not run on Ares yet**.
The user explicitly selected the fast CPU pilot: learn a scorer of existing
LiDAR proposals using RGB crops. This is stage B of the agreed roadmap, before
trainable multimodal BEV fusion and later multi-agent multimodal acquisition.

## Question and fixed protocol

Does Car1's RGB content help rank its existing LiDAR detections, beyond a
LiDAR-only learned recalibrator, on the existing development recordings?

| Variant | Inputs / behavior |
|---|---|
| `original_lidar` | Frozen CoBEVT ego-only proposals and original scores |
| `lidar_recalibrated` | Original score, box geometry, camera projection availability/geometry; learned residual scorer |
| `lidar_rgb` | Same inputs plus frozen RGB features; learned residual scorer |
| `lidar_rgb_shuffled_diagnostic` | Frozen fusion scorer, validation RGB features shuffled within predicted class and usable-RGB mask, seed 0 |

All variants have identical boxes, predicted classes, sampled frames and GT.
They request **zero peers**. This is a perception pilot, not another acquisition
policy or an extension of the previous 1400-frame policy table. The important
RGB comparison is `lidar_rgb` versus `lidar_recalibrated`; original scores alone
cannot separate RGB benefit from learning a new scorer. Shuffle is a diagnostic,
not a significance test or model-selection criterion.

Predeclared sampling uses 60 uniformly spaced native frame keys per original
recording, independent of scores and GT:

- Train: 60 of200 from `20241126_0017_crossing1_00` and 60 of200 from
  `20241126_0001_crossing2_00` = **120** frames.
- Validation: 60 of200 from `20241126_0004_crossing2_00` = **60** frames.
- No crossing3 access. These are previously inspected development recordings,
  not a newly blind test. Do not compare sampled AP directly to historical
  full200 / full1400 AP; the paired original baseline is reproduced here.

Primary metric remains **four-class BEV mAP@IoU0.5 with global confidence sort**.
Report per-class AP at0.3/0.5/0.7 and the historical frame-order AP separately.
After any score changes, recompute greedy matching. Precomputed fixed-label AP
would be incorrect because proposal ordering can change duplicate assignments.
Pairwise BEV IoU is computed once per frame and reused for fresh matching in all
variants. Raw and reversed scores were checked against the existing evaluator
on five actual cached inspection frames, across all classes/IoU thresholds.

## Model and boundaries

Each fixed predicted box is projected into Car1's six converted RGB cameras.
Choose the usable view with the largest clipped area times in-image fraction;
ties use camera index. Reject near-plane straddles, projections smaller than12px
on either side, or less than50% inside the image. Add10% crop padding. There is
no GT-based view/crop choice and no proposal filtering using camera content.
Missing crops receive an availability flag and zero visual features.

Frozen `torchvision0.21.0+cpu` MobileNetV3-small IMAGENET1K_V1, global average
pooling, produces576 features. Input: RGB224 square resize, ImageNet mean/std,
no augmentation. Train-only PCA reduces to at most16 dimensions. The RGB CNN
is **not fine-tuned**. Two per-predicted-class residual logistic heads learn
corrections to the original confidence logit. Fixed mean-BCE plus ridge0.1,
intercept ridge0.01, at most40 Newton steps; no validation hyperparameter search.
Classes with fewer than5 training examples of either target value retain raw
scores. Offline target: original-score greedy same-class TP at BEV IoU0.5.
This is a binary supervision surrogate, not direct AP optimization.

The LiDAR-only control receives the same geometric projection metadata as the
fusion head, including availability, camera index and crop area/coverage. Only
RGB content is added to the fusion head. Neither head sees GT at application.
GT and counterfactual partner predictions are omitted from feature-extractor
inputs. GT is used only for offline targets and evaluation.

**No new boxes, coordinates or classes are produced.** A missed object without
a LiDAR proposal cannot be recovered by this pilot. A negative result does not
rule out trainable BEV/image fusion or using RGB to generate new proposals.
This CPU path is chosen to get a controlled first measurement with the existing
allocation. Full perception training needs a separate architecture/data/GPU plan.

## Coordinate and timestamp binding

Reuse rectified `*_camera0.png` ... `*_camera5.png` and camera calibration fields
from the already-converted Car1 YAML, never repeat the dataset conversion.
Camera order in the pinned official converter is back_left, left, front_left,
front_right, right, back_right. The source is
[the converter](https://github.com/thi-ad/UrbanIng-V2X/blob/d5766e75f985c6c566a09abfa23d3fbb32f03820/urbaning/urbaning/converters/opencood.py)
and its
[helpers](https://github.com/thi-ad/UrbanIng-V2X/blob/d5766e75f985c6c566a09abfa23d3fbb32f03820/urbaning/urbaning/converters/utils.py).

The cached local coordinate is the converted LiDAR coordinate. The converter
stores `E = R1 inv(R2) cTg gTl R3 R1`, which is **not** a native optical-camera
transform. Recover optical camera coordinates with `R2 R1 E x` before applying
the rectified intrinsic matrix. A synthetic nonzero-translation transformation
test checks this identity and image projection/near-plane handling.
Only numeric camera fields are parsed with YAML composition; object/label tags
are never constructed. Yellow projection overlays and a few actual crops from
the first train/validation frames are exported for human alignment inspection.
Real RGB/box alignment has not been visually checked before the Ares run.

Run/trace/prediction/GT/YAML hashes and converter commit/native frame association
are verified before extraction. The original portable AP archive is verified
and paired baseline AP is reproduced from raw boxes. Converted image hashes are
recorded at first extraction and checked on partial resume. Original sensor
filenames and camera offsets are preserved in provenance. Associations can be
after the anchor time; this remains offline synchronized evaluation, without a
causal online claim. No original payload is rewritten.

## Runtime and submission

Requires the same CPU worker wrapper, frozen torch2.6.0+cpu / NumPy1.26.4 and
converted train/validation inputs used previously. Existing packet:
`$WORK/inputs/urbaning-gap-acquisition-inputs-001.zip`, SHA256
`c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee`.
Only its embedded AP export is used; no new file upload is necessary.

Submit from this checkout root:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb_pilot.sbatch
```

Eight CPU cores,24GiB,3h upper limit. The existing container worker wrapper is
used. Install only pinned torchvision into the output's isolated dependency
directory with `--no-deps`; never change the shared venv. Download official
ImageNet weights once and check full SHA256
`047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`.
Source: [torchvision0.21 weight definition](https://github.com/pytorch/vision/blob/v0.21.0/torchvision/models/mobilenetv3.py).

Target: a short CPU pilot rather than hours of detector inference. Actual Ares
wall time is not measured. A local compatibility check with the exact CPU
packages and official weights extracted a64-crop224 batch in about1.6s on4
threads; this excludes Ares queue, GPFS I/O and evaluation and is not an Ares
runtime estimate. The job prints measured extraction rate and remaining-time
estimate after its first frames. Queue wait is outside runtime.

Default output is stable for partial resume:
`$WORK/phdsim/runs/urbaning-rgb-pilot-001`.
The script holds a file lock. Each completed frame's features are saved atomically
with source/encoder/code hashes; interrupted extraction resumes verified frames.
Complete reruns verify the output ZIP receipt and return without repeating work.
Changed code/configuration requires a new output, provided as the first sbatch
script argument. Runtime dependencies, image features and pretrained weights
remain on Ares; they are excluded from the downloadable result ZIP.

Outputs:

- `summary.md`: paired mAP, changes in percentage points and per-class AP;
- `report.json`: both AP modes, class results, crop coverage and timing offsets;
- `index.html`, `projection-qa/`: overlays and crops for alignment inspection;
- `model.json`: fitted heads and train-only PCA, encoder identity/weight hash;
- `inputs.json`: sampled keys and original source bindings;
- `urbaning-rgb-pilot.zip`: compact downloadable reports/model/QA;
- `features/`, `weights/`, `dependencies/`: reusable local runtime caches.

Local checks:7 focused tests including synthetic manifest-loader/end-to-end
export/resume; raw/reversed matching parity on5 real NPZ caches; actual frozen
MobileNet weight download, CPU import and64-crop feature extraction; shell syntax
and Python compilation. These do **not** constitute an Ares RGB experiment or
proof of improvement. The first actual result is still pending.
