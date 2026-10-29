# PHDSIM

A research framework for **selective acquisition of existing peer observations**.
An agent uses its available observations to decide whether to request additional
observations from another agent. Perception, fusion and acquisition decisions are
separate modules.

The current research focus is **LiDAR cooperative object detection and selective
acquisition on UrbanIng-V2X**, using the authors' frozen CoBEVT checkpoint.
A real-data CPU pilot is complete; full held-out evaluation is pending.
See the [UrbanIng experiment status](docs/URBANING_EXPERIMENTS.md) and
[stage 1 protocol](docs/URBANING_STAGE1.md).

The earlier **PST900 / PSTNet RGB-thermal segmentation** study and whole-frame
Survivor-presence baseline remain separate research tracks. Their data, models
and metrics are described in the [experiment index](docs/EXPERIMENTS.md).

The agreed target model is **agent -> sensors[] -> timestamped observations**.
An agent may have multiple sensors and modalities. Vehicles are mobile agents;
infrastructure sensing stations are static agents. This generalization is a
design decision, not an implemented UrbanIng replay: the existing v1 allocator
still assigns one modality and at most one own observation per agent per tick.

## Set up on another computer

For the main phdsim and PSTNet environment, use Python 3.11+ and create a fresh
environment in the cloned repository. The UrbanIng CoBEVT runtime has separate
[dependency and execution instructions](docs/URBANING_STAGE1.md#run-on-cpu-or-gpu):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[pstnet-training,urbaning]"
.\scripts\test.ps1
```

Git contains source, tests, configurations, documentation and attributed upstream
references. **Datasets, trained weights, local reports and generated workbooks
are separate files and do not travel with a clone.** See the
[computer migration guide](docs/MIGRATION.md) for the exact directories to copy,
path settings and verification commands. Recreate `.venv` instead of copying it.

## Current status

### UrbanIng-V2X: active detection study

- One native sequence has been imported and cataloged with sensor timing,
  calibration and labels preserved.
- The official LiDAR CoBEVT checkpoint is pinned and frozen. The runner compares
  Car1, Car1 + Car2, Car1 + Infra, all sources and offline acquisition policies
  using the same ground truth.
- Two ten-frame CPU smoke windows completed. The example entropy gate requested
  a partner on every frame, so effective adaptive stopping is not established.
- Full held-out evaluation, GPU execution and native macOS setup remain pending.
  See [UrbanIng measurements and limitations](docs/URBANING_EXPERIMENTS.md).
- [Joint subset acquisition](docs/URBANING_SUBSET_POLICIES.md) supports none,
  Car2, Infra or both, a gain predictor and exact matched random controls.
  Synthetic fitting and 20-frame cached replay passed; a real-data policy has
  not been trained or evaluated on independent recordings.

### PST900 / PSTNet: earlier segmentation study

- RGB and neural RGB-thermal fusion architectures, preprocessing and global
  pixel-IoU evaluation have upstream numerical parity tests.
- An own RGB pilot used 48 training frames, 24 validation frames and five epochs:
  **31.21% validation mIoU**, versus 19.24% for background-only prediction.
  Segmentation remains weak; hand-drill IoU is zero.
- Own fusion training and learned acquisition experiments remain pending.
- The official author checkpoint links checked on 2026-10-17 did not provide
  the files. See [PSTNet measurements and limitations](docs/PSTNET_EXPERIMENTS.md).

## PSTNet segmentation data flow

```text
source data -> observation pool -> agent/tick allocation
                                  |
                                  v
                           local RGB perception
                                  |
                           acquisition decision
                            /              \
                         stop          request thermal
                          |                 |
                      RGB mask       original neural fusion
```

The separate PSTNet experiment uses paired RGB-to-thermal acquisition. The general
multi-agent allocator is exercised by the presence baseline. A policy receives
local evidence and transfer metadata; reference masks and unrequested peer images
are excluded. Offline teacher collection is separate from online replay.

## Repository map

| Location | Purpose |
|---|---|
| `src/phdsim/datasets/` | Observations, allocation, PST900 conversion and UrbanIng import |
| `src/phdsim/perception/` | RGB segmentation/training and the UrbanIng LiDAR model adapter |
| `src/phdsim/fusion/` | One implementation per fusion method; PSTNet neural fusion |
| `src/phdsim/decision/` | Acquisition contracts and separate policy implementations |
| `src/phdsim/learning/` | Offline fusion and acquisition fitting |
| `src/phdsim/runtime/` | Observation delivery and frozen-model execution |
| `src/phdsim/experiments/` | Protocol orchestration, caches, comparisons and reports |
| `src/phdsim/evaluation/` | Separate segmentation, detection and presence metrics |
| `src/phdsim/models/` | Shared numerical estimators |
| `src/phdsim/cli/` | Explicit `pstnet`, `presence` and `urbaning` workflows |
| `configs/pstnet/`, `configs/presence/` | Task-specific settings |
| `tests/` | Unit, protocol, upstream-parity and integration checks |
| `third_party/pst900/` | Upstream attribution, license and unchanged test references |
| `archive/` | Recoverable source snapshots and the original project description |

Detailed boundaries and extension rules: [architecture](docs/ARCHITECTURE.md).
For a source-linked, step-by-step reading session, start with the
[simulation walkthrough](docs/WALKTHROUGH.md). Run `scripts/walkthrough.ps1` to
generate an executed trace with current file/line links. PSTNet inspection uses
synthetic images and randomly initialized architectures; presence uses one real
test frame and existing trained checkpoints.

## Run on Windows

The launchers prefer a project `.venv`, then the existing environment at
`D:\Doktorat\Platforma\.venv`, then a compatible installed Python. Configuration
files contain local data/model paths; adjust them when using another machine.

```powershell
# Inspect the current environment and checkpoint availability; no training.
.\scripts\pstnet.ps1 -Action status

# Run the test suite. Training checks use small temporary fixtures.
.\scripts\test.ps1

# Generate a source-linked walkthrough of both runtime paths.
.\scripts\walkthrough.ps1
```

Start a new RGB pilot with separate output and model directories:

```powershell
.\scripts\pstnet.ps1 -Action train-rgb `
  -TrainingConfig configs\pstnet\rgb_pilot.json `
  -Output runs\pstnet_rgb_pilot_v2 `
  -ModelDirectory D:\Doktorat\Platforma\models\pstnet_rgb_pilot_v2
```

Existing result/model directories are protected from overwrite. Full dataset
preparation is available through `-Action prepare`. Neural checkpoint loading,
counterfactual collection, gate fitting and selective replay are documented in
[PSTNet reproduction and own training](docs/PSTNET_REPRODUCTION.md).

The installed Python CLI uses the same workflows:

```powershell
phdsim --help
phdsim pstnet --help
phdsim presence --help
phdsim urbaning --help
```

The PSTNet pilot's tested local stack uses PyTorch 2.14.1 CPU, torchvision 0.29.1,
Pillow and OpenCV. The RGB trainer expects the checksum-verified ImageNet encoder cache;
its preparation is described in the training guide.

## Documentation and artifacts

- [Research context and latest decisions for continuing in a new Codex chat](docs/CONTEXT.md)
- [Computer migration: clone, environment, datasets, models and reports](docs/MIGRATION.md)
- [Architecture and module responsibilities](docs/ARCHITECTURE.md)
- [Step-by-step simulation walkthrough and domain type map](docs/WALKTHROUGH.md)
- [Data formats, file counts and the two preprocessing stages](docs/DATA.md)
- [Dataset compatibility audit and proposed shared data/storage contract](docs/DATASET_AUDIT.md)
- [UrbanIng-V2X real sequence import, catalog and geometry inspection](docs/URBANING.md)
- [Experiment index: separate datasets, models, tasks and status](docs/EXPERIMENTS.md)
- [UrbanIng CoBEVT measurements and next research steps](docs/URBANING_EXPERIMENTS.md)
- [Ares: frozen recording-level experiment and Slurm submission](docs/URBANING_ARES.md)
- [PST900 / PSTNet pilot measurements and pending work](docs/PSTNET_EXPERIMENTS.md)
- [PSTNet reproduction and own RGB training](docs/PSTNET_REPRODUCTION.md)
- [Historical presence baseline](docs/PRESENCE_BASELINE.md)
- [Quality, computation and resource comparisons](docs/RESOURCES.md)

Large data, cached downloads and checkpoints live under `D:\Doktorat\Platforma`.
`runs/` contains local reports, figures and traces and is Git-ignored. The RGB
pilot is in `runs/pstnet_rgb_pilot/`; its weights are in
`D:\Doktorat\Platforma\models\pstnet_rgb_pilot_v1`.
Historical results and trained weights are retained during repository cleanup.

PSTNet transfer accounting uses image pulls and stored PNG bytes. UrbanIng
stage 1 counts requested peer bundles; byte and network-latency savings have not
been measured. Movement, physical network transport, energy measurement and
online policy updates remain future work.

PSTNet-derived code retains the upstream GPL-3.0 license and attribution;
see [the third-party notice](third_party/pst900/NOTICE.md).
