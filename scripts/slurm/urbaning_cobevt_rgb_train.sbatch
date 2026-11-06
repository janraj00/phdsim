#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-adapter
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=urbaning-rgb-adapter-%j.out
#SBATCH --error=urbaning-rgb-adapter-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the adapter training checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
PREFLIGHT="$BASE/runs/urbaning-cobevt-rgb-preflight-21597293"
OUT="${1:-$BASE/runs/urbaning-cobevt-rgb-adapter-train8-001}"
test -x "$WORK/bin/urbaning-python.sh"
test -f "$PREFLIGHT/urbaning-cobevt-rgb-preflight.zip"
test -f "$BASE/runs/urbaning-rgb-pilot-001/weights/checkpoints/mobilenet_v3_small-047dcff4.pth"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job owns this adapter output' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo 'TRAIN8 memorization only; same8 frames for fitting/evaluation; no validation/test or peer requests.'
echo 'Frozen official cls/reg heads; reuse native BEV caches; fit matched LiDAR and LiDAR+RGB adapters.'
echo 'Fixed64 epochs;2h scheduler upper bound, not an ETA; isolated torchvision only.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb_env.py \
  "$OUT/dependencies" scripts/urbaning_cobevt_rgb_train.py \
  --base "$BASE" --preflight "$PREFLIGHT" --upstream "$BASE/external/UrbanIng-V2X" \
  --model-dir "$BASE/models/urbaning/CoBEVT_SIS_1_2_vs_3" --output "$OUT" \
  --weights-dir "$BASE/runs/urbaning-rgb-pilot-001/weights" --cpu-threads "$SLURM_CPUS_PER_TASK" --epochs 64
