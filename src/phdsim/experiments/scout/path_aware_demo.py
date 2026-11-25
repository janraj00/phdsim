"""All-grid one-view path-aware baseline and a matched analytical comparison."""

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from phdsim.agents.drone import DroneConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.decision.acquisition.path_aware import PathAwareView, rank_grid_views
from phdsim.decision.acquisition.recipient_value import ObservationAction, rank_actions
from phdsim.experiments.scout.provenance import source_identity
from phdsim.experiments.scout.single_decision import DEFAULT_CONFIG, build_problem


PAPER_URL = "https://arxiv.org/html/2406.05313v2#S5.SS1"


def compare(config):
    # This intentionally does not consume or validate the three manual pose
    # fixtures, their quality values or the original sensor-model label.
    problem, _, geometry = build_problem({**config, "observation_quotes": []})
    width, height = geometry["grid_size"]
    probabilities = [[1.0]*width for _ in range(height)]
    observed = [[True]*width for _ in range(height)]
    for cells in (geometry["approach"], *geometry["routes"]):
        for x, y in cells:
            probabilities[y][x] = 0.0
    for question in problem.questions:
        x, y = question.cell
        probabilities[y][x], observed[y][x] = question.p_blocked, False
    view = PathAwareView(problem.tick, problem.decision_at,
        geometry["approach"][0], geometry["routes"][0][-1], geometry["drone_start"],
        tuple(map(tuple, probabilities)), tuple(map(tuple, observed)),
        problem.acquisition_energy_limit)
    drone_data = {name: value for name, value in config["drone"].items() if name != "position"}
    drone = DroneConfig(**drone_data)
    communication = CommunicationConfig(delivery_delay=(0, 0), **config["communication"])
    path_aware = rank_grid_views(view, drone, communication)

    # The comparison uses the SAME generated poses, timing, energy and ideal
    # evidence for both selectors. It is not compared against the old noisy
    # three-pose result, whose sensor assumptions differ.
    actions = tuple(ObservationAction(q.action_id, q.measurement_pose, q.flight_ticks,
        q.sensing_ticks, q.energy, q.payload_bytes,
        tuple(1.0 if need.cell in q.covered_unknown_cells else None for need in problem.questions))
        for q in path_aware.ranked_views if q.covered_unknown_cells)
    values = rank_actions(problem, actions)
    by_value = {v.action_id: v for v in values}
    by_quote = {q.action_id: q for q in path_aware.ranked_views}
    choices = (("no_query", "no_query"),
               ("path_coverage_per_tick", path_aware.selected_action_id),
               ("expected_recipient_gain", values[0].action_id))
    summaries = []
    for method, action_id in choices:
        estimate = by_value[action_id]
        quote = by_quote.get(action_id)
        summaries.append({"method": method, "action_id": action_id,
            "measurement_pose": estimate.measurement_pose,
            "result_available_at": estimate.result_available_at,
            "energy": estimate.energy,
            "covered_unknown_cells": quote.covered_unknown_cells if quote else (),
            "path_gain": quote.path_gain if quote else 0,
            "gain_per_tick": quote.gain_per_tick if quote else 0,
            "expected_route_cost": estimate.expected_route_cost,
            "expected_gain": estimate.expected_gain})
    return {
        "schema": "scout-path-aware-comparison/v1",
        "kind": "analytical_perfect_sensing_comparison",
        "reference": {"title": "Traversing Mars", "url": PAPER_URL,
            "reused_idea": "unobserved optimistic follower-path coverage (equation 7)",
            "adaptations": ["one view instead of an IPP trajectory tree",
                "all grid poses instead of sampled continuous viewpoints",
                "gain per flight-plus-sensing tick instead of accumulated scout travel cost",
                "SCOUT deadline and incremental energy constraints",
                "known binary corridors; no feasibility/optimality exploration-mode loop"],
            "reproduces_original_method": False},
        "inputs": {"view": asdict(view), "decision_problem": asdict(problem),
            "public_geometry": geometry, "drone": asdict(drone),
            "communication": asdict(communication),
            "observation_model": "perfect_reports_for_every_covered_unknown_cell",
            "ignored_config_fields": ["observation_quotes", "sensor_model_ref", "quality_source"]},
        "optimistic_path": path_aware.optimistic_path,
        "information_needs": path_aware.information_needs,
        "grid_poses_enumerated": len(path_aware.ranked_views),
        "poses_covering_any_unknown": len(actions),
        "physically_admissible_poses": sum(q.result_available_at <= view.decision_at
            and q.energy <= view.acquisition_energy_limit for q in path_aware.ranked_views),
        "comparison": summaries,
        "ranked_views": [asdict(q) for q in path_aware.ranked_views],
        "recipient_values": [asdict(v) for v in values],
    }


def report(result):
    data = result["inputs"]
    view, geometry = data["view"], data["public_geometry"]
    need_set = set(map(tuple, result["information_needs"]))
    markers = {tuple(q["cell"]): "?" for q in data["decision_problem"]["questions"]}
    markers.update({tuple(view["rover_position"]): "R", tuple(view["goal"]): "G",
                    tuple(view["drone_position"]): "D", tuple(geometry["approach"][-1]): "F"})
    selected = result["comparison"][1]["measurement_pose"]
    if selected is not None:
        markers.setdefault(tuple(selected), "P")
    width, height = geometry["grid_size"]
    grid = ["".join(markers.get((x, y), "." if view["probabilities"][y][x] == 0 else "#")
                    for x in range(width)) for y in range(height)]
    lines = ["# Automatically proposed observation: one route decision", "",
        "Analytical, perfect-sensing comparison. No physical world or measurement outcome was sampled.", "",
        f"Inspired by [Traversing Mars, section V-A]({PAPER_URL}); this is a one-view adaptation, not a reproduction.", "",
        "```text", *grid, "```", "",
        "R rover; D drone; F decision; G goal; P proposed measurement pose; ? uncertain passage.", "",
        f"Enumerated grid poses: {result['grid_poses_enumerated']}. "
        f"Cover at least one unknown: {result['poses_covering_any_unknown']}. "
        f"Meet time and energy limits: {result['physically_admissible_poses']}.", "",
        f"Decision tick: {view['decision_at']}. Optimistic rover path: {len(result['optimistic_path'])-1} steps.",
        f"Automatically selected information needs on that path: {sorted(need_set)}.", "",
        "## Matched observation-model comparison", "",
        "Both selectors use the same automatically generated poses, perfect sensor, costs and deadline.",
        "Expected route costs include the same fixed failure penalty and exclude the common approach.", "",
        "| Selector | Pose | Result tick | Energy | Expected route cost | Expected saving |",
        "|---|---|---:|---:|---:|---:|"]
    for row in result["comparison"]:
        lines.append(f"| {row['method']} | {row['measurement_pose']} | {row['result_available_at']} | "
            f"{row['energy']:.4f} | {row['expected_route_cost']:.4f} | {row['expected_gain']:.4f} |")
    lines += ["", "## First five path-aware poses", "",
        "Score is the number of covered unknown optimistic-path cells divided by execution ticks.", "",
        "| Pose | Path coverage | Score | Result tick | Energy | Status |",
        "|---|---:|---:|---:|---:|---|"]
    for row in result["ranked_views"][:5]:
        lines.append(f"| {row['measurement_pose']} | {row['path_gain']} | {row['gain_per_tick']:.4f} | "
            f"{row['result_available_at']} | {row['energy']:.4f} | {row['status']} |")
    lines += ["", "## Scope", "",
        "Manual observation poses and their noisy likelihood fixtures are ignored. The geometry, current beliefs, start, goal and one decision deadline are still scenario inputs.",
        "Perfect reports are an explicit matched comparison assumption. The earlier noisy three-pose result is not a numerical competitor in this comparison.",
        "This does not implement an online scout trajectory, the paper's stopping criteria or its completeness/optimality guarantees. No superiority claim follows from this example.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="Fresh output directory")
    args = parser.parse_args(argv)
    raw = args.config.read_bytes()
    result = compare(json.loads(raw))
    result["provenance"] = {"input_sha256": hashlib.sha256(raw).hexdigest(), **source_identity()}
    text = report(result)
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/"input.json").write_bytes(raw)
        (args.output/"comparison.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        (args.output/"report.md").write_text(text, encoding="utf-8")
        fields = ("action_id", "measurement_pose", "covered_unknown_cells", "covered_path_unknown_cells",
                  "flight_ticks", "sensing_ticks", "result_available_at", "energy", "payload_bytes",
                  "path_gain", "gain_per_tick", "status")
        with (args.output/"views.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(result["ranked_views"])
    print(text)


if __name__ == "__main__":
    main()
