#!/bin/bash -l
#SBATCH --job-name=urbaning-th-head
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=24:00:00
#SBATCH --output=urbaning-thermal-head-%j.out
#SBATCH --error=urbaning-thermal-head-%j.err
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit from the thermal-head checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
MODEL="$BASE/runs/urbaning-rgb3d-late-21655505/models/outdoor"
RUNTIME="$BASE/runs/urbaning-rgb3d-late-21649159/runtime"
SOURCE="$BASE/runs/urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip"
OUT="${1:-$BASE/runs/urbaning-thermal-head-$SLURM_JOB_ID}"
DATA_ROOT_ARGS=()
if [[ -n "${URBANING_DATA_ROOT:-}" ]]; then
  DATA_ROOT_ARGS=(--data-root "$URBANING_DATA_ROOT")
fi

echo "OUTPUT: $OUT"
echo 'One fixed TRAIN epoch of native thermal ROI heads; backbone/FPN and RPN frozen.'
echo 'RPN test budget: post-NMS 4000, pre-NMS at least 4000; TRAIN only during fitting.'
echo 'TRAIN: 20241126_0001_crossing2_00 + 20241126_0017_crossing1_00 (400 anchors, up to 2400 views).'
echo 'Development validation: 20241126_0004_crossing2_00 (200 anchors), loaded after freeze.'
echo 'No crossing3; this pilot does not claim an independent test result.'
echo 'Reuses verified private CPU runtime; no install/build, new LiDAR inference, or source writes.'
echo '24h is a scheduler ceiling, not an ETA; checkpoints and logs are kept in OUTPUT.'

srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_thermal_head.py \
  --base "$BASE" --runtime "$RUNTIME" --model-dir "$MODEL" --source "$SOURCE" \
  --output "$OUT" --threads "$SLURM_CPUS_PER_TASK" \
  "${DATA_ROOT_ARGS[@]}"
