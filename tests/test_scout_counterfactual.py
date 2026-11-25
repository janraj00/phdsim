"""Offline labels must preserve pending work and never use truth as input."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
import unittest

from phdsim.cli.scout import main
from phdsim.decision.acquisition.candidates import CandidateConfig, generate_candidates
from phdsim.decision.acquisition.factory import make_policy
from phdsim.environments.corridors import generate_corridors
from phdsim.experiments.scout.counterfactual import evaluate_checkpoint
from phdsim.experiments.scout.mission import simulate
from phdsim.simulation.config import Config
from phdsim.simulation.mission import MissionSimulator


def engine(config=Config()):
    return MissionSimulator(config, generate_corridors(config.world.size, config.seed),
                            make_policy(config.policy, config.acquisition))


class CounterfactualTests(unittest.TestCase):
    def test_pause_is_idempotent_and_unintervened_resume_is_identical(self):
        sim = engine()
        point = sim.advance_to_decision(8)
        before = deepcopy(sim.events)
        self.assertEqual(sim.next_decision(), point)
        self.assertEqual(sim.events, before)
        self.assertEqual(sim.run(), simulate(Config()))

    def test_forks_preserve_undelivered_measurements_and_are_independent(self):
        config = replace(Config(), communication=replace(Config().communication, delivery_delay=(15, 15)))
        sim = engine(config)
        sim.next_decision()
        sim.act((16, 8))
        sim.advance_to_decision(8)
        self.assertTrue(sim.drone.busy)
        self.assertTrue(any(e["kind"] == "drone_capture" for e in sim.events))
        self.assertFalse(any(e["kind"] == "observation_delivered" for e in sim.events))
        branch = sim.fork()
        branch.run()
        self.assertFalse(any(e["kind"] == "observation_delivered" for e in sim.events))
        actual = sim.run()
        self.assertEqual(actual, branch.run())
        self.assertEqual(actual["summary"]["delivered"], 1)

    def test_candidates_use_belief_and_include_alternative_route(self):
        sim = engine()
        point = sim.next_decision()
        c = sim.config
        candidates = generate_candidates(point.view, point.path, c.planning, c.drone,
                                         c.communication, c.rover.sensor_radius, c.rover.speed,
                                         c.rover.move_energy, CandidateConfig(max_observations=30))
        self.assertIsNone(candidates[0].target)
        self.assertGreater(len(candidates), 2)
        self.assertTrue(any(a.origin_route.startswith("alternative") for a in candidates))
        self.assertEqual(len({a.target for a in candidates}), len(candidates))
        original = sim.belief.snapshot()
        self.assertEqual(original, point.view.probabilities)
        # Inverting truth cannot affect proposals made from the same local view.
        sim.world = replace(sim.world, blocked=tuple(tuple(not p for p in row) for row in sim.world.blocked))
        self.assertEqual(candidates, generate_candidates(point.view, point.path, c.planning, c.drone,
                         c.communication, c.rover.sensor_radius, c.rover.speed,
                         c.rover.move_energy, CandidateConfig(max_observations=30)))

    def test_labels_reproduce_direct_interventions_without_mutating_source(self):
        sim = engine()
        point = sim.advance_to_decision(8)
        events = deepcopy(sim.events)
        rows = evaluate_checkpoint(sim, CandidateConfig(max_observations=3), 101)
        self.assertEqual(sim.events, events)
        self.assertEqual(sim.next_decision(), point)
        baseline = rows[0]["target"]["mission_cost"]
        for row in rows:
            branch = sim.fork()
            branch.act(row["inputs"]["action"]["target"])
            direct = branch.run()["summary"]
            self.assertEqual(direct, row["target"]["outcome"])
            cost = direct["elapsed_ticks"] if direct["success"] else 101
            self.assertEqual(row["target"]["realized_gain_ticks"], baseline-cost)
            inputs = json.dumps(row["inputs"])
            for forbidden in ('"truth"', '"world_seed"', '"outcome"', '"world_sha256"', '"realized_gain_ticks"'):
                self.assertNotIn(forbidden, inputs)
        self.assertEqual(rows[0]["target"]["realized_gain_ticks"], 0)

    def test_busy_drone_only_allows_no_new_request_and_retains_pending_work(self):
        sim = engine()
        sim.next_decision()
        sim.act((16, 8))
        sim.next_decision()
        rows = evaluate_checkpoint(sim, CandidateConfig(), 101)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["inputs"]["action"]["target"])
        self.assertEqual(rows[0]["target"]["outcome"]["requests"], 1)

    def test_slow_rover_checkpoint_uses_actual_next_decision_tick(self):
        sim = engine(replace(Config(), rover=replace(Config().rover, speed=0.5)))
        point = sim.advance_to_decision(1)
        self.assertEqual(point.view.tick, 2)

    def test_failure_cost_does_not_reward_failing_early(self):
        c = replace(Config(), mission=replace(Config().mission, time_budget=1))
        sim = engine(c)
        sim.next_decision()
        rows = evaluate_checkpoint(sim, CandidateConfig(), 2)
        self.assertEqual(rows[0]["target"]["mission_cost"], 2)
        with self.assertRaises(ValueError):
            evaluate_checkpoint(sim, CandidateConfig(), 1)

    def test_cli_collects_separate_inputs_targets_and_group_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            config_path = path/"config.json"
            config_path.write_text(json.dumps(Config().to_dict()))
            with redirect_stdout(io.StringIO()):
                main(["--config", str(config_path), "--output", str(path/"labels"),
                      "--collect-labels", "--decision-ticks", "0", "8", "--max-candidates", "2"])
            summary = json.loads((path/"labels/summary.json").read_text())
            rows = [json.loads(line) for line in (path/"labels/labels.jsonl").read_text().splitlines()]
            self.assertEqual(summary["label_rows"], len(rows))
            self.assertEqual(len(summary["states"]), 2)
            self.assertTrue((path/"labels/report.md").is_file())
            self.assertTrue(all(set(row) == {"schema", "group", "inputs", "target"} for row in rows))


if __name__ == "__main__":
    unittest.main()
