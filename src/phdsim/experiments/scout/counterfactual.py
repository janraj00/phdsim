"""Offline paired interventions. Hidden-state scores are labels, never inputs."""

from dataclasses import asdict
import json
import math
from pathlib import Path

from phdsim.decision.acquisition.candidates import CandidateConfig, generate_candidates
from phdsim.decision.acquisition.factory import make_policy
from phdsim.environments.corridors import generate_corridors
from phdsim.simulation.mission import MissionSimulator
from .provenance import source_identity


def evaluate_checkpoint(simulator: MissionSimulator, candidate_config: CandidateConfig,
                        failure_penalty: float) -> list[dict]:
    """Compare one decision; then resume identical continuation policies.

    The fixed hidden world and noise are retained. Each label is a REALIZED
    marginal outcome in that world, not an expected VoI over possible worlds.
    Copies preserve the queue and any measurement captured but not delivered.
    """
    c = simulator.config
    if not math.isfinite(failure_penalty) or failure_penalty <= c.mission.time_budget:
        raise ValueError("Failure penalty must be finite and exceed the mission time budget")
    point = simulator.next_decision()
    if point is None:
        raise ValueError("Cannot evaluate a completed mission")
    candidates = generate_candidates(point.view, point.path, c.planning, c.drone,
                                     c.communication, c.rover.sensor_radius, c.rover.speed,
                                     c.rover.move_energy, candidate_config)
    outcomes = []
    start_events = len(simulator.events)
    baseline_cost = None
    baseline_energy = None
    for candidate in candidates:
        branch = simulator.fork()
        branch.act(candidate.target)
        first_events = branch.events[start_events:]
        accepted = candidate.target is not None and any(e["kind"] == "request_accepted" for e in first_events)
        request_ids = [e["request_id"] for e in first_events if e["kind"] == "request_accepted"]
        result = branch.run()
        summary = result["summary"]
        cost = summary["elapsed_ticks"] if summary["success"] else failure_penalty
        if candidate.target is None:
            baseline_cost = cost
            baseline_energy = summary["energy_reserved"]
        delivered = any(e["kind"] == "observation_delivered" and e["request_id"] in request_ids
                        for e in result["events"][start_events:])
        outcomes.append({
            "schema": "scout-counterfactual-v0",
            "group": {"world_seed": c.seed, "decision_tick": point.view.tick,
                      "continuation_policy": simulator.policy.name},
            "inputs": {"view": asdict(point.view), "action": asdict(candidate)},
            "target": {"realized_gain_ticks": baseline_cost-cost,
                       "extra_energy_reserved": summary["energy_reserved"]-baseline_energy,
                       "mission_cost": cost, "request_accepted": accepted,
                       "new_observation_delivered_before_end": delivered,
                       "outcome": summary},
        })
    return outcomes


def collect_labels(config, config_path, output, seeds, decision_ticks,
                   candidate_config=CandidateConfig(), failure_penalty=None):
    """Collect diagnostic labels without installing a clairvoyant online policy."""
    from dataclasses import replace
    import hashlib

    penalty = config.mission.time_budget+1 if failure_penalty is None else failure_penalty
    if not math.isfinite(penalty) or penalty <= config.mission.time_budget:
        raise ValueError("Failure penalty must exceed the mission time budget")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be nonempty and unique")
    if (not decision_ticks or list(decision_ticks) != sorted(set(decision_ticks))
            or any(type(t) is not int or t < 0 for t in decision_ticks)):
        raise ValueError("Decision ticks must be nonnegative, unique and increasing")
    output = Path(output)
    if output.exists():
        raise ValueError(f"Output already exists: {output}; choose a fresh directory")
    output.mkdir(parents=True)
    provenance = source_identity()
    config_bytes = Path(config_path).read_bytes()
    provenance["config_sha256"] = hashlib.sha256(config_bytes).hexdigest()
    records, skipped, states = [], [], []
    for seed in seeds:
        c = replace(config, seed=seed)
        simulator = MissionSimulator(c, generate_corridors(c.world.size, seed), make_policy(c.policy, c.acquisition))
        previous_actual_tick = None
        for requested_tick in decision_ticks:
            if requested_tick < simulator.tick:
                skipped.append({"seed": seed, "requested_tick": requested_tick, "reason": "already_passed"})
                continue
            point = simulator.advance_to_decision(requested_tick)
            if point is None:
                skipped.append({"seed": seed, "requested_tick": requested_tick, "reason": "mission_finished"})
                continue
            if point.view.tick == previous_actual_tick:
                skipped.append({"seed": seed, "requested_tick": requested_tick, "reason": "same_decision"})
                continue
            previous_actual_tick = point.view.tick
            rows = evaluate_checkpoint(simulator, candidate_config, penalty)
            records.extend(rows)
            best = max(rows, key=lambda row: row["target"]["realized_gain_ticks"])
            states.append({"seed": seed, "requested_tick": requested_tick,
                           "actual_tick": point.view.tick, "candidates": len(rows),
                           "offline_best_action": best["inputs"]["action"]["candidate_id"],
                           "offline_best_realized_gain_ticks": best["target"]["realized_gain_ticks"]})
    summary = {
        "schema": "scout-counterfactual-v0", "provenance": provenance,
        "scope": "Offline realized counterfactual labels; no expected-VoI or learned-policy result.",
        "objective": {"success_cost": "absolute arrival tick", "failure_cost": penalty,
                      "energy": "hard shared mission budget; not an additional weighted reward"},
        "continuation_policy": config.policy,
        "resolved_config": config.to_dict(),
        "candidate_config": asdict(candidate_config), "seeds": list(seeds),
        "requested_decision_ticks": list(decision_ticks),
        "states": states, "skipped": skipped, "label_rows": len(records),
        "positive_request_labels": sum(r["inputs"]["action"]["target"] is not None
                                       and r["target"]["realized_gain_ticks"] > 0 for r in records),
        "negative_request_labels": sum(r["target"]["realized_gain_ticks"] < 0 for r in records),
        "split_warning": "Split by complete world seed, never by individual decision/action rows.",
    }
    (output/"labels.jsonl").write_text(''.join(json.dumps(r, allow_nan=False)+"\n" for r in records))
    (output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    (output/"config.json").write_bytes(config_bytes)
    lines = ["# SCOUT offline counterfactual diagnostic", "", summary["scope"], "",
             "Gain is baseline mission cost minus candidate mission cost. Positive means better.",
             "All branches use the same hidden world and continuation policy; scores are hindsight labels.", "",
             "| Seed | Decision tick | Action | Origin route | Gain (ticks) | Arrival/end tick | Reserved energy | Delivered new observation |",
             "|---|---|---|---|---:|---:|---:|---|"]
    for r in records:
        g, action, target = r["group"], r["inputs"]["action"], r["target"]
        s = target["outcome"]
        lines.append(f'| {g["world_seed"]} | {g["decision_tick"]} | {action["candidate_id"]} | '
                     f'{action["origin_route"]} | {target["realized_gain_ticks"]:g} | {s["elapsed_ticks"]} | '
                     f'{s["energy_reserved"]:.2f} | {target["new_observation_delivered_before_end"]} |')
    (output/"report.md").write_text('\n'.join(lines)+"\n")
    print(f'Offline labels: {len(records)} rows from {len(states)} states; '
          f'{summary["positive_request_labels"]} positive, {summary["negative_request_labels"]} negative request labels.')
    print(f'Reports: {output.resolve()}')
    return summary
