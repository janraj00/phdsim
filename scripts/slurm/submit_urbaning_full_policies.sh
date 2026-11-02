#!/bin/bash -l
set -euo pipefail
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
BASE="$WORK/phdsim"
OUT="$BASE/runs/urbaning-full-policies-001"
module load python/3.12.3-gcccore-13.3.0
python scripts/urbaning_full_policies.py plan \
    --reference "$BASE/runs/urbaning-benchmark-001/benchmark-report.json" \
    --ego-model "$BASE/runs/urbaning-joint-gain-001/joint-gain.json" \
    --geometry-model "$BASE/runs/urbaning-geometry-001/geometry-gain.json" \
    --model-dir "$BASE/models/urbaning/CoBEVT_SIS_1_2_vs_3" --output "$OUT/plan.json"
POLICY_COUNT=$(python -c 'import json; print(len(json.load(open("../phdsim/runs/urbaning-full-policies-001/plan.json"))["test_sequences"]))')
# Read-only shared inputs; each task writes only to its own output directory.
sbatch --test-only -A plgkgacq-cpu --array="0-$((POLICY_COUNT - 1))%2" scripts/slurm/urbaning_full_policies.sbatch
POLICY_JOB=$(sbatch --parsable -A plgkgacq-cpu --array="0-$((POLICY_COUNT - 1))%2" scripts/slurm/urbaning_full_policies.sbatch)
echo "POLICY ARRAY: $POLICY_JOB"
sbatch -A plgkgacq-cpu --dependency="afterok:$POLICY_JOB" --mem=24G \
    --time=04:00:00 scripts/slurm/urbaning_full_policies.sbatch collect
