#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-depth
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --output=urbaning-rgb-depth-%j.out
#SBATCH --error=urbaning-rgb-depth-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the native-depth checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
RUNTIME="$BASE/runs/urbaning-rgb3d-late-21649159/runtime"
PILOT="$BASE/runs/urbaning-rgb3d-late-21655505/run/urbaning-rgb3d-outdoor-train8.zip"
MODEL="$BASE/runs/urbaning-rgb3d-late-21655505/models/outdoor"
OUT="${1:-$BASE/runs/urbaning-rgb3d-depth-$SLURM_JOB_ID}"
echo "OUTPUT: $OUT"
echo '400 TRAIN -> freeze existing depth layer -> 200 development-validation.'
echo 'Reuse compiled CPU runtime/model; no installations, new LiDAR inference or crossing3.'
echo 'Native head/decoder parity gate precedes full RGB feature extraction.'
echo 'Four hours is a scheduler ceiling, not an ETA. Per-camera caches support verified resume.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb3d_depth.py \
  --base "$BASE" --runtime "$RUNTIME" --model-dir "$MODEL" --pilot "$PILOT" \
  --output "$OUT" --cpu-threads "$SLURM_CPUS_PER_TASK"
