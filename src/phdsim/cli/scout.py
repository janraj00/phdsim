"""Command-line arguments for the synthetic SCOUT experiment."""

import argparse
from dataclasses import replace
from phdsim.experiments.scout.config import load_config
from phdsim.experiments.scout.runner import run_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description="SCOUT synthetic rover/drone pilot")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True, help="New output directory; existing directories are never overwritten")
    parser.add_argument("--compare", action="store_true", help="Compare no_scouting and uncertainty_scouting")
    parser.add_argument("--policy", choices=("no_scouting", "uncertainty_scouting"))
    parser.add_argument("--seeds", type=int, nargs="+", help="Explicit paired diagnostic seeds; default: config seed")
    parser.add_argument("--collect-labels", action="store_true", help="Offline paired counterfactual labels, not an online policy")
    parser.add_argument("--decision-ticks", type=int, nargs="+", help="Checkpoint ticks for offline labeling; default: 0 8 16")
    parser.add_argument("--max-candidates", type=int, help="Maximum observation candidates per checkpoint; default: 6, plus no-request")
    parser.add_argument("--failure-penalty", type=float, help="Labeling cost of failure; default: mission time budget + 1")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    if args.compare and args.policy:
        parser.error("Choose --compare or --policy")
    if args.collect_labels and args.compare:
        parser.error("Choose --collect-labels or --compare")
    if not args.collect_labels and any(v is not None for v in (args.decision_ticks, args.max_candidates, args.failure_penalty)):
        parser.error("Labeling options require --collect-labels")
    seeds = args.seeds if args.seeds is not None else [config.seed]
    if len(set(seeds)) != len(seeds):
        parser.error("Duplicate seeds would double-count missions")
    policies = ("no_scouting", "uncertainty_scouting") if args.compare else (args.policy or config.policy,)
    try:
        if args.collect_labels:
            from phdsim.decision.acquisition.candidates import CandidateConfig
            from phdsim.experiments.scout.counterfactual import collect_labels
            config = replace(config, policy=args.policy or config.policy)
            return collect_labels(config, args.config, args.output, seeds,
                                  args.decision_ticks if args.decision_ticks is not None else [0, 8, 16],
                                  CandidateConfig(max_observations=args.max_candidates if args.max_candidates is not None else 6),
                                  args.failure_penalty)
        return run_experiment(config, args.config, args.output, seeds, policies)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
