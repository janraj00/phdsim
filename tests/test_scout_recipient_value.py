"""A single decision must value useful noisy evidence, not unseen terrain."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

from phdsim.decision.acquisition.recipient_value import (
    BinaryNeed, DecisionProblem, ExpectedObservation, ObservationAction,
    RouteOption, rank_actions,
)
from phdsim.experiments.scout.single_decision import (
    DEFAULT_CONFIG, build_problem, evaluate, main,
)


def binary_problem():
    return DecisionProblem(0, 3, (BinaryNeed("passage", (7, 4), 0.5),),
        (RouteOption("through", (10, 30)), RouteOption("detour", (18, 18))), 5)


def observe(action_id="observe", quality=(0.72,), flight=2, energy=1):
    return ObservationAction(action_id, (5, 4), flight, 1, energy, 8, quality)


class RecipientValueTests(unittest.TestCase):
    def test_noisy_measurement_averages_best_decision_after_each_report(self):
        ranked = rank_actions(binary_problem(), (observe(),))
        best = ranked[0]
        self.assertEqual(best.action_id, "observe")
        self.assertAlmostEqual(best.expected_route_cost, 16.8)
        self.assertAlmostEqual(best.expected_gain, 1.2)
        self.assertEqual([b.selected_route for b in best.branches], ["through", "detour"])
        self.assertAlmostEqual(best.branches[0].posterior_blocked[0], 0.28)
        self.assertAlmostEqual(sum(b.probability for b in best.branches), 1)

    def test_timely_lower_quality_beats_more_accurate_late_observation(self):
        ranked = rank_actions(binary_problem(), (observe(), observe("late", (0.9,), flight=3)))
        by_id = {e.action_id: e for e in ranked}
        self.assertEqual(ranked[0].action_id, "observe")
        self.assertEqual(by_id["observe"].result_available_at, 3)
        self.assertEqual(by_id["late"].status, "too_late")
        self.assertEqual(by_id["late"].expected_gain, 0)
        self.assertEqual(by_id["late"].expected_route_cost, by_id["no_query"].expected_route_cost)

    def test_energy_is_a_hard_limit_and_rejected_value_is_not_zero(self):
        ranked = rank_actions(binary_problem(), (observe(energy=6),))
        self.assertEqual(ranked[0].action_id, "no_query")
        self.assertEqual(ranked[1].status, "energy_limit")
        self.assertIsNone(ranked[1].expected_gain)

    def test_uninformative_and_irrelevant_measurements_do_not_trigger_query(self):
        for problem, action in (
            (binary_problem(), observe(quality=(0.5,), energy=0)),
            (replace(binary_problem(), questions=(BinaryNeed("passage", (7, 4), 0),)), observe()),
            (replace(binary_problem(), routes=(RouteOption("through", (30, 30)),
                                              RouteOption("detour", (18, 18)))), observe()),
        ):
            with self.subTest(problem=problem):
                ranked = rank_actions(problem, (action,))
                self.assertEqual(ranked[0].action_id, "no_query")
                self.assertEqual(ranked[1].expected_gain, 0)

    def test_own_future_observation_changes_both_baseline_and_incremental_value(self):
        problem = replace(binary_problem(), own_observations=(
            ExpectedObservation("rover", 2, (0.85,)),))
        ranked = rank_actions(problem, (observe(),))
        self.assertEqual(ranked[0].action_id, "no_query")
        self.assertAlmostEqual(ranked[0].expected_route_cost, 15.5)
        self.assertEqual(ranked[1].expected_gain, 0)
        self.assertEqual(len(ranked[1].branches), 4)

    def test_late_own_evidence_does_not_magically_improve_no_query(self):
        problem = replace(binary_problem(), own_observations=(
            ExpectedObservation("rover", 4, (1.0,)),))
        ranked = rank_actions(problem, ())
        self.assertAlmostEqual(ranked[0].expected_route_cost, 18)
        self.assertEqual(len(ranked[0].branches), 1)

    def test_recipient_context_changes_which_area_the_drone_should_observe(self):
        questions = (BinaryNeed("upper", (7, 4), 0.5), BinaryNeed("lower", (7, 10), 0.5))
        context = DecisionProblem(0, 3, questions,
            (RouteOption("uncertain", (10, 10, 30, 30)), RouteOption("safe", (18,)*4)), 5)
        actions = (observe("upper_view", (0.9, None)), observe("lower_view", (None, 0.9)))
        self.assertEqual(rank_actions(context, actions)[0].action_id, "upper_view")
        changed = replace(context, routes=(RouteOption("uncertain", (10, 30, 10, 30)),
                                           RouteOption("safe", (18,)*4)))
        self.assertEqual(rank_actions(changed, actions)[0].action_id, "lower_view")
        self.assertEqual(rank_actions(changed, actions), rank_actions(changed, tuple(reversed(actions))))

    def test_perfect_measurement_and_impossible_reports_are_handled(self):
        best = rank_actions(binary_problem(), (observe(quality=(1.0,)),))[0]
        self.assertAlmostEqual(best.expected_route_cost, 14)
        certain = replace(binary_problem(), questions=(BinaryNeed("passage", (7, 4), 1),))
        ranked = rank_actions(certain, (observe(quality=(1.0,)),))
        self.assertEqual(ranked[0].action_id, "no_query")
        self.assertEqual(len(ranked[1].branches), 1)
        self.assertAlmostEqual(ranked[1].branches[0].probability, 1)

    def test_missing_likelihoods_and_duplicate_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            observe(quality=(None,))
        with self.assertRaises(ValueError):
            observe(quality=(float("nan"),))
        with self.assertRaises(ValueError):
            rank_actions(binary_problem(), (observe(quality=(0.9, 0.9)),))
        with self.assertRaises(ValueError):
            replace(binary_problem(), own_observations=(ExpectedObservation("past", 0, (0.9,)),))
        with self.assertRaises(ValueError):
            rank_actions(binary_problem(), (observe(), observe()))
        problem = replace(binary_problem(), own_observations=(ExpectedObservation("observe", 1, (0.9,)),))
        with self.assertRaises(ValueError):
            rank_actions(problem, (observe(),))


class SingleDecisionExampleTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(DEFAULT_CONFIG.read_text())

    def test_public_geometry_produces_costs_and_deadline(self):
        problem, _, geometry = build_problem(self.config)
        self.assertEqual(problem.decision_at, 4)
        self.assertEqual(problem.routes[0].costs, (14, 14, 29, 61))
        self.assertEqual(problem.routes[1].costs, (16, 29, 16, 61))
        self.assertEqual(len(geometry["approach"])-1, 4)

    def test_example_ranks_all_three_quotes_and_retains_no_query(self):
        before = deepcopy(self.config)
        result = evaluate(self.config)
        self.assertEqual(self.config, before)
        rows = {e["action_id"]: e for e in result["estimates"]}
        self.assertEqual(result["selected_action_id"], "observe_upper")
        self.assertAlmostEqual(rows["no_query"]["expected_route_cost"], 24.7)
        self.assertAlmostEqual(rows["observe_upper"]["expected_route_cost"], 22.5)
        self.assertAlmostEqual(rows["observe_both"]["expected_route_cost"], 23.85)
        self.assertEqual(rows["observe_lower"]["status"], "too_late")
        self.assertEqual(len(rows["observe_both"]["branches"]), 4)
        first = rows["observe_both"]["branches"][0]
        self.assertAlmostEqual(first["probability"], 0.282)
        self.assertAlmostEqual(first["posterior_blocked"][0], 0.28)
        self.assertAlmostEqual(first["posterior_blocked"][1], 0.102/0.564)

    def test_quote_fixture_matches_approved_quality_at_its_specific_distances(self):
        # Checks the declared fixture; deliberately does not add a sensor model.
        expected_at_distance = {0: 0.9, 3: 0.72, 4: 0.66}
        for action in self.config["observation_quotes"]:
            for question in self.config["questions"]:
                distance = math.dist(action["measurement_pose"], question["cell"])
                quality = action["accuracies"][question["name"]]
                if distance > 5:
                    self.assertIsNone(quality)
                else:
                    self.assertEqual(quality, expected_at_distance[distance])

    def test_example_rejects_incomplete_coverage_and_unfunded_failure_horizon(self):
        changed = deepcopy(self.config)
        changed["observation_quotes"][2]["accuracies"]["lower_passage"] = None
        with self.assertRaises(ValueError):
            build_problem(changed)
        changed = deepcopy(self.config)
        changed["mission_time_budget"] = 10
        with self.assertRaises(ValueError):
            build_problem(changed)

    def test_cli_outputs_predictions_with_provenance_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/"decision"
            with redirect_stdout(io.StringIO()):
                main(["--output", str(output)])
            result = json.loads((output/"estimates.json").read_text())
            self.assertEqual(result["kind"], "analytical_model_prediction")
            self.assertTrue((output/"report.md").is_file())
            self.assertEqual(json.loads((output/"input.json").read_text()), self.config)
            self.assertIn("src/phdsim/decision/acquisition/recipient_value.py",
                          result["provenance"]["source_files"])
            inputs = json.dumps(result["inputs"])
            for forbidden in ('"truth"', '"world_seed"', '"realized_gain_ticks"', '"outcome"'):
                self.assertNotIn(forbidden, inputs)
            with self.assertRaises(FileExistsError), redirect_stdout(io.StringIO()):
                main(["--output", str(output)])


if __name__ == "__main__":
    unittest.main()
