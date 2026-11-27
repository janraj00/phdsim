# PHDSIM research handoff — SCOUT semantic branch

Updated: **2026-11-27** (branch `scout`).

> Earlier October PST900/UrbanIng work and November corridors/elevation pilots were removed from branch `scout` after commit `2f3dc96` to keep the active research branch lean (58 tracked files, Python 3.11+ stdlib only). Full history remains available in Git at `2f3dc96`.

## Frozen project anchors

1. **Task & fleet:** Multi-agent semantic terrain mapping (24 × 18 grid, 0.5 m cells, seeded Earth-analogue profiles) with 2 RGB quadcopters (X500) and 2 LiDAR ground rovers.
2. **Plug-in perception:** `SemanticEstimator` black-box protocol in `src/phdsim/belief/semantic_terrain.py`, with `JointGMMClassifier(K=3)` in `src/phdsim/belief/semantic_gmm.py` (exact RGB/LiDAR/fused marginalization, fitted strictly on `seeds.fit`).
3. **Minimal benchmark CLI:** `phdsim scout-bench` (`src/phdsim/cli/scout_bench.py`, `bench_config.py`, `bench_runner.py`, starter config `configs/scout/bench_2uav_2ugv.json`) with disjoint `fit` / `cal` / `test` splits and no network/queue simulation by design.
4. **Frozen visualizer:** `apps/scout-studio/` for `scout-replay-v1` replays.

## Latest verified pilot results (30 held-out seeds `2001–2030`)

Fitted on `seeds.fit` (`11–30`), VoI calibrated on `seeds.cal` (`101–120`), evaluated on `seeds.test` (`2001–2030`) with `JointGMMClassifier(K=3)`. These are synthetic pilot results, not confirmed research novelty.

| Variant | Policy | Mean accuracy | Delta vs RGB | Mean rover visits | Mean rover energy | Mean ticks |
|---|---|---:|---:|---:|---:|---:|
| `rgb_only` | `rgb_only` | 73.01% | — | 0.00 | 0.00 | 33.0 |
| `selective_voi_10` | `selective_rovers_voi` (gain ≥ 1.0) | 79.65% | +6.64 pp | 5.63 | 16.67 | 41.5 |
| `selective_voi_05` | `selective_rovers_voi` (gain ≥ 0.5) | 80.21% | +7.20 pp | 6.40 | 18.47 | 42.7 |
| `selective_entropy` | `selective_rovers_entropy` (H ≥ 0.6) | 82.31% | +9.30 pp | 12.47 | 30.86 | 55.3 |
| `full_ground` | `full_ground_sweep` | 81.84% | +8.83 pp | 20.00 | 38.44 | 57.0 |

### Key diagnostic takeaway
- At matched budget (~6 rover visits, ~18 energy), offline-calibrated `selective_voi_05` achieves **80.21%** versus **78.27%** for `selective_rovers_entropy` at threshold `0.8` (**+1.94 pp** at matched cost), and cuts rover visits by 49% / mission time by 12.6 ticks relative to `selective_entropy` (`0.6`).
- However, static offline-only VoI calibration averages across calibration fields and assigns negative mean gain (`-0.08`) to `low_vegetation vs exposed_soil`, causing it to skip brown patches entirely and trail `selective_entropy` (`0.6`) by ~2.1 pp when double the ground budget is available.

## Candidate next directions
1. **Offline prior + online VoI adaptation (without ground truth):** Update per-pair VoI estimates online during a mission using observable cross-modal shifts (e.g. `KL(P_fused || P_rgb)`, entropy reduction, or label flips) and evaluate under terrain/illumination domain shift.
2. **Cross-modal adaptation from rovers to aerial map:** Propagate confirmed LiDAR+RGB rover observations to visually similar unvisited RGB cells on the same plot.
3. **Adaptive drone altitude (6 m / 2 m) + 2 rovers:** Extend active acquisition beyond ground dispatch to aerial standoff selection.
