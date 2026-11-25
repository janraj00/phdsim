"""Command line for the paired SCOUT elevation benchmark."""

from argparse import ArgumentParser
from pathlib import Path

from phdsim.experiments.scout.elevation import run_experiment
from phdsim.experiments.scout.elevation_stopping import run_stopping_experiment


def main(argv=None):
    parser = ArgumentParser(description="Compare fixed and adaptive SCOUT elevation mapping")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--calibration-seeds", type=int, nargs="+",
                        help="Compare stopping rules on matched traces using this separate calibration split")
    args = parser.parse_args(argv)
    try:
        if args.calibration_seeds is None:
            run_experiment(args.config, args.output, args.seeds)
        else:
            run_stopping_experiment(args.config, args.output, args.seeds, args.calibration_seeds)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
