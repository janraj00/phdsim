"""Fit/replay joint UrbanIng subset policies from frozen stage 1 caches."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_subsets import main

if __name__ == '__main__':
    main()
