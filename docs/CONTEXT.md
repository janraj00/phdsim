# PHDSIM research handoff

Updated: **2026-11-03**. This document summarizes the latest decisions in the
project conversation. Earlier explanations in the
[conversation archive](CHAT_HISTORY_2026-10-19.md) include superseded assumptions.

## Completed regional feature-ablation pilot (2026-11-03)

Regional dataset job **21576386** completed and its uploaded ZIP was audited:
400 train / 200 validation frames, exact file hashes, identities, availability,
TP/FP/FN conservation and recovery/loss bindings. Validation frame F1 reconstructed
from regional counts equals the earlier tree pilot. Overflow target counts are
zero in these recordings. The 46 features are manually engineered hypotheses,
not a feature set supplied by the UrbanIng paper.

The user authorized fitting the first regional learner. A NumPy ridge experiment
ran directly on that ZIP locally in about five seconds, with no new Ares job,
detector calls or crossing3 access. Three directly supervised action heads predict
per-class regional **FP+FN reduction**. Train-only scaling, unavailable-action
masks and recording splits are enforced. Fixed alpha grid .01/.1/1 selects by
validation macro MSE; this is not acquisition policy selection.

Validation MSE: zero **.049041**, training mean **.048335**, geometry **.047468**,
local evidence **.041654**, combined **.041330**, plus neighbors **.041260**,
full class-aware 46 features **.037557** (alpha .1). Full improves this prediction
error 23.4% versus zero, **not detection F1/AP**. Changed-cell MSE improves
1.562838→1.131719, but harm-cell MSE worsens 1.278871→1.602021. Empty-Car1
regions improve minimally or not at all: most signal remains in regions with
existing detections. The information-deficit goal is therefore not solved.

Five models, predictions, a fixed example map and detailed stratified report
are generated. No independent test or new request/F1/AP/utility result exists.
The one validation recording has already been inspected; avoid treating it as
unseen. See [regional learning protocol](URBANING_REGIONAL_LEARNING.md).
Earlier preparation statements below are superseded by this section.

## Regional dataset preparation (2026-11-03)

Inspection job **21574240** completed in 2m18s (exit 0). The uploaded
`urbaning-frame-inspection.zip` contains five selected validation cases and
all 200 frame match traces. In frame 161, GT object 2 is Vehicle at about 67m
from Car1. Car1 has no overlapping prediction, Car1+Car2 reaches IoU .532,
Car1+Infra's best overlap is .412 and all sources .503. This is a qualitative
GT-selected case, not proof of visibility or a general partner ranking. The
NO-beneficial category had three positive candidates but was omitted by spacing;
do not claim it was absent from the recording.

The user approved the next concrete step: prepare fixed regional inputs and
offline targets from the existing **400 train / 200 validation** frames. The
exporter is prepared, not yet run on real full recordings. It retains all 400
fixed 10m cells plus explicit overflow, uses only Car1 detections and assumed
pose/availability metadata as 46 input features, and exports GT-derived regional
TP/FP/FN, recovered/lost objects and deltas separately. Count conservation must
reproduce full-frame matching. Unavailable action masks are mandatory; no GT-driven
cell selection or per-cell communication charge is allowed. There is no fitting,
inference, download or crossing3 access. See
[regional dataset protocol](URBANING_REGIONAL_DATASET.md).

This is input/label preparation, not a learned information-deficit map or a
new performance result. Empty detection cells do not establish observability.
The intended next learner can predict local partner usefulness after checking
these labels; raw LiDAR coverage and RGB/thermal remain later steps.

## Current objective, verified results and spatial inspection (2026-11-03)

The user restated the main goal: Car1 should identify spatial regions with
missing/uncertain information and predict whether another agent's particular
sensor can improve the task there, before receiving its perception payload.
Agents can own multiple modalities; RGB/thermal are later extensions. Global
frame-level partner selection and class-wise reporting are intermediate steps.
Low-score detections alone cannot represent entirely missed/occluded objects;
do not claim to have a visibility/observability map from box summaries.

The user supplied the completed **1400-frame full-policy report** (seven
crossing3 sequences, five original recording groups). All-source predictions
match the earlier benchmark numerically. Global-sort mAP@.5 / F1 / requests /
utility at cost .05: ALWAYS **33.7102% / 54.5905% / 2033 / .473298**;
Gain–Ego **33.1274% / 53.7529% / 1838 / .471886**;
Gain–Geometry **32.2393% / 52.2992% / 1533 / .468242**. Both learned policies
lose F1/utility to all 100 corresponding exact budget-matched random draws.
Entropy's frozen thresholds reproduce ALWAYS. NO occurs only in 89 frames
with no available partner; neither learned model skips all available peers.
Car2 is available in 766 frames, Infra in 1267, both in 722. Direct partner
quality comparisons must stratify availability.

The GT-assisted offline F1-minus-cost reference uses **1306 requests** (35.8%
less than ALWAYS), F1 **54.0039%**, global mAP@.5 **33.6362%**, utility **.493396**.
This establishes hindsight headroom for that objective, not a deployable policy
or an mAP optimum. Default-order mAP@.5 for ALWAYS is **24.8134%**; keep AP
ordering explicit. The report was read from `urbaning-full-policy-report.zip`.
No completed diagnostic report has yet been supplied.

The validation tree pilot succeeded as job **21569108** after dependency
isolation. On its 200 crossing2 validation frames, ridge alpha 10 won utility
(.594805, F1 66.8805%, 296 requests) against the selected tree (.591830,
67.0080%, 313 requests) and ALWAYS (.591033, 67.4533%, 334 requests).
Its ridge weights/scaling equal the original Gain–Geometry model exactly;
validation success therefore did not generalize to crossing3. Trees have not
been evaluated on the full test in this report. These are validation-selected
results, not an independent performance estimate.

The user now authorized looking at concrete frames and where each source
recovers/misses objects. A separate **train/validation-only** inspector is
prepared, not run on real recordings. It exports full-scene/zoom comparisons,
object-index match traces and a strict Car1-evidence versus offline-outcome
boundary, bundled as one ZIP. It performs no inference/fitting/downloads and
does not alter the completed experiment. See
[frame inspection protocol](URBANING_FRAME_INSPECTION.md). Older preparation
and pending-result statements below are superseded by this section.

## Validation-only nonlinear policy pilot (2026-11-02)

The first pilot job **21569029** failed during the scikit-learn import preflight,
before any cache loading or training. The supplied log tail does not reveal the
original ImportError. The revised batch entry point installs all five pinned
scientific runtime packages into a fresh job-specific directory under
`phdsim-work/dependencies`, verifies versions/module origins and a tiny model
fit inside the existing container, then runs the pilot. It does not change the
shared venv. The experiment output path remains unchanged because that failed
preflight occurred before output creation. No real pilot results exist yet.

The user authorized a cheap comparison of ridge and shallow boosted trees on
the existing crossing1/2 training/validation caches, keeping the same 32
Gain–Geometry features and request cost .05. The isolated runner and batch job
are prepared, not executed on real caches. Three gain heads are independently
fitted with availability masks. A fixed four-configuration tree grid and the
existing ridge alphas are selected on validation utility; the best constant
NO/Car2/Infra/ALWAYS baseline is also selected on validation. Exact matched
random controls use seeds 0–99. See [tree pilot protocol](URBANING_TREE_PILOT.md).

This pilot performs no new detector inference, downloads, pose exports or
crossing3 evaluation, and does not modify the active experiment worktrees,
models or jobs. Validation-selected performance is development evidence only;
no new real results or model improvement are claimed. User-reported diagnostics
job **21566813** was submitted after the full-policy collector; no completed
diagnostic report has been supplied yet.

## Latest execution and diagnostic follow-up (2026-11-02)

The user submitted full-policy array **21564341**, collector **21564342**, and
single-sequence preview **21564899**. Sequence `20241127_0010_crossing3_08` and its
preview completed successfully. The uploaded preview ZIP was read: 200 frames,
Infra available in all 200 and Car2 in 39. Gain–Ego used 217 requests with global
mAP@.5 39.2178%; Gain–Geometry used 237 with 38.6464%; Infra-only used 200 with
39.3278%. Geometry did not improve selection in this inspected recording. The
full seven-sequence policy report has not been supplied yet.

The user authorized post-hoc availability-stratified, original-recording and
paired marginal-F1 analysis, plus frozen gain prediction errors and GT-assisted
utility headroom. A separate diagnostics job is prepared to wait for collector
21564342; it performs no training/tuning/detector inference and packages both
full and diagnostic reports into `urbaning-analysis.zip`. See
[diagnostic protocol](URBANING_DIAGNOSTICS.md). Submit from a separate worktree;
do not edit the checkout used by the active full-policy array. Older preparation
statements below are superseded by these user-confirmed submissions/results.

## Current verified state and next run (2026-11-02)

User-supplied full benchmark report confirms completion of seven crossing3
sequences, 1400 frames, all-source frozen CoBEVT. mAP@.5 with upstream default
ordering is 24.8134%, compared with 24.8563% in the checkpoint release report;
with global confidence sorting the same predictions score 33.7102%. This is a
close numerical reproduction, not an exact match. Do not mix AP ordering modes.

The earlier recording-level experiment and Gain–Geometry fit/test completed.
On the inspected 200-frame crossing3 pilot, Gain–Geometry used 295 requests,
versus 370 for ALWAYS and 365 for Gain–Ego; global-sort mAP@.5 was 36.9542%,
36.0734% and 36.1705%, respectively. Infra-only used 184 requests and scored
37.3602%. These are pilot results, not full-test policy results.

The user authorized expanded policy evaluation on the full 1400-frame test,
using the existing frozen Gain–Ego/Geometry models, cost .05 and seeds 0–99.
The separate full-policy runner is prepared, but no such job has been submitted
from this session. It reads completed benchmark conversions, computes four
counterfactual outcomes per frame and reports both AP ordering modes with matched
random controls. No policy refitting or tuning on crossing3 is authorized by
this expansion. See [full-policy protocol](URBANING_FULL_POLICIES.md).

This session has no direct Ares SSH access; the user runs supplied SSH commands.
Ares paths: `/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work`,
original repo `phdsim`, verified container wrapper `bin/urbaning-python.sh`.
Use a separate worktree and preserve existing outputs. The official model release
currently offers only CoBEVT weights; other methods have configurations but no
weights were found in that release. Earlier dated machine/progress statements
below are historical and superseded by this section.

## Latest geometry-policy extension (2026-10-30)

The user approved predicting partner utility from partner poses relative to
low-score Car1 detections. A separate 32-feature geometry profile, pose-only
sidecar exporter and cached fit/replay path are implemented; the 16-feature
baseline remains unchanged by default. No geometry model has been trained on
real recordings. See [geometry policy contract](URBANING_GEOMETRY_POLICY.md).
Infra's released pose is the bundled site's coordinate origin, not an individual
sensor; use proximity only as a proxy. Pre-query pose sharing is explicit added
metadata, not an established online transport capability.

The user supplied successful Ares container doctor output and the 10-frame CPU
smoke metrics, matching the earlier pilot. Preflight Slurm job 21540119 completed
with exit 0. The user then submitted baseline job **21540128** (8 CPUs, 24 GB,
12 hours); the latest supplied trace showed crossing2 inference in progress.
No final independent-recording policy result has been supplied. This assistant
still has no direct Ares SSH access. Do not update the active Ares checkout while
that experiment runs; use the separate geometry branch/check out afterwards.
Earlier machine-state notes below describe preparation history and are superseded
by these user-provided execution observations.

## Research tracks and reporting

[EXPERIMENTS.md](EXPERIMENTS.md) is an index only. Current UrbanIng LiDAR detection
results live in [URBANING_EXPERIMENTS.md](URBANING_EXPERIMENTS.md); earlier PST900 /
PSTNet segmentation results live in [PSTNET_EXPERIMENTS.md](PSTNET_EXPERIMENTS.md).
Keep their models, splits, metrics and pending work distinct: pixel mIoU is not
detection AP/mAP. Use Car1, Car2 and Infra in UrbanIng explanations and state
which platform performs the detection task.

## Research objective

Study **selective acquisition of existing peer observations** for a defined
perception task. An agent first uses its own available observations and decides
whether to request useful additional observations from other agents. Measure
task quality against communication cost, transferred bytes and latency.

Acquisition here means requesting a measurement already captured by another
agent. It does not inherently mean driving somewhere, taking a new measurement
or exchanging every agent's predictions automatically. Exchanging features or
predictions can be an explicitly chosen protocol, but it is not the definition
of observation acquisition.

Keep the dataset importer, agent allocation, perception, fusion, acquisition
decision, runtime delivery and evaluation as separate responsibilities. Avoid
changing several of these at once when interpreting experiment results.

## Latest agent model

The user explicitly replaced the earlier one-modality-per-agent restriction with
**agent -> sensors[] -> timestamped observations**:

- An agent can own several sensors, including different modalities.
- Each sensor produces its own observations and has its own capture times.
- Vehicles are mobile agents; physical infrastructure sensing stations can be
  static agents with the same observation/communication responsibilities.
- Movement is not the immediate research objective; replay uses recorded poses.
- The observation pool remains independent of simulator agent assignment.
- Allocation controls which observations each agent receives and in which time
  slots. Per-agent counts should be configurable, not fixed at 100.

For UrbanIng, the two recorded cars are the two natural mobile agents. Each has
six RGB cameras and a LiDAR. Infrastructure has thermal cameras and LiDARs.
Representing each physical station as a static agent is the intended direction;
the exact mapping from source sensor names to stations still needs verification.
The number of sensor streams is not automatically the number of agents.

**Implementation boundary:** `datasets/allocation.py` still implements the older
v1 `AgentSlot` with one modality and at most one own observation per frame. The
multi-sensor design and UrbanIng simulation ownership have not been implemented.

## Dataset preparation and storage

The agreed two-stage approach is:

1. Dataset-specific preprocessing creates a pool/catalog of native observations,
   independent of agents, with payload references and separate offline labels.
2. A later scenario preparation stage assigns sensors/observations to agents and
   establishes time-dependent input availability.

The user wants multiple datasets normalized into a common representation, with
large batch downloads/transforms potentially running on Cyfronet later. The
[25-dataset audit](DATASET_AUDIT.md) describes the proposed generic v2 contract;
that general loader is not implemented yet.

The storage direction is Parquet metadata queried with DuckDB, with binary
payloads retained as files/object-storage assets. New datasets are appended
occasionally; experiments generally read stable snapshots. No central database
server or Cyfronet deployment has been set up.

## UrbanIng-V2X: active detection and acquisition study

The current research direction is cooperative **3D object detection**, followed
by acquisition experiments on a working detector/fusion baseline. The dataset
authors benchmarked **LiDAR-only** cooperative detection using PointPillars and
several fusion methods. The availability of RGB and thermal in the dataset does
not mean their published benchmark trained RGB/thermal fusion.

The intended order agreed with the user is:

1. Establish working 3D detection and fusion as a reference.
2. Compare strategies for deciding when, from whom and which information to
   acquire, measuring detection quality and communication cost.

Selective communication already has prior work, including methods in the
authors' benchmark. Do not claim novelty without a relevant literature comparison.
The user selected the authors' released **LiDAR CoBEVT SIS_1_2_vs_3** checkpoint
for stage 1. A pinned external-model adapter and offline comparison runner are
implemented: Car1, Car1 + Car2, Car1 + Infra, all sources, random-one-peer and
an optional uncertainty gate based on Car1's predictions. Car1 (`100000`) and
Car2 (`200000`) are platform identities; this pilot uses Car1 as the detector's
reference agent. Infra (`-1` at crossing1) is the bundled infrastructure site.
All actions share fixed all-source GT. The original multi-sensor native catalog
remains separate.
The released model groups roadside sensors into one infrastructure-site input;
this is not sensor-level acquisition or RGB/thermal fusion.
See [stage 1 protocol and commands](URBANING_STAGE1.md).

Joint subset acquisition is now implemented: no acquisition, Car2, Infra, or
both, with a separately fitted joint-gain head rather than additive single-peer
gains. The user requires comparable random behavior: schedule-matched and
exact histogram/budget-matched randomized controls over the same feasible
subsets, including zero and two requests. The independent Bernoulli-subset
baseline is also retained. Use 100 predeclared seeds, not a selected seed.
See [subset policy protocol and diagnostic replay](URBANING_SUBSET_POLICIES.md).
The fitting/export/replay path passed synthetic tests and cached replay passed
on the existing 20 real frames. No gain model was trained on real data: these
windows share one original recording, so they cannot be split between policy
fitting and validation. Recordings used for either stage are rejected during
evaluation; crossing3 remains reserved. The offline hindsight F1 selector uses
GT and must never be presented as a deployable learned policy.

Model archive integrity and strict checkpoint compatibility have been checked.
CPU tests use synthetic voxels and known boxes. A real-data CPU smoke evaluation
also completed on 20 frames (1–10 and 101–110 of the prepared crossing1 sequence);
see [UrbanIng experiment status](URBANING_EXPERIMENTS.md). The full held-out
benchmark and online acquisition remain pending. The execution environment is a remote
Linux CPU session, not the user's MacBook. One native sequence was downloaded and
verified again there; no GPU or PLGrid session is available. The complete CPU
path works on Linux; native macOS/Apple Silicon dependency installation is not validated.

One real sequence, `20241126_0017_crossing1_00`, release 1.0 of
`doi:10.7910/DVN/A9LPY7`, was downloaded, hash-verified, extracted and cataloged:

| Item | Verified count |
|---|---:|
| RGB streams / native images | 12 / 4,814 |
| Thermal streams / native images | 6 / 3,721 |
| LiDAR streams / native point clouds | 6 / 2,478 |
| Auxiliary navigation streams / records | 2 / 5,600 |
| Source synchronization anchors | 200 |
| Association memberships | 5,200 |
| Tracks / timestamped object annotations | 152 / 25,250 |

There are 201 annotation timestamps. One endpoint, containing 15 object records,
has no source synchronization anchor and is retained with an explicit flag.
Source-selected camera capture times differ from association anchors by up to
45 ms. Replay must define decision time, observation age and availability rather
than silently exposing measurements captured after the decision.

RGB images are JPEG 1920 x 1080; thermal images are 8-bit grayscale JPEG 640 x
480, without an inferred temperature conversion. LiDAR NPZ files preserve
`x`, `y`, `z`, `intensity` and per-point `time_offset_ms`. RGB vehicle views and
roadside thermal views have different viewpoints; calibration does not make
them pixel-aligned pairs.

The experimental adapter exports six JSONL/Parquet tables: `observations`,
`assets`, `streams`, `associations`, `annotations`, `geometry`. Native files are
referenced rather than copied; UTC nanoseconds remain integers. This adapter
spike is not the final cross-dataset v2 schema.

Camera rectification matched SDK 1.0.1 pixel-for-pixel on one image from each of
18 cameras. All catalog fingerprints, asset existence, observation/association
links and timestamp precision were checked. Geometry roundtrip checks establish
matrix consistency, not independent physical calibration accuracy. Image and
point-cloud previews show source data and ground truth, not learned predictions.

See [UrbanIng import and inspection](URBANING.md) and the separate
[CoBEVT stage 1 adapter](URBANING_STAGE1.md). A diagnostic real-data CPU result is
available; full held-out evaluation and online replay are pending. No general simulator agent assignment has been
performed for this dataset; the model adapter follows the official three-source
vehicle/site grouping only.

## PST900: implemented earlier research, retained separately

The implemented neural task is five-class RGB/thermal semantic segmentation.
Original PSTNet RGB/fusion computations, preprocessing, inference and global IoU
evaluation have numerical parity tests against attributed upstream reference
code. Random-weight parity is not a reproduction of trained benchmark accuracy.

An own RGB pilot completed with 48 training frames, 24 validation frames and
five epochs. Validation mIoU was **31.21%**, versus **19.24%** for background-only
prediction. Segmentation remains weak; hand-drill IoU is zero. Keep this small
pilot separate from published results and from earlier whole-frame Survivor
presence experiments.

Own PSTNet fusion training and acquisition experiments are pending. The original
authors' checkpoint links were unavailable when checked on 2026-10-17; do not
silently use random or unrelated weights. Existing code for an offline Ridge
acquisition gate predicts expected task-quality gain from locally available RGB
features, including entropy, margins and prediction statistics. Ground-truth
counterfactual gains are offline targets, not runtime policy inputs.

Training, validation, acquisition learning and final testing must remain
separate. Keep related recordings together, and account for the fact that the
older presence test subset was inspected during development. See
[PSTNet experiment status](PSTNET_EXPERIMENTS.md),
[PSTNet guide](PSTNET_REPRODUCTION.md) and
[presence baseline](PRESENCE_BASELINE.md).

## Repository and machine handoff

The user confirmed active Ares access on 2026-10-29. A recording-level protocol
and resumable subprocess driver are prepared with a CPU Slurm wrapper; see
[Ares experiment setup](URBANING_ARES.md). Two training recordings, one validation
recording and one crossing3 test recording are predeclared, up to 200 frames
each. Policy fitting is frozen before collecting test predictions. The wrapper
requests 8 CPUs, 24 GB RAM and 12 hours (maximum allocation 96 CPU-hours).
No job has been submitted: this session has no authenticated SSH configuration,
and the grant allocation/environment paths are not known. Dataverse currently
returns HTTP 403 here; connectivity from Ares has not been checked. Do not infer
that active cluster access means a runnable runtime or accessible source data.

Private GitHub repository: `https://github.com/janraj00/phdsim`.
The initial published commit is `f7323c22e953042cfc2d735c0027aa6e7b831ec2` on
`master`; this handoff is a subsequent documentation change. README and maintained
guides are in English. The user usually discusses the project in Polish and
prefers concrete, step-by-step explanations of data and decision flow.

The full suite passed **70 tests**, including on a fresh clone fetched from the
private GitHub repository, using the source machine's Python environment. Setup
on a new machine still requires recreating that machine's environment.

External research root: `D:\Doktorat\Platforma`:

- `data/pst900/` and `data/urbaning-v2x/`: roughly 11.3 GB combined.
- `models/`: roughly 326 MB, including `pstnet_rgb_pilot_v1`,
  `pst900_resnet18_v1`, `pst900_learning_cnn_v1`.
- `cache/torch/`: the verified ImageNet initializer.
- Old checkout `runs/`: roughly 38 MB of reports, histories and previews.
- Old checkout archive ZIPs and selected `outputs/` workbook files are also local.

These files are Git-ignored and are not recovered by cloning. The checkout may
move; preserve or update configured external paths. PST900 manifests embed
absolute asset paths, while UrbanIng catalog asset keys are root-relative.
Follow [the migration guide](MIGRATION.md) before assuming data or weights exist.

## Suggested starting prompt after cloning

> Read AGENTS.md, docs/CONTEXT.md and docs/MIGRATION.md. Verify the available code,
> environment, datasets and checkpoints. Continue PHDSIM with the agreed
> multi-sensor agent model. First establish a working UrbanIng 3D detection/fusion
> reference, then compare acquisition strategies under communication costs.
> Preserve earlier PST900 results and clearly distinguish implemented components
> from plans and experiments that have actually run.
