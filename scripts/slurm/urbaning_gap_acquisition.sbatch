#!/bin/bash -l
#SBATCH --job-name=urbaning-gap-acq
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=urbaning-gap-acq-%j.out
#SBATCH --error=urbaning-gap-acq-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the gap-acquisition checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
INPUTS="${1:?Pass the portable input ZIP path}"
INPUT_SHA="${2:?Pass its exact SHA256}"
OUT="${3:-$WORK/phdsim/runs/urbaning-gap-acquisition-$SLURM_JOB_ID}"
test -f "$INPUTS"
test -x "$WORK/bin/urbaning-python.sh"
mkdir -p "$(dirname "$OUT")"
# Protect a resumed directory from concurrent jobs; lock is outside its contents.
exec 9>"$OUT.lock"
flock -n 9 || { echo 'Another job holds this output directory' >&2; exit 1; }
echo "OUTPUT: $OUT"
echo 'No detector, refitting, crossing3 access, package installation or shared venv changes'
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_gap_acquisition_job.py run \
  --inputs "$INPUTS" --inputs-sha256 "$INPUT_SHA" --output-dir "$OUT" --resume
