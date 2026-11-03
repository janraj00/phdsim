#!/bin/bash -l
#SBATCH --job-name=urbaning-frozen-full
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=urbaning-frozen-full-%j.out
#SBATCH --error=urbaning-frozen-full-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the frozen-full checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
INPUTS="${1:?Pass the frozen inputs ZIP path}"
INPUT_SHA="${2:?Pass its exact SHA256}"
OUT="$WORK/phdsim/runs/urbaning-frozen-full-$SLURM_JOB_ID"
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_frozen_full.py run \
  --inputs "$INPUTS" --inputs-sha256 "$INPUT_SHA" \
  --cache-root "$WORK/phdsim/runs/urbaning-full-policies-001" --output-dir "$OUT"
