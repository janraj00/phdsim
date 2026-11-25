# SCOUT mission viewer

The browser viewer reads saved `scout-replay-v1` missions. It shows estimated
terrain layers, optional offline reference layers, the last confirmed robot
positions and the planned destinations. Semantic replays include the modeled
drone position, altitude and flight or measurement stage each second. The time
control advances one tick at a time. Between recorded events it holds the last
recorded map and positions without repeating completed measurements. Imported
fractional timestamps retain their recorded steps. The viewer can open another
JSON file directly from disk.

## Generate a terrain map from JSON

From the checkout root, run the following command with Python 3.11 or newer.

```sh
PYTHONPATH=src python3.11 -m phdsim.cli scout-map --config configs/scout/map.json
```

Use **Otwórz JSON** in the viewer and select `runs/scout-map/map.json`. The
first layer is the generated class map. The other two show ground and surface
elevation in metres. This static preview has one frame and no robot activity.
Rerunning the command replaces the output. Use `--output PATH` to keep variants.

Edit `width`, `height` (cells), `cell_size_m`, `seed` and `shares_pct` in
the example. A share is a percentage of the total plot area. Omitted materials
have zero share. Percentages must sum to 100. Fractional cell counts are
rounded down, then the remaining cells go to the largest fractional parts.
Ties follow material order in the profile. The output records the resulting
counts under `terrain.cell_counts`.

The `type` field selects `profiles/<type>.json` next to the input file.
To add a `space` type, copy `profiles/agri.json` to `profiles/space.json`,
define its materials (for example regolith and bedrock), and set `type` and
`shares_pct` accordingly. Each material has one or more appearance and relief
variants with normalized `rgb`, mean height above ground (`height_m`), and
height standard deviation (`roughness_m`). All types use the same patch and
topography generator.

From the SCOUT checkout, generate a semantic replay and start the local server.
Use Python 3.11 or newer and generate the replay into a fresh directory.

```sh
PYTHONPATH=src python3 -m phdsim.experiments.scout.semantic_mission \
  --output runs/scout-semantic-demo
python3 apps/scout-viewer/serve.py --port 8766
```

Open `http://localhost:8766/` in a browser to see the fused class map (Mapa klas
terenu). Select Mapa wysokości to switch demos if the elevation replay is
available at `runs/scout-visualizer-demo/mission.json`. Both the server and the
offline builder accept `--mission` and `--semantic` to select specific exports.
For an offline copy, run `python3 apps/scout-viewer/build.py --output
runs/scout-viewer/scout.html` and open it directly in a browser with JavaScript
enabled.

The first semantic demo uses a synthetic terrestrial field, a fixed sweep
for two drones and two scheduled LiDAR observations from a rover. The
classifier compares RGB, LiDAR and fused estimates on the same collected
evidence. The communication panel reports that transport is unmodeled.
