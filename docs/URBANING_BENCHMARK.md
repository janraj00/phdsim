# Full CoBEVT reference before extending acquisition policies

This is a **prepared, not yet executed** full-test reference. It does not replace
or overwrite the completed 200-frame policy pilot. No detector or policy is
trained by this runner.

## Contract

- Pinned upstream commit and hash-verified official CoBEVT SIS 1/2 vs 3 bundle.
- All crossing3 sequences from the local Dataverse release 1.0 inventory; all
  synchronization anchors, no frame cap. The plan records the inventory hash.
- Unmodified released model/configuration except the local validation data path.
  Keep the upstream default ego vehicle selection; do not force another ego.
- Upstream intermediate inference and postprocessing, all in-range collaborators.
- The existing evaluation adapter calls upstream BEV polygon matching and its
  0–100 m corner-radius filter. Report four-class AP/mAP at IoU .3/.5/.7.
- Aggregate TP/FP/confidence/GT statistics over every sequence **before** computing
  AP. Never average sequence APs to obtain the benchmark AP.
- Report both upstream default ordering (`False`) and global confidence sorting
  (`True`) from the same detections. Sequence order is lexical, matching upstream.
  The official CLI defaults to False; our earlier pilot uses True. This is a
  known implementation distinction, not a proven explanation for all differences.
- Compare per-class AP with `eval_3d_det.yaml` in the official bundle. A completed
  run is not automatically a successful reproduction; review class-wise deltas.
- CPU software versions and code hashes are recorded. Upstream's original CUDA
  environment, worker seeding and point shuffling may cause numerical differences.
- The independent acquisition study retains fixed all-source labels across
  actions. Benchmark NO Fusion in the paper is a separately trained baseline,
  not necessarily CoBEVT with partner inputs removed.

## Ares execution

Use a separate checkout. Keep the existing native dataset and verified container
wrapper. The plan command is a short standard-library operation and can run on
login after loading Python. Conversion and inference run only on workers.

```bash
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
cd "$WORK/phdsim-benchmark"
module load python/3.12.3-gcccore-13.3.0
python scripts/urbaning_benchmark.py plan \
  --metadata "$WORK/phdsim/data/urbaning-v2x/source/dataverse-dataset.json" \
  --output "$WORK/phdsim/runs/urbaning-benchmark-001/plan.json"
```

Alternatively, `bash scripts/slurm/submit_urbaning_benchmark.sh` creates the plan, validates the Slurm request and submits both jobs. It must run from the benchmark checkout root. The explicit equivalent after the plan command is:

```bash
BENCH_COUNT=$(python -c 'import json; print(len(json.load(open("../phdsim/runs/urbaning-benchmark-001/plan.json"))["test_sequences"]))')
BENCH_JOB=$(sbatch --parsable -A plgkgacq-cpu \
  --array="0-$((BENCH_COUNT - 1))%1" scripts/slurm/urbaning_benchmark.sbatch)
echo "$BENCH_JOB"
sbatch -A plgkgacq-cpu --dependency="afterok:$BENCH_JOB" \
  --time=00:15:00 scripts/slurm/urbaning_benchmark.sbatch collect
```

The array deliberately runs one sequence at a time: shared native supporting
files are downloaded by the existing importer, which is not a concurrent-writer
API. Each task requests 4 CPUs, 12 GB, at most 24 hours; this is a limit, not a
runtime estimate. A successful sequence is reused with identity/statistics hash
checks. Interrupted inference repeats that sequence from frame 1. Partial
conversion/view directories are preserved and rejected if unmarked; inspect and
rename the affected partial directory before retrying. No automatic deletions.
If any task fails, the afterok collector will not run; resubmit failed indices,
then submit collect after all tasks succeed.

Results: `../phdsim/runs/urbaning-benchmark-001/benchmark-report.json` and
per-sequence `result.json`, `statistics.json`, converted data and source views.
The collector refuses missing or capped sequences and mixed implementations.

Download to the agreed Mac results directory:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-benchmark-001
scp 'plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-benchmark-001/benchmark-report.json' \
  ~/Documents/phdsim-results/urbaning-benchmark-001/
```

## Next boundary

Once reference deltas are understood, expand counterfactual caches and evaluate
frozen policies on a common full test set. The already inspected crossing3 pilot
is not a fresh unseen test after method changes. Other fusion methods require
UrbanIng-trained weights: the audited official v1.0.0 release contains only
CoBEVT weights. Configurations are available for all eight benchmark rows;
configurations alone are not trained models.

Sources: [release](https://github.com/thi-ad/UrbanIng-V2X/releases/tag/v1.0.0),
[official split script](https://github.com/thi-ad/UrbanIng-V2X/blob/main/scripts/create_opencood_splits.py),
[inference](https://github.com/thi-ad/UrbanIng-V2X/blob/main/opencood/opencood/tools/inference.py).
