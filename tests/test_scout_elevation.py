"""Protect paired starts, the information boundary and concurrent budgets."""

from dataclasses import replace
import unittest

from phdsim.decision.acquisition.elevation import ElevationPlanner
from phdsim.environments.elevation import generate_world
from phdsim.experiments.scout.elevation_stopping import calibrate_threshold, stopping_outcomes
from phdsim.simulation.elevation import (
    MappingConfig, fixed_schedule, initial_belief, initial_fleet, simulate,
)


class ElevationExperimentTests(unittest.TestCase):
    def setup_trial(self, poor_probability):
        config = MappingConfig(poor_probability=poor_probability)
        world = generate_world(42, poor_probability)
        planner = ElevationPlanner(config.time_budget, config.tolerance_m, config.confidence)
        schedule = fixed_schedule(config, planner, initial_belief(world.coarse_m))
        return world, config, planner, schedule, 42

    def test_without_surprises_the_two_schedulers_execute_the_same_mission(self):
        trial = self.setup_trial(0)
        fixed = simulate(*trial, adaptive=False)
        adaptive = simulate(*trial, adaptive=True)
        self.assertEqual(fixed["events"], adaptive["events"])
        self.assertEqual(fixed["trace"], adaptive["trace"])

    def test_shared_start_and_budgets_with_unknown_imaging_quality(self):
        trial = self.setup_trial(0.3)
        budgets = initial_fleet(trial[1])
        starts = []
        for adaptive in (False, True):
            result = simulate(*trial, adaptive=adaptive)
            dispatches = [e for e in result["events"] if e["event"] == "dispatch"]
            starts.append([e for e in dispatches if e["tick"] == 0])
            for name, robot in budgets.items():
                jobs = [e for e in dispatches if e["robot"] == name]
                self.assertTrue(jobs)
                self.assertLessEqual(sum(e["energy"] for e in jobs), robot.energy)
                self.assertTrue(all(e["finish"] <= trial[1].time_budget for e in jobs))
                self.assertTrue(all(a["finish"] <= b["tick"] for a, b in zip(jobs, jobs[1:])))
        self.assertEqual(starts[0], starts[1])
        self.assertEqual(len(starts[0]), 3)

    def test_realized_evaluation_error_cannot_stop_the_mission(self):
        world, *rest = self.setup_trial(0.3)
        changed_truth = replace(world, truth_m={cell: tuple(z + 10 for z in heights)
                                                for cell, heights in world.truth_m.items()})
        original = simulate(world, *rest, adaptive=True)
        changed = simulate(changed_truth, *rest, adaptive=True)
        self.assertEqual(original["events"], changed["events"])
        self.assertEqual(original["summary"]["declared_tick"], changed["summary"]["declared_tick"])
        self.assertNotEqual(original["trace"][0]["rmse_m"], changed["trace"][0]["rmse_m"])

    def test_stopping_replay_preserves_the_original_policy_prefix(self):
        trial = self.setup_trial(0)
        original = simulate(*trial, adaptive=True)
        replay = simulate(*trial, adaptive=True, stop_on_quality=False)
        original_tick = original["summary"]["declared_tick"]
        self.assertIsNotNone(original_tick)
        self.assertEqual([e for e in replay["events"] if e["tick"] < original_tick],
                         [e for e in original["events"] if e["tick"] < original_tick])
        outcomes = stopping_outcomes(replay["trace"], trial[1].coverage, 0.86)
        self.assertEqual(outcomes["pointwise"]["tick"], original_tick)
        self.assertEqual(outcomes["pointwise"]["verified"], original["summary"]["verified_at_declaration"])

    def test_calibration_controls_the_largest_premature_score_per_mission(self):
        trace = [
            {"tick": 1, "expected_coverage": 0.86, "estimated_qualified_fraction": 0.70, "actual_fraction": 0.82},
            {"tick": 2, "expected_coverage": 0.89, "estimated_qualified_fraction": 0.73, "actual_fraction": 0.84},
            {"tick": 3, "expected_coverage": 0.90, "estimated_qualified_fraction": 0.80, "actual_fraction": 0.87},
            {"tick": 4, "expected_coverage": 0.92, "estimated_qualified_fraction": 0.85, "actual_fraction": 0.88},
        ]
        threshold = calibrate_threshold([trace] * 19, 0.85, 0.05)
        self.assertEqual(threshold, 0.89)
        self.assertEqual(calibrate_threshold([trace], 0.85, 0.05), 1.0)
        outcomes = stopping_outcomes(trace, 0.85, threshold)
        self.assertEqual(outcomes["expected_coverage"], {"tick": 1, "verified": False, "actual_fraction": 0.82})
        self.assertEqual(outcomes["calibrated_coverage"], {"tick": 3, "verified": True, "actual_fraction": 0.87})
        self.assertEqual(outcomes["pointwise"]["tick"], 4)
