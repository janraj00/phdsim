"""Minimal, plug-in benchmark runner for SCOUT semantic missions (immediate shared map)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import csv
from dataclasses import asdict
import json
from pathlib import Path
from statistics import fmean
from typing import Any

from phdsim.belief.semantic_gmm import JointGMMClassifier
from phdsim.belief.semantic_terrain import (
    MODES,
    Capture,
    CellFeatures,
    Grid,
    Mode,
    Prediction,
    SemanticEstimator,
    TerrainClassifier,
    extract_features,
)
from phdsim.decision.acquisition.semantic import AerialPlanner, AerialSettings
from phdsim.decision.acquisition.semantic_rover import MIN_RGB_ENTROPY, SelectiveRoverPlanner
from phdsim.decision.acquisition.semantic_voi import (
    DEFAULT_MIN_SITE_GAIN,
    DEFAULT_PRIOR_STRENGTH,
    DEFAULT_PROB_BINS,
    CrossModalGainEstimator,
    SelectiveRoverVoIPlanner,
)
from phdsim.environments.semantic_terrain import SemanticTerrain, TerrainConfig, generate_terrain
from phdsim.evaluation.semantic_terrain import semantic_metrics
from phdsim.experiments.scout.bench_config import BenchConfig, ClassifierSpec, FleetSpec, VariantSpec
from phdsim.experiments.scout.provenance import source_identity
from phdsim.experiments.scout.semantic_mission import (
    AERIAL_SENSORS,
    LABELS,
    LAYER_LABELS,
    ROVER_SENSOR_HEIGHT_M,
    GroundTransit,
    Task,
    as_capture,
    class_labels,
    display_xy,
    fixed_drone_tasks,
    fixed_tasks,
    observe,
    replay_tasks,
)
from phdsim.planning.coverage_sweep import Plot, SweepRobot, plan_coverage_sweep, regular_sites
from phdsim.planning.x500_trajectory import MODEL_ID, SECONDS_PER_TICK, x500_level_travel_ticks
from phdsim.sensors.semantic_terrain import CaptureConditions


ClassifierFactory = Callable[[tuple[str, ...], list[tuple[str, CellFeatures]], dict[str, Any]], SemanticEstimator]


def _fit_gaussian(classes: tuple[str, ...], examples: list[tuple[str, CellFeatures]], params: dict[str, Any]):
    if params:
        raise ValueError(f"gaussian classifier does not accept parameters: {sorted(params)}")
    return TerrainClassifier.fit(classes, examples)


def _fit_gmm(classes: tuple[str, ...], examples: list[tuple[str, CellFeatures]], params: dict[str, Any]):
    allowed = {"n_components", "n_iters", "seed"}
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"unknown gmm parameters: {sorted(unknown)}")
    return JointGMMClassifier.fit(
        classes,
        examples,
        n_components=params.get("n_components", 3),
        n_iters=params.get("n_iters", 25),
        seed=params.get("seed", 0),
    )


CLASSIFIER_REGISTRY: dict[str, ClassifierFactory] = {
    "gaussian": _fit_gaussian,
    "gmm": _fit_gmm,
}


def collect_training_examples(config: TerrainConfig, fit_seeds: tuple[int, ...]) -> list[tuple[str, CellFeatures]]:
    grid = Grid(config.width, config.height, config.cell_size_m)
    plot = Plot(config.width, config.height, config.cell_size_m)
    sites = regular_sites(plot, (7, 7))
    examples: list[tuple[str, CellFeatures]] = []
    for seed in fit_seeds:
        terrain = generate_terrain(seed, config)
        captures: list[Capture] = []
        for tick, site in enumerate(sites, start=1):
            task = Task("training-pair", site.xy, site.footprint, tick - 1, tick, ("rgb", "lidar"), 3.0)
            captures.extend(as_capture(o) for o in observe(terrain.fields, task, seed, CaptureConditions()))
        examples.extend(zip(class_labels(terrain), extract_features(grid, captures), strict=True))
    return examples


def fit_registered_classifier(
    spec: ClassifierSpec,
    config: TerrainConfig,
    examples: list[tuple[str, CellFeatures]],
) -> SemanticEstimator:
    if spec.type not in CLASSIFIER_REGISTRY:
        raise ValueError(f"unknown classifier {spec.type!r}; available: {sorted(CLASSIFIER_REGISTRY)}")
    classes = tuple(cls.name for cls in config.classes)
    return CLASSIFIER_REGISTRY[spec.type](classes, examples, spec.params)


def _make_drones(plot: Plot, fleet: FleetSpec) -> tuple[SweepRobot, ...]:
    return (
        SweepRobot("drone-1", (0, 0), None, 2, 0.8, 2, fleet.drone_energy_budget, x500_level_travel_ticks),
        SweepRobot(
            "drone-2",
            (plot.width - 1, plot.height - 1),
            None,
            2,
            0.8,
            2,
            fleet.drone_energy_budget,
            x500_level_travel_ticks,
        ),
    )


def _make_rovers(drones: tuple[SweepRobot, ...], fleet: FleetSpec) -> tuple[SweepRobot, ...]:
    return tuple(
        SweepRobot(
            f"rover-{i}",
            drone.start_xy,
            fleet.rover_speed_m_per_tick,
            2,
            0.4,
            1,
            fleet.rover_energy_budget,
        )
        for i, drone in enumerate(drones, start=1)
    )


PolicyHandler = Callable[
    [Grid, Plot, SemanticEstimator, FleetSpec, dict[str, Any], Callable[[Task], tuple[Capture, ...]]],
    tuple[list[dict], list[dict], list[Capture], dict[Mode, tuple[Prediction | None, ...]], dict[str, Any]],
]


def _policy_rgb_only(grid, plot, model, fleet, params, capture_task):
    drones = _make_drones(plot, fleet)
    tasks, summary = fixed_drone_tasks(
        plot, drones, {d.agent_id: ("rgb",) for d in drones}, fleet.initial_altitude_m, fleet.drone_fov_deg,
    )
    agents = [
        {"id": d.agent_id, "label": "Dron RGB", "start_xy": display_xy(d.start_xy),
         "start_altitude_m": fleet.initial_altitude_m, "flight_model": MODEL_ID}
        for d in drones
    ]
    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task)
    summary["rover_visits"] = 0
    return agents, frames, captures, predictions, summary


def _policy_selective_rovers_entropy(grid, plot, model, fleet, params, capture_task):
    drones = _make_drones(plot, fleet)
    rovers = _make_rovers(drones, fleet)
    tasks, summary = fixed_drone_tasks(
        plot, drones, {d.agent_id: ("rgb",) for d in drones}, fleet.initial_altitude_m, fleet.drone_fov_deg,
    )
    agents = [
        {"id": d.agent_id, "label": "Dron RGB", "start_xy": display_xy(d.start_xy),
         "start_altitude_m": fleet.initial_altitude_m, "flight_model": MODEL_ID}
        for d in drones
    ]
    agents.extend({"id": r.agent_id, "label": "Łazik LiDAR", "start_xy": display_xy(r.start_xy)} for r in rovers)

    ground_plan = plan_coverage_sweep(plot, regular_sites(plot, fleet.rover_footprint), rovers)
    last_drone_tick = max((t.finish_tick for t in tasks), default=0)
    deadline = int(params.get("deadline_tick", max(last_drone_tick, ground_plan.makespan_ticks)))
    min_entropy = float(params.get("min_rgb_entropy", MIN_RGB_ENTROPY))
    planner = SelectiveRoverPlanner(
        plot, rovers, deadline, min_rgb_entropy=min_entropy, rover_footprint=fleet.rover_footprint,
    )
    rover_visits = 0

    def choose_tasks(tick: int, estimates: dict[Mode, tuple[Prediction | None, ...]], pending: list[Task]) -> list[Task]:
        nonlocal rover_visits
        commitments = tuple((t.agent_id, t.footprint) for t in pending if t.sensors == ("lidar",))
        assignments = planner.dispatch(tick, estimates["rgb"], estimates["lidar"], commitments)
        selected: list[Task] = []
        for assignment in assignments:
            cap = assignment.capture
            rover_visits += 1
            selected.append(
                Task(
                    assignment.agent_id,
                    cap.site.xy,
                    cap.site.footprint,
                    cap.start_tick,
                    cap.finish_tick,
                    ("lidar",),
                    ROVER_SENSOR_HEIGHT_M,
                    nominal_footprint_wh=fleet.rover_footprint,
                    ground_transit=GroundTransit(assignment.origin_xy, cap.arrival_tick),
                )
            )
        return selected

    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task, choose_tasks=choose_tasks)
    summary["energy_reserved"].update(planner.energy_reserved)
    summary["rover_visits"] = rover_visits
    summary["rover_min_rgb_entropy"] = min_entropy
    return agents, frames, captures, predictions, summary


def _policy_full_ground_sweep(grid, plot, model, fleet, params, capture_task):
    drones = _make_drones(plot, fleet)
    rovers = _make_rovers(drones, fleet)
    tasks, summary = fixed_drone_tasks(
        plot, drones, {d.agent_id: ("rgb",) for d in drones}, fleet.initial_altitude_m, fleet.drone_fov_deg,
    )
    agents = [
        {"id": d.agent_id, "label": "Dron RGB", "start_xy": display_xy(d.start_xy),
         "start_altitude_m": fleet.initial_altitude_m, "flight_model": MODEL_ID}
        for d in drones
    ]
    agents.extend({"id": r.agent_id, "label": "Łazik LiDAR", "start_xy": display_xy(r.start_xy)} for r in rovers)

    ground_plan = plan_coverage_sweep(plot, regular_sites(plot, fleet.rover_footprint), rovers)
    rover_visits = 0
    for route in ground_plan.routes:
        origin = next(r.start_xy for r in rovers if r.agent_id == route.agent_id)
        for cap in route.captures:
            rover_visits += 1
            tasks.append(
                Task(
                    route.agent_id,
                    cap.site.xy,
                    cap.site.footprint,
                    cap.start_tick,
                    cap.finish_tick,
                    ("lidar",),
                    ROVER_SENSOR_HEIGHT_M,
                    nominal_footprint_wh=fleet.rover_footprint,
                    ground_transit=GroundTransit(origin, cap.arrival_tick),
                )
            )
            origin = cap.site.xy
        summary["energy_reserved"][route.agent_id] = route.energy

    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task)
    summary["rover_visits"] = rover_visits
    return agents, frames, captures, predictions, summary


def _policy_fixed_sweep(grid, plot, model, fleet, params, capture_task):
    agents, tasks, summary = fixed_tasks(
        plot, include_drones=True, initial_altitude_m=fleet.initial_altitude_m, drone_fov_deg=fleet.drone_fov_deg,
    )
    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task)
    summary["rover_visits"] = sum(1 for t in tasks if t.agent_id.startswith("rover"))
    return agents, frames, captures, predictions, summary


def _policy_adaptive_aerial(grid, plot, model, fleet, params, capture_task):
    altitudes = tuple(float(v) for v in params.get("altitudes_m", AerialSettings.altitudes_m))
    time_budget = int(params.get("time_budget", AerialSettings.time_budget))
    settings = AerialSettings(
        altitudes_m=altitudes,
        fov_deg=fleet.drone_fov_deg,
        initial_altitude_m=fleet.initial_altitude_m,
        time_budget=time_budget,
    )
    agents, tasks, summary = fixed_tasks(
        plot, include_drones=False, initial_altitude_m=settings.initial_altitude_m, drone_fov_deg=settings.fov_deg,
    )
    drones = _make_drones(plot, fleet)
    planner = AerialPlanner(plot, drones, settings)

    def capture_and_record(task: Task) -> tuple[Capture, ...]:
        observed = capture_task(task)
        if task.agent_id in AERIAL_SENSORS:
            planner.record_samples(task.standoff_m, (s.xy for c in observed for s in c.samples))
        return observed

    def choose_tasks(tick: int, estimates: dict[Mode, tuple[Prediction | None, ...]], pending: list[Task]) -> list[Task]:
        commitments = tuple((t.agent_id, t.footprint) for t in pending)
        return [
            Task(
                choice.agent_id, choice.view.site.xy, choice.view.site.footprint, tick,
                choice.finish_tick, AERIAL_SENSORS[choice.agent_id], choice.view.standoff_m,
                choice.view.nominal_footprint_wh, choice.transit,
            )
            for choice in planner.dispatch(tick, estimates["fused"], commitments)
        ]

    frames, captures, predictions = replay_tasks(
        grid, model, agents, tasks, capture_and_record, choose_tasks=choose_tasks,
    )
    summary["energy_reserved"].update(planner.energy_reserved)
    summary["rover_visits"] = sum(1 for t in tasks if t.agent_id.startswith("rover"))
    summary["aerial_measurements_by_altitude_m"] = dict(Counter(
        t["standoff_m"] for f in frames for t in f["completed"] if "standoff_m" in t
    ))
    return agents, frames, captures, predictions, summary


def fit_cross_modal_gain_estimator(
    terrain_cfg: TerrainConfig,
    cal_seeds: tuple[int, ...],
    model: SemanticEstimator,
    fleet: FleetSpec,
    conditions: CaptureConditions,
    *,
    bins: int = DEFAULT_PROB_BINS,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
) -> CrossModalGainEstimator:
    """Calibrate expected LiDAR accuracy gain on held-out cal_seeds using only model outputs."""
    if not cal_seeds:
        raise ValueError("selective_rovers_voi requires nonempty seeds.cal (disjoint from fit and test)")
    grid = Grid(terrain_cfg.width, terrain_cfg.height, terrain_cfg.cell_size_m)
    plot = Plot(grid.width, grid.height, grid.cell_size_m)
    drones = _make_drones(plot, fleet)
    rovers = _make_rovers(drones, fleet)
    drone_tasks, _ = fixed_drone_tasks(
        plot, drones, {d.agent_id: ("rgb",) for d in drones}, fleet.initial_altitude_m, fleet.drone_fov_deg,
    )
    ground_plan = plan_coverage_sweep(plot, regular_sites(plot, fleet.rover_footprint), rovers)
    rover_tasks = [
        Task(
            route.agent_id,
            cap.site.xy,
            cap.site.footprint,
            cap.start_tick,
            cap.finish_tick,
            ("lidar",),
            ROVER_SENSOR_HEIGHT_M,
            nominal_footprint_wh=fleet.rover_footprint,
        )
        for route in ground_plan.routes
        for cap in route.captures
    ]

    cal_examples: list[tuple[Prediction, int]] = []
    for seed in cal_seeds:
        terrain = generate_terrain(seed, terrain_cfg)
        reference = class_labels(terrain)
        rgb_caps = [as_capture(o) for t in drone_tasks for o in observe(terrain.fields, t, seed, conditions)]
        lidar_caps = [as_capture(o) for t in rover_tasks for o in observe(terrain.fields, t, seed, conditions)]
        rgb_preds = model.predict(extract_features(grid, rgb_caps), "rgb")
        fused_preds = model.predict(extract_features(grid, rgb_caps + lidar_caps), "fused")
        for truth, p_rgb, p_fused in zip(reference, rgb_preds, fused_preds, strict=True):
            if p_rgb is None:
                continue
            rgb_ok = int(p_rgb.label == truth)
            fused_ok = int(p_fused is not None and p_fused.label == truth)
            cal_examples.append((p_rgb, fused_ok - rgb_ok))

    return CrossModalGainEstimator.fit(cal_examples, bins=bins, prior_strength=prior_strength)


def _policy_selective_rovers_voi(grid, plot, model, fleet, params, capture_task):
    gain_estimator = params.get("_gain_estimator")
    if not isinstance(gain_estimator, CrossModalGainEstimator):
        raise ValueError("selective_rovers_voi requires a calibrated CrossModalGainEstimator")

    drones = _make_drones(plot, fleet)
    rovers = _make_rovers(drones, fleet)
    tasks, summary = fixed_drone_tasks(
        plot, drones, {d.agent_id: ("rgb",) for d in drones}, fleet.initial_altitude_m, fleet.drone_fov_deg,
    )
    agents = [
        {"id": d.agent_id, "label": "Dron RGB", "start_xy": display_xy(d.start_xy),
         "start_altitude_m": fleet.initial_altitude_m, "flight_model": MODEL_ID}
        for d in drones
    ]
    agents.extend({"id": r.agent_id, "label": "Łazik LiDAR", "start_xy": display_xy(r.start_xy)} for r in rovers)

    ground_plan = plan_coverage_sweep(plot, regular_sites(plot, fleet.rover_footprint), rovers)
    last_drone_tick = max((t.finish_tick for t in tasks), default=0)
    deadline = int(params.get("deadline_tick", max(last_drone_tick, ground_plan.makespan_ticks)))
    min_site_gain = float(params.get("min_site_gain", DEFAULT_MIN_SITE_GAIN))
    planner = SelectiveRoverVoIPlanner(
        plot,
        rovers,
        deadline,
        gain_estimator,
        min_site_gain=min_site_gain,
        rover_footprint=fleet.rover_footprint,
    )
    rover_visits = 0

    def choose_tasks(tick: int, estimates: dict[Mode, tuple[Prediction | None, ...]], pending: list[Task]) -> list[Task]:
        nonlocal rover_visits
        commitments = tuple((t.agent_id, t.footprint) for t in pending if t.sensors == ("lidar",))
        assignments = planner.dispatch(tick, estimates["rgb"], estimates["lidar"], commitments)
        selected: list[Task] = []
        for assignment in assignments:
            cap = assignment.capture
            rover_visits += 1
            selected.append(
                Task(
                    assignment.agent_id,
                    cap.site.xy,
                    cap.site.footprint,
                    cap.start_tick,
                    cap.finish_tick,
                    ("lidar",),
                    ROVER_SENSOR_HEIGHT_M,
                    nominal_footprint_wh=fleet.rover_footprint,
                    ground_transit=GroundTransit(assignment.origin_xy, cap.arrival_tick),
                )
            )
        return selected

    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task, choose_tasks=choose_tasks)
    summary["energy_reserved"].update(planner.energy_reserved)
    summary["rover_visits"] = rover_visits
    summary["voi_min_site_gain"] = min_site_gain
    return agents, frames, captures, predictions, summary


POLICY_REGISTRY: dict[str, PolicyHandler] = {
    "rgb_only": _policy_rgb_only,
    "selective_rovers_entropy": _policy_selective_rovers_entropy,
    "selective_rovers_voi": _policy_selective_rovers_voi,
    "full_ground_sweep": _policy_full_ground_sweep,
    "fixed_sweep": _policy_fixed_sweep,
    "adaptive_aerial": _policy_adaptive_aerial,
}


def run_variant_seed(
    seed: int,
    terrain: SemanticTerrain,
    model: SemanticEstimator,
    variant: VariantSpec,
    fleet: FleetSpec,
    conditions: CaptureConditions,
    *,
    record_replay: bool = False,
    policy_context: dict[str, Any] | None = None,
) -> tuple[dict | None, dict]:
    if variant.policy not in POLICY_REGISTRY:
        raise ValueError(f"unknown policy {variant.policy!r}; available: {sorted(POLICY_REGISTRY)}")
    grid = Grid(terrain.fields.width, terrain.fields.height, terrain.fields.cell_size_m)
    plot = Plot(grid.width, grid.height, grid.cell_size_m)

    def capture_task(task: Task) -> tuple[Capture, ...]:
        return tuple(as_capture(obs) for obs in observe(terrain.fields, task, seed, conditions))

    params = {**variant.policy_params, **(policy_context or {})}
    agents, frames, _, predictions, summary = POLICY_REGISTRY[variant.policy](
        grid, plot, model, fleet, params, capture_task,
    )

    reference = class_labels(terrain)
    whole_metrics = {mode: semantic_metrics(model.classes, reference, predictions[mode], None) for mode in MODES}
    energy_map = summary.get("energy_reserved", {})
    drone_energy = sum(v for k, v in energy_map.items() if k.startswith("drone"))
    rover_energy = sum(v for k, v in energy_map.items() if k.startswith("rover"))

    run_summary = {
        "seed": seed,
        "variant": variant.name,
        "policy": variant.policy,
        "elapsed_ticks": frames[-1]["tick"],
        "accuracy_whole_area": whole_metrics["fused"]["accuracy_whole_area"],
        "coverage": whole_metrics["fused"]["coverage"],
        "rgb_accuracy_whole_area": whole_metrics["rgb"]["accuracy_whole_area"],
        "rover_visits": summary.get("rover_visits", 0),
        "drone_energy": drone_energy,
        "rover_energy": rover_energy,
        "metrics": whole_metrics,
    }

    replay = None
    if record_replay:
        categories = [{"id": name, "label": LABELS.get(name, name.replace("_", " "))} for name in model.classes]
        replay = {
            "schema": "scout-replay-v1",
            "title": f"SCOUT · {variant.label} · seed {seed}",
            "seconds_per_tick": SECONDS_PER_TICK,
            "grid": asdict(grid),
            "agents": agents,
            "frames": frames,
            "layers": [
                {"id": mode, "label": LAYER_LABELS[mode], "kind": "categorical", "categories": categories}
                for mode in MODES
            ] + [{"id": "confidence", "label": "Pewność fuzji (szacunek modelu)", "kind": "scalar", "domain": [0, 1]}],
            "reference_layers": {mode: reference for mode in MODES},
        }
    return replay, run_summary


def run_benchmark(config: BenchConfig, output_dir: Path) -> dict:
    """Run all configured variants on paired test seeds and write reports + replays."""
    terrain_cfg = config.terrain.to_terrain_config()
    conditions = CaptureConditions(occluded_cells=config.terrain.occluded_cells())

    for variant in config.variants:
        if variant.policy not in POLICY_REGISTRY:
            raise ValueError(f"unknown policy {variant.policy!r}; available: {sorted(POLICY_REGISTRY)}")
        clf_spec = variant.classifier or config.classifier
        if clf_spec.type not in CLASSIFIER_REGISTRY:
            raise ValueError(f"unknown classifier {clf_spec.type!r}; available: {sorted(CLASSIFIER_REGISTRY)}")
        if variant.policy == "selective_rovers_voi" and not config.seeds.cal:
            raise ValueError("selective_rovers_voi requires nonempty seeds.cal (disjoint from fit and test)")

    examples = collect_training_examples(terrain_cfg, config.seeds.fit)
    model_cache: dict[tuple[str, str], SemanticEstimator] = {}
    voi_cache: dict[tuple[str, str, int, float], CrossModalGainEstimator] = {}

    def get_model(spec: ClassifierSpec) -> SemanticEstimator:
        key = (spec.type, json.dumps(spec.params, sort_keys=True))
        if key not in model_cache:
            model_cache[key] = fit_registered_classifier(spec, terrain_cfg, examples)
        return model_cache[key]

    def get_voi(spec: ClassifierSpec, model: SemanticEstimator, params: dict[str, Any]) -> CrossModalGainEstimator:
        bins = int(params.get("prob_bins", DEFAULT_PROB_BINS))
        prior = float(params.get("prior_strength", DEFAULT_PRIOR_STRENGTH))
        key = (spec.type, json.dumps(spec.params, sort_keys=True), bins, prior)
        if key not in voi_cache:
            voi_cache[key] = fit_cross_modal_gain_estimator(
                terrain_cfg, config.seeds.cal, model, config.fleet, conditions, bins=bins, prior_strength=prior,
            )
        return voi_cache[key]

    terrains = {seed: generate_terrain(seed, terrain_cfg) for seed in config.seeds.test}
    replay_seeds = set(config.save_replays_for_seeds)

    output_dir.mkdir(parents=True, exist_ok=False)
    variant_reports: list[dict] = []
    saved_replays: list[dict] = []

    for variant in config.variants:
        clf_spec = variant.classifier or config.classifier
        model = get_model(clf_spec)
        policy_context: dict[str, Any] = {}
        if variant.policy == "selective_rovers_voi":
            policy_context["_gain_estimator"] = get_voi(clf_spec, model, variant.policy_params)
        per_seed: list[dict] = []
        variant_dir = output_dir / variant.name
        replay_index = 0

        for seed in config.seeds.test:
            want_replay = seed in replay_seeds
            replay, run_summary = run_variant_seed(
                seed,
                terrains[seed],
                model,
                variant,
                config.fleet,
                conditions,
                record_replay=want_replay,
                policy_context=policy_context,
            )
            per_seed.append(run_summary)
            if replay is not None:
                variant_dir.mkdir(parents=True, exist_ok=True)
                filename = "mission.json" if replay_index == 0 else f"mission-{seed}.json"
                replay_path = variant_dir / filename
                replay_path.write_text(json.dumps(replay, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
                saved_replays.append({
                    "variant": variant.name,
                    "label": variant.label,
                    "seed": seed,
                    "path": str(replay_path.relative_to(output_dir).as_posix()),
                })
                replay_index += 1

        variant_reports.append({
            "name": variant.name,
            "label": variant.label,
            "policy": variant.policy,
            "classifier": clf_spec.type,
            "mean_accuracy": round(fmean(r["accuracy_whole_area"] for r in per_seed), 6),
            "mean_rgb_accuracy": round(fmean(r["rgb_accuracy_whole_area"] for r in per_seed), 6),
            "mean_coverage": round(fmean(r["coverage"] for r in per_seed), 6),
            "mean_rover_visits": round(fmean(r["rover_visits"] for r in per_seed), 3),
            "mean_drone_energy": round(fmean(r["drone_energy"] for r in per_seed), 3),
            "mean_rover_energy": round(fmean(r["rover_energy"] for r in per_seed), 3),
            "mean_elapsed_ticks": round(fmean(r["elapsed_ticks"] for r in per_seed), 3),
            "runs": per_seed,
        })

    rgb_ref = next((v["mean_accuracy"] for v in variant_reports if v["policy"] == "rgb_only"), None)
    for report in variant_reports:
        baseline = rgb_ref if rgb_ref is not None else report["mean_rgb_accuracy"]
        report["delta_vs_rgb_pp"] = round((report["mean_accuracy"] - baseline) * 100.0, 3)

    provenance = source_identity(("cli/scout_bench.py", "evaluation/semantic_terrain.py"))
    comparison = {
        "schema": "scout-bench-v1",
        "name": config.name,
        "description": config.description,
        "git_head": provenance["git_head"],
        "scout_source_sha256": provenance["scout_source_sha256"],
        "terrain": asdict(config.terrain),
        "seeds": {
            "fit": list(config.seeds.fit),
            "cal": list(config.seeds.cal),
            "test": list(config.seeds.test),
        },
        "variants": variant_reports,
        "replays": saved_replays,
    }

    (output_dir / "resolved_config.json").write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
    )
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
    )

    csv_fields = [
        "name", "label", "policy", "classifier",
        "mean_accuracy", "delta_vs_rgb_pp", "mean_coverage",
        "mean_rover_visits", "mean_rover_energy", "mean_drone_energy", "mean_elapsed_ticks",
    ]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        for v in variant_reports:
            writer.writerow({k: v[k] for k in csv_fields})
    return comparison


def format_comparison_table(comparison: dict) -> str:
    headers = ("Variant", "Acc %", "Δ RGB", "Cov %", "Visits", "Rov E", "Ticks")
    rows = [
        (
            v["name"],
            f"{v['mean_accuracy'] * 100:5.2f}",
            f"{v['delta_vs_rgb_pp']:+5.2f}",
            f"{v['mean_coverage'] * 100:5.1f}",
            f"{v['mean_rover_visits']:5.2f}",
            f"{v['mean_rover_energy']:5.2f}",
            f"{v['mean_elapsed_ticks']:5.1f}",
        )
        for v in comparison["variants"]
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    sep = "  "
    lines = [
        sep.join(h.ljust(widths[i]) if i == 0 else h.rjust(widths[i]) for i, h in enumerate(headers)),
        sep.join("-" * w for w in widths),
    ]
    for r in rows:
        lines.append(sep.join(r[i].ljust(widths[i]) if i == 0 else r[i].rjust(widths[i]) for i, _ in enumerate(headers)))
    return "\n".join(lines)


def plugin_catalog() -> dict[str, list[str]]:
    return {
        "classifiers": sorted(CLASSIFIER_REGISTRY),
        "policies": sorted(POLICY_REGISTRY),
    }
