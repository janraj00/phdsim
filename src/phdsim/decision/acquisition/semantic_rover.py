"""Select ground observations after RGB data arrive in a semantic mission."""

from dataclasses import dataclass
from math import dist, isclose

from phdsim.belief.semantic_terrain import Prediction
from phdsim.core.grid import Cell
from phdsim.decision.acquisition.semantic import cell_uncertainty, footprint_indices
from phdsim.planning.coverage_sweep import Capture, CaptureSite, Plot, SweepRobot, regular_sites


ROVER_FOOTPRINT = (5, 5)
MIN_RGB_ENTROPY = 0.6


@dataclass(frozen=True)
class RoverAssignment:
    agent_id: str
    origin_xy: Cell
    capture: Capture


class SelectiveRoverPlanner:
    def __init__(self, plot: Plot, rovers: tuple[SweepRobot, ...], deadline: int):
        self.plot = plot
        self.rovers = {rover.agent_id: rover for rover in rovers}
        self.deadline = deadline
        self.positions = {rover.agent_id: rover.start_xy for rover in rovers}
        self.energy_reserved = dict.fromkeys(self.rovers, 0.0)
        self.remaining = {site: footprint_indices(site.footprint, plot.width)
                          for site in regular_sites(plot, ROVER_FOOTPRINT)}

    def dispatch(self, tick: int, rgb: tuple[Prediction | None, ...], lidar: tuple[Prediction | None, ...],
                 pending: tuple[tuple[str, tuple[int, int, int, int]], ...]) -> list[RoverAssignment]:
        weights = [cell_uncertainty(photo) if photo is not None and ground is None else 0.0
                   for photo, ground in zip(rgb, lidar, strict=True)]
        busy = {agent for agent, _ in pending}
        for _, footprint in pending:
            for index in footprint_indices(footprint, self.plot.width):
                weights[index] = 0.0

        free = [rover for rover in self.rovers.values() if rover.agent_id not in busy]
        assignments = []
        while free and self.remaining:
            gains = {site: sum(weights[i] for i in cells if weights[i] >= MIN_RGB_ENTROPY)
                     for site, cells in self.remaining.items()}
            assignment = self._best_assignment(tick, free, gains)
            if assignment is None:
                break

            capture = assignment.capture
            rover_id = assignment.agent_id
            assignments.append(assignment)
            self.positions[rover_id] = capture.site.xy
            self.energy_reserved[rover_id] += capture.move_energy + capture.capture_energy
            for index in self.remaining.pop(capture.site):
                weights[index] = 0.0
            free.remove(self.rovers[rover_id])

        return assignments

    def _best_assignment(self, tick: int, free: list[SweepRobot],
                         gains: dict[CaptureSite, float]) -> RoverAssignment | None:
        best, best_score = None, (0.0, 0.0)
        for rover in free:
            origin = self.positions[rover.agent_id]
            for site, gain in gains.items():
                if gain <= 0.0:
                    continue
                metres = dist(origin, site.xy) * self.plot.cell_size_m
                move_energy = metres * rover.move_energy_per_m
                charge = move_energy + rover.capture_energy
                arrival = tick + rover.travel_ticks(metres)
                finish = arrival + rover.capture_ticks
                committed = self.energy_reserved[rover.agent_id] + charge
                if finish > self.deadline:
                    continue
                if committed > rover.energy_budget and not isclose(committed, rover.energy_budget, rel_tol=1e-12):
                    continue
                score = (gain / (finish - tick), -charge)
                if score > best_score:
                    best_score = score
                    capture = Capture(site, tick, arrival, finish, metres, move_energy, rover.capture_energy)
                    best = RoverAssignment(rover.agent_id, origin, capture)
        return best
