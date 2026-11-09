#!/bin/bash -l
#SBATCH --job-name=urbaning-th-rpn
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-thermal-rpn-%j.out
#SBATCH --error=urbaning-thermal-rpn-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the thermal-gate checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
MODEL="$BASE/runs/urbaning-rgb3d-late-21655505/models/outdoor"
RUNTIME="$BASE/runs/urbaning-rgb3d-late-21649159/runtime"
OUT="${1:-$BASE/runs/urbaning-thermal-rpn-budget-$SLURM_JOB_ID}"
DATA_ROOT_ARGS=()
if [[ -n "${URBANING_DATA_ROOT:-}" ]]; then
  DATA_ROOT_ARGS=(--data-root "$URBANING_DATA_ROOT")
fi
echo "OUTPUT: $OUT"
echo 'Read-only frozen-RPN proposal-budget sweep; no fitting or validation access.'
echo 'Samples twelve uniform TRAIN anchors from crossing1 across associated thermal cameras (up to 72 views).'
echo 'Compares configured, 2000 and 4000 proposal limits at IoU .3/.5/.7.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_thermal_rpn_gate.py \
  --base "$BASE" --runtime "$RUNTIME" --model-dir "$MODEL" --output "$OUT" \
  --threads "$SLURM_CPUS_PER_TASK" \
  "${DATA_ROOT_ARGS[@]}"
