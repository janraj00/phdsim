#!/bin/bash -l
#SBATCH --job-name=urbaning-diagnostics
#SBATCH --partition=plgrid
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --output=urbaning-diagnostics-%j.out
#SBATCH --error=urbaning-diagnostics-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from diagnostics checkout root}"
WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work
ROOT="$WORK/phdsim/runs/urbaning-full-policies-001"
PY="$WORK/bin/urbaning-python.sh"
srun "$PY" scripts/urbaning_diagnostics.py --root "$ROOT" --output "$ROOT/diagnostics-report.json"
# Deliver one archive, the attachment format verified to work in this conversation.
srun "$PY" - <<'PY'
from pathlib import Path
import zipfile
root = Path('/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-full-policies-001')
with zipfile.ZipFile(root / 'urbaning-analysis.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name in ('full-policy-report.json', 'diagnostics-report.json'):
        archive.write(root / name, name)
print('DONE:', root / 'urbaning-analysis.zip')
PY
