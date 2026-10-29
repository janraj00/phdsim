"""Run from the separate OpenCOOD environment without installing phdsim there."""

import os
from pathlib import Path
import sys

# Upstream uses set() while deduplicating GT. Set hash seed before the interpreter
# starts so its order is repeatable; numpy/torch seeds are set in the runner.
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable] + sys.argv)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_stage1 import main

if __name__ == '__main__':
    main()
