"""Small analytical recipient-value demonstration, separate from mission runs."""

import argparse
from dataclasses import asdict
import hashlib
from itertools import product
import json
import math
from pathlib import Path

from phdsim.agents.drone import Drone, DroneConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.decision.acquisition.recipient_value import (
    BinaryNeed, DecisionProblem, ExpectedObservation, ObservationAction,
    RouteOption, rank_actions,
)
from phdsim.experiments.scout.provenance import source_identity
from phdsim.sensors.occupancy import footprint


DEFAULT_CONFIG = Path(__file__).resolve().parents[4]/"configs/scout/single_decision.json"


def _path(waypoints):
    points = tuple(tuple(p) for p in waypoints)
    if not points or any(len(p) != 2 or any(type(v) is not int for v in p) for p in points):
        raise ValueError("waypoints must contain integer grid coordinates")
    path = [points[0]]
    for end in points[1:]:
        x, y = path[-1]
        if x != end[0] and y != end[1]:
            raise ValueError("route segments must be four-connected")
        dx = (end[0] > x)-(end[0] < x)
        dy = (end[1] > y)-(end[1] < y)
        while (x, y) != end:
            x, y = x+dx, y+dy
            path.append((x, y))
    if len(set(path)) != len(path):
        raise ValueError("scenario paths must not loop")
    return tuple(path)


def build_problem(config):
    """Derive a local decision table from public routes, not a terrain truth."""
    if config.get("schema") != "scout-single-decision/v1":
        raise ValueError("unsupported single-decision configuration schema")
    size = tuple(config["grid_size"])
    if len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("grid_size must contain two positive integers")
    rover = config["rover"]
    speed = rover["speed"]
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed <= 0:
        raise ValueError("rover speed must be positive and finite")
    step_ticks = max(1, math.ceil(1/speed))
    fork, goal = tuple(rover["fork"]), tuple(rover["goal"])
    approach = _path((rover["position"], fork))
    questions = tuple(BinaryNeed(q["name"], tuple(q["cell"]), q["p_blocked"])
                      for q in config["questions"])
    routes = config["routes"]
    if len(questions) != 2 or len(routes) != 2:
        raise ValueError("this grid example requires two questions and two routes")
    paths = tuple(_path(r["waypoints"]) for r in routes)
    if any(p[0] != fork or p[-1] != goal for p in paths):
        raise ValueError("routes must connect the fork to the same goal")
    if set(paths[0]) & set(paths[1]) != {fork, goal}:
        raise ValueError("the two branches may share only the fork and goal")
    if any(set(approach) & set(path) != {fork} for path in paths):
        raise ValueError("the shared approach must meet each branch only at the fork")
    names = [q.name for q in questions]
    if len(set(names)) != 2 or {r["question"] for r in routes} != set(names):
        raise ValueError("each route needs its own distinct question")
    indices = tuple(names.index(r["question"]) for r in routes)
    for i, path in enumerate(paths):
        cell = questions[indices[i]].cell
        if cell not in path[1:-1] or cell in paths[1-i]:
            raise ValueError("each question must be internal to its own route")
    all_cells = set(approach).union(*map(set, paths)) | {q.cell for q in questions}
    if any(not (0 <= x < size[0] and 0 <= y < size[1]) for x, y in all_cells):
        raise ValueError("scenario geometry is outside the grid")
    budget = config["mission_time_budget"]
    if type(budget) is not int or budget < 1:
        raise ValueError("mission_time_budget must be a positive integer")
    costs = [[], []]
    successful_costs = []
    for state in product((False, True), repeat=2):
        for i, path in enumerate(paths):
            if not state[indices[i]]:
                cost = (len(path)-1)*step_ticks
            elif state[indices[1-i]]:
                cost = budget+1
            else:
                before = path.index(questions[indices[i]].cell)-1
                # One tick for the rejected move, matching the pilot clock.
                cost = 2*before*step_ticks+1+(len(paths[1-i])-1)*step_ticks
            costs[i].append(cost)
            if not all(state):
                successful_costs.append(cost)
    approach_ticks = (len(approach)-1)*step_ticks
    tick = config["tick"]
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a nonnegative integer")
    if any(tick+approach_ticks+cost > budget for cost in successful_costs):
        raise ValueError("time budget must cover every successful continuation")
    own = tuple(ExpectedObservation(o["source"], o["available_at"],
                tuple(o["accuracies"][name] for name in names))
                for o in config.get("own_observations", ()))
    problem = DecisionProblem(config["tick"], config["tick"]+approach_ticks,
              questions, tuple(RouteOption(r["name"], tuple(c)) for r, c in zip(routes, costs)),
              config["acquisition_energy_limit"], own)

    drone_data = dict(config["drone"])
    position = tuple(drone_data.pop("position"))
    if len(position) != 2 or any(type(v) is not int for v in position) or not (0 <= position[0] < size[0] and 0 <= position[1] < size[1]):
        raise ValueError("drone position must be inside the grid")
    # No sensor likelihood implementation is added here. Quotes carry explicit
    # fixture likelihoods pending reconciliation of the approved sensor source.
    drone = Drone(position, DroneConfig(**drone_data))
    for name in ("speed", "move_energy", "measurement_energy"):
        value = getattr(drone.config, name)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or (name == "speed" and value == 0)):
            raise ValueError(f"invalid drone {name}")
    if type(drone.config.sensor_radius) is not int or drone.config.sensor_radius < 0:
        raise ValueError("sensor_radius must be a nonnegative integer")
    if type(drone.config.measurement_ticks) is not int or drone.config.measurement_ticks < 1:
        raise ValueError("measurement_ticks must be a positive integer")
    link = CommunicationConfig(delivery_delay=(0, 0), **config["communication"])
    if type(link.bytes_per_cell) is not int or link.bytes_per_cell < 1:
        raise ValueError("bytes_per_cell must be a positive integer")
    if (isinstance(link.energy_per_byte, bool) or not isinstance(link.energy_per_byte, (int, float))
            or not math.isfinite(link.energy_per_byte) or link.energy_per_byte < 0):
        raise ValueError("energy_per_byte must be finite and nonnegative")
    actions = []
    for item in config["observation_quotes"]:
        pose = tuple(item["measurement_pose"])
        quote = drone.quote(pose, problem.tick, size, link)
        cells = footprint(pose, drone.config.sensor_radius, size)
        accuracy = item["accuracies"]
        if set(accuracy) != set(names):
            raise ValueError("quote must explicitly specify every question's likelihood or no coverage")
        for question in questions:
            if (question.cell in cells) != (accuracy[question.name] is not None):
                raise ValueError("quote likelihood coverage disagrees with sensor footprint")
        actions.append(ObservationAction(item["action_id"], pose,
                       quote.capture_at-problem.tick-drone.config.measurement_ticks,
                       drone.config.measurement_ticks, quote.energy,
                       len(cells)*link.bytes_per_cell, tuple(accuracy[name] for name in names)))
    return problem, tuple(actions), {
        "grid_size": size, "approach": approach, "routes": paths,
        "state_order": tuple(product((False, True), repeat=2)),
        "failure_cost": budget+1, "estimate_method": "known-corridors-contact-fallback-v1",
        "drone_start": position,
    }


def evaluate(config):
    problem, actions, geometry = build_problem(config)
    estimates = rank_actions(problem, actions)
    return {
        "schema": "scout-single-decision-result/v1",
        "kind": "analytical_model_prediction",
        "assumptions": ["independent binary terrain beliefs", "conditionally independent sensor errors",
            "fixed shared approach until one route decision", "zero communication delay",
            "follow chosen route; on blockage return and try the other; no further drone request",
            "no-query retains all explicitly forecast own observations"],
        "inputs": {"problem": asdict(problem), "actions": [asdict(a) for a in actions],
                   "public_geometry": geometry, "sensor_model_ref": config["sensor_model_ref"],
                   "quality_source": config["quality_source"]},
        "selected_action_id": estimates[0].action_id,
        "estimates": [asdict(e) for e in estimates],
    }


def report(result):
    problem = result["inputs"]["problem"]
    geometry = result["inputs"]["public_geometry"]
    known = set(map(tuple, geometry["approach"]))
    for path in geometry["routes"]:
        known.update(map(tuple, path))
    markers = {tuple(q["cell"]): "?" for q in problem["questions"]}
    markers.update({tuple(geometry["approach"][0]): "R",
                    tuple(geometry["approach"][-1]): "F",
                    tuple(geometry["routes"][0][-1]): "G",
                    tuple(geometry["drone_start"]): "D"})
    grid = ["".join(markers.get((x, y), "." if (x, y) in known else "#")
                    for x in range(geometry["grid_size"][0]))
            for y in range(geometry["grid_size"][1])]
    lines = ["# One route decision: analytical observation proposals", "",
        "Model predictions only; no hidden world or actual measurement was sampled.", "",
        f"Decision tick: {problem['decision_at']}. Selected action: `{result['selected_action_id']}`.", "",
        "```text", *grid, "```", "",
        "R rover; D drone; F route decision; G goal; ? uncertain passage; . known corridor; # known rover obstacle.", "",
        "Costs are from the fork; the common approach is identical for every action.",
        "Failure receives the fixed penalty declared in the public continuation model.", "",
        "| Action | Measurement pose | Result tick | Energy | Expected route cost | Expected saving | Status |",
        "|---|---|---:|---:|---:|---:|---|"]
    for estimate in result["estimates"]:
        number = lambda v: "—" if v is None else f"{v:.4f}"
        lines.append(f"| {estimate['action_id']} | {estimate['measurement_pose']} | "
            f"{estimate['result_available_at']} | {number(estimate['energy'])} | "
            f"{number(estimate['expected_route_cost'])} | {number(estimate['expected_gain'])} | {estimate['status']} |")
    lines += ["", "## Conditional route costs", "",
        "States follow question order; False = free, True = blocked.", "",
        "| State | " + " | ".join(r["name"] for r in problem["routes"]) + " |",
        "|---|" + "---:|"*len(problem["routes"])]
    for i, state in enumerate(result["inputs"]["public_geometry"]["state_order"]):
        lines.append("| " + str(state) + " | " + " | ".join(str(r["costs"][i]) for r in problem["routes"]) + " |")
    return "\n".join(lines)+"\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="Fresh directory for inputs, estimates and report")
    args = parser.parse_args(argv)
    raw = args.config.read_bytes()
    config = json.loads(raw)
    result = evaluate(config)
    result["provenance"] = {"input_sha256": hashlib.sha256(raw).hexdigest(), **source_identity()}
    text = report(result)
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/"input.json").write_bytes(raw)
        (args.output/"estimates.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        (args.output/"report.md").write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
