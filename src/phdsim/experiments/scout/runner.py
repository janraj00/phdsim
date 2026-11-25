"""Run paired SCOUT experiments and persist configs, metrics and reports."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from .mission import simulate
from .provenance import source_identity
from .report import render_svg


def run_experiment(config, config_path, output, seeds, policies):
    output = Path(output)
    if output.exists():
        raise ValueError(f"Output already exists: {output}; choose a fresh directory")
    output.mkdir(parents=True)
    provenance = source_identity()
    config_bytes = Path(config_path).read_bytes()
    provenance["config_sha256"] = hashlib.sha256(config_bytes).hexdigest()
    summaries = []
    for seed in seeds:
        seed_results = []
        for policy in policies:
            result = simulate(replace(config, seed=seed, policy=policy))
            result["provenance"] = provenance
            name = f"seed-{seed}-{policy}"
            (output/f"{name}.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
            (output/f"{name}.events.jsonl").write_text(''.join(json.dumps(e)+"\n" for e in result["events"]))
            summaries.append(result["summary"])
            seed_results.append(result)
            s = result["summary"]
            print(f'{policy} seed={seed}: {s["status"]}, ticks={s["elapsed_ticks"]}, '
                  f'energy={s["energy_reserved"]:.2f}, requests={s["requests"]}, delivered={s["delivered"]}')
        (output/f"seed-{seed}.svg").write_text(render_svg(seed_results))
    aggregate = []
    for policy in policies:
        group = [s for s in summaries if s["policy"] == policy]
        aggregate.append({"policy": policy, "missions": len(group),
                          "successes": sum(s["success"] for s in group),
                          "mean_elapsed_ticks_all_missions": sum(s["elapsed_ticks"] for s in group)/len(group),
                          "mean_energy_reserved": sum(s["energy_reserved"] for s in group)/len(group),
                          "mean_requests": sum(s["requests"] for s in group)/len(group)})
    (output/"summary.json").write_text(json.dumps({"provenance": provenance,
        "scope": "Synthetic diagnostic; no scientific superiority claim. Durations include failed missions.",
        "runs": summaries, "aggregate": aggregate}, indent=2)+"\n")
    (output/"config.json").write_bytes(config_bytes)
    print(f"Reports: {output.resolve()}")
