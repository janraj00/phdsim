"""One-view path-coverage baseline inspired by Traversing Mars, section V-A.

This uses the paper's unknown-optimistic-path coverage idea, not its full IPP
tree or stopping proofs. Candidate poses are exhaustively enumerated on a grid.
Gain is divided by execution ticks; deadline/energy filters are SCOUT additions.
Known cells have exact binary occupancy under this perfect-sensing baseline.
"""

from dataclasses import dataclass
import math

from phdsim.agents.drone import Drone, DroneConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.core.grid import Cell
from phdsim.planning.grid import PlanningConfig, plan_path
from phdsim.sensors.occupancy import footprint


@dataclass(frozen=True)
class PathAwareView:
    tick: int
    decision_at: int
    rover_position: Cell
    goal: Cell
    drone_position: Cell
    probabilities: tuple[tuple[float, ...], ...]
    observed: tuple[tuple[bool, ...], ...]
    acquisition_energy_limit: float

    def __post_init__(self):
        if type(self.tick) is not int or self.tick < 0 or type(self.decision_at) is not int or self.decision_at < self.tick:
            raise ValueError("invalid decision interval")
        if (type(self.probabilities) is not tuple or not self.probabilities
                or type(self.probabilities[0]) is not tuple or not self.probabilities[0]):
            raise ValueError("an immutable nonempty probability grid is required")
        size = len(self.probabilities[0]), len(self.probabilities)
        if type(self.observed) is not tuple or len(self.observed) != size[1]:
            raise ValueError("observed mask must match probability grid")
        for row, mask in zip(self.probabilities, self.observed):
            if type(row) is not tuple or type(mask) is not tuple or len(row) != size[0] or len(mask) != size[0]:
                raise ValueError("probability grid and observed mask must be rectangular")
            for p, known in zip(row, mask):
                if type(known) is not bool or isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
                    raise ValueError("invalid belief cell")
                if (known and p not in (0, 1)) or (not known and not 0 < p < 1):
                    raise ValueError("this baseline requires exact known cells and uncertain unobserved cells")
        for cell in (self.rover_position, self.goal, self.drone_position):
            if type(cell) is not tuple or len(cell) != 2 or any(type(v) is not int for v in cell) or not (0 <= cell[0] < size[0] and 0 <= cell[1] < size[1]):
                raise ValueError("agent/goal cell must be inside the grid")
        x, y = self.rover_position
        if not self.observed[y][x] or self.probabilities[y][x] != 0:
            raise ValueError("rover position must be known free")
        limit = self.acquisition_energy_limit
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit < 0:
            raise ValueError("energy limit must be finite and nonnegative")


@dataclass(frozen=True)
class GridViewQuote:
    action_id: str
    measurement_pose: Cell
    covered_unknown_cells: tuple[Cell, ...]
    covered_path_unknown_cells: tuple[Cell, ...]
    flight_ticks: int
    sensing_ticks: int
    result_available_at: int
    energy: float
    payload_bytes: int
    path_gain: int
    gain_per_tick: float
    status: str


@dataclass(frozen=True)
class PathAwareRanking:
    optimistic_path: tuple[Cell, ...]
    information_needs: tuple[Cell, ...]
    ranked_views: tuple[GridViewQuote, ...]
    selected_action_id: str


def rank_grid_views(view: PathAwareView, drone_config: DroneConfig,
                    communication: CommunicationConfig) -> PathAwareRanking:
    """Generate all poses using only local evidence and public helper parameters.

    Physical feasibility is independent of path gain. The returned table keeps
    late, unaffordable and off-path poses for inspection. No-query is selected
    unless an affordable timely pose has positive unknown-path coverage.
    """
    if communication.delivery_delay != (0, 0):
        raise ValueError("this one-decision baseline assumes zero transmission delay")
    if (isinstance(drone_config.speed, bool) or not isinstance(drone_config.speed, (int, float))
            or not math.isfinite(drone_config.speed) or drone_config.speed <= 0):
        raise ValueError("drone speed must be positive and finite")
    if type(drone_config.sensor_radius) is not int or drone_config.sensor_radius < 0:
        raise ValueError("sensor radius must be a nonnegative integer")
    if type(drone_config.measurement_ticks) is not int or drone_config.measurement_ticks < 1:
        raise ValueError("sensing must take a positive integer number of ticks")
    for value in (drone_config.move_energy, drone_config.measurement_energy, communication.energy_per_byte):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("energy coefficients must be finite and nonnegative")
    if type(communication.bytes_per_cell) is not int or communication.bytes_per_cell < 1:
        raise ValueError("bytes_per_cell must be a positive integer")
    size = len(view.probabilities[0]), len(view.probabilities)
    optimistic = tuple(tuple(p if known else 0 for p, known in zip(row, mask))
                       for row, mask in zip(view.probabilities, view.observed))
    path = plan_path(optimistic, view.rover_position, view.goal,
                     PlanningConfig(risk_weight=0, blocked_threshold=1))
    needs = tuple((x, y) for x, y in path if not view.observed[y][x])
    need_set = set(needs)
    helper = Drone(view.drone_position, drone_config)
    estimates = []
    for y in range(size[1]):
        for x in range(size[0]):
            pose = x, y
            quote = helper.quote(pose, view.tick, size, communication)
            cells = footprint(pose, drone_config.sensor_radius, size)
            unknown = tuple(c for c in cells if not view.observed[c[1]][c[0]])
            relevant = tuple(c for c in unknown if c in need_set)
            gain = len(relevant)
            elapsed = quote.capture_at-view.tick
            if quote.energy > view.acquisition_energy_limit:
                status = "energy_limit"
            elif quote.capture_at > view.decision_at:
                status = "too_late"
            elif not gain:
                status = "no_path_information"
            else:
                status = "within_deadline"
            score = gain/elapsed if status == "within_deadline" else 0
            estimates.append(GridViewQuote(
                f"observe_{x}_{y}", pose, unknown, relevant,
                elapsed-drone_config.measurement_ticks, drone_config.measurement_ticks,
                quote.capture_at, quote.energy, len(cells)*communication.bytes_per_cell,
                gain, score, status))
    ranked = tuple(sorted(estimates, key=lambda q: (
        -q.gain_per_tick, q.status != "within_deadline", q.energy,
        q.result_available_at, q.measurement_pose)))
    selected = ranked[0].action_id if ranked and ranked[0].gain_per_tick > 0 else "no_query"
    return PathAwareRanking(path, needs, ranked, selected)
