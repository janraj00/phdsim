# SCOUT semantic benchmark workstreams

2026-11-20. Work from the [semantic environment design](SCOUT_SEMANTIC_ENVIRONMENT.md)
in the current SCOUT checkout. Keep integration and changes to shared interfaces
in the coordinating chat. Parallel work uses disjoint files in this checkout.

| Workstream | First handoff | File ownership |
|---|---|---|
| Terrain and sensors | Seeded civilian plot, noisy RGB and sparse LiDAR samples, reproducible captures | `src/phdsim/environments/semantic_terrain.py`, `src/phdsim/sensors/semantic_terrain.py`, focused terrain and sensor tests |
| Semantic estimates and fusion | RGB-only, LiDAR-only and fused predictions on the same sample positions | `src/phdsim/belief/semantic_terrain.py`, `src/phdsim/evaluation/semantic_terrain.py`, `src/phdsim/experiments/scout/semantic_fusion.py`, focused fusion tests |
| Coverage planning | Fixed sweep optimized over route orientation, direction, split and assignments | `src/phdsim/planning/coverage_sweep.py`, focused coverage tests |
| Replay viewer | Local browser interface with a map, robot paths and a time control | `apps/scout-viewer/` |

Active implementation chats:

- [SCOUT — Teren i sensory](codex://threads/01a1faec-9fce-7ef3-86ff-941bf423f516)
- [SCOUT — Segmentacja i fuzja](codex://threads/01a1faec-b035-7fe1-84c5-49de831ac4c7)
- [SCOUT — Bazowe planowanie pokrycia](codex://threads/01a1faec-c134-70c2-b962-28f8592b0bbd)
- [SCOUT — Wizualizator misji](codex://threads/01a1faec-cd8c-7781-b625-224f39c542e8)

## Boundary for the first semantic sensor and fusion tests

Python modules may use internal types suited to their roles. For the first
handoff, agree on an ordinary row-major 2D grid with explicit dimensions and
metres per cell. Each captured observation has an observation ID, sensor ID,
modality and capture tick. Valid sample records refer to grid cells `[x, y]`.
RGB samples use three normalized channels. LiDAR samples supply a measured
surface elevation in metres, with absent returns represented by absent samples.
Derive local geometric features from available observations. Reserve true
classes and true physical fields for the generator and offline evaluation.
Fusion can use structural test fixtures until real sensor output arrives.
Document fields and units of any export in the terrain or fusion handoff.

The coverage workstream can develop against a rectangular grid with explicit
candidate poses, footprints and robot travel and per-capture costs. It does
not need the reference class map or learned predictions. Its output must be
an inspectable schedule with per-robot ordered captures and timings.

## Browser replay contract

The UI is a separate local reader of saved mission replays. The shared shape
is an export interface independent of the simulator's internal types.

```text
schema    "scout-replay-v1"
title     Human-readable mission title
grid      {width, height, cell_size_m}
agents    [{id, label, start_xy}]
layers    [{id, label, kind, unit?, domain?, categories?}]
reference_layers  Optional {layer_id: flat values} for explicit offline comparison
frames    [{tick, layers, agents, completed, scheduled, messages?}]
```

- Grid layers are flat arrays indexed `y * width + x` with the origin in the
  upper left. `kind` is `scalar` or `categorical`. Null means unresolved or
  unavailable. Scalar layers may declare `domain: [min, max]`. Categorical
  layers may declare `categories: [{id, label}]`.
- A frame's `layers` is a map from declared layer ID to flat values. Optional
  `reference_layers` should be hidden by default. A layer can be absent in
  one mission and present in another.
- A frame's `agents` is `[{id, xy}]`, using the most recent completed sensor
  pose. `completed` lists captures completed at this tick. `scheduled` lists
  active tasks after this tick's assignments, including previous commitments.
  Task records use `{agent_id, mode, xy, footprint, start_tick, finish_tick}`.
  `footprint` is `[x, y, width, height]` in grid-cell units. Poses use the same
  units with fractional coordinates allowed. Show the arrow to the assigned
  pose as a plan rather than a recorded real-time robot position.
- Optional `messages` will carry traffic data when a simulator models it.
  An absent message stream means unmodeled, not a zero-byte mission.

The initial demo at `runs/scout-visualizer-demo/mission.json` is from the
runnable elevation simulator, with 27 snapshots from adaptive mission seed 2021.
The integrated semantic replay is at `runs/scout-semantic-demo/mission.json`.
It includes class estimates from RGB, LiDAR and their fusion using simulated
sensor returns recorded along a fixed two-drone sweep and two local rover
checks. The [viewer](../apps/scout-viewer/README.md) loads both examples and
packages them into a standalone offline HTML file.

## Integrated checkpoint

All four working chats completed their verification after the restart. The
coordinating chat connected their saved components and repaired the floating
point budget boundary found by the coverage check. On three held-out scenes,
the correct fraction of the full map averaged 62.35% for RGB and 65.51% for
fusion. LiDAR was available only on part of the plot. On paired support the
better individual sensor varied by scene. The first demo uses simple,
uncalibrated classification and a fixed schedule. Semantic replanning and
constrained communication remain future experiments.

The focused Python suite passed 65 tests. An offline JavaScript smoke check
exercised both examples, forward and backward steps, playback, map layers
and the reference toggle. Browser tool policy blocked direct verification of
the local file URL.
