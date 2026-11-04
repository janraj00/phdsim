#!/bin/bash -l
#SBATCH --job-name=urbaning-gap-hybrid
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=urbaning-gap-hybrid-%j.out
#SBATCH --error=urbaning-gap-hybrid-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the hybrid checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
INPUTS="$WORK/inputs/urbaning-gap-acquisition-inputs-001.zip"
REFERENCE="$WORK/phdsim/runs/urbaning-gap-acquisition-21586379/urbaning-gap-acquisition-validation.zip"
OUT="${1:-$WORK/phdsim/runs/urbaning-gap-hybrid-$SLURM_JOB_ID}"
test -f "$INPUTS"
test -f "$REFERENCE"
test -x "$WORK/bin/urbaning-python.sh"
mkdir -p "$(dirname "$OUT")"
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job holds this output directory' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo '200 crossing2 validation frames; split gap/benefit roles; no fitting, detector or crossing3 reads'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_gap_hybrid.py \
  --inputs "$INPUTS" \
  --inputs-sha256 c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee \
  --reference-validation-zip "$REFERENCE" \
  --reference-validation-sha256 78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786 \
  --output-dir "$OUT" --resume
