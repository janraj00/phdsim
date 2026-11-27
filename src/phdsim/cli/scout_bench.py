"""Run modular, config-driven SCOUT semantic benchmarks from the CLI."""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import replace
import json
from pathlib import Path

from phdsim.experiments.scout.bench_config import SeedsSpec, list_terrain_profiles, load_bench_config
from phdsim.experiments.scout.bench_runner import format_comparison_table, plugin_catalog, run_benchmark


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to a SCOUT benchmark JSON config")
    parser.add_argument("--output", type=Path, help="Fresh output directory under runs/")
    parser.add_argument("--test-seeds", nargs="+", type=int, help="Override config test seeds for a quick run")
    parser.add_argument("--replay-seeds", nargs="+", type=int, help="Override which test seeds export scout-replay-v1")
    parser.add_argument("--list-plugins", action="store_true", help="List registered classifiers, policies and terrain profiles")
    args = parser.parse_args(argv)

    if args.list_plugins:
        catalog = {**plugin_catalog(), "terrain_profiles": list_terrain_profiles()}
        print(json.dumps(catalog, indent=2, ensure_ascii=False))
        return

    if not args.config or not args.output:
        parser.error("--config and --output are required unless --list-plugins is passed")

    try:
        config = load_bench_config(args.config)
        if args.test_seeds is not None:
            new_test = tuple(args.test_seeds)
            new_seeds = SeedsSpec(fit=config.seeds.fit, cal=config.seeds.cal, test=new_test)
            save_seeds = tuple(args.replay_seeds) if args.replay_seeds is not None else (new_test[0],)
            config = replace(config, seeds=new_seeds, save_replays_for_seeds=save_seeds)
        elif args.replay_seeds is not None:
            if any(s not in config.seeds.test for s in args.replay_seeds):
                raise ValueError("--replay-seeds must be a subset of test seeds")
            config = replace(config, save_replays_for_seeds=tuple(dict.fromkeys(args.replay_seeds)))

        comparison = run_benchmark(config, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    print(format_comparison_table(comparison))
    print(f"\nSaved to: {args.output.resolve()}")
    if comparison["replays"]:
        print(f"SCOUT Studio replays: {len(comparison['replays'])} file(s)")


if __name__ == "__main__":
    main()
