"""Run semantic mapping on generated terrain and export the mission for SCOUT Viewer."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
from math import ceil, dist
from pathlib import Path

from phdsim.belief.semantic_terrain import (
    MODES, Capture, Grid, Mode, Prediction, Sample, TerrainClassifier, extract_features,
)
from phdsim.core.grid import Cell
from phdsim.decision.acquisition.semantic import (
    DEFAULT_DRONE_FOV_DEG, INITIAL_ALTITUDE_M, AerialPlanner, AerialSettings, AerialTransit,
)
from phdsim.decision.acquisition.semantic_rover import MIN_RGB_ENTROPY, ROVER_FOOTPRINT, SelectiveRoverPlanner
from phdsim.environments.semantic_terrain import TerrainConfig, generate_terrain
from phdsim.evaluation.semantic_terrain import semantic_metrics
from phdsim.experiments.scout.semantic_fusion import compare_observations
from phdsim.planning.coverage_sweep import Plot, SweepRobot, plan_coverage_sweep, regular_sites
from phdsim.planning.x500_trajectory import MODEL_ID, SECONDS_PER_TICK, x500_flight, x500_level_travel_ticks
from phdsim.sensors.semantic_terrain import (
    CaptureConditions, CapturePose, LidarConfig, RGBConfig, RGBSample, TerrainObservation, capture_lidar, capture_rgb,
    nadir_footprint_side,
)


FIT_SEEDS = tuple(range(11, 31))
LABELS = {"exposed_soil": "Odsłonięta gleba", "rock": "Skała", "low_vegetation": "Niska roślinność"}
LAYER_LABELS = {"rgb": "Klasy · RGB", "lidar": "Klasy · LiDAR", "fused": "Klasy · fuzja"}
AERIAL_SENSORS = {"drone-1": ("rgb",), "drone-2": ("rgb", "lidar")}
ROVER_SENSOR_HEIGHT_M = 0.8


@dataclass(frozen=True)
class GroundTransit:
    origin_xy: Cell
    arrival_tick: int


@dataclass(frozen=True)
class Task:
    agent_id: str
    xy: Cell
    footprint: tuple[int, int, int, int]
    start_tick: int
    finish_tick: int
    sensors: tuple[str, ...]
    standoff_m: float
    nominal_footprint_wh: Cell | None = None
    transit: AerialTransit | None = None
    ground_transit: GroundTransit | None = None

    def replay_record(self) -> dict:
        record = {"agent_id": self.agent_id, "mode": "+".join(self.sensors),
                  "xy": display_xy(self.xy), "footprint": self.footprint,
                  "start_tick": self.start_tick, "finish_tick": self.finish_tick}
        if self.transit is not None:
            profile = self.transit.profile
            record.update(standoff_m=self.standoff_m, arrival_tick=self.start_tick + profile.travel_ticks,
                          flight_seconds=round(profile.duration_s, 6))
        if self.ground_transit is not None:
            record["arrival_tick"] = self.ground_transit.arrival_tick
        return record

    def aerial_pose(self, tick: int) -> dict:
        transit = self.transit
        assert transit is not None
        progress = transit.profile.progress_at((tick - self.start_tick) * SECONDS_PER_TICK)
        x, y = display_xy(transit.origin_xy)
        target_x, target_y = display_xy(self.xy)
        z = transit.origin_altitude_m
        return {"id": self.agent_id, "xy": (x + (target_x - x) * progress, y + (target_y - y) * progress),
                "altitude_m": z + (self.standoff_m - z) * progress}

    def ground_pose(self, tick: int) -> dict:
        transit = self.ground_transit
        assert transit is not None
        if tick >= transit.arrival_tick:
            return {"id": self.agent_id, "xy": display_xy(self.xy)}
        progress = (tick - self.start_tick) / (transit.arrival_tick - self.start_tick)
        xy = tuple(start + (end - start) * progress for start, end in
                   zip(display_xy(transit.origin_xy), display_xy(self.xy), strict=True))
        return {"id": self.agent_id, "xy": xy}


def display_xy(xy: Cell) -> tuple[float, float]:
    # Internal coordinates index cell centres. The viewer measures from the grid edge.
    return xy[0] + 0.5, xy[1] + 0.5


def as_capture(observation: TerrainObservation) -> Capture:
    samples = tuple(Sample(sample.xy, sample.rgb if isinstance(sample, RGBSample) else (sample.surface_m,))
                    for sample in observation.samples)
    return Capture(observation.observation_id, observation.sensor_id, observation.modality,
                   observation.capture_tick, samples)


def class_labels(terrain) -> tuple[str, ...]:
    return tuple(terrain.class_names[label] for row in terrain.labels for label in row)


def observe(fields, task: Task, seed: int, conditions: CaptureConditions) -> tuple[TerrainObservation, ...]:
    pose = CapturePose(*task.xy, task.standoff_m)
    footprint_wh = task.nominal_footprint_wh or task.footprint[2:]
    args = dict(seed=seed, capture_tick=task.finish_tick, conditions=conditions)
    captures = []
    if "rgb" in task.sensors:
        captures.append(capture_rgb(fields, pose, sensor_id=f"{task.agent_id}-rgb",
                                    config=RGBConfig(footprint_wh=footprint_wh), **args))
    if "lidar" in task.sensors:
        captures.append(capture_lidar(fields, pose, sensor_id=f"{task.agent_id}-lidar",
                                      config=LidarConfig(footprint_wh=footprint_wh), **args))
    if any(capture.footprint != task.footprint for capture in captures):
        raise ValueError("scheduled footprint and sensor support differ")
    return tuple(captures)


def fit_classifier(config: TerrainConfig, fit_seeds: tuple[int, ...]) -> TerrainClassifier:
    grid = Grid(config.width, config.height, config.cell_size_m)
    plot = Plot(config.width, config.height, config.cell_size_m)
    sites = regular_sites(plot, (7, 7))
    examples = []
    for seed in fit_seeds:
        terrain = generate_terrain(seed, config)
        captures = []
        for tick, site in enumerate(sites, start=1):
            task = Task("training-pair", site.xy, site.footprint, tick - 1, tick, ("rgb", "lidar"), 3.0)
            captures.extend(as_capture(o) for o in observe(terrain.fields, task, seed, CaptureConditions()))
        examples.extend(zip(class_labels(terrain), extract_features(grid, captures), strict=True))
    return TerrainClassifier.fit(tuple(cls.name for cls in config.classes), examples)


def initial_drones(plot: Plot) -> tuple[SweepRobot, ...]:
    return (
        SweepRobot("drone-1", (0, 0), None, 2, 0.8, 2, 65, x500_level_travel_ticks),
        SweepRobot("drone-2", (plot.width - 1, plot.height - 1), None, 2, 0.8, 2, 65, x500_level_travel_ticks),
    )


def fixed_drone_tasks(plot: Plot, drones: tuple[SweepRobot, ...], sensors: dict[str, tuple[str, ...]],
                      altitude_m: float, fov_deg: float) -> tuple[list[Task], dict]:
    side = nadir_footprint_side(altitude_m, fov_deg, plot.cell_size_m)
    footprint = (side, side)
    plan = plan_coverage_sweep(plot, regular_sites(plot, footprint), drones)
    positions = {drone.agent_id: drone.start_xy for drone in drones}
    tasks = []
    for route in plan.routes:
        xy = positions[route.agent_id]
        for capture in route.captures:
            transit = AerialTransit(xy, altitude_m, x500_flight(capture.travel_m))
            tasks.append(Task(route.agent_id, capture.site.xy, capture.site.footprint, capture.start_tick,
                              capture.finish_tick, sensors[route.agent_id], altitude_m,
                              nominal_footprint_wh=footprint, transit=transit))
            xy = capture.site.xy
    summary = {"drone_sweep_orientation": plan.orientation, "nominal_drone_coverage_cells": plan.covered_cells,
               "energy_reserved": {route.agent_id: route.energy for route in plan.routes}}
    return tasks, summary


def fixed_tasks(plot: Plot, *, include_drones: bool = True,
                initial_altitude_m: float = INITIAL_ALTITUDE_M,
                drone_fov_deg: float = DEFAULT_DRONE_FOV_DEG) -> tuple[list[dict], list[Task], dict]:
    drones = initial_drones(plot)
    positions = {drone.agent_id: drone.start_xy for drone in drones}
    tasks = []
    summary = {}
    if include_drones:
        tasks, summary = fixed_drone_tasks(plot, drones, AERIAL_SENSORS, initial_altitude_m, drone_fov_deg)

    # The rover checks two local plots selected by location before any measurement.
    rover = "rover"
    positions[rover] = (plot.width // 2, plot.height // 2)
    sites = sorted(regular_sites(plot, ROVER_FOOTPRINT), key=lambda site: dist(site.xy, positions[rover]))[:2]
    tick, xy, rover_energy = 0, positions[rover], 0.0
    for site in sites:
        metres = dist(xy, site.xy) * plot.cell_size_m
        finish = tick + ceil(metres / 0.7) + 2
        rover_energy += metres * 0.4 + 1
        tasks.append(Task(rover, site.xy, site.footprint, tick, finish, ("lidar",), ROVER_SENSOR_HEIGHT_M))
        tick, xy = finish, site.xy

    labels = {"drone-1": "Dron RGB", "drone-2": "Dron RGB + LiDAR", "rover": "Łazik LiDAR"}
    agents = [{"id": agent, "label": labels[agent], "start_xy": display_xy(xy)} for agent, xy in positions.items()]
    for agent in agents:
        if agent["id"] in AERIAL_SENSORS:
            agent.update(start_altitude_m=initial_altitude_m, flight_model=MODEL_ID)
    summary.setdefault("energy_reserved", {})[rover] = rover_energy
    return agents, tasks, summary


def replay_tasks(
    grid: Grid,
    model: TerrainClassifier,
    agents: list[dict],
    tasks: list[Task],
    capture_task: Callable[[Task], tuple[Capture, ...]],
    *,
    choose_tasks: Callable[[int, dict[Mode, tuple[Prediction | None, ...]], list[Task]], list[Task]] | None = None,
) -> tuple[list[dict], list[Capture], dict[Mode, tuple[Prediction | None, ...]]]:
    """Fuse registered captures as tasks complete, without access to scene truth."""
    positions = {agent["id"]: {"id": agent["id"], "xy": agent["start_xy"]} for agent in agents}
    for agent in agents:
        if "start_altitude_m" in agent:
            positions[agent["id"]]["altitude_m"] = agent["start_altitude_m"]

    def agent_reports(tick: int, pending: list[Task]) -> list[dict]:
        moving = {task.agent_id: task.aerial_pose(tick) for task in pending if task.transit is not None}
        moving.update({task.agent_id: task.ground_pose(tick) for task in pending if task.ground_transit is not None})
        return [moving.get(agent, pose) for agent, pose in positions.items()]

    completions = defaultdict(list)
    issued = list(tasks)
    for task in issued:
        completions[task.finish_tick].append(task)
    frames, captures = [], []
    ticks = {0, *completions, *(task.start_tick for task in issued)}
    while ticks:
        tick = min(ticks)
        ticks.remove(tick)
        completed = completions[tick]
        for task in completed:
            pose = {"id": task.agent_id, "xy": display_xy(task.xy)}
            if task.transit is not None:
                pose["altitude_m"] = task.standoff_m
            positions[task.agent_id] = pose
            captures.extend(capture_task(task))
        predictions = compare_observations(grid, tuple(captures), model)
        pending = [task for task in issued if task.start_tick <= tick < task.finish_tick]
        if choose_tasks is not None:
            new = choose_tasks(tick, predictions, pending)
            for task in new:
                completions[task.finish_tick].append(task)
                ticks.add(task.finish_tick)
            issued.extend(new)
            pending.extend(new)
        layers = {mode: [p.label if p else None for p in predictions[mode]] for mode in MODES}
        layers["confidence"] = [round(max(p.probabilities), 4) if p else None for p in predictions["fused"]]
        frame = {"tick": tick, "layers": layers, "agents": agent_reports(tick, pending),
                 "completed": [task.replay_record() for task in completed],
                 "scheduled": [task.replay_record() for task in pending]}
        frames.append(frame)
        # Sample motion without dispatching new tasks or fusing evidence between events.
        next_event = min(ticks, default=tick + 1)
        for interim_tick in range(tick + 1, next_event):
            frames.append({**frame, "tick": interim_tick, "agents": agent_reports(interim_tick, pending),
                           "completed": []})
    return frames, captures, predictions


def selective_rover_replay(grid: Grid, plot: Plot, model: TerrainClassifier, fov_deg: float,
                           capture_task: Callable[[Task], tuple[Capture, ...]]):
    drones = initial_drones(plot)
    rovers = tuple(SweepRobot(f"rover-{i}", drone.start_xy, 0.7, 2, 0.4, 1, 65)
                   for i, drone in enumerate(drones, start=1))
    drone_sensors = {drone.agent_id: ("rgb",) for drone in drones}
    tasks, summary = fixed_drone_tasks(plot, drones, drone_sensors, INITIAL_ALTITUDE_M, fov_deg)
    agents = [{"id": drone.agent_id, "label": "Dron RGB", "start_xy": display_xy(drone.start_xy),
               "start_altitude_m": INITIAL_ALTITUDE_M, "flight_model": MODEL_ID} for drone in drones]
    agents.extend({"id": rover.agent_id, "label": "Łazik LiDAR", "start_xy": display_xy(rover.start_xy)}
                  for rover in rovers)

    ground_plan = plan_coverage_sweep(plot, regular_sites(plot, ROVER_FOOTPRINT), rovers)
    last_drone_tick = max((task.finish_tick for task in tasks), default=0)
    deadline = max(last_drone_tick, ground_plan.makespan_ticks)
    planner = SelectiveRoverPlanner(plot, rovers, deadline)

    def choose_tasks(tick: int, estimates: dict[Mode, tuple[Prediction | None, ...]], pending: list[Task]) -> list[Task]:
        commitments = tuple((task.agent_id, task.footprint) for task in pending if task.sensors == ("lidar",))
        assignments = planner.dispatch(tick, estimates["rgb"], estimates["lidar"], commitments)
        selected = []
        for assignment in assignments:
            capture = assignment.capture
            selected.append(Task(assignment.agent_id, capture.site.xy, capture.site.footprint,
                                 capture.start_tick, capture.finish_tick, ("lidar",), ROVER_SENSOR_HEIGHT_M,
                                 nominal_footprint_wh=ROVER_FOOTPRINT,
                                 ground_transit=GroundTransit(assignment.origin_xy, capture.arrival_tick)))
        return selected

    frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task, choose_tasks=choose_tasks)
    summary["energy_reserved"].update(planner.energy_reserved)
    summary.update(rover_deadline_tick=deadline, rover_min_rgb_entropy=MIN_RGB_ENTROPY,
                   nominal_ground_sweep_cells=ground_plan.covered_cells)
    return agents, frames, captures, predictions, summary


def semantic_replay(seed: int, model: TerrainClassifier, config: TerrainConfig, *,
                    aerial: AerialSettings | None = None,
                    fixed_fov_deg: float = DEFAULT_DRONE_FOV_DEG,
                    selective_rovers: bool = False) -> tuple[dict, dict]:
    if selective_rovers and aerial is not None:
        raise ValueError("selective rovers require a fixed drone sweep")
    terrain = generate_terrain(seed, config)
    grid = Grid(config.width, config.height, config.cell_size_m)
    plot = Plot(grid.width, grid.height, grid.cell_size_m)
    if not selective_rovers:
        altitude = INITIAL_ALTITUDE_M if aerial is None else aerial.initial_altitude_m
        agents, tasks, summary = fixed_tasks(plot, include_drones=aerial is None,
                                             initial_altitude_m=altitude, drone_fov_deg=fixed_fov_deg)
    # This small shaded patch is an observation condition, separate from semantic labels.
    shade = frozenset((x, y) for x in range(2, min(5, grid.width)) for y in range(2, min(4, grid.height)))
    conditions = CaptureConditions(occluded_cells=shade)

    def capture_task(task: Task) -> tuple[Capture, ...]:
        return tuple(as_capture(observation) for observation in observe(terrain.fields, task, seed, conditions))

    if selective_rovers:
        agents, frames, captures, predictions, summary = selective_rover_replay(
            grid, plot, model, fixed_fov_deg, capture_task)
    elif aerial is None:
        frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_task)
    else:
        planner = AerialPlanner(plot, initial_drones(plot), aerial)

        def capture_and_record(task: Task) -> tuple[Capture, ...]:
            observed = capture_task(task)
            if task.agent_id in AERIAL_SENSORS:
                planner.record_samples(task.standoff_m, (sample.xy for capture in observed for sample in capture.samples))
            return observed

        def choose_tasks(tick: int, estimates: dict[Mode, tuple[Prediction | None, ...]],
                         pending: list[Task]) -> list[Task]:
            commitments = tuple((task.agent_id, task.footprint) for task in pending)
            return [Task(choice.agent_id, choice.view.site.xy, choice.view.site.footprint, tick,
                         choice.finish_tick, AERIAL_SENSORS[choice.agent_id], choice.view.standoff_m,
                         choice.view.nominal_footprint_wh, choice.transit)
                    for choice in planner.dispatch(tick, estimates["fused"], commitments)]

        frames, captures, predictions = replay_tasks(grid, model, agents, tasks, capture_and_record,
                                                      choose_tasks=choose_tasks)
        summary["energy_reserved"].update(planner.energy_reserved)
        summary["aerial_views_per_drone"] = len(planner.views)
        summary["aerial_measurements_by_altitude_m"] = dict(Counter(
            task["standoff_m"] for frame in frames for task in frame["completed"] if "standoff_m" in task))

    reference = class_labels(terrain)
    if selective_rovers:
        summary["accuracy_by_tick"] = [
            {"tick": frame["tick"], **{
                mode: sum(label == actual for label, actual in zip(frame["layers"][mode], reference, strict=True))
                / len(reference) for mode in ("rgb", "fused")
            }} for frame in frames
        ]
    categories = [{"id": name, "label": LABELS.get(name, name)} for name in model.classes]
    replay = {"schema": "scout-replay-v1", "title": f"SCOUT — klasy terenu · misja {seed}",
              "seconds_per_tick": SECONDS_PER_TICK, "grid": asdict(grid), "agents": agents, "frames": frames,
              "layers": [{"id": mode, "label": LAYER_LABELS[mode], "kind": "categorical", "categories": categories}
                         for mode in MODES] + [{"id": "confidence", "label": "Pewność fuzji (szacunek modelu)",
                                                "kind": "scalar", "domain": [0, 1]}],
              "reference_layers": {mode: reference for mode in MODES}}
    common = tuple(a is not None and b is not None for a, b in zip(predictions["rgb"], predictions["lidar"], strict=True))
    summary.update({"seed": seed, "elapsed_ticks": frames[-1]["tick"],
                    "measurement_tasks": sum(len(frame["completed"]) for frame in frames),
                    "capture_count_by_modality": {mode: sum(c.modality == mode for c in captures)
                                                  for mode in ("rgb", "lidar")},
                    "metrics": {scope: {mode: semantic_metrics(model.classes, reference, estimates, mask)
                                        for mode, estimates in predictions.items()}
                                for scope, mask in (("whole_map", None), ("paired_support", common))}})
    return replay, summary


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fit-seeds", nargs="+", type=int, default=FIT_SEEDS)
    parser.add_argument("--test-seeds", nargs="+", type=int, default=(2021, 2022, 2023))
    strategy = parser.add_mutually_exclusive_group()
    strategy.add_argument("--drone-altitudes", nargs="+", type=float, metavar="METRES",
                          help="Use the adaptive reference policy with these altitudes above the terrain")
    strategy.add_argument("--selective-rovers", action="store_true",
                          help="Fly a fixed two-drone RGB sweep and send two LiDAR rovers on demand")
    parser.add_argument("--drone-fov-deg", type=float, default=DEFAULT_DRONE_FOV_DEG, metavar="DEGREES",
                        help="Shared horizontal and vertical field of view of drone sensors (default: %(default)s)")
    parser.add_argument("--cell-size-m", type=float, default=TerrainConfig.cell_size_m, metavar="METRES",
                        help="Terrain cell side length in metres at a fixed grid size (default: %(default)s)")
    args = parser.parse_args(argv)
    combined = (*args.fit_seeds, *args.test_seeds)
    if len(set(combined)) != len(combined):
        parser.error("Fit and test seeds must be unique and disjoint")
    try:
        config = TerrainConfig(cell_size_m=args.cell_size_m)
        settings = AerialSettings(
            altitudes_m=tuple(args.drone_altitudes) if args.drone_altitudes else AerialSettings.altitudes_m,
            fov_deg=args.drone_fov_deg,
        )
    except ValueError as error:
        parser.error(str(error))
    aerial = settings if args.drone_altitudes else None
    model = fit_classifier(config, tuple(args.fit_seeds))
    args.output.mkdir(parents=True, exist_ok=False)
    runs = []
    for i, seed in enumerate(args.test_seeds):
        replay, summary = semantic_replay(seed, model, config, aerial=aerial, fixed_fov_deg=settings.fov_deg,
                                          selective_rovers=args.selective_rovers)
        name = "mission.json" if i == 0 else f"mission-{seed}.json"
        (args.output / name).write_text(json.dumps(replay, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        runs.append(summary)
    report = {"fit_seeds": args.fit_seeds, "test_seeds": args.test_seeds,
              "flight_model": MODEL_ID, "seconds_per_tick": SECONDS_PER_TICK, "terrain": asdict(config), "runs": runs,
              "drone_fov_deg": settings.fov_deg,
              "scope": "Fixed terrestrial synthetic coverage, immediate sharing, uncalibrated classifier."}
    if aerial is not None:
        report["aerial"] = asdict(aerial)
        report["scope"] = "Adaptive drone views, fixed rover schedule, immediate sharing, uncalibrated classifier."
    if args.selective_rovers:
        report["scope"] = "Fixed RGB drone sweep, selected LiDAR rover captures, immediate sharing, uncalibrated classifier."
    (args.output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
