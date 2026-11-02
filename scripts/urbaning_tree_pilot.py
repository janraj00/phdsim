"""Run the fixed validation-only tree policy pilot from this checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_tree_pilot import main

if __name__ == '__main__':
    main()
