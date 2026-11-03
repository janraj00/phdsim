#!/bin/bash -l
#SBATCH --job-name=urbaning-ap-export
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=urbaning-ap-export-%j.out
#SBATCH --error=urbaning-ap-export-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the AP replay checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
CACHE="$WORK/phdsim/runs/urbaning-joint-gain-001/runs"
OUT="${URBANING_AP_OUTPUT:-$WORK/phdsim/runs/urbaning-ap-export-$SLURM_JOB_ID}"
srun "$WORK/bin/urbaning-python.sh" -u scripts/urbaning_ap_replay.py export \
  --train-runs "$CACHE/20241126_0017_crossing1_00" "$CACHE/20241126_0001_crossing2_00" \
  --validation-runs "$CACHE/20241126_0004_crossing2_00" \
  --output-dir "$OUT"
