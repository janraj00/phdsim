"""Finite observation proposals from local belief and alternative routes only."""

from dataclasses import dataclass
import math

from phdsim.agents.drone import Drone, DroneConfig
from phdsim.belief.occupancy import entropy
from phdsim.communication.delayed import CommunicationConfig
from phdsim.core.grid import Cell
from phdsim.planning.grid import PlanningConfig, plan_path
from phdsim.sensors.occupancy import footprint
from .view import DecisionView


@dataclass(frozen=True)
class CandidateConfig:
    max_observations: int = 6
    alternative_routes: int = 2
    lookaheads: tuple[int, ...] = (6, 12, 18)

    def __post_init__(self):
        if type(self.max_observations) is not int or self.max_observations < 0:
            raise ValueError("max_observations must be a nonnegative integer")
        if type(self.alternative_routes) is not int or self.alternative_routes < 0:
            raise ValueError("alternative_routes must be a nonnegative integer")
        if not self.lookaheads or any(type(v) is not int or v < 1 for v in self.lookaheads):
            raise ValueError("lookaheads must contain positive integer route offsets")


@dataclass(frozen=True)
class ObservationCandidate:
    candidate_id: str
    target: Cell | None
    origin_route: str
    features: dict


def generate_candidates(view: DecisionView, path: tuple[Cell, ...], planning: PlanningConfig,
                        drone: DroneConfig, communication: CommunicationConfig,
                        rover_radius: int, rover_speed: float, rover_step_energy: float,
                        config: CandidateConfig = CandidateConfig()) -> tuple[ObservationCandidate, ...]:
    """Heuristic coverage proposals, not a value-of-information policy.

    Temporarily block uncertain bottlenecks in a COPY of the local map to find
    alternative routes. Candidate ordering is only a bounded search heuristic.
    Helper quotation uses its last received position, never its hidden state.
    """
    none = ObservationCandidate("no_request", None, "baseline", {"is_request": False})
    if view.drone_busy or not path or config.max_observations == 0:
        return (none,)
    w, h = len(view.probabilities[0]), len(view.probabilities)
    size = w, h
    routes = [("current", path)]
    shadow = [list(row) for row in view.probabilities]
    for index in range(config.alternative_routes):
        previous = routes[-1][1]
        possible = [c for c in previous[1:-1] if shadow[c[1]][c[0]] < planning.blocked_threshold]
        if not possible:
            break
        center = max(possible, key=lambda c: entropy(view.probabilities[c[1]][c[0]]))
        for x, y in footprint(center, 2, size):
            if (x, y) not in (view.position, view.goal):
                shadow[y][x] = 1.0
        alternative = plan_path(shadow, view.position, view.goal, planning)
        if not alternative or any(alternative == p for _, p in routes):
            break
        routes.append((f"alternative_{index+1}", alternative))

    proposals = {}
    helper = Drone(view.drone_position, drone)
    step_ticks = max(1, math.ceil(1/rover_speed))
    for route_name, route in routes:
        centers = [route[min(offset, len(route)-1)] for offset in config.lookaheads]
        uncertain = sorted(route[1:-1], key=lambda c: -entropy(view.probabilities[c[1]][c[0]]))
        centers.extend(uncertain[:3])
        for target in centers:
            if target in proposals or target in (view.position, view.goal):
                continue
            quote = helper.quote(target, view.tick, size, communication)
            if helper.rejection_reason(quote, view.remaining_energy, rover_step_energy,
                                       view.tick+view.remaining_ticks, communication.delivery_delay[0]):
                continue
            cells = footprint(target, drone.sensor_radius, size)
            cell_set = set(cells)
            covered = [i for i, c in enumerate(path) if c in cell_set]
            visible = [i for i, c in enumerate(path)
                       if math.dist(c, target) <= rover_radius]
            features = {
                "is_request": True,
                "target_entropy": entropy(view.probabilities[target[1]][target[0]]),
                "mean_footprint_entropy": sum(entropy(view.probabilities[y][x]) for x, y in cells)/len(cells),
                "current_route_covered_cells": len(covered),
                "rover_eta_to_first_covered_cell": min(covered)*step_ticks if covered else None,
                "rover_eta_to_local_visibility": min(visible)*step_ticks if visible else None,
                "earliest_delivery_ticks": quote.capture_at-view.tick+communication.delivery_delay[0],
                "latest_delivery_ticks": quote.capture_at-view.tick+communication.delivery_delay[1],
                "energy_reserved": quote.energy,
                "payload_bytes": len(cells)*communication.bytes_per_cell,
                "sensor_accuracy": drone.sensor_accuracy,
            }
            score = features["mean_footprint_entropy"] + features["target_entropy"]
            candidate = ObservationCandidate(f"observe_{target[0]}_{target[1]}", target, route_name, features)
            proposals[target] = score, candidate
    ordered = sorted(proposals.values(), key=lambda item: (-item[0], item[1].target))
    return (none,) + tuple(c for _, c in ordered[:config.max_observations])
