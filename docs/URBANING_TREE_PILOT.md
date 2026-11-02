# Validation-only tree gain pilot

Prepared on 2026-11-02; not yet executed on the real Ares caches. This is an
isolated development comparison and does not change the frozen models or the
active full crossing3 experiment. First job 21569029 failed at the dependency
import preflight before loading caches or creating output; the updated batch
entry point below installs dependencies into a private job directory.

## Question and fixed protocol

Can a shallow nonlinear model extract useful acquisition decisions from the
same 32 pre-query features used by Gain–Geometry? Compare three separate gain
heads (Car2, Infra, both) with ridge regression. Both predict frame micro F1
at BEV IoU .5 minus Car1-only F1. The joint head is not the sum of single gains.
GT and counterfactual outcomes remain offline supervision/evaluation only.

- Training: 200 cached frames each from `20241126_0017_crossing1_00` and
  `20241126_0001_crossing2_00`.
- Validation: 200 frames from `20241126_0004_crossing2_00`.
- Split by original date/recording identity, not sequence segment or frame.
- Features: unchanged 32-element geometry profile, including Car1 scores,
  uncertainty summaries, availability and pose-based proximity proxies.
- Cost: **.05 per available peer bundle requested**. Choose the feasible subset
  with maximum predicted gain minus request cost, including no request.
- Ridge grid: alpha .1, 1, 10; training-only scaling, as before.
- Tree grid: squared-error `GradientBoostingRegressor`, 100 estimators,
  learning rate .05, depths 1/2 crossed with minimum leaf sizes 10/20,
  subsample 1, random state 42. Four configurations, fitted on training only.
  Each head excludes frames where its action is unavailable.
- Within each family select maximum validation mean F1 minus .05 times mean
  requests. Ties prefer fewer requests, then earlier declared configuration.
- Select the best constant policy on the same validation objective among NO,
  Car2, Infra and ALWAYS. Unavailable partners use the established fallback.
  Compare both learned policies with that baseline; constant wins an exact
  utility/request tie with a learned policy.
- For each selected learner, replay random controls with seeds 0–99, both
  schedule-matched and budget-matched, preserving the complete 0/1/2 request
  histogram within availability strata. These are retrospective controls.

All candidate utilities, selected choices, gain MAE/RMSE/bias and full metrics
for both AP ordering modes are reported. AP is diagnostic; it does not select
the model. Models and their input provenance are saved with SHA-256 hashes.
Boosted trees are stored in plain JSON with a NumPy predictor; no pickle is
loaded and existing ridge consumers/formats are not changed. The batch entry
point installs the five exact versions in `requirements/urbaning-tree-pilot.txt`
into `phdsim-work/dependencies/urbaning-tree-pilot-<job-id>`, using the existing
container Python and pip's `--target --no-deps --only-binary=:all:`. This keeps
the shared venv unchanged. It verifies all five module origins and versions,
then fits a two-sample smoke model before reading any experiment payloads.

## Run without repeating detector inference

Use a separate worktree. The batch script reads only the three completed
training/validation caches and their existing pose sidecars under the original
`phdsim/runs`. It downloads dependency wheels only; it never exports poses
again, imports upstream OpenCOOD, downloads dataset/model files, runs the
detector, submits another job or reads crossing3 predictions.
Crossing3 and recording overlaps are rejected from run headers before loading
prediction payloads. GT fingerprints, trace-bound poses and the original
baseline AP are checked by the existing independent cache reader; hashes of
the cache payloads and pose sidecars are recorded in the output provenance.

From the new checkout root on Ares:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_tree_pilot.sbatch
```

The job reserves 4 CPUs, 12 GB and at most one hour. This is a resource limit,
not a measured runtime: rechecking cached boxes can dominate the small fit.
It does not wait for or alter the active full-test array. Dependency installation
and verification run on the worker inside the container; missing/broken packages
in the shared venv are not reused for these five modules. A failed installation
is preserved in its job-specific directory and does not create experiment
output. Network access to the Python package index is needed for the wheels.

Output directory (must not exist):
`/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-tree-pilot-001`.
To preserve a failed attempt, use a fresh `URBANING_TREE_OUTPUT` with `sbatch
--export=ALL,URBANING_TREE_OUTPUT=/absolute/new/path ...`.

The log ends with F1, utility and requests for all six policies. Attach
`urbaning-tree-pilot.zip`, containing the report and both selected models:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-tree-pilot-001
scp plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-tree-pilot-001/urbaning-tree-pilot.zip \
  ~/Documents/phdsim-results/urbaning-tree-pilot-001/
```

## Interpretation and next decision

The selected policies are scored on the same validation labels used to select
them. This is **development evidence, not an independent performance estimate**.
There are only two original training recordings and one validation recording;
adjacent frames are correlated. No confidence interval over recordings is
claimed from random seeds. Previously inspected crossing3 results must not be
used to choose this pilot's parameters or features.

A useful next candidate should improve the cost/quality trade-off over the
validation-selected constant and matched random controls, not merely beat
ridge. If trees do not, do not repeat expensive detector inference on their
account. First inspect gain errors and whether the existing features explain
useful cases; low-score detections do not cover all missed objects. Any later
evaluation of a frozen new policy can replay existing test caches cheaply,
but crossing3 has already been inspected and is an iterative benchmark rather
than a pristine confirmatory test. Pose availability, native timing and bundled
request cost retain the limitations documented in the geometry policy.
