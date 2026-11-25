# SCOUT Mission Studio

Interactive 2D + 3D WebGL2 mission visualizer and analytics studio for `scout-replay-v1` recordings, built with zero external runtime dependencies. Lives alongside the minimal `apps/scout-viewer/` without modifying it.

## Features

- **Hybrid 2D + 3D Viewport**:
  - **3D WebGL2 Terrain & Fleet**: Textured 3D terrain mesh driven by elevation layers (`elevation_m`, `surface`, `ground`) or semantic relief, with a diorama pedestal, orbit/pan/zoom camera presets, 3D quadcopter (X500) and 6-wheel rover models, elevated flight trajectories, altitude drop tethers, volumetric translucent sensor frustums, and projected HUD labels.
  - **2D Tactical Map**: HiDPI pan/zoom canvas with custom oriented robot silhouettes, animated measurement scan sweeps, tapered trails, metric axis ticks, and hover cell inspection.
- **Reference Comparison**: Switch between **Estymacja**, **Referencja**, draggable **Kurtyna** (split-screen in both 2D and 3D), **Błędy** (categorical match/mismatch or scalar error heatmap), plus an optional **Niepewność** overlay.
- **Smooth Playback & Analytics Dock**: Continuous-time motion interpolation between frames (toggleable), interactive per-robot **Gantt** task timeline (flight vs. measurement phases), and live **Coverage**, **Quality / Reference**, and **Altitude Profile** charts with click-and-drag time scrubbing.
- **Automatic Run Discovery & Offline Export**: The local server automatically scans `runs/` for all `scout-replay-v1` JSON files, and `build.py` bundles the entire studio plus selected missions into a single standalone offline HTML file.

## Usage

Start the local server from the repository root (Python 3.11+):

```sh
python3 apps/scout-studio/serve.py --port 8768
```

Open `http://127.0.0.1:8768/` in a browser. You can switch among all discovered missions in `runs/`, click **Otwórz JSON**, or drag and drop any `scout-replay-v1` JSON file onto the window.

### Build a standalone offline HTML bundle

```sh
python3 apps/scout-studio/build.py --output runs/scout-studio/studio.html
```

Or pick specific mission JSON files:

```sh
python3 apps/scout-studio/build.py \
  --output runs/scout-studio/x500-demo.html \
  --mission runs/scout-semantic-x500/mission.json \
  --mission runs/scout-visualizer-demo/mission.json
```

### Tests

```sh
node --test apps/scout-studio/tests/replay.test.mjs
```
