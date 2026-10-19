"""One entry point for the current real-data experiment."""

from argparse import ArgumentParser
from pathlib import Path
import json

from phdsim.datasets.pst900 import fetch_pilot, inspect_source, prepare_pst900
from phdsim.experiments.presence.replay import ProcessingConfig, run_replay
from phdsim.datasets import AgentSlot, ObservationPool, Schedule, allocate, prepare_pool

def main(argv=None):
    parser = ArgumentParser(prog='phdsim presence', description="Whole-frame survivor presence and selective peer pulls")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "fetch"):
        item = commands.add_parser(command)
        item.add_argument("--data", type=Path, required=True)
    item = commands.add_parser("prepare-pst900")
    item.add_argument("--data", type=Path, required=True)
    item.add_argument("--pool", type=Path, required=True)
    item = commands.add_parser("review-pst900")
    item.add_argument("--pool", type=Path, required=True)
    item.add_argument("--output", type=Path, required=True)
    item = commands.add_parser("train-cnn")
    item.add_argument("--pool", type=Path, required=True)
    item.add_argument("--config", type=Path, default=Path("configs/presence/perception_cnn.json"))
    item.add_argument("--output", type=Path, required=True)
    item = commands.add_parser("learn-acquisition")
    item.add_argument("--pool", type=Path, required=True)
    item.add_argument("--config", type=Path, default=Path("configs/presence/learning.json"))
    item.add_argument("--cnn-config", type=Path, default=Path("configs/presence/perception_cnn.json"))
    item.add_argument("--cnn-models", type=Path, required=True)
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--trace", action="store_true")
    item.add_argument("--reference-run", type=Path, help="Compare acquisition objectives while enforcing identical CNN and fusion models")
    item = commands.add_parser("prepare")
    item.add_argument("--input", type=Path, required=True)
    item.add_argument("--labels", type=Path)
    item.add_argument("--dataset-id", required=True)
    item.add_argument("--dataset-version", required=True)
    item.add_argument("--pool", type=Path, required=True)
    item = commands.add_parser("allocate")
    item.add_argument("--pool", type=Path, required=True)
    item.add_argument("--agents", type=Path, default=Path("configs/presence/agents.json"))
    item.add_argument("--schedule", type=Path, required=True)
    item = commands.add_parser("run")
    item.add_argument("--pool", type=Path, required=True)
    item.add_argument("--schedule", type=Path, required=True)
    item.add_argument("--processing", type=Path, default=Path("configs/presence/experiment.json"))
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--transfer-budget", type=int)
    item.add_argument("--byte-budget", type=int)
    item.add_argument("--models", type=Path, help="Load a frozen CNN bundle instead of fitting the legacy baseline")
    item.add_argument("--learning", type=Path, help="Frozen learning.json for this fusion and CNN")
    item.add_argument("--no-traces", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "inspect":
        print(json.dumps(inspect_source(args.data), indent=2))
    elif args.command == "fetch":
        fetch_pilot(args.data)
    elif args.command == "prepare-pst900":
        prepare_pst900(args.data, args.pool)
    elif args.command == "review-pst900":
        from phdsim.datasets.pst900.review import prepare_reviewed_pool
        prepare_reviewed_pool(args.pool, args.output)
    elif args.command == "train-cnn":
        from phdsim.perception import CnnConfig
        from phdsim.perception.cnn_training import train_cnn
        train_cnn(ObservationPool(args.pool), args.output, CnnConfig.load(args.config))
    elif args.command == "learn-acquisition":
        from phdsim.learning.config import LearningConfig
        from phdsim.experiments.presence.learning import run_learning_experiment
        from phdsim.perception import CnnConfig
        print(json.dumps(run_learning_experiment(ObservationPool(args.pool), args.output, args.cnn_models,
                         CnnConfig.load(args.cnn_config), LearningConfig.load(args.config), trace=args.trace,
                         reference_run=args.reference_run), indent=2))
    elif args.command == "prepare":
        pool = prepare_pool(args.input, args.pool, dataset_id=args.dataset_id,
                            dataset_version=args.dataset_version, labels=args.labels)
        print(f"Prepared {len(pool.records)} observations")
    elif args.command == "allocate":
        pool = ObservationPool(args.pool)
        settings = json.loads(args.agents.read_text(encoding="utf-8-sig"))
        agents = tuple(AgentSlot(**{**row, "stream_ids": tuple(row.get("stream_ids", ()))})
                       for row in settings["agents"])
        schedule = allocate(pool, agents, split=settings.get("split", "test"), mode=settings.get("mode", "partition"))
        schedule.save(args.schedule)
        counts = {agent.agent_id: sum(a.agent_id == agent.agent_id for a in schedule.assignments)
                  for agent in agents}
        print(json.dumps({"assigned": counts, "unassigned": len(schedule.unassigned_observation_ids)}, indent=2))
    elif args.command == "run":
        pool = ObservationPool(args.pool)
        trained = None
        if args.models:
            from phdsim.perception.cnn_training import load_cnn
            trained = load_cnn(pool, args.models)
        learned = None
        if args.learning:
            from phdsim.learning.bundle import LearningBundle
            learned = LearningBundle.load(args.learning)
        result = run_replay(pool, Schedule.load(args.schedule, pool), args.output,
                            processing=ProcessingConfig.load(args.processing),
                            transfer_budget=args.transfer_budget, byte_budget=args.byte_budget, trained=trained,
                            learned=learned, trace=not args.no_traces)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
