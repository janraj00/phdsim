"""Resumable mission execution; full-state forks are for offline analysis only."""

from copy import deepcopy
from dataclasses import dataclass

from phdsim.agents.drone import Drone
from phdsim.agents.rover import Rover
from phdsim.belief.occupancy import Belief
from phdsim.communication.delayed import DelayedLink
from phdsim.costs.mission import MissionLedger
from phdsim.core.grid import Cell
from phdsim.decision.acquisition.view import DecisionView
from phdsim.evaluation.mission import mission_result
from phdsim.planning.grid import plan_path
from phdsim.sensors.occupancy import observe
from .config import Config
from .events import EventQueue


@dataclass(frozen=True)
class DecisionPoint:
    view: DecisionView
    path: tuple[Cell, ...]


class MissionSimulator:
    """Own hidden state; policies receive only DecisionPoint.view and path.

    Pausing happens after deliveries/local sensing and before acquisition.
    fork() copies queued observations, resources and continuation policy state.
    This API is an offline simulator capability, not an agent capability.
    """

    def __init__(self, config: Config, world, policy):
        self.config, self.world, self.policy = config, world, policy
        self.belief = Belief(world.prior, world.start, world.goal)
        self.initial_belief = self.belief.snapshot()
        self.queue = EventQueue()
        self.rover = Rover(world.start, config.rover)
        self.drone = Drone(world.start, config.drone)
        self.link = DelayedLink(config.communication, config.seed)
        self.ledger = MissionLedger(config.mission.energy_budget)
        self.known_drone_position = world.start
        self.requests, self.last_request = 0, None
        self.events = []
        self.trajectory = [{"tick": 0, "position": list(world.start)}]
        self.tick, self.status, self._decision = 0, None, None

    def _log(self, kind, **fields):
        self.events.append({"tick": self.tick, "kind": kind, **fields})

    def _deliver_events(self):
        for _, _, kind, payload in self.queue.due(self.tick):
            if kind == "capture":
                target, request_id = payload
                self.drone.position = target
                obs = observe(self.world, "drone", target, self.config.drone.sensor_radius,
                              self.config.drone.sensor_accuracy, self.tick)
                self.queue.schedule(self.tick+self.link.delay(request_id), "deliver", (obs, request_id, target))
                self._log("drone_capture", request_id=request_id, position=list(target),
                          captured_at=self.tick, cells=len(obs.cells))
            elif kind == "deliver":
                obs, request_id, self.known_drone_position = payload
                self.belief.update(obs)
                self.drone.busy = False
                self._log("observation_delivered", request_id=request_id, captured_at=obs.captured_at,
                          bytes=self.link.payload_bytes(len(obs.cells)), age_ticks=self.tick-obs.captured_at,
                          cells=[list(cell) for cell in obs.cells])

    def next_decision(self) -> DecisionPoint | None:
        if self._decision is not None:
            return self._decision
        while self.status is None:
            self._deliver_events()
            if self.rover.arrive(self.tick):
                self.belief.contact(self.rover.position, False)
                self.trajectory.append({"tick": self.tick, "position": list(self.rover.position)})
                self._log("rover_arrived", position=list(self.rover.position))
            if self.rover.position == self.world.goal:
                self.status = "goal_reached"
                return None
            if self.tick == self.config.mission.time_budget:
                self.status = "time_budget"
                return None
            if self.rover.pending_move is not None:
                self.tick += 1
                continue
            obs = observe(self.world, "rover", self.rover.position, self.config.rover.sensor_radius,
                          self.config.rover.sensor_accuracy, self.tick)
            self.belief.update(obs)
            self._log("rover_observation", captured_at=self.tick, position=list(self.rover.position), cells=len(obs.cells))
            probabilities = self.belief.snapshot()
            path = plan_path(probabilities, self.rover.position, self.world.goal, self.config.planning)
            view = DecisionView(self.tick, self.rover.position, self.world.goal, probabilities,
                                self.known_drone_position, self.drone.busy, self.ledger.remaining,
                                self.config.mission.time_budget-self.tick, self.requests, self.last_request)
            self._decision = DecisionPoint(view, path)
            return self._decision
        return None

    def _request(self, target: Cell):
        config = self.config
        quote = self.drone.quote(target, self.tick, self.world.size, config.communication)
        reason = self.drone.rejection_reason(quote, self.ledger.remaining, config.rover.move_energy,
                                            config.mission.time_budget, config.communication.delivery_delay[0])
        if reason:
            self._log("request_rejected", reason=reason)
        else:
            self.requests += 1
            self.last_request, self.drone.busy = self.tick, True
            self.ledger.reserve_drone(quote.energy)
            self.queue.schedule(quote.capture_at, "capture", (target, self.requests))
            self._log("request_accepted", request_id=self.requests, target=list(target),
                      origin=list(self.drone.position), capture_at=quote.capture_at, energy_reserved=quote.energy)

    def act(self, target: Cell | None):
        if self._decision is None:
            raise RuntimeError("Call next_decision() before act()")
        path = self._decision.path
        self._decision = None
        if target is not None:
            self._request(target)
        if len(path) < 2:
            if self.drone.busy:
                self._log("rover_wait", reason="no_path_pending_observation")
                self.tick += 1
                return
            self.status = "no_believed_path"
            return
        if self.ledger.total+self.config.rover.move_energy > self.ledger.budget+1e-10:
            self.status = "energy_budget"
            return
        target = path[1]
        self.ledger.charge_rover(self.config.rover.move_energy)
        x, y = target
        if self.world.blocked[y][x]:
            self.belief.contact(target, True)
            self._log("blocked_attempt", position=list(target))
        else:
            arrival = self.rover.depart(target, self.tick)
            self._log("rover_move", origin=list(self.rover.position), target=list(target), arrival_at=arrival)
        self.tick += 1

    def advance_to_decision(self, earliest_tick: int) -> DecisionPoint | None:
        """Run continuation policy until the first decision at/after the tick."""
        if type(earliest_tick) is not int or earliest_tick < self.tick:
            raise ValueError("Checkpoint tick must be an integer at or after the current tick")
        while (point := self.next_decision()) is not None:
            if point.view.tick >= earliest_tick:
                return point
            self.act(self.policy.request(point.view, point.path))
        return None

    def fork(self):
        if self._decision is None:
            raise RuntimeError("Fork only at a paused decision point")
        return deepcopy(self)

    def run(self) -> dict:
        while (point := self.next_decision()) is not None:
            self.act(self.policy.request(point.view, point.path))
        return mission_result(self.config, self.world, self.policy.name, self.status, self.tick,
                              self.ledger, self.events, self.trajectory,
                              self.initial_belief, self.belief.snapshot())


def run_mission(config: Config, world, policy) -> dict:
    return MissionSimulator(config, world, policy).run()
