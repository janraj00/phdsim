#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb3d-late
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --output=urbaning-rgb3d-late-%j.out
#SBATCH --error=urbaning-rgb3d-late-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the RGB3D late-fusion checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="${1:-$BASE/runs/urbaning-rgb3d-late-$SLURM_JOB_ID}"
test ! -e "$OUT"
mkdir -p "$OUT"
echo "OUTPUT: $OUT"
echo 'Independent frozen Cube R-CNN RGB3D + cached Car1 LiDAR; no adapter fitting.'
echo 'Eight TRAIN frames, six cameras each; technical check, not held-out accuracy.'
RUNTIME_ARGS=(--bootstrap "$OUT/runtime")
if [ -n "${2:-}" ]; then
  test -f "$2/ready.json"
  RUNTIME_ARGS=(--reuse-runtime "$2")
  echo "REUSE RUNTIME: $2 (no install or compilation)"
fi
export MPLCONFIGDIR="$OUT/matplotlib-cache"
echo 'Four hours is a scheduler ceiling, not an ETA.'
VARIANT="${3:-omni3d}"
REFERENCE_ARGS=()
if [ -n "${4:-}" ]; then REFERENCE_ARGS=(--reference-archive "$4"); fi
echo "MODEL VARIANT: $VARIANT"
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb3d_late.py \
  "${RUNTIME_ARGS[@]}" --base "$BASE" --output "$OUT/run" \
  --cpu-threads "$SLURM_CPUS_PER_TASK" --model-variant "$VARIANT" "${REFERENCE_ARGS[@]}"
