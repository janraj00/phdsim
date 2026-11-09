#!/bin/bash -l
#SBATCH --job-name=urbaning-thermal-gate
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-thermal-gate-%j.out
#SBATCH --error=urbaning-thermal-gate-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the thermal-gate checkout}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
MODEL="$BASE/runs/urbaning-rgb3d-late-21655505/models/outdoor"
OUT="${1:-$BASE/runs/urbaning-thermal-rpn-gate-$SLURM_JOB_ID}"
DATA_ROOT_ARGS=()
if [[ -n "${URBANING_DATA_ROOT:-}" ]]; then
  DATA_ROOT_ARGS=(--data-root "$URBANING_DATA_ROOT")
fi
echo "OUTPUT: $OUT"
echo 'Read-only thermal data and frozen-RPN recall gate; no fitting or validation access.'
echo 'Samples two TRAIN frames per recording across associated infrastructure thermal cameras.'
echo 'Stops unless frozen RPN recall reaches the predeclared IoU .3/.5 gates.'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_thermal_rpn_gate.py \
  --base "$BASE" --model-dir "$MODEL" --output "$OUT" --threads "$SLURM_CPUS_PER_TASK" \
  "${DATA_ROOT_ARGS[@]}"
