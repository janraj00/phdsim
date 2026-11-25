"""Fixed coverage on small public geometry fixtures (no generated terrain)."""

from dataclasses import replace
from math import sqrt
import unittest

from phdsim.planning.coverage_sweep import (
    CaptureSite, Plot, SweepRobot, plan_coverage_sweep, regular_sites,
)


def robot(name, start, budget=11):
    return SweepRobot(name, start, speed_m_per_tick=1, capture_ticks=1,
                      move_energy_per_m=1, capture_energy=2, energy_budget=budget)


class CoverageSweepTests(unittest.TestCase):
    def setUp(self):
        self.plot = Plot(6, 4, 1)
        self.sites = regular_sites(self.plot, (2, 2))
        self.robots = (robot("A", (-1, 0)), robot("B", (5, 2)))

    def test_six_capture_walkthrough(self):
        plan = plan_coverage_sweep(self.plot, self.sites, self.robots)
        self.assertEqual((plan.orientation, plan.split, plan.first_block_agent),
                         ("horizontal", 1, "A"))
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (24, 8))
        expected_poses = [[(0, 0), (2, 0), (4, 0)], [(4, 2), (2, 2), (0, 2)]]
        for route, poses in zip(plan.routes, expected_poses):
            self.assertEqual([c.site.xy for c in route.captures], poses)
            self.assertEqual([(c.start_tick, c.arrival_tick, c.finish_tick) for c in route.captures],
                             [(0, 1, 2), (2, 4, 5), (5, 7, 8)])
            self.assertEqual([c.move_energy for c in route.captures], [1, 2, 2])
            self.assertEqual((route.travel_m, route.energy), (5, 11))

    def test_rotation_and_swapped_assignment(self):
        plot = Plot(4, 6, 1)
        robots = (robot("B", (2, 5)), robot("A", (0, -1)))
        plan = plan_coverage_sweep(plot, regular_sites(plot, (2, 2)), robots)
        self.assertEqual((plan.orientation, plan.split, plan.first_block_agent),
                         ("vertical", 1, "A"))
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (24, 8))
        self.assertEqual([r.agent_id for r in plan.routes], ["B", "A"])

    def test_budget_limited_prefixes(self):
        robots = [replace(r, energy_budget=7) for r in self.robots]
        plan = plan_coverage_sweep(self.plot, self.sites, robots)
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (16, 5))
        self.assertEqual([r.energy for r in plan.routes], [7, 7])

    def test_idle_robot_and_serpentine_transition(self):
        robots = [robot("B", (0, 0), 0), robot("A", (4, 2), 100)]
        plan = plan_coverage_sweep(self.plot, self.sites, robots)
        idle, active = plan.routes
        self.assertEqual((idle.captures, idle.finish_tick, idle.energy), ((), 0, 0))
        self.assertEqual([c.site.xy for c in active.captures],
                         [(4, 2), (2, 2), (0, 2), (0, 0), (2, 0), (4, 0)])
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (24, 16))

    def test_unbalanced_split_for_heterogeneous_robots(self):
        plot = Plot(1, 5, 1)
        robots = (robot("A", (0, 0), 100), replace(robot("B", (0, 4)), capture_ticks=7))
        plan = plan_coverage_sweep(plot, regular_sites(plot, (1, 1)), robots)
        self.assertEqual([len(r.captures) for r in plan.routes], [4, 1])
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (5, 7))

    def test_earliest_prefix_with_overlapping_explicit_support(self):
        plot = Plot(3, 1, 1)
        sites = (CaptureSite((0, 0), (0, 0, 2, 1)), CaptureSite((1, 0), (1, 0, 2, 1)),
                 CaptureSite((2, 0), (1, 0, 2, 1)))
        robots = (robot("A", (0, 0), 20), robot("B", (2, 0), 0))
        plan = plan_coverage_sweep(plot, reversed(sites), robots)
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (3, 3))
        self.assertEqual([c.site for c in plan.routes[0].captures], list(sites[:2]))
        self.assertEqual(plan, plan_coverage_sweep(plot, sites, robots))

    def test_shifted_edge_footprints_and_metric_diagonal(self):
        plot = Plot(5, 1, 2)
        sites = regular_sites(plot, (3, 7))
        self.assertEqual(sites, (CaptureSite((1, 0), (0, 0, 3, 1)),
                                 CaptureSite((3, 0), (2, 0, 3, 1))))
        robots = (replace(robot("A", (0, -1), 100), speed_m_per_tick=2),
                  robot("B", (1, 0), 0))
        plan = plan_coverage_sweep(plot, sites, robots)
        self.assertEqual((plan.covered_cells, plan.makespan_ticks), (5, 6))
        self.assertEqual(plan.routes[0].captures[0].arrival_tick, 2)
        self.assertAlmostEqual(plan.routes[0].energy, 2 * sqrt(2) + 8)

    def test_empty_and_unaffordable(self):
        for sites in ((), self.sites):
            robots = [replace(r, energy_budget=0) for r in self.robots]
            plan = plan_coverage_sweep(self.plot, sites, robots)
            self.assertEqual((plan.covered_cells, plan.makespan_ticks), (0, 0))
            self.assertTrue(all(not r.captures for r in plan.routes))

    def test_fractional_budget_at_exact_cost(self):
        plot = Plot(3, 1, 1)
        robots = (replace(robot("A", (0, 0), 0.3), capture_energy=0.1, move_energy_per_m=0),
                  robot("B", (2, 0), 0))
        plan = plan_coverage_sweep(plot, regular_sites(plot, (1, 1)), robots)
        self.assertEqual(plan.covered_cells, 3)
        self.assertAlmostEqual(plan.routes[0].energy, 0.3)

    def test_reject_invalid_sites_or_profiles(self):
        for sites in ((self.sites[0],) * 2, (CaptureSite((0, 0), (0, 0, 7, 1)),)):
            with self.assertRaises(ValueError):
                plan_coverage_sweep(self.plot, sites, self.robots)
        for fields in ({"capture_ticks": -1}, {"energy_budget": float("nan")},
                       {"speed_m_per_tick": 0}):
            with self.assertRaises(ValueError):
                replace(self.robots[0], **fields)
        with self.assertRaises(ValueError):
            plan_coverage_sweep(self.plot, (), self.robots[:1])
