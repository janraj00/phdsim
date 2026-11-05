"""Car1 CPU RGB late-fusion pilot entry point."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from phdsim.experiments.urbaning_rgb_pilot import main

if __name__ == '__main__':
    main()
