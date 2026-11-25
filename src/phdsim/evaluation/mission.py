"""Offline mission metrics and evaluator-only snapshots of hidden truth."""

import hashlib
import json


def mission_result(config, world, policy_name, status, tick, ledger, events,
                   trajectory, initial_belief, final_belief):
    def count(kind):
        return sum(e["kind"] == kind for e in events)

    requests, delivered = count("request_accepted"), count("observation_delivered")
    truth_json = json.dumps(world.blocked, separators=(",", ":"))
    return {
        "schema": "scout-pilot-v0", "config": config.to_dict(),
        "summary": {
            "policy": policy_name, "seed": config.seed, "status": status,
            "success": status == "goal_reached", "elapsed_ticks": tick,
            "energy_reserved": round(ledger.total, 6),
            "rover_energy": round(ledger.rover, 6),
            "drone_energy_reserved": round(ledger.drone, 6),
            "requests": requests, "captures": count("drone_capture"),
            "delivered": delivered, "pending_requests_at_end": requests-delivered,
            "delivered_bytes": sum(e["bytes"] for e in events if e["kind"] == "observation_delivered"),
            "blocked_attempts": count("blocked_attempt"),
            "rover_steps": len(trajectory)-1,
            "world_sha256": hashlib.sha256(truth_json.encode()).hexdigest(),
        },
        "trajectory": trajectory, "events": events,
        "evaluation": {
            "truth": [list(row) for row in world.blocked],
            "initial_belief": [list(row) for row in initial_belief],
            "final_belief": [list(row) for row in final_belief],
            "start": list(world.start), "goal": list(world.goal),
        },
    }
