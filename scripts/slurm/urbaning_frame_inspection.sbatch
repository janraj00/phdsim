#!/bin/bash -l
#SBATCH --job-name=urbaning-inspect
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-inspect-%j.out
#SBATCH --error=urbaning-inspect-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the separate inspection checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
SEQUENCE=20241126_0004_crossing2_00
OUT="${URBANING_INSPECTION_OUTPUT:-$BASE/runs/urbaning-frame-inspection-001}"
# All perception outputs and pose sidecars already exist. No installs or downloads.
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_frame_inspection.py \
    --run "$BASE/runs/urbaning-joint-gain-001/runs/$SEQUENCE" \
    --geometry "$BASE/runs/urbaning-geometry-001/$SEQUENCE-poses.json" \
    --output-dir "$OUT"
