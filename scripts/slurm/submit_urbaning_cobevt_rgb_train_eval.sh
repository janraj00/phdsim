#!/bin/bash
set -euo pipefail
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
SOURCE="${1:-$WORK/phdsim/runs/urbaning-cobevt-rgb-controlled-001}"
OUT="${2:-$WORK/phdsim/runs/urbaning-cobevt-rgb-train-eval-001}"
SOURCE_REPORT_JOB="${3:-21599633}"
JOB=scripts/slurm/urbaning_cobevt_rgb_train_eval.sbatch
test -f "$JOB"
test -x "$WORK/bin/urbaning-python.sh"
test -f "$SOURCE/protocol.json"
DEPENDENCY=()
if [ -f "$SOURCE/completed.json" ] && [ -f "$SOURCE/report.json" ]; then
  echo 'SOURCE: completed report found; workers will verify archive/model/cache hashes'
else
  STATE=$(squeue -h -j "$SOURCE_REPORT_JOB" -o '%T' 2>/dev/null || true)
  case "$STATE" in
    PENDING|RUNNING|CONFIGURING|COMPLETING|SUSPENDED)
      DEPENDENCY=(--dependency="afterok:$SOURCE_REPORT_JOB")
      echo "SOURCE: waiting for original collector $SOURCE_REPORT_JOB"
      ;;
    *)
      echo 'Source report is not completed and its collector is not active. Inspect the original run first.' >&2
      exit 1
      ;;
  esac
fi
mkdir -p "$OUT/logs"
RESPONSE=$(sbatch -A plgkgacq-cpu --parsable --array=0-2%2 --time=08:00:00 \
  "${DEPENDENCY[@]}" --output="$OUT/logs/train-eval-%A_%a.out" --error="$OUT/logs/train-eval-%A_%a.err" \
  "$JOB" seed "$SOURCE" "$OUT")
ARRAY="${RESPONSE%%;*}"
echo "TRAIN EVAL ARRAY: $ARRAY"
RESPONSE=$(sbatch -A plgkgacq-cpu --parsable --time=04:00:00 --dependency="afterok:$ARRAY" \
  --output="$OUT/logs/report-%A_%a.out" --error="$OUT/logs/report-%A_%a.err" \
  "$JOB" collect "$SOURCE" "$OUT")
echo "REPORT: ${RESPONSE%%;*}"
echo "OUTPUT: $OUT"
echo "LOGS: $OUT/logs"
echo 'Read-only source models/caches; original TRAIN baseline evaluated once; at most2 seed workers.'
echo 'Scheduler time limits are ceilings, not completion estimates.'
