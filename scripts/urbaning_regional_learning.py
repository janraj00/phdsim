#!/usr/bin/env python3
"""Run the regional feature-ablation experiment from this checkout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_regional_learning import main

if __name__ == '__main__':
    main()
