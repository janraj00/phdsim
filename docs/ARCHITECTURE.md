# Architecture

PHDSIM separates observation preparation, perception, fusion, acquisition decisions,
offline learning, runtime delivery, and experiment orchestration.

## Package responsibilities

| Package | Responsibility |
|---|---|
| `core/identity.py` | Minimal shared target identity and deterministic identifiers |
| `datasets/` | Observation pools, allocation, dataset adapters and provenance |
| `perception/` | Turn a delivered observation into a task prediction |
| `perception/pstnet/` | RGB segmentation, authors' preprocessing, checkpoint loading and RGB features |
| `perception/pstnet/training/` | Explicit supervised RGB training: configuration, data selection, trainer and report |
| `fusion/` | Combine information that has already been acquired |
| `fusion/pstnet/` | Original neural fusion model and its internal ERFNet blocks |
| `decision/` | Acquisition policies and their permitted information |
| `decision/pstnet/` | RGB-only decision view, fixed policy, and learned expected-gain policy |
| `learning/` | Offline fitting of fusion and acquisition parameters |
| `learning/pstnet/` | Fit the segmentation acquisition gate from frozen model outcomes |
| `models/` | Shared Ridge and logistic estimators; independent of experiment orchestration |
| `runtime/` | Deliver observations and execute frozen models and policies |
| `evaluation/` | Task metrics computed from predictions and offline reference labels |
| `costs/` | Cost quantities in `types.py`; budget validation and charging in `ledger.py` |
| `experiments/` | Assemble complete protocols, caches, policy comparisons and reports |
| `cli/` | Argument parsing and dispatch to the selected workflow |
| `artifacts.py` | JSON/JSONL serialization, atomic JSON writing, and SHA256 helpers |
| `walkthrough/` | Executed, source-linked inspection examples, separate from research protocols |

## Domain-owned contracts

There is no central `records.py`. Types live beside the responsibility that
owns them: delivered observations in `datasets/observations.py`, perception
predictions in `perception/results.py`, actions in `decision/actions.py`, the
presence decision view in `decision/view.py`, cost quantities in `costs/types.py`,
offline quality changes in `evaluation/results.py`, and segmentation runtime
outputs in `runtime/segmentation_result.py`. `TargetRef` and `stable_id` are the
small shared identity layer in `core/identity.py`.

Keep dependencies directed: observations do not depend on policies or evaluation;
decision views may reference local observations and predictions, but not offline
reference scores. Existing fields, validation and artifact schemas are preserved.
PSTNet's `RgbAcquisitionView` remains in `decision/pstnet/view.py` because it has a
different information contract from the presence view. See the complete type map
and execution order in [WALKTHROUGH.md](WALKTHROUGH.md).

## Two task workflows

`pstnet` is the current five-class pixel segmentation workflow. `presence` is
the retained whole-frame Survivor-presence baseline. Their metrics, splits,
models and reports must remain distinct.

```text
src/phdsim/
  cli/                    # phdsim pstnet ... / phdsim presence ...
  datasets/
    pool.py               # canonical observations without agents
    allocation.py         # observations -> agents and ticks
    pst900/               # source, download, provenance, segmentation manifest
  perception/
    pstnet/
      rgb.py              # original ResNet18 + UNet RGB architecture
      input.py            # RGB, thermal and mask preprocessing
      features.py         # local RGB features available before acquisition
      checkpoint.py       # strict RGB/fusion checkpoint loading
      training/           # own RGB training and validation
    cnn_*.py              # earlier independent presence classifiers
  fusion/
    pstnet/model.py       # original nine-channel fusion stream
    pstnet/blocks.py      # internal layer building blocks
    mean_probability.py   # one class per probability-fusion method
    learned_probability.py
    independent_evidence.py
  decision/
    policies/             # presence acquisition strategies
    pstnet/               # segmentation acquisition policies and view
  learning/
    acquisition/          # presence gain targets and fitting
    fusion/               # presence fusion fitting and cross-fitting
    pstnet/training.py    # segmentation gain regression
  models/linear.py        # estimator fitting and frozen prediction
  runtime/
    presence.py           # multi-agent original-image replay
    segmentation.py       # RGB -> gate -> optional thermal -> fusion
  evaluation/
    presence.py           # binary prediction and Brier evaluation
    segmentation.py       # pixel confusion, class IoU, global mIoU
  experiments/
    presence/             # replay, learned-policy studies, reports, comparisons
    pstnet/
      cache.py            # offline outcomes for both acquisition choices
      acquisition.py      # train the gate and compare fixed policies
      replay.py           # actual selective execution and timing
      report.py           # comparison presentation
```

## Segmentation runtime

1. Load the current RGB image and compute the original RGB confidence volume.
2. Construct an acquisition view containing RGB-derived features and transfer metadata.
3. Run the frozen acquisition policy.
4. If acquisition is declined, return the RGB mask.
5. Otherwise deliver the existing paired thermal image and run the original fusion
   stream with the cached RGB output. The RGB network is not run a second time.
6. Load the reference mask outside the decision logic and evaluate the result.

The online manifest reader parses metadata only. Image hashes are verified on
delivery, so integrity checks cannot read unrequested thermal images in advance.
Reference masks are never part of the policy view.

The current PSTNet runtime is a paired RGB-to-thermal experiment. The more general
observation allocation and multi-agent replay are exercised by the presence workflow.

## Offline learning and orchestration

`perception/pstnet/training/` fits the RGB segmentation network. `learning/pstnet/`
fits only the acquisition gate. `experiments/pstnet/cache.py` runs both frozen
vision outcomes offline to obtain supervision; that full-information cache is
not exposed to the deployed policy.

The runtime imports perception features and shared estimators, not experiment
orchestration. CLI modules delegate work and contain no training algorithms.
Fusion and decision remain separate: choosing to acquire an image does not itself
combine it with the local prediction.

## Extending the project

- Put a new fusion method in its own file or package, with its own class.
- Put a new acquisition strategy in its own policy file. Keep its input view explicit.
- Keep fitting and checkpoint selection outside runtime inference.
- Add dataset-specific conversion to the dataset adapter; keep pools free of agent IDs.
- Store model/data identity and the exact protocol with every research run.
- Add experiment combinations to `experiments/`, rather than enlarging model classes or CLI handlers.

The earlier `phdsim <presence-command>` syntax and `scripts/run.ps1` are retained
as compatibility entry points. New commands should specify the workflow explicitly.
