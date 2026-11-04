#!/bin/bash -l
#SBATCH --job-name=urbaning-zero-cost
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=urbaning-zero-cost-%j.out
#SBATCH --error=urbaning-zero-cost-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the zero-cost checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
SPATIAL="$BASE/runs/urbaning-gap-full-21586593/urbaning-gap-full.zip"
REFERENCE="$BASE/runs/urbaning-frozen-full-21578375/urbaning-frozen-full.zip"
OUT="${1:-$BASE/runs/urbaning-zero-cost-$SLURM_JOB_ID}"
test -f "$SPATIAL"
test -f "$REFERENCE"
test -x "$WORK/bin/urbaning-python.sh"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job holds this output directory' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo 'Post-hoc cost0 control on same1400 frames; cached scores/outcomes only, no fitting or detector'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_zero_cost.py \
  --spatial-zip "$SPATIAL" \
  --spatial-sha 82227530fb755da55bc516cc495ebeb70aaa9323a3e6adf892b13af3ee814869 \
  --reference-zip "$REFERENCE" \
  --reference-sha e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802 \
  --output-dir "$OUT" --resume
