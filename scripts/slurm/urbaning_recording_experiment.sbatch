#!/bin/bash -l
#SBATCH --job-name=urbaning-joint-gain
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=12:00:00
#SBATCH --partition=plgrid
#SBATCH --output=urbaning-%j.out
#SBATCH --error=urbaning-%j.err

set -euo pipefail

# Submit with sbatch -A YOUR_GRANT-cpu ... . This file never guesses an account.
# PHDSIM_ENV_SETUP may load the same modules used to build the Python environment.
if [[ -n "${PHDSIM_ENV_SETUP:-}" ]]; then
    source "$PHDSIM_ENV_SETUP"
fi
: "${PHDSIM_PYTHON:?Set PHDSIM_PYTHON to the absolute python path in the prepared Linux environment}"
: "${PHDSIM_UPSTREAM:?Set PHDSIM_UPSTREAM to the pinned external UrbanIng checkout}"
: "${PHDSIM_DATA_ROOT:?Set PHDSIM_DATA_ROOT to the native data directory}"
: "${PHDSIM_MODEL_DIR:?Set PHDSIM_MODEL_DIR to the CoBEVT bundle directory}"
: "${PHDSIM_EXPERIMENT_DIR:?Set PHDSIM_EXPERIMENT_DIR to a dedicated experiment output directory}"

cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"
export MKL_NUM_THREADS="$SLURM_CPUS_PER_TASK"
export OPENBLAS_NUM_THREADS="$SLURM_CPUS_PER_TASK"

srun "$PHDSIM_PYTHON" scripts/urbaning_recording_experiment.py \
    --upstream "$PHDSIM_UPSTREAM" \
    --data-root "$PHDSIM_DATA_ROOT" \
    --model-dir "$PHDSIM_MODEL_DIR" \
    --output "$PHDSIM_EXPERIMENT_DIR" \
    --cpu-threads "$SLURM_CPUS_PER_TASK" \
    --fetch --execute
