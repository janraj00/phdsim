# PHDSIM research handoff

Updated: **2026-10-29**. This document summarizes the latest decisions in the
project conversation. Earlier explanations in the
[conversation archive](CHAT_HISTORY_2026-10-19.md) include superseded assumptions.

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
