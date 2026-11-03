#!/bin/bash -l
#SBATCH --job-name=urbaning-regions
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-regions-%j.out
#SBATCH --error=urbaning-regions-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the separate regional-dataset checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
CACHE="$BASE/runs/urbaning-joint-gain-001/runs"
POSES="$BASE/runs/urbaning-geometry-001"
TRAIN1=20241126_0017_crossing1_00
TRAIN2=20241126_0001_crossing2_00
VAL=20241126_0004_crossing2_00
OUT="${URBANING_REGIONAL_OUTPUT:-$BASE/runs/urbaning-regional-dataset-001}"
# Existing cache/pose inputs only; no installs, downloads, inference or fitting.
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_regional_dataset.py \
    --train-runs "$CACHE/$TRAIN1" "$CACHE/$TRAIN2" \
    --validation-runs "$CACHE/$VAL" \
    --train-geometry "$POSES/$TRAIN1-poses.json" "$POSES/$TRAIN2-poses.json" \
    --validation-geometry "$POSES/$VAL-poses.json" \
    --output-dir "$OUT"
