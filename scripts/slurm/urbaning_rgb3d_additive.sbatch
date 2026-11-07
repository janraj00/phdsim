#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-add
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-rgb-add-%j.out
#SBATCH --error=urbaning-rgb-add-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the additive-fusion checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
SOURCE="${1:-$BASE/runs/urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip}"
OUT="${2:-$BASE/runs/urbaning-rgb3d-additive-$SLURM_JOB_ID}"
echo "SOURCE: $SOURCE"
echo "OUTPUT: $OUT"
echo 'Cached TRAIN400 / development-validation200; fixed additive rules, no detector or training.'
echo 'Keep all LiDAR boxes; compare raw scores with separately labeled LiDAR-first ranking.'
echo 'One hour is a scheduler ceiling, not an ETA.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb3d_additive.py \
  --source "$SOURCE" --output "$OUT"
