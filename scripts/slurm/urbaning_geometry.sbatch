#!/bin/bash -l
#SBATCH --job-name=urbaning-geometry
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=04:00:00
#SBATCH --output=urbaning-geometry-%j.out
#SBATCH --error=urbaning-geometry-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the geometry checkout root}"
test -f scripts/urbaning_geometry.py
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
CACHE="$BASE/runs/urbaning-joint-gain-001/runs"
UPSTREAM="$BASE/external/UrbanIng-V2X"
PY="$WORK/bin/urbaning-python.sh"
OUT="$BASE/runs/urbaning-geometry-001"
TRAIN1=20241126_0017_crossing1_00
TRAIN2=20241126_0001_crossing2_00
VAL=20241126_0004_crossing2_00
TEST=20241127_0009_crossing3_00

# Refuse accidental overwrites; retain failed attempts for inspection.
mkdir "$OUT"
git rev-parse HEAD > "$OUT/code-commit.txt"
printf '%s\n' "Slurm job ${SLURM_JOB_ID}; 4 CPUs; 12G; geometry protocol v1" > "$OUT/job.txt"

for SEQ in "$TRAIN1" "$TRAIN2" "$VAL"; do
    echo "EXPORT $SEQ"
    srun "$PY" scripts/urbaning_geometry.py --run "$CACHE/$SEQ" \
        --upstream "$UPSTREAM" --output "$OUT/$SEQ-poses.json"
done

echo "FIT geometry gain: training and validation only"
srun "$PY" scripts/urbaning_subsets.py fit \
    --train-runs "$CACHE/$TRAIN1" "$CACHE/$TRAIN2" \
    --validation-runs "$CACHE/$VAL" \
    --train-geometry "$OUT/$TRAIN1-poses.json" "$OUT/$TRAIN2-poses.json" \
    --validation-geometry "$OUT/$VAL-poses.json" \
    --request-cost 0.05 --alphas 0.1 1 10 --output "$OUT/geometry-gain.json"

echo "EXPORT test poses after policy freeze"
srun "$PY" scripts/urbaning_geometry.py --run "$CACHE/$TEST" \
    --upstream "$UPSTREAM" --output "$OUT/$TEST-poses.json"

echo "COMPARE frozen geometry gain on crossing3; default random seeds 0-99"
srun "$PY" scripts/urbaning_subsets.py compare --runs "$CACHE/$TEST" \
    --geometry "$OUT/$TEST-poses.json" --model "$OUT/geometry-gain.json" \
    --output "$OUT/geometry-report.json"
echo "DONE: $OUT/geometry-report.json"
