#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-audit
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=00:30:00
#SBATCH --output=urbaning-rgb-audit-%j.out
#SBATCH --error=urbaning-rgb-audit-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the complementarity checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
SOURCE="${1:-$BASE/runs/urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip}"
OUT="${2:-$BASE/runs/urbaning-rgb3d-complementarity-$SLURM_JOB_ID}"
echo "SOURCE: $SOURCE"
echo "OUTPUT: $OUT"
echo 'Cached outcomes only. No detector, training, runtime build or source writes.'
echo 'Reproduce all five AP baselines before accepting object-identity counts.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb3d_complementarity.py \
  --source "$SOURCE" --output "$OUT"
