# Car1 RGB adaptation around the existing CoBEVT detector

Status2026-11-06: **adapter scaffold and native preflight implemented, not run
on Ares; RGB encoder/training and a fusion accuracy result are not available.**

The CPU standalone detector performed poorly even for LiDAR. Preserve those
results and use the working official detector as the next engineering base.
This is distinct from the earlier fixed-proposal RGB score recalibration.

## What can be reused

The pinned UrbanIng model is `PointPillarCoBEVT`: PillarVFE/scatter/backbone,
optional shrink, agent fusion, and trained classification/regression heads.
Its weights consume LiDAR features; images are not a drop-in replacement.
The official camera CoBEVT implementation provides a useful architecture
reference, but its camera results are primarily BEV segmentation, not our
four-class UrbanIng box detection protocol:

- <https://github.com/DerrickXuNu/CoBEVT>
- <https://proceedings.mlr.press/v205/xu23a.html>
- UrbanIng pinned source:
  `opencood/opencood/models/lidar/point_pillar_cobevt.py`,
  commit `d5766e75f985c6c566a09abfa23d3fbb32f03820`.

## Implemented first step

`ResidualBEVAdapter` adds a learned RGB-derived residual to an existing BEV
tensor, with an exactly zero-initialized final convolution. At initialization
the LiDAR tensor and original detector outputs are retained. A zero start is
an implementation safeguard, not evidence RGB will improve detection.

RGB and LiDAR must share metric coordinates, extent, resolution and frame.
Matching array shapes alone does not establish this. The adapter does not
perform image-to-BEV lifting. That encoder remains to be implemented/selected
after native geometry inspection. No GT or peer results enter runtime inputs.

The initial insertion point is the **Car1-only final BEV immediately before
the unchanged classification/regression heads**. It is not a multi-agent
RGB fusion implementation. Feeding RGB-aware source features through the
inter-agent fusion network will be separate work later.

## Ready Ares preflight

`scripts/slurm/urbaning_cobevt_rgb_preflight.sbatch` uses8 CPU/24GiB/1h upper
limit, no new dependencies/weights/dataset download. It reads the existing
container wrapper, official hash-verified checkpoint and converted inputs.

1. Verify the pinned clean upstream and official model bundle.
2. Uniformly select4 TRAIN frames from each existing training recording:
   `20241126_0001_crossing2_00` and `20241126_0017_crossing1_00`,8 total.
   Existing AP packet/provenance headers are checked; no validation prediction
   or image is evaluated and no crossing3 inputs are accessed.
3. Run the unchanged official detector with Car1 voxels only. Capture final
   BEV through a temporary forward hook; pass it through original cls/reg heads
   and require output agreement within1e-6. Keep max_cav/upstream masks intact.
4. Save float32 BEV/features/logits and the metric rectangular cell centers.
   This is actual native inference, not the previous200x200 square toy head.
5. Export six-camera mosaics with projected Car1 points and offline GT boxes,
   native associations, immutable image/point/source hashes, shape and timings.
   Visual inspection is required; in-image projection counts do not prove
   alignment or visibility.

The small result ZIP contains report/protocol/NEXT and8 QA mosaics. Larger
feature NPZs remain under the dedicated Ares output directory. Existing source
files, checkpoints and historical reports are never overwritten. Reuse of a
partial output is refused; default outputs include the Slurm job ID.

Submit from the new checkout root:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_cobevt_rgb_preflight.sbatch
```

One hour is a scheduler upper bound, not an ETA. This job does not fit an
adapter or evaluate RGB accuracy. It checks the actual feature/head boundary
and provides geometry QA before a training job is prepared.

## Next training gate and controlled comparison

After inspection, construct a calibrated RGB BEV encoder on exactly the
native detector grid. Freeze the official LiDAR branch and original detector
first; train the RGB residual with an explicitly documented detection objective
and offline train targets. Check memorization on a tiny native TRAIN set before
expanding to400 train/200 development-validation frames. Frozen RGB CNN maps
and LiDAR features can be cached; actual memory/training cost must be measured.

Controls: unchanged LiDAR, identically trained capacity-matched LiDAR-only
adapter, aligned LiDAR+RGB adapter, and a fixed GT-free RGB-shuffle diagnostic.
Use the same primary four-class global-sort BEV mAP@.5 and unchanged GT support;
re-match boxes after changes, report class AP and both AP orders separately.
Do not attribute learned recalibration/capacity gains solely to RGB.

RGB-only needs a separately trained/adapted camera-to-BEV detector. A residual
that still consumes LiDAR features or LiDAR-derived depth is not RGB-only.
The historical development set has been inspected and the official LiDAR
checkpoint may have seen those clips; preserve that limitation and do not
select new settings on crossing3. No performance claim is made by this scaffold.

## Checks performed locally

Six focused checks: zero-start identity/learnability without mutating LiDAR;
wrong-grid/nonfinite rejection; original head replay and hook cleanup; rectangular
metric axes; six-image projection QA; complete synthetic8-frame preflight export
and ZIP integrity with mocked upstream I/O. These are implementation tests, not
proof of native calibration or Ares compatibility. Python compilation and shell
syntax pass. Native run/submission and training remain pending.
