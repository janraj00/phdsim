"""Contract and action validation shared by all acquisition policies."""

from abc import ABC, abstractmethod

from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.decision.view import DecisionView


class Policy(ABC):
    """Choose a legal pull or stop from the information available before transfer.

    ``view`` contains only the receiver's current evidence and metadata. The
    engine supplies candidates that are currently available and within budget.
    Implementations must return one of those exact actions or a ``Stop`` for
    the same receiver and target. Reference labels and unreceived pixels are
    not policy inputs. Fitting belongs to ``learning``, outside this contract.
    """

    name: str

    @abstractmethod
    def choose(self, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
        """Select one advertised transfer, or explain why acquisition stops."""
        ...

    @abstractmethod
    def configuration(self) -> dict[str, object]:
        """Return a serializable description of the frozen decision rule."""
        ...


def choose_action(policy: Policy, view: DecisionView, candidates: tuple[ActionEstimate, ...]) -> Acquire | Stop:
    choice = policy.choose(view, candidates)
    if not isinstance(choice, (Acquire, Stop)):
        raise ValueError('Policy must choose Acquire or Stop')
    if choice.receiver_id != view.receiver_id or choice.target != view.target:
        raise ValueError('Policy chose a different recipient or target')
    if isinstance(choice, Acquire) and (not any((c.action == choice for c in candidates))):
        raise ValueError('Policy chose outside the supplied candidates')
    return choice
