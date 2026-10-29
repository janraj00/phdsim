# Recording-level joint-gain experiment on Ares

Prepared 2026-10-29. **Not submitted or run on Ares.** The user confirmed active
Ares access; this Work session has no SSH configuration or authenticated cluster
connection. Dataverse returns HTTP 403 from this session, so data access must be
checked from the execution environment. The previous CPU profile was validated
on another Linux x86_64 session, not on Ares.

## Frozen first independent-recording experiment

The [protocol](../configs/urbaning/joint_gain_recordings.json) uses Car1 and up to
200 synchronization frames per recording, starting at the first source frame.
No label-dependent frame selection is made.

| Role | Sequence |
|---|---|
| Fit | `20241126_0017_crossing1_00` |
| Fit | `20241126_0001_crossing2_00` |
| Validation | `20241126_0004_crossing2_00` |
| Test | `20241127_0009_crossing3_00` |

These recording names occur in the pinned authors' source. This is our policy
split, not a claim to reproduce their full SIS/EIS benchmark. Only one crossing3
recording and Car1 are tested; the complete test benchmark and Car2 evaluation
remain separate extensions. The source release is pinned to 1.0. Cost is fixed
at 0.05 F1 units per bundle, ridge alpha is selected from 0.1/1/10 on validation,
and random seeds are 0–99. Fitting completes before any test-data collection.

## Inspect the cluster first

From the user's terminal, connect with the real PLGrid login:

```bash
ssh YOUR_PLGRID_LOGIN@ares.cyfronet.pl
hpc-grants
hpc-fs
module spider python
```

Use the exact CPU allocation reported by `hpc-grants`, including its `-cpu`
suffix. Do not guess the grant or Unix group name. Module names must be selected
from the actual Ares inventory. Create/install/compile the CPU runtime on a
worker allocation, using the same modules later loaded for the batch job.
The repository's [CPU setup instructions](URBANING_STAGE1.md#run-on-cpu-or-gpu)
describe the dependencies and pinned external checkout. SDK conversion also
needs `py7zr`/`multivolumefile`; these are installed by the `urbaning-stage1`
extra. Run `doctor --device cpu` in the prepared environment before a long run.

## Review and submit

With the repository cloned on the cluster, use the PR branch
`codex/urbaning-stage1-cobevt`. Set absolute paths for the prepared environment,
external checkout, native data, model bundle and dedicated output directory:

```bash
export PHDSIM_PYTHON=/absolute/path/to/venv/bin/python
export PHDSIM_UPSTREAM=/absolute/path/to/UrbanIng-V2X
export PHDSIM_DATA_ROOT=/absolute/path/to/data/urbaning-v2x
export PHDSIM_MODEL_DIR=/absolute/path/to/models/CoBEVT_SIS_1_2_vs_3
export PHDSIM_EXPERIMENT_DIR=/absolute/path/to/experiments/joint-gain-001
# Optional shell script loading the same modules used to build the environment:
export PHDSIM_ENV_SETUP=/absolute/path/to/ares-environment.sh

"$PHDSIM_PYTHON" scripts/urbaning_recording_experiment.py \
  --upstream "$PHDSIM_UPSTREAM" --data-root "$PHDSIM_DATA_ROOT" \
  --model-dir "$PHDSIM_MODEL_DIR" --output "$PHDSIM_EXPERIMENT_DIR" --fetch

sbatch --test-only -A YOUR_ALLOCATION-cpu scripts/slurm/urbaning_recording_experiment.sbatch
sbatch -A YOUR_ALLOCATION-cpu scripts/slurm/urbaning_recording_experiment.sbatch
```

The first command prints the full plan without performing downloads, creating
outputs or starting subprocesses. Submission requests **8 CPU cores, 24 GB RAM,
12 hours** on `plgrid`: at most 96 allocated CPU-hours, not an estimated runtime.
Environment preparation is a prerequisite; this script does not silently install
packages or assume a module version. Dataverse connectivity from the node is not
yet verified. If fetch fails, pre-stage verified data using the importer from a
machine that can access the source; no authentication challenge is bypassed.

The driver writes `experiment-plan.json` and completion markers. Successful
stages are reused only if their declared artifact still matches its hash;
unfinished conversion/inference directories are retained for inspection rather
than overwritten. Do not delete source archives to recover a failed stage.
Use a new experiment directory when parameters or execution paths change.
Final outputs include per-recording counterfactual caches, `joint-gain.json` and
`test-report.json`, with all fixed baselines and matched random controls.

## Cluster references

- [Ares access, partitions, memory and worker-node compilation](https://docs.hpc.cyfronet.pl/supercomputers/ares/)
- [Allocation suffixes and hpc-grants](https://docs.hpc.cyfronet.pl/environment/batch-system/accounts-and-grants/)
- [Python environments and Modules](https://docs.hpc.cyfronet.pl/software/python/)
- [Slurm job examples](https://docs.hpc.cyfronet.pl/environment/batch-system/examples/)
