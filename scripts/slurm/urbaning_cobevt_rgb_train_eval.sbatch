#!/bin/bash -l
#SBATCH --job-name=rgb-train-eval
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=08:00:00
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the diagnostic checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
STAGE="${1:?Expected stage}"
SOURCE="${2:?Expected source run}"
OUT="${3:?Expected diagnostic output}"
SEED="${SLURM_ARRAY_TASK_ID:-0}"
mkdir -p "$OUT/locks"
exec 9>"$OUT/locks/$STAGE-$SEED.lock"
flock -n 9 || { echo 'Another job owns this diagnostic stage/seed' >&2; exit 1; }
echo "STAGE=$STAGE SEED=$SEED SOURCE=$SOURCE OUTPUT=$OUT"
echo 'Frozen final models; no fitting, new normalization, image encoder or LiDAR backbone.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_cobevt_rgb_train_eval.py \
  --base "$BASE" --source "$SOURCE" --output "$OUT" --upstream "$BASE/external/UrbanIng-V2X" \
  --stage "$STAGE" --seed "$SEED" --cpu-threads "$SLURM_CPUS_PER_TASK"
