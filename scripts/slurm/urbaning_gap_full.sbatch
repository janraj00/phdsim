#!/bin/bash -l
#SBATCH --job-name=urbaning-gap-full
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=04:00:00
#SBATCH --output=urbaning-gap-full-%j.out
#SBATCH --error=urbaning-gap-full-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the gap-full checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
VALIDATION="$BASE/runs/urbaning-gap-acquisition-21586379/urbaning-gap-acquisition-validation.zip"
REFERENCE="$BASE/runs/urbaning-frozen-full-21578375/urbaning-frozen-full.zip"
OUT="${1:-$BASE/runs/urbaning-gap-full-$SLURM_JOB_ID}"
test -f "$VALIDATION"
test -f "$REFERENCE"
test -x "$WORK/bin/urbaning-python.sh"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job holds this output directory' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo 'Same 1400 crossing3 frames; frozen validation settings; no detector, fitting or installs'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_gap_full.py \
  --validation-zip "$VALIDATION" \
  --validation-sha 78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786 \
  --reference-zip "$REFERENCE" \
  --reference-sha e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802 \
  --cache-root "$BASE/runs/urbaning-full-policies-001" \
  --output-dir "$OUT" --resume
