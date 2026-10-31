#!/bin/bash -l
#SBATCH --job-name=urbaning-reference
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=24:00:00
#SBATCH --output=urbaning-reference-%A_%a.out
#SBATCH --error=urbaning-reference-%A_%a.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the benchmark checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="$BASE/runs/urbaning-benchmark-001"
PY="$WORK/bin/urbaning-python.sh"
if [[ "${1:-}" == collect ]]; then
    srun "$PY" scripts/urbaning_benchmark.py collect \
        --plan "$OUT/plan.json" --upstream "$BASE/external/UrbanIng-V2X" \
        --model-dir "$BASE/models/urbaning/CoBEVT_SIS_1_2_vs_3" --output "$OUT"
else
    srun "$PY" scripts/urbaning_benchmark.py run \
        --plan "$OUT/plan.json" --upstream "$BASE/external/UrbanIng-V2X" \
        --model-dir "$BASE/models/urbaning/CoBEVT_SIS_1_2_vs_3" --output "$OUT" \
        --data-root "$BASE/data/urbaning-v2x" --index "${SLURM_ARRAY_TASK_ID:?Use an array}" \
        --cpu-threads "$SLURM_CPUS_PER_TASK"
fi
