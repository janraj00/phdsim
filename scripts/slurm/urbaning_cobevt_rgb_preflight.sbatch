#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-check
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-rgb-check-%j.out
#SBATCH --error=urbaning-rgb-check-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the preflight checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="${1:-$BASE/runs/urbaning-cobevt-rgb-preflight-$SLURM_JOB_ID}"
test -x "$WORK/bin/urbaning-python.sh"
test -d "$BASE/external/UrbanIng-V2X"
echo "OUTPUT: $OUT"
echo 'Eight TRAIN frames; native projection QA and unchanged CoBEVT feature/head parity.'
echo 'No adapter training or RGB accuracy result. One hour is an upper limit, not an ETA.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_cobevt_rgb_preflight.py \
  --base "$BASE" --upstream "$BASE/external/UrbanIng-V2X" \
  --model-dir "$BASE/models/urbaning/CoBEVT_SIS_1_2_vs_3" \
  --output "$OUT" --cpu-threads "$SLURM_CPUS_PER_TASK"
