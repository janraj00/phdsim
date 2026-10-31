#!/bin/bash -l
# Run on Ares login from the benchmark checkout. No inference runs here.
set -euo pipefail
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
module load python/3.12.3-gcccore-13.3.0
python scripts/urbaning_benchmark.py plan \
    --metadata "$WORK/phdsim/data/urbaning-v2x/source/dataverse-dataset.json" \
    --output "$WORK/phdsim/runs/urbaning-benchmark-001/plan.json"
BENCH_COUNT=$(python -c 'import json; print(len(json.load(open("../phdsim/runs/urbaning-benchmark-001/plan.json"))["test_sequences"]))')
sbatch --test-only -A plgkgacq-cpu --array="0-$((BENCH_COUNT - 1))%1" \
    scripts/slurm/urbaning_benchmark.sbatch
BENCH_JOB=$(sbatch --parsable -A plgkgacq-cpu --array="0-$((BENCH_COUNT - 1))%1" \
    scripts/slurm/urbaning_benchmark.sbatch)
echo "BENCHMARK ARRAY: $BENCH_JOB"
sbatch -A plgkgacq-cpu --dependency="afterok:$BENCH_JOB" \
    --time=00:15:00 scripts/slurm/urbaning_benchmark.sbatch collect
