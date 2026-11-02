#!/bin/bash -l
#SBATCH --job-name=urbaning-tree-pilot
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-tree-pilot-%j.out
#SBATCH --error=urbaning-tree-pilot-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the separate tree-pilot checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
CACHE="$BASE/runs/urbaning-joint-gain-001/runs"
POSES="$BASE/runs/urbaning-geometry-001"
PY="$WORK/bin/urbaning-python.sh"
OUT="${URBANING_TREE_OUTPUT:-$BASE/runs/urbaning-tree-pilot-001}"
DEPS="$WORK/dependencies/urbaning-tree-pilot-${SLURM_JOB_ID:?}"
TRAIN1=20241126_0017_crossing1_00
TRAIN2=20241126_0001_crossing2_00
VAL=20241126_0004_crossing2_00

# Only pinned dependency wheels are downloaded into a new job-specific target.
# No changes to the shared venv, detector, data, pose exports or active jobs.
if [[ -e "$OUT" ]]; then
    echo "Output already exists: $OUT; preserve it and set URBANING_TREE_OUTPUT to a fresh path." >&2
    exit 1
fi
srun "$PY" -u scripts/urbaning_tree_env.py --dependency-dir "$DEPS" -- \
    --train-runs "$CACHE/$TRAIN1" "$CACHE/$TRAIN2" \
    --validation-runs "$CACHE/$VAL" \
    --train-geometry "$POSES/$TRAIN1-poses.json" "$POSES/$TRAIN2-poses.json" \
    --validation-geometry "$POSES/$VAL-poses.json" \
    --output-dir "$OUT"
