"""Generate an offline terrain map for SCOUT Viewer from a JSON configuration."""

from argparse import ArgumentParser
from collections import Counter
import json
from math import isfinite
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from phdsim.environments.semantic_terrain import SurfaceProfile, TerrainClass, TerrainConfig, generate_terrain


def _read_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _classes(profile):
    classes = []
    for name, profiles in profile.items():
        if not isinstance(profiles, list):
            raise ValueError(f"{name}: expected a list of surface profiles")
        surfaces = []
        for p in profiles:
            if not isinstance(p, dict) or set(p) != {"rgb", "height_m", "roughness_m"}:
                raise ValueError(f"{name}: each surface needs rgb, height_m and roughness_m")
            if not isinstance(p["rgb"], list) or not all(
                type(v) in (int, float) for v in (*p["rgb"], p["height_m"], p["roughness_m"])
            ):
                raise ValueError(f"{name}: material parameters must be numeric")
            surfaces.append(SurfaceProfile(tuple(p["rgb"]), p["height_m"], p["roughness_m"]))
        classes.append(TerrainClass(name, tuple(surfaces)))
    return tuple(classes)


def load_config(path):
    spec = _read_object(path)
    required = {"type", "width", "height", "cell_size_m", "seed", "shares_pct"}
    if set(spec) != required:
        raise ValueError(f"map config requires these fields: {', '.join(sorted(required))}")
    kind = spec["type"]
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", kind):
        raise ValueError("type must be a profile name using letters, digits, underscores or hyphens")
    if type(spec["seed"]) is not int:
        raise ValueError("seed must be an integer")
    if type(spec["cell_size_m"]) not in (int, float) or not isfinite(spec["cell_size_m"]):
        raise ValueError("cell_size_m must be a finite number")
    profile_path = path.parent / "profiles" / f"{kind}.json"
    profile = _read_object(profile_path)
    shares = spec["shares_pct"]
    if not isinstance(shares, dict) or set(shares) - set(profile):
        raise ValueError(f"shares_pct must name materials from {profile_path}")
    classes = _classes(profile)
    config = TerrainConfig(width=spec["width"], height=spec["height"], cell_size_m=spec["cell_size_m"],
                           classes=classes, shares_pct=tuple(shares.get(c.name, 0) for c in classes))
    return kind, spec["seed"], config, profile_path


def make_replay(kind, seed, config):
    terrain = generate_terrain(seed, config)
    classes = [label for row in terrain.labels for label in row]
    counts = Counter(classes)
    categories = [{"id": i, "label": name.replace("_", " ")} for i, name in enumerate(terrain.class_names)]
    return {
        "schema": "scout-replay-v1", "title": f"SCOUT · {kind} · mapa terenu · seed {seed}",
        "grid": {"width": config.width, "height": config.height, "cell_size_m": config.cell_size_m},
        "terrain": {"type": kind, "seed": seed, "shares_pct": dict(zip(terrain.class_names, config.shares_pct)),
                    "cell_counts": {name: counts[i] for i, name in enumerate(terrain.class_names)}},
        "agents": [],
        "layers": [{"id": "terrain", "label": "Klasy terenu", "kind": "categorical", "categories": categories},
                   {"id": "ground", "label": "Wysokość gruntu", "kind": "scalar", "unit": "m"},
                   {"id": "surface", "label": "Wysokość powierzchni", "kind": "scalar", "unit": "m"}],
        "frames": [{"tick": 0, "agents": [], "scheduled": [], "completed": [], "layers": {
            "terrain": classes, "ground": [z for row in terrain.fields.ground_m for z in row],
            "surface": [z for row in terrain.fields.surface_m for z in row],
        }}],
    }


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("runs/scout-map/map.json"))
    args = parser.parse_args(argv)
    try:
        kind, seed, config, profile = load_config(args.config)
        if args.output.resolve() in (args.config.resolve(), profile.resolve()):
            raise ValueError("choose an output file distinct from the config and profile")
        replay = make_replay(kind, seed, config)
        data = json.dumps(replay, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as fp:
            temp = Path(fp.name)
            try:
                fp.write(data + "\n")
                fp.close()
                temp.replace(args.output)
            finally:
                temp.unlink(missing_ok=True)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())
