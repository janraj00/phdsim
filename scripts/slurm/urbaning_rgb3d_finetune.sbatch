#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-fit
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=24:00:00
#SBATCH --output=urbaning-rgb-fit-%j.out
#SBATCH --error=urbaning-rgb-fit-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the new RGB fine-tuning checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
RUNTIME="$BASE/runs/urbaning-rgb3d-late-21649159/runtime"
MODEL="$BASE/runs/urbaning-rgb3d-late-21655505/models/outdoor"
SOURCE="$BASE/runs/urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip"
OUT="${1:-$BASE/runs/urbaning-rgb3d-finetune-$SLURM_JOB_ID}"
echo "OUTPUT: $OUT"
echo 'Native startup gate -> four fixed TRAIN400 epochs -> freeze -> TRAIN400 / validation200 evaluation.'
echo 'Train native 2D/3D ROI heads, including foreground/background classification; frozen backbone/FPN/RPN.'
echo 'Reuses existing CPU runtime; no installation, new LiDAR inference, source writes or crossing3.'
echo '24h is a scheduler ceiling, not an ETA. Fresh output required; checkpoints preserve partial work.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb3d_finetune.py \
  --base "$BASE" --runtime "$RUNTIME" --model-dir "$MODEL" --source "$SOURCE" \
  --output "$OUT" --cpu-threads "$SLURM_CPUS_PER_TASK"
