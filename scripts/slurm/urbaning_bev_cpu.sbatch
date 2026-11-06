#!/bin/bash -l
#SBATCH --job-name=urbaning-bev-cpu
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=06:00:00
#SBATCH --output=urbaning-bev-cpu-%j.out
#SBATCH --error=urbaning-bev-cpu-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the BEV CPU checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="${1:-$BASE/runs/urbaning-bev-cpu-001}"
test -x "$WORK/bin/urbaning-python.sh"
test -f "$WORK/inputs/urbaning-gap-acquisition-inputs-001.zip"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job owns this CPU BEV output' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo 'Real new BEV boxes: RGB-only / point-grid LiDAR-only / RGB+LiDAR; small CPU prototype'
echo '400 train /200 validation; fixed8 epochs per variant; no crossing3 or pretrained CoBEVT inference'
echo 'The old CoBEVT checkpoint is only an external reference, not a controlled modality ablation'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb_env.py \
  "$OUT/dependencies" scripts/urbaning_bev_cpu.py \
  --base "$BASE" --output-dir "$OUT" --epochs 8 \
  --weights-dir "$BASE/runs/urbaning-rgb-pilot-001/weights"
