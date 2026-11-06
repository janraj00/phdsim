#!/bin/bash
set -euo pipefail
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
OUT="${1:-$WORK/phdsim/runs/urbaning-cobevt-rgb-controlled-001}"
test -f scripts/slurm/urbaning_cobevt_rgb_controlled.sbatch
test -x "$WORK/bin/urbaning-python.sh"
test -f "$WORK/inputs/urbaning-gap-acquisition-inputs-001.zip"
test -f "$WORK/phdsim/runs/urbaning-cobevt-rgb-preflight-21597293/urbaning-cobevt-rgb-preflight.zip"
mkdir -p "$OUT/logs"
JOB=scripts/slurm/urbaning_cobevt_rgb_controlled.sbatch
COMMON=(-A plgkgacq-cpu --parsable)
submit() {
  local stage="$1"; shift
  local response
  response=$(sbatch "${COMMON[@]}" --job-name="rgb-$stage" \
    --output="$OUT/logs/$stage-%A_%a.out" --error="$OUT/logs/$stage-%A_%a.err" \
    "$@" "$JOB" "$stage" "$OUT")
  printf '%s\n' "${response%%;*}"
}
INV=$(submit inventory --time=00:30:00)
echo "INVENTORY: $INV"
SMOKE=$(submit smoke --time=01:00:00 --dependency="afterok:$INV")
echo "NATIVE STARTUP GATE: $SMOKE"
FEATURES=$(submit extract --time=24:00:00 --array=0-2%2 --dependency="afterok:$SMOKE")
echo "FEATURE ARRAY: $FEATURES"
PREP=$(submit prepare --time=02:00:00 --dependency="afterok:$FEATURES")
echo "TRAIN NORMALIZATION: $PREP"
FIT=$(submit seed --time=48:00:00 --array=0-2%2 --dependency="afterok:$PREP")
echo "FIT ARRAY: $FIT"
REPORT=$(submit collect --time=02:00:00 --dependency="afterok:$FIT")
echo "REPORT: $REPORT"
echo "OUTPUT: $OUT"
echo "LOGS: $OUT/logs"
echo '400 TRAIN /200 development-validation;3 seeds;32 fixed epochs; no crossing3.'
echo 'At most2 feature workers or2 seed workers at a time;8CPU/24GiB each.'
echo 'Wall-time limits are scheduler ceilings, not completion estimates.'
