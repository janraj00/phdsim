#!/bin/bash -l
#SBATCH --job-name=urbaning-rgb-pilot
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=03:00:00
#SBATCH --output=urbaning-rgb-pilot-%j.out
#SBATCH --error=urbaning-rgb-pilot-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the RGB pilot checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="${1:-$BASE/runs/urbaning-rgb-pilot-001}"
TRAIN_PER_RECORDING="${2:-60}"
VALIDATION_PER_RECORDING="${3:-60}"
SEED="${4:-}"
[[ "$TRAIN_PER_RECORDING" =~ ^[1-9][0-9]*$ && "$VALIDATION_PER_RECORDING" =~ ^[1-9][0-9]*$ ]] || {
  echo 'Frame caps must be positive integers' >&2; exit 1;
}
test -x "$WORK/bin/urbaning-python.sh"
test -f "$WORK/inputs/urbaning-gap-acquisition-inputs-001.zip"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another RGB pilot owns this output directory' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo "Car1 only: cap $TRAIN_PER_RECORDING frames per train recording / $VALIDATION_PER_RECORDING per validation recording; no crossing3 or detector"
echo 'Frozen MobileNet crops + learned residual logistic scorer; fixed existing 3D boxes'
if [[ -n "$SEED" ]]; then
  test -f "$SEED/completed.json"
  mkdir -p "$OUT/features"
  for source in "$SEED/features/"*.npz "$SEED/features/"*.json; do
    test -f "$source"
    target="$OUT/features/${source##*/}"
    if [[ ! -e "$target" ]]; then cp "$source" "$target"; fi
  done
  echo "SEED cached RGB features from $SEED; Python verifies every reused frame's inputs, encoder, code and payload hash"
fi
# --cleanenv in the existing worker wrapper does not preserve host PYTHONPATH.
# The bootstrap modifies sys.path inside the container instead. No shared venv edits.
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_rgb_env.py \
  "$OUT/dependencies" scripts/urbaning_rgb_pilot.py \
  --base "$BASE" --output-dir "$OUT" \
  --train-per-recording "$TRAIN_PER_RECORDING" --validation-per-recording "$VALIDATION_PER_RECORDING"
