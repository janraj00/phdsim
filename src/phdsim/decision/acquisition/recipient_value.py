"""Exact pre-measurement value for one decision and up to two binary needs.

Inputs are recipient beliefs/cost estimates and public observation quotes.
There is no environment, sampled truth, simulator fork or trained model here.
Question states and observation errors are conditionally independent under
the declared model. The shared rover approach is fixed until decision_at.
"""

from dataclasses import dataclass
from itertools import product
import math

from phdsim.core.grid import Cell


def _number(value, name, low=0, high=math.inf):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")


def _tick(value, name, low=0):
    if type(value) is not int or value < low:
        raise ValueError(f"{name} must be an integer >= {low}")


def _cell(value):
    if (type(value) is not tuple or len(value) != 2
            or any(type(v) is not int or v < 0 for v in value)):
        raise ValueError("cell must be a tuple of two nonnegative integers")


def _accuracies(values):
    if type(values) is not tuple or not 1 <= len(values) <= 2:
        raise ValueError("accuracies must be a tuple for one or two questions")
    if all(q is None for q in values):
        raise ValueError("an observation must cover at least one question")
    for q in values:
        if q is not None:
            _number(q, "accuracy", 0.5, 1)


@dataclass(frozen=True)
class BinaryNeed:
    name: str
    cell: Cell
    p_blocked: float

    def __post_init__(self):
        if not self.name:
            raise ValueError("question name is required")
        _cell(self.cell)
        _number(self.p_blocked, "p_blocked", 0, 1)


@dataclass(frozen=True)
class RouteOption:
    name: str
    # product((False, True), repeat=n): free/free, free/blocked, ...
    costs: tuple[float, ...]

    def __post_init__(self):
        if not self.name or type(self.costs) is not tuple:
            raise ValueError("route name and immutable costs are required")
        for cost in self.costs:
            _number(cost, "route cost")


@dataclass(frozen=True)
class ExpectedObservation:
    """A shared forecast of future own evidence, never its future value."""

    source: str
    available_at: int
    accuracies: tuple[float | None, ...]

    def __post_init__(self):
        if not self.source:
            raise ValueError("observation source is required")
        _tick(self.available_at, "available_at")
        _accuracies(self.accuracies)


@dataclass(frozen=True)
class DecisionProblem:
    tick: int
    decision_at: int
    questions: tuple[BinaryNeed, ...]
    routes: tuple[RouteOption, ...]
    acquisition_energy_limit: float
    own_observations: tuple[ExpectedObservation, ...] = ()

    def __post_init__(self):
        _tick(self.tick, "tick")
        _tick(self.decision_at, "decision_at", self.tick)
        _number(self.acquisition_energy_limit, "acquisition_energy_limit")
        if type(self.questions) is not tuple or not 1 <= len(self.questions) <= 2:
            raise ValueError("this small model supports one or two questions")
        if len({q.name for q in self.questions}) != len(self.questions):
            raise ValueError("question names must be unique")
        if len({q.cell for q in self.questions}) != len(self.questions):
            raise ValueError("question cells must be unique")
        if type(self.routes) is not tuple or len(self.routes) != 2:
            raise ValueError("exactly two route choices are required")
        if len({r.name for r in self.routes}) != len(self.routes):
            raise ValueError("route names must be unique")
        if any(len(r.costs) != 2 ** len(self.questions) for r in self.routes):
            raise ValueError("each route needs a cost for every question state")
        if type(self.own_observations) is not tuple or len(self.own_observations) > 2:
            raise ValueError("at most two forecast own observations are supported")
        if len({o.source for o in self.own_observations}) != len(self.own_observations):
            raise ValueError("duplicate own observation source")
        for obs in self.own_observations:
            if obs.available_at <= self.tick:
                raise ValueError("past evidence must already be in the current belief")
            if len(obs.accuracies) != len(self.questions):
                raise ValueError("own observation must describe every question slot")


@dataclass(frozen=True)
class ObservationAction:
    action_id: str
    measurement_pose: Cell
    flight_ticks: int
    sensing_ticks: int
    energy: float
    payload_bytes: int
    # Supplied by a sensor owner/quote fixture; None means no coverage.
    accuracies: tuple[float | None, ...]

    def __post_init__(self):
        if not self.action_id or self.action_id == "no_query":
            raise ValueError("action_id is required and no_query is reserved")
        _cell(self.measurement_pose)
        _tick(self.flight_ticks, "flight_ticks")
        _tick(self.sensing_ticks, "sensing_ticks", 1)
        _number(self.energy, "energy")
        _tick(self.payload_bytes, "payload_bytes")
        _accuracies(self.accuracies)


@dataclass(frozen=True)
class ReportBranch:
    probability: float
    # (source, question name, report_blocked)
    reports: tuple[tuple[str, str, bool], ...]
    posterior_blocked: tuple[float, ...]
    selected_route: str
    expected_route_cost: float


@dataclass(frozen=True)
class ActionEstimate:
    action_id: str
    measurement_pose: Cell | None
    result_available_at: int | None
    energy: float
    payload_bytes: int
    status: str
    expected_route_cost: float | None
    expected_gain: float | None
    branches: tuple[ReportBranch, ...]


def _expected_decision(problem, observations):
    states = tuple(product((False, True), repeat=len(problem.questions)))
    priors = tuple(math.prod(q.p_blocked if blocked else 1-q.p_blocked
                            for q, blocked in zip(problem.questions, state))
                   for state in states)
    channels = tuple((obs.source, index, q)
                     for obs in observations if obs.available_at <= problem.decision_at
                     for index, q in enumerate(obs.accuracies) if q is not None)
    branches = []
    for reports in product((False, True), repeat=len(channels)):
        weights = tuple(prior * math.prod(q if report == state[index] else 1-q
                        for (_, index, q), report in zip(channels, reports))
                        for state, prior in zip(states, priors))
        probability = math.fsum(weights)
        if probability == 0:
            continue
        route_costs = tuple(math.fsum(w*c for w, c in zip(weights, route.costs))
                            / probability for route in problem.routes)
        chosen = min(range(len(route_costs)), key=route_costs.__getitem__)
        posterior = tuple(math.fsum(w for w, state in zip(weights, states) if state[i])
                          / probability for i in range(len(problem.questions)))
        branches.append(ReportBranch(
            probability,
            tuple((source, problem.questions[i].name, report)
                  for (source, i, _), report in zip(channels, reports)),
            posterior, problem.routes[chosen].name, route_costs[chosen]))
    expected = math.fsum(b.probability*b.expected_route_cost for b in branches)
    return expected, tuple(branches)


def rank_actions(problem: DecisionProblem,
                 actions: tuple[ObservationAction, ...]) -> tuple[ActionEstimate, ...]:
    """Rank one forced first observation against continuing without a new one.

    Receipt at decision_at is timely and is processed before the route choice.
    Late evidence cannot affect this single decision. Energy is a hard limit,
    not an arbitrary conversion into time; lower energy breaks cost ties.
    """
    if len({a.action_id for a in actions}) != len(actions):
        raise ValueError("action ids must be unique")
    own_sources = {o.source for o in problem.own_observations}
    for action in actions:
        if len(action.accuracies) != len(problem.questions):
            raise ValueError("action must describe every question slot")
        if action.action_id in own_sources:
            raise ValueError("action must not duplicate a forecast observation")
    baseline, baseline_branches = _expected_decision(problem, problem.own_observations)
    estimates = [ActionEstimate("no_query", None, None, 0, 0, "no_query",
                                baseline, 0, baseline_branches)]
    for action in actions:
        available_at = problem.tick + action.flight_ticks + action.sensing_ticks
        if action.energy > problem.acquisition_energy_limit:
            cost, gain, branches, status = None, None, (), "energy_limit"
        elif available_at > problem.decision_at:
            cost, gain, branches, status = baseline, 0, baseline_branches, "too_late"
        else:
            observation = ExpectedObservation(action.action_id, available_at, action.accuracies)
            cost, branches = _expected_decision(problem, problem.own_observations+(observation,))
            gain, status = baseline-cost, "within_deadline"
            if abs(gain) <= 1e-10:
                cost, gain = baseline, 0
        estimates.append(ActionEstimate(action.action_id, action.measurement_pose,
                         available_at, action.energy, action.payload_bytes, status,
                         cost, gain, branches))
    return tuple(sorted(estimates, key=lambda e: (
        e.expected_route_cost is None,
        math.inf if e.expected_route_cost is None else e.expected_route_cost,
        e.energy, e.action_id != "no_query", e.action_id)))
