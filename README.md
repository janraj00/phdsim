# PHDSIM — SCOUT Semantic Terrain Mapping Benchmark

Minimal, zero-dependency Python 3.11+ benchmark for multi-agent semantic terrain mapping and selective cross-modal information acquisition (**2× UAV RGB + 2× UGV LiDAR**).

> Earlier October PST900/UrbanIng code and November corridors/elevation prototypes were removed from branch `scout` to keep this branch focused and lean; full history remains intact in Git at commit `2f3dc96`.

## Quick start

Run the paired 2×UAV + 2×UGV benchmark (uses Python standard library only):

```bash
PYTHONPATH=src python3 -m phdsim.cli scout-bench \
  --config configs/scout/bench_2uav_2ugv.json \
  --output runs/scout-voi-30seeds
```

Quick 2-seed showcase with replays exported for SCOUT Studio:

```bash
PYTHONPATH=src python3 -m phdsim.cli scout-bench \
  --config configs/scout/bench_2uav_2ugv.json \
  --test-seeds 2004 2021 \
  --replay-seeds 2004 2021 \
  --output runs/scout-demo-showcase
```

List registered classifiers, acquisition policies and terrain profiles:

```bash
PYTHONPATH=src python3 -m phdsim.cli scout-bench --list-plugins
```

## Architecture

| Module | Responsibility |
|---|---|
| `src/phdsim/environments/semantic_terrain.py` | Seeded synthetic terrain generator and class profiles (`configs/scout/profiles/`). |
| `src/phdsim/sensors/semantic_terrain.py` | Aerial RGB and ground LiDAR observation models. |
| `src/phdsim/belief/semantic_terrain.py` | `SemanticEstimator` black-box protocol, multimodal cell belief and factorized baseline. |
| `src/phdsim/belief/semantic_gmm.py` | Plug-in `JointGMMClassifier` (diagonal EM GMM with exact RGB/LiDAR/fused marginalization). |
| `src/phdsim/planning/` | Fixed aerial sweep (`coverage_sweep.py`) and X500 trajectory timing (`x500_trajectory.py`). |
| `src/phdsim/decision/acquisition/` | Footprint helpers (`semantic.py`), entropy rover dispatch (`semantic_rover.py`), and model-agnostic cross-modal VoI dispatch (`semantic_voi.py`). |
| `src/phdsim/evaluation/semantic_terrain.py` | Offline ground-truth evaluation metrics. |
| `src/phdsim/experiments/scout/` | Mission simulator (`semantic_mission.py`), config/runner (`bench_config.py`, `bench_runner.py`), provenance (`provenance.py`). |
| `apps/scout-studio/` | Offline 2D/3D WebGL2 replay visualizer for `scout-replay-v1` JSON files. |

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -v
node --test apps/scout-studio/tests/replay.test.mjs
```

Generated runs belong under the git-ignored `runs/` directory. See [docs/CONTEXT.md](docs/CONTEXT.md) for current pilot findings and next research directions.
