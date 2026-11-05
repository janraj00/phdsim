# Car1 LiDAR + RGB: CPU late-fusion pilot

Status: pilot completed on Ares **21593944**, 2026-11-05, **6m01s**, exit0.
Result ZIP SHA256 `01a846a25d7a760505423a5fd6163a9d07fd4a6bab70c48ff0f644fe2a244455`,
6,974,819bytes; hash, ZIP CRC, counts and report arithmetic checked.
The user explicitly selected the fast CPU pilot: learn a scorer of existing
LiDAR proposals using RGB crops. This is stage B of the agreed roadmap, before
trainable multimodal BEV fusion and later multi-agent multimodal acquisition.

## Full existing400/200 development run completed (2026-11-05)

Ares **21594528** completed13m41s, exit0 (worker step13m17s). Result ZIP
SHA256 `886a4fe190a8fd065bb5fcfee7e3ae90b171d9354dc9bf38fdcc2fe09e34efd6`,
134,604bytes. Uploaded archive hash/CRC, all class-to-macro arithmetic,400/200
unique disjoint native keys, exact extractor-code identity and encoder weight
hash checked. Original Car1 class AP, GT counts and macro AP match the separate
historical AP-export validation ego baseline exactly. No detector inference.

| Variant | BEV mAP@0.5 (%) | Change vs original (pp) |
|---|---:|---:|
| Original LiDAR |21.5380|0|
| Learned LiDAR scoring |22.9784|+1.4404|
| Learned LiDAR+RGB scoring |22.6447|+1.1067|
| RGB-shuffle diagnostic |20.2564|-1.2816|

**RGB minus learned LiDAR = -.3337pp**, so the small pilot's+.2147pp incremental
RGB gain did not persist on this larger development measurement. The1.1067pp
increase versus raw scores must not be attributed entirely to RGB.

| Class | Original AP@.5 (%) | Learned LiDAR | LiDAR+RGB | RGB minus learned LiDAR (pp) | Validation GT instances |
|---|---:|---:|---:|---:|---:|
| Vehicle |48.3758|48.3750|49.2513|+.8764|12241|
| Heavy_Vehicle |20.0164|26.9184|26.7670|-.1515|249|
| 2Wheeler |14.8483|14.1490|11.6862|-2.4627|289|
| Pedestrian |2.9116|2.4712|2.8744|+.4031|2158|

The two-wheeler decrease contributes-.6157pp to the four-class macro average;
the other classes together offset+.2820pp. This diagnoses where the aggregate
loss occurs, not why. The full train target support is Vehicle10424/5769,
Heavy566/777,2Wheeler**26/332**,Pedestrian812/2677 correct/incorrect proposals
within the evaluation radius. These are frame-proposal examples, not unique
objects; repetition across adjacent frames further limits independent support.
The26 positives motivate an overfitting/data-coverage diagnostic, but do not
establish the cause of degradation.

RGB's incremental mAP is+1.0497pp atIoU.3 and-.8006pp atIoU.7; primary remains
IoU.5. Shuffle gives20.2564%,2.3884pp below actual RGB, but is only one fixed
perturbation and does not establish superiority over the learned LiDAR control.
Projected crops exist for21100/21395 train and13739/13880 validation proposals.
This does not measure occlusion or semantic visibility. Native offsets remain
-1..+45ms, offline associations.

The full ZIP contains only reports/model/provenance, **no QA images**. Both
first frames came from the pilot feature seed; the unchanged extractor returns
verified cached features before its QA-export branch. This explains the smaller
archive. Prior limited visual QA belongs to the pilot's two frames; there has
been no new full-run visual inspection. Cached features were used in the full
measurement, not omitted from inference.

This remains the same3 development recordings, fixed LiDAR proposals and frozen
RGB encoder, with training-only PCA/head refits. It neither validates all RGB
fusion designs nor supplies new boxes/recall. Useful next diagnostic: inspect
class-specific train versus validation scoring and the scarce correct two-
wheeler proposals/crops using existing Ares features, before changing the
model. Any choice based on this inspected validation remains development,
not a new blind result. No further job is prepared/submitted here.

## Observed pilot result and next measurement

120 train /60 validation frames, same predeclared protocol and zero peers:

| Variant | BEV mAP@0.5 (%) | Change vs original (pp) |
|---|---:|---:|
| Original LiDAR |22.3192|0|
| Learned LiDAR scoring |23.2347|+.9155|
| Learned LiDAR+RGB scoring |23.4494|+1.1302|
| RGB-shuffle diagnostic |21.3288|-.9904|

RGB's incremental difference versus the learned LiDAR control is **+.2147pp**,
not the entire1.1302pp. Per-class AP@.5, global confidence sort:

| Class | Original | Learned LiDAR | LiDAR+RGB | RGB minus learned LiDAR (pp) |
|---|---:|---:|---:|---:|
| Vehicle |48.4893|48.4475|49.3418|+.8943|
| Heavy_Vehicle |22.5253|28.1704|29.5993|+1.4289|
| 2Wheeler |14.8789|13.6868|11.8107|-1.8762|
| Pedestrian |3.3832|2.6340|3.0459|+.4119|

Train binary target support (correct/incorrect proposals, not unique objects):
Vehicle3123/1772; Heavy176/240; 2Wheeler**7/101**; Pedestrian241/804.
This sparse positive supervision is a concrete concern for the two-wheeler head;
it is not established as the sole cause of degradation. RGB has usable projected
crops for6376/6465 train proposals and4110/4147 validation proposals; geometric
coverage is not proof of visible/unoccluded content. Source offsets range-1 to+45ms.

Visual QA sampled the first train and validation frame: inspected overlays show
plausible projections onto cars and a pedestrian, alongside background/occluded
proposals. This does not establish correctness over all frames or prove that
all background crops are detector errors rather than projection issues. Only
two native frames have exported overlays. No systematic gross axis error was
apparent in the inspected views.

The smaller mAP increase is not uniform: relative to learned LiDAR scoring,
RGB also changes mAP@.3 by+1.6296pp but mAP@.7 by-.4550pp. The primary remains
mAP@.5. The shuffled diagnostic is one perturbation, not causal or significance
evidence; no model-selection claim. Previous full1400 policy AP is a different
scope and not a paired baseline here.

Next prepared measurement: **all existing400 train /200 validation frames**
from these same3 development recordings, not the complete UrbanIng dataset or
new independent recordings. Freeze the same encoder/PCA16/head settings,
matching and metric. Refit PCA/heads on400 train only; no validation parameter
search or post-hoc per-class bypass. Reuse120+60 existing feature cache entries
with exact per-frame source/encoder/code/hash validation. No detector inference.
This described the preparation state; the completed full400/200 measurement
is now recorded above.

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb_pilot.sbatch \
  "$WORK/phdsim/runs/urbaning-rgb-full-001" 200 200 \
  "$WORK/phdsim/runs/urbaning-rgb-pilot-001"
```

Script arguments: output directory, train frame cap per original recording,
validation frame cap per original recording, optional completed feature-cache
seed. Defaults remain the original60/60 pilot. Partial resumes keep matching
configuration; copied feature bytes and metadata are reverified by the unchanged
extractor. Source caches/models/reports remain untouched. The repeated development
validation is exploratory, not a blind generalization test.

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
The initial run was prepared before real RGB QA; the completed pilot now has
the limited two-frame visual inspection described above.

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
pilot wall time was6m01s including setup; full400/200 subsequently completed in13m41s. A local compatibility check with the exact CPU
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

Local checks:8 focused tests including synthetic manifest-loader/end-to-end
export/resume and shell frame-cap/cache-seeding checks; raw/reversed matching parity on5 real NPZ caches; actual frozen
MobileNet weight download, CPU import and64-crop feature extraction; shell syntax
and Python compilation. The actual Ares pilot result and its limited visual inspection are recorded
above; none of these checks proves generalization or full BEV fusion benefit.
