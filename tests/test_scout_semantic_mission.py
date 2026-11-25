"""Check the integrated path from planned capture through map replay."""

from math import dist
import unittest

from phdsim.belief.semantic_terrain import Prediction
from phdsim.decision.acquisition.semantic import AerialSettings, cell_uncertainty
from phdsim.environments.semantic_terrain import TerrainConfig
from phdsim.experiments.scout.semantic_mission import fit_classifier, initial_drones, semantic_replay
from phdsim.planning.coverage_sweep import Plot
from phdsim.planning.x500_trajectory import MODEL_ID, x500_flight
from phdsim.sensors.semantic_terrain import nadir_footprint_side


class SemanticMissionTests(unittest.TestCase):
    def test_utility_uses_normalized_entropy_of_all_class_probabilities(self):
        def uncertainty(probabilities):
            return cell_uncertainty(Prediction("soil", probabilities, ("rgb-1",)))

        self.assertEqual(cell_uncertainty(None), 1.0)
        self.assertEqual(uncertainty((1.0,)), 0.0)
        self.assertEqual(uncertainty((1.0, 0.0, 0.0)), 0.0)
        self.assertAlmostEqual(uncertainty((1 / 3, 1 / 3, 1 / 3)), 1.0)
        self.assertGreater(uncertainty((0.6, 0.2, 0.2)), uncertainty((0.6, 0.4, 0.0)))

    def test_fusion_applies_only_completed_measurements(self):
        config = TerrainConfig()
        model = fit_classifier(config, (11, 12, 13))
        replay, summary = semantic_replay(2021, model, config)
        before, last = replay["frames"][0], replay["frames"][-1]
        count = config.width * config.height
        self.assertEqual(before["completed"], [])
        self.assertEqual(before["layers"]["fused"], [None] * count)
        self.assertEqual(summary["nominal_drone_coverage_cells"], count)
        self.assertEqual(last["tick"], summary["elapsed_ticks"])
        self.assertFalse(last["scheduled"])
        self.assertEqual([frame["tick"] for frame in replay["frames"]], list(range(last["tick"] + 1)))
        self.assertEqual(sum(len(frame["completed"]) for frame in replay["frames"]), summary["measurement_tasks"])
        for frame in replay["frames"]:
            self.assertTrue(all(task["finish_tick"] == frame["tick"] for task in frame["completed"]))
            self.assertTrue(all(task["start_tick"] <= frame["tick"] < task["finish_tick"]
                                for task in frame["scheduled"]))
        self.assertGreater(summary["metrics"]["whole_map"]["fused"]["resolved"], 0)
        self.assertEqual({a["flight_model"] for a in replay["agents"] if "flight_model" in a}, {MODEL_ID})
        for agent in (a for a in replay["agents"] if "flight_model" in a):
            xy = agent["start_xy"]
            for frame in replay["frames"]:
                for task in frame["completed"]:
                    if task["agent_id"] == agent["id"]:
                        profile = x500_flight(dist(xy, task["xy"]) * config.cell_size_m)
                        self.assertEqual(task["arrival_tick"] - task["start_tick"], profile.travel_ticks)
                        self.assertAlmostEqual(task["flight_seconds"], profile.duration_s, places=5)
                        self.assertEqual(task["finish_tick"] - task["arrival_tick"], 2)
                        xy = task["xy"]

    def test_adaptive_drones_complete_views_at_both_altitudes_and_pay_for_height_changes(self):
        config = TerrainConfig()
        settings = AerialSettings()
        model = fit_classifier(config, (11, 12, 13))
        replay, summary = semantic_replay(2021, model, config, aerial=settings)

        side = {height: nadir_footprint_side(height, settings.fov_deg, config.cell_size_m)
                for height in settings.altitudes_m}
        self.assertEqual(side, {2.0: 5, 6.0: 13})
        self.assertEqual(summary["aerial_views_per_drone"], 2 * config.width * config.height)
        self.assertEqual(set(summary["aerial_measurements_by_altitude_m"]), {2.0, 6.0})
        self.assertFalse(replay["frames"][-1]["scheduled"])
        for drone in initial_drones(Plot(config.width, config.height, config.cell_size_m)):
            xy = tuple(coordinate + 0.5 for coordinate in drone.start_xy)
            altitude, previous_finish, energy = settings.initial_altitude_m, 0, 0.0
            for frame in replay["frames"]:
                for task in frame["completed"]:
                    if task["agent_id"] != drone.agent_id:
                        continue
                    metres = dist(xy, task["xy"]) * config.cell_size_m
                    climb = task["standoff_m"] - altitude
                    profile = x500_flight(metres, climb)
                    duration = profile.travel_ticks + drone.capture_ticks
                    self.assertGreaterEqual(task["start_tick"], previous_finish)
                    self.assertEqual(task["arrival_tick"], task["start_tick"] + profile.travel_ticks)
                    self.assertAlmostEqual(task["flight_seconds"], profile.duration_s, places=5)
                    self.assertEqual(task["finish_tick"], task["start_tick"] + duration)
                    self.assertLessEqual(task["finish_tick"], settings.time_budget)
                    limit = side[task["standoff_m"]]
                    x, y, w, h = task["footprint"]
                    self.assertLessEqual(w, min(limit, config.width - x))
                    self.assertLessEqual(h, min(limit, config.height - y))
                    for tick in range(task["start_tick"], task["finish_tick"]):
                        pose = next(a for a in replay["frames"][tick]["agents"] if a["id"] == drone.agent_id)
                        progress = profile.progress_at(tick - task["start_tick"])
                        self.assertAlmostEqual(pose["altitude_m"], altitude + climb * progress)
                        for actual, start, end in zip(pose["xy"], xy, task["xy"], strict=True):
                            self.assertAlmostEqual(actual, start + (end - start) * progress)
                    energy += (metres + abs(climb)) * drone.move_energy_per_m + drone.capture_energy
                    xy, altitude, previous_finish = task["xy"], task["standoff_m"], task["finish_tick"]
            self.assertAlmostEqual(energy, summary["energy_reserved"][drone.agent_id])

        # The first moving sample has no new evidence, even though the aircraft moved.
        start, moving = replay["frames"][:2]
        self.assertNotEqual(start["agents"][0]["xy"], moving["agents"][0]["xy"])
        self.assertNotEqual(start["agents"][0]["altitude_m"], moving["agents"][0]["altitude_m"])
        self.assertEqual(start["layers"], moving["layers"])
        self.assertEqual(moving["completed"], [])

    def test_selective_rovers_keep_the_drone_sweep_and_wait_for_rgb_evidence(self):
        config = TerrainConfig()
        model = fit_classifier(config, (11, 12, 13))
        fixed, _ = semantic_replay(2021, model, config)
        selective, summary = semantic_replay(2021, model, config, selective_rovers=True)
        frames = selective["frames"]

        def drone_schedule(replay):
            return [{key: task[key] for key in ("agent_id", "xy", "footprint", "start_tick", "finish_tick")}
                    for frame in replay["frames"] for task in frame["completed"]
                    if task["agent_id"].startswith("drone-")]

        self.assertEqual(drone_schedule(selective), drone_schedule(fixed))
        self.assertEqual(len(selective["agents"]), 4)
        for frame in fixed["frames"]:
            self.assertEqual(frames[frame["tick"]]["layers"]["rgb"], frame["layers"]["rgb"])

        captures = [task for frame in frames for task in frame["completed"]]
        self.assertTrue(all(task["mode"] == "rgb" for task in captures if task["agent_id"].startswith("drone-")))
        ground = [task for task in captures if task["agent_id"].startswith("rover-")]
        self.assertEqual({task["agent_id"] for task in ground}, {"rover-1", "rover-2"})
        first_photo = min(task["finish_tick"] for task in captures if task["mode"] == "rgb")
        first_lidar = min(task["finish_tick"] for task in ground)
        self.assertTrue(all(task["start_tick"] >= first_photo and task["finish_tick"] <= summary["rover_deadline_tick"]
                            for task in ground))
        self.assertEqual(len({tuple(task["xy"]) for task in ground}), len(ground))
        self.assertTrue(all(frame["layers"]["lidar"] == [None] * (config.width * config.height)
                            for frame in frames[:first_lidar]))
        for task in ground:
            agent = task["agent_id"]
            arrival = next(pose for pose in frames[task["arrival_tick"]]["agents"] if pose["id"] == agent)
            self.assertEqual(arrival["xy"], task["xy"])

    def test_x500_curve_respects_speed_acceleration_and_jerk_limits(self):
        self.assertEqual(x500_flight(0.0).travel_ticks, 0)
        self.assertLess(x500_flight(0, 10).duration_s, x500_flight(0, -10).duration_s)
        for horizontal, climb in ((0.5, 0), (4.25, 3), (80, 0), (15, 10), (15, -10), (0, 12), (0, -12)):
            with self.subTest(horizontal=horizontal, climb=climb):
                profile = x500_flight(horizontal, climb)
                interval = profile.duration_s / 400
                samples = [profile.progress_at(i * interval) for i in range(401)]
                self.assertEqual(samples[0], 0.0)
                self.assertEqual(samples[-1], 1.0)
                self.assertAlmostEqual(samples[200], 0.5)

                def derivative(values):
                    return [(b - a) / interval for a, b in zip(values, values[1:])]

                speed = derivative(samples)
                acceleration = derivative(speed)
                jerk = derivative(acceleration)
                self.assertGreaterEqual(min(speed), 0)
                self.assertLess(max(speed[0], speed[-1]) * profile.distance_m, 0.01)
                for rates, xy_limit, z_limit in ((speed, 5.0, 3.0 if climb > 0 else 1.5),
                                                 (acceleration, 3.0, 3.0), (jerk, 4.0, 4.0)):
                    peak = max(map(abs, rates))
                    self.assertLessEqual(peak * horizontal, xy_limit + 1e-6)
                    self.assertLessEqual(peak * abs(climb), z_limit + 1e-6)
