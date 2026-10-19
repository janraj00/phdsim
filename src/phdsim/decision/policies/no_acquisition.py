"""Keep the result obtained from the agent's own observation."""

from __future__ import annotations
from dataclasses import dataclass
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView
from ..policy import Policy


@dataclass(frozen=True)
class NoAcquisition(Policy):
    """Keep the result obtained from the agent's own observation.

    Always returns ``Stop``, even if a neighbor image is available. This is the
    zero-communication reference for measuring the effect of acquisition.
    """

    name: str = 'no_acquisition'

    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Stop:
        return Stop(view.receiver_id, view.target, 'baseline')

    def configuration(self) -> dict[str, object]:
        return {'name': self.name}
