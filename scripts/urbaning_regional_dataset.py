"""Build regional Car1 inputs and offline labels from this checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_regional_dataset import main

if __name__ == '__main__':
    main()
