#!/bin/bash -l
#SBATCH --job-name=urbaning-regional-fit
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=urbaning-regional-fit-%j.out
#SBATCH --error=urbaning-regional-fit-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the regional-learning checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
DATA="${URBANING_REGIONAL_DATASET:-$WORK/phdsim/runs/urbaning-regional-dataset-001/urbaning-regional-dataset.zip}"
OUT="${URBANING_REGIONAL_LEARNING_OUTPUT:-$WORK/phdsim/runs/urbaning-regional-learning-$SLURM_JOB_ID}"
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_regional_learning.py --dataset "$DATA" --output-dir "$OUT"
