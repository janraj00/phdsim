"""Model-agnostic cross-modal Value-of-Information (VoI) rover dispatch.

Learns expected per-cell net classification gain E[Delta_acc | RGB_prediction]
on a separate calibration split using only the black-box outputs of a frozen
SemanticEstimator, then dispatches ground LiDAR rovers to maximize expected
net gain per tick of travel and capture.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import dist, isclose, isfinite

from phdsim.belief.semantic_terrain import Prediction
from phdsim.core.grid import Cell
from phdsim.decision.acquisition.semantic import footprint_indices
from phdsim.decision.acquisition.semantic_rover import ROVER_FOOTPRINT, RoverAssignment
from phdsim.planning.coverage_sweep import Capture, CaptureSite, Plot, SweepRobot, regular_sites


DEFAULT_PROB_BINS = 8
DEFAULT_PRIOR_STRENGTH = 5.0
DEFAULT_MIN_SITE_GAIN = 0.5


def _top2_key(probabilities: tuple[float, ...], bins: int) -> tuple[int, int, int, int]:
    """Map an arbitrary-length probability vector to (top1, top2, p1_bin, p2_bin)."""
    n = len(probabilities)
    if n == 0:
        raise ValueError("probabilities must be nonempty")
    if n == 1:
        return (0, 0, min(bins - 1, max(0, int(probabilities[0] * bins))), 0)
    ranked = sorted(range(n), key=lambda i: (probabilities[i], -i), reverse=True)
    c1, c2 = ranked[0], ranked[1]
    b1 = min(bins - 1, max(0, int(probabilities[c1] * bins)))
    b2 = min(bins - 1, max(0, int(probabilities[c2] * bins)))
    return (c1, c2, b1, b2)


@dataclass(frozen=True)
class CrossModalGainEstimator:
    """Hierarchical Empirical-Bayes lookup table predicting expected net accuracy gain.

    Fitted purely from calibration pairs (rgb_prediction, delta_acc) where
    delta_acc in {-1, 0, +1} is the realized change in correctness when LiDAR
    is fused with RGB by the frozen black-box SemanticEstimator.
    """

    bins: int
    prior_strength: float
    global_mean: float
    pair_means: dict[tuple[int, int], float]
    mid_means: dict[tuple[int, int, int], float]
    fine_means: dict[tuple[int, int, int, int], float]
    calibration_samples: int

    @classmethod
    def fit(
        cls,
        examples: Iterable[tuple[Prediction, int]],
        *,
        bins: int = DEFAULT_PROB_BINS,
        prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    ) -> CrossModalGainEstimator:
        if type(bins) is not int or bins < 2:
            raise ValueError("bins must be an integer >= 2")
        if not isfinite(prior_strength) or prior_strength < 0.0:
            raise ValueError("prior_strength must be finite and nonnegative")

        pair_sum: dict[tuple[int, int], float] = defaultdict(float)
        pair_cnt: dict[tuple[int, int], int] = defaultdict(int)
        mid_sum: dict[tuple[int, int, int], float] = defaultdict(float)
        mid_cnt: dict[tuple[int, int, int], int] = defaultdict(int)
        fine_sum: dict[tuple[int, int, int, int], float] = defaultdict(float)
        fine_cnt: dict[tuple[int, int, int, int], int] = defaultdict(int)

        total_sum = 0.0
        total_cnt = 0
        for pred, delta in examples:
            if delta not in (-1, 0, 1):
                raise ValueError("calibration delta must be -1, 0 or 1")
            c1, c2, b1, b2 = _top2_key(pred.probabilities, bins)
            pair_k = (c1, c2)
            mid_k = (c1, c2, b1)
            fine_k = (c1, c2, b1, b2)
            pair_sum[pair_k] += delta
            pair_cnt[pair_k] += 1
            mid_sum[mid_k] += delta
            mid_cnt[mid_k] += 1
            fine_sum[fine_k] += delta
            fine_cnt[fine_k] += 1
            total_sum += delta
            total_cnt += 1

        if total_cnt == 0:
            raise ValueError("calibration set produced zero RGB/LiDAR examples")

        # Conservative shrinkage: top-level prior shrinks toward 0.0 (no assumed gain).
        s = float(prior_strength)
        global_mean = total_sum / (total_cnt + s)
        pair_means = {
            k: (pair_sum[k] + s * global_mean) / (pair_cnt[k] + s)
            for k in pair_cnt
        }
        mid_means = {
            k: (mid_sum[k] + s * pair_means[(k[0], k[1])]) / (mid_cnt[k] + s)
            for k in mid_cnt
        }
        fine_means = {
            k: (fine_sum[k] + s * mid_means[(k[0], k[1], k[2])]) / (fine_cnt[k] + s)
            for k in fine_cnt
        }
        return cls(
            bins=bins,
            prior_strength=s,
            global_mean=global_mean,
            pair_means=pair_means,
            mid_means=mid_means,
            fine_means=fine_means,
            calibration_samples=total_cnt,
        )

    def expected_gain(self, rgb_prediction: Prediction | None) -> float:
        """Predict expected net accuracy improvement from fusing LiDAR on this cell."""
        if rgb_prediction is None:
            return 0.0
        c1, c2, b1, b2 = _top2_key(rgb_prediction.probabilities, self.bins)
        fine_k = (c1, c2, b1, b2)
        if fine_k in self.fine_means:
            return self.fine_means[fine_k]
        mid_k = (c1, c2, b1)
        if mid_k in self.mid_means:
            return self.mid_means[mid_k]
        pair_k = (c1, c2)
        if pair_k in self.pair_means:
            return self.pair_means[pair_k]
        return self.global_mean


class SelectiveRoverVoIPlanner:
    """Dispatch idle LiDAR rovers to sites maximizing expected net accuracy gain per tick."""

    def __init__(
        self,
        plot: Plot,
        rovers: tuple[SweepRobot, ...],
        deadline: int,
        gain_estimator: CrossModalGainEstimator,
        *,
        min_site_gain: float = DEFAULT_MIN_SITE_GAIN,
        rover_footprint: tuple[int, int] = ROVER_FOOTPRINT,
    ):
        if not isfinite(min_site_gain) or min_site_gain < 0.0:
            raise ValueError("min_site_gain must be finite and nonnegative")
        self.plot = plot
        self.rovers = {rover.agent_id: rover for rover in rovers}
        self.deadline = deadline
        self.gain_estimator = gain_estimator
        self.min_site_gain = min_site_gain
        self.positions = {rover.agent_id: rover.start_xy for rover in rovers}
        self.energy_reserved = dict.fromkeys(self.rovers, 0.0)
        self.remaining = {
            site: footprint_indices(site.footprint, plot.width)
            for site in regular_sites(plot, rover_footprint)
        }

    def dispatch(
        self,
        tick: int,
        rgb: tuple[Prediction | None, ...],
        lidar: tuple[Prediction | None, ...],
        pending: tuple[tuple[str, tuple[int, int, int, int]], ...],
    ) -> list[RoverAssignment]:
        cell_gains = [
            self.gain_estimator.expected_gain(photo) if photo is not None and ground is None else 0.0
            for photo, ground in zip(rgb, lidar, strict=True)
        ]
        busy = {agent for agent, _ in pending}
        for _, footprint in pending:
            for index in footprint_indices(footprint, self.plot.width):
                cell_gains[index] = 0.0

        free = [rover for rover in self.rovers.values() if rover.agent_id not in busy]
        assignments: list[RoverAssignment] = []
        while free and self.remaining:
            gains = {
                site: sum(cell_gains[i] for i in cells)
                for site, cells in self.remaining.items()
            }
            assignment = self._best_assignment(tick, free, gains)
            if assignment is None:
                break

            capture = assignment.capture
            rover_id = assignment.agent_id
            assignments.append(assignment)
            self.positions[rover_id] = capture.site.xy
            self.energy_reserved[rover_id] += capture.move_energy + capture.capture_energy
            for index in self.remaining.pop(capture.site):
                cell_gains[index] = 0.0
            free.remove(self.rovers[rover_id])
        return assignments

    def _best_assignment(
        self,
        tick: int,
        free: list[SweepRobot],
        gains: dict[CaptureSite, float],
    ) -> RoverAssignment | None:
        best: RoverAssignment | None = None
        best_score = (0.0, 0.0)
        for rover in free:
            origin = self.positions[rover.agent_id]
            for site, gain in gains.items():
                if gain <= 0.0 or gain < self.min_site_gain:
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
