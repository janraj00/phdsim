"""Request a view based on route uncertainty, without mission-value prediction."""

from phdsim.core.grid import Cell
from .view import DecisionView
from phdsim.belief.occupancy import entropy
from .config import AcquisitionConfig

class UncertaintyScouting:
    """Request a view ahead of the planned route if its mean entropy is high.

    A simple baseline: does not predict mission value or account for delivery
    deadlines. Feasibility/energy are checked by the drone controller.
    """

    name = "uncertainty_scouting"

    def __init__(self, config: AcquisitionConfig):
        self.config = config

    def request(self, view: DecisionView, path: tuple[Cell, ...]) -> Cell | None:
        c = self.config
        if view.drone_busy or view.requests_sent >= c.max_requests or len(path) < 3:
            return None
        if view.last_request_at is not None and view.tick-view.last_request_at < c.cooldown_ticks:
            return None
        ahead = path[1:min(len(path), c.lookahead+1)]
        uncertainty = sum(entropy(view.probabilities[y][x]) for x, y in ahead)/len(ahead)
        return ahead[-1] if uncertainty >= c.entropy_threshold else None
