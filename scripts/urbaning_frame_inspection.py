"""Inspect cached Car1/partner detection outcomes without detector inference."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_frame_inspection import main

if __name__ == '__main__':
    main()
