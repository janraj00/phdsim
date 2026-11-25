"""Local optimistic-path coverage and automatic viewpoint proposals."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from phdsim.agents.drone import DroneConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.decision.acquisition.path_aware import PathAwareView, rank_grid_views
from phdsim.experiments.scout.path_aware_demo import compare, main
from phdsim.experiments.scout.single_decision import DEFAULT_CONFIG


LINK = CommunicationConfig(delivery_delay=(0, 0))
DRONE = DroneConfig(speed=2, sensor_radius=1, measurement_ticks=1)


def small_view():
    p = [[1.0]*7 for _ in range(5)]
    observed = [[True]*7 for _ in range(5)]
    corridors = {(0, 2), (1, 2), (5, 2), (6, 2)}
    corridors.update((x, y) for x in range(1, 6) for y in (1, 3))
    for x, y in corridors:
        p[y][x] = 0.0
    for x, y in ((3, 1), (3, 3)):
        p[y][x], observed[y][x] = 0.5, False
    return PathAwareView(0, 5, (0, 2), (6, 2), (0, 0),
                         tuple(map(tuple, p)), tuple(map(tuple, observed)), 20)


def after_evidence(view, cell, blocked):
    p = [list(row) for row in view.probabilities]
    observed = [list(row) for row in view.observed]
    x, y = cell
    p[y][x], observed[y][x] = float(blocked), True
    return replace(view, probabilities=tuple(map(tuple, p)), observed=tuple(map(tuple, observed)))


class PathAwareTests(unittest.TestCase):
    def test_path_and_need_are_computed_from_local_map(self):
        view = small_view()
        ranked = rank_grid_views(view, DRONE, LINK)
        self.assertEqual(len(ranked.optimistic_path)-1, 8)
        self.assertEqual(ranked.information_needs, ((3, 1),))
        self.assertEqual(len(ranked.ranked_views), 35)
        self.assertEqual(len({q.measurement_pose for q in ranked.ranked_views}), 35)
        self.assertEqual(ranked.ranked_views[0].action_id, ranked.selected_action_id)
        self.assertEqual(view, small_view())

    def test_gain_counts_only_unknown_cells_on_the_optimistic_path(self):
        ranked = rank_grid_views(small_view(), DRONE, LINK)
        joint = next(q for q in ranked.ranked_views if q.measurement_pose == (3, 2))
        self.assertEqual(set(joint.covered_unknown_cells), {(3, 1), (3, 3)})
        self.assertEqual(joint.covered_path_unknown_cells, ((3, 1),))
        self.assertEqual(joint.path_gain, 1)
        lower = next(q for q in ranked.ranked_views if q.measurement_pose == (3, 4))
        self.assertEqual(lower.path_gain, 0)

    def test_received_blockage_changes_path_and_information_need(self):
        view = after_evidence(small_view(), (3, 1), True)
        ranked = rank_grid_views(view, DRONE, LINK)
        self.assertNotIn((3, 1), ranked.optimistic_path)
        self.assertEqual(ranked.information_needs, ((3, 3),))
        self.assertNotEqual(ranked.selected_action_id, "no_query")

    def test_known_optimistic_path_needs_no_new_observation(self):
        ranked = rank_grid_views(after_evidence(small_view(), (3, 1), False), DRONE, LINK)
        self.assertEqual(ranked.information_needs, ())
        self.assertEqual(ranked.selected_action_id, "no_query")
        self.assertTrue(all(q.path_gain == 0 for q in ranked.ranked_views))

    def test_no_optimistic_path_stops_querying(self):
        view = after_evidence(after_evidence(small_view(), (3, 1), True), (3, 3), True)
        ranked = rank_grid_views(view, DRONE, LINK)
        self.assertEqual(ranked.optimistic_path, ())
        self.assertEqual(ranked.selected_action_id, "no_query")

    def test_deadline_and_energy_can_force_no_query(self):
        for view in (replace(small_view(), decision_at=0),
                     replace(small_view(), acquisition_energy_limit=0)):
            with self.subTest(view=view):
                ranked = rank_grid_views(view, DRONE, LINK)
                self.assertEqual(ranked.selected_action_id, "no_query")
                self.assertTrue(any(q.path_gain for q in ranked.ranked_views))
                self.assertTrue(all(q.gain_per_tick == 0 for q in ranked.ranked_views))

    def test_exact_deadline_is_timely_and_score_uses_execution_ticks(self):
        ranked = rank_grid_views(replace(small_view(), decision_at=3), DRONE, LINK)
        quote = next(q for q in ranked.ranked_views if q.measurement_pose == (2, 1))
        self.assertEqual(quote.result_available_at, 3)
        self.assertEqual(quote.status, "within_deadline")
        self.assertAlmostEqual(quote.gain_per_tick, 1/3)

    def test_optimistic_coverage_is_not_an_entropy_or_expected_gain_policy(self):
        view = small_view()
        p = [list(row) for row in view.probabilities]
        p[1][3], p[3][3] = 0.1, 0.8
        changed = replace(view, probabilities=tuple(map(tuple, p)))
        self.assertEqual(rank_grid_views(view, DRONE, LINK), rank_grid_views(changed, DRONE, LINK))

    def test_perfect_known_mask_and_zero_delay_assumptions_are_enforced(self):
        p = [list(row) for row in small_view().probabilities]
        p[0][0] = 0.7
        with self.assertRaises(ValueError):
            replace(small_view(), probabilities=tuple(map(tuple, p)))
        with self.assertRaises(ValueError):
            rank_grid_views(small_view(), DRONE, CommunicationConfig())
        with self.assertRaises(ValueError):
            rank_grid_views(small_view(), replace(DRONE, speed=0), LINK)


class AutomaticViewExampleTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(DEFAULT_CONFIG.read_text())

    def test_all_225_poses_are_proposed_without_using_manual_fixture(self):
        original = deepcopy(self.config)
        result = compare(self.config)
        self.assertEqual(self.config, original)
        self.assertEqual(result["grid_poses_enumerated"], 225)
        self.assertEqual(result["information_needs"], ((9, 4),))
        self.assertEqual(len(result["optimistic_path"])-1, 18)
        self.assertEqual(result["comparison"][1]["measurement_pose"], (4, 4))
        manual = {tuple(a["measurement_pose"]) for a in self.config["observation_quotes"]}
        self.assertNotIn((4, 4), manual)
        self.config["observation_quotes"] = "intentionally invalid: must not be read"
        self.config["sensor_model_ref"] = "unused legacy label"
        self.config.pop("quality_source")
        self.assertEqual(compare(self.config), result)

    def test_comparison_uses_identical_physics_and_perfect_sensor(self):
        result = compare(self.config)
        baseline, path_aware, expected = result["comparison"]
        self.assertAlmostEqual(baseline["expected_route_cost"], 24.7)
        self.assertEqual(path_aware["measurement_pose"], expected["measurement_pose"])
        self.assertEqual(path_aware["result_available_at"], 2)
        self.assertAlmostEqual(path_aware["expected_route_cost"], 21.75)
        self.assertAlmostEqual(path_aware["expected_gain"], 2.95)
        self.assertEqual(path_aware["energy"], expected["energy"])
        self.assertFalse(result["reference"]["reproduces_original_method"])
        self.assertEqual(result["inputs"]["observation_model"], "perfect_reports_for_every_covered_unknown_cell")

    def test_tight_deadline_exposes_off_path_information_value(self):
        config_path = DEFAULT_CONFIG.with_name("path_aware_near_fork.json")
        result = compare(json.loads(config_path.read_text()))
        baseline, path_aware, expected = result["comparison"]
        self.assertEqual(result["inputs"]["view"]["decision_at"], 1)
        self.assertEqual(result["information_needs"], ((9, 4),))
        self.assertEqual(path_aware["action_id"], "no_query")
        self.assertAlmostEqual(path_aware["expected_route_cost"], baseline["expected_route_cost"])
        self.assertEqual(expected["measurement_pose"], (9, 11))
        self.assertEqual(expected["result_available_at"], 1)
        self.assertAlmostEqual(expected["expected_route_cost"], 22.45)
        self.assertAlmostEqual(expected["expected_gain"], 2.25)
        self.assertEqual(expected["path_gain"], 0)

    def test_cli_preserves_every_pose_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/"views"
            with redirect_stdout(io.StringIO()):
                main(["--output", str(output)])
            result = json.loads((output/"comparison.json").read_text())
            with (output/"views.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 225)
            self.assertEqual(len(result["ranked_views"]), 225)
            self.assertTrue((output/"report.md").is_file())
            self.assertIn("src/phdsim/decision/acquisition/path_aware.py", result["provenance"]["source_files"])
            with self.assertRaises(FileExistsError), redirect_stdout(io.StringIO()):
                main(["--output", str(output)])


if __name__ == "__main__":
    unittest.main()
