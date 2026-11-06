#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-control
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=48:00:00
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the controlled adapter checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
STAGE="${1:?Expected stage}"
OUT="${2:?Expected output directory}"
INDEX="${SLURM_ARRAY_TASK_ID:-0}"
mkdir -p "$OUT/locks"
exec 9>"$OUT/locks/$STAGE-$INDEX.lock"
flock -n 9 || { echo 'Another job owns this stage/index' >&2; exit 1; }
echo "STAGE=$STAGE INDEX=$INDEX OUTPUT=$OUT"
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb_env.py \
  "$OUT/dependencies" scripts/urbaning_cobevt_rgb_controlled.py \
  --base "$BASE" --upstream "$BASE/external/UrbanIng-V2X" \
  --output "$OUT" --weights-dir "$BASE/runs/urbaning-rgb-pilot-001/weights" \
  --stage "$STAGE" --index "$INDEX" --cpu-threads "$SLURM_CPUS_PER_TASK"
