"""JSON configuration loader and schema validation for SCOUT semantic benchmarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any

from phdsim.environments.semantic_terrain import SurfaceProfile, TerrainClass, TerrainConfig


_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_PROFILES_DIR = Path(__file__).resolve().parents[4] / "configs" / "scout" / "profiles"


@dataclass(frozen=True)
class TerrainSpec:
    profile: str = "default"
    width: int = 24
    height: int = 18
    cell_size_m: float = 0.5
    patches_per_class: int = 3
    shares_pct: dict[str, float] | None = None
    shade_box: tuple[int, int, int, int] | None = (2, 2, 5, 4)

    def to_terrain_config(self, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> TerrainConfig:
        if self.profile == "default":
            if self.shares_pct is not None:
                default_cfg = TerrainConfig(width=self.width, height=self.height, cell_size_m=self.cell_size_m)
                names = {c.name for c in default_cfg.classes}
                unknown = set(self.shares_pct) - names
                if unknown:
                    raise ValueError(f"unknown class names in shares_pct: {sorted(unknown)}")
                shares = tuple(self.shares_pct.get(c.name, 0) for c in default_cfg.classes)
                return TerrainConfig(
                    width=self.width,
                    height=self.height,
                    cell_size_m=self.cell_size_m,
                    patches_per_class=self.patches_per_class,
                    shares_pct=shares,
                )
            return TerrainConfig(
                width=self.width,
                height=self.height,
                cell_size_m=self.cell_size_m,
                patches_per_class=self.patches_per_class,
            )

        if not _SLUG_RE.fullmatch(self.profile):
            raise ValueError(f"invalid terrain profile name: {self.profile!r}")
        profile_path = profiles_dir / f"{self.profile}.json"
        if not profile_path.is_file():
            raise ValueError(f"terrain profile not found: {profile_path}")
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw:
            raise ValueError(f"{profile_path}: expected a nonempty JSON object")
        classes = []
        for name, entries in raw.items():
            if not isinstance(entries, list) or not entries:
                raise ValueError(f"{name}: expected a nonempty list of surface profiles")
            surfaces = []
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"rgb", "height_m", "roughness_m"}:
                    raise ValueError(f"{name}: each surface needs rgb, height_m and roughness_m")
                surfaces.append(SurfaceProfile(tuple(entry["rgb"]), entry["height_m"], entry["roughness_m"]))
            classes.append(TerrainClass(name, tuple(surfaces)))
        class_tuple = tuple(classes)
        shares_tuple = None
        if self.shares_pct is not None:
            unknown = set(self.shares_pct) - {c.name for c in class_tuple}
            if unknown:
                raise ValueError(f"shares_pct names unknown classes for {self.profile!r}: {sorted(unknown)}")
            shares_tuple = tuple(self.shares_pct.get(c.name, 0) for c in class_tuple)
        return TerrainConfig(
            width=self.width,
            height=self.height,
            cell_size_m=self.cell_size_m,
            patches_per_class=self.patches_per_class,
            classes=class_tuple,
            shares_pct=shares_tuple,
        )

    def occluded_cells(self) -> frozenset[tuple[int, int]]:
        if self.shade_box is None:
            return frozenset()
        x0, y0, x1, y1 = self.shade_box
        return frozenset(
            (x, y)
            for x in range(max(0, x0), min(self.width, x1))
            for y in range(max(0, y0), min(self.height, y1))
        )


@dataclass(frozen=True)
class SeedsSpec:
    fit: tuple[int, ...] = tuple(range(11, 31))
    cal: tuple[int, ...] = ()
    test: tuple[int, ...] = (2021, 2022, 2023)

    def __post_init__(self):
        if not self.fit or not self.test:
            raise ValueError("seeds.fit and seeds.test must be nonempty")
        for split_name, values in (("fit", self.fit), ("cal", self.cal), ("test", self.test)):
            if any(type(v) is not int for v in values):
                raise ValueError(f"seeds.{split_name} must contain integers")
            if len(set(values)) != len(values):
                raise ValueError(f"seeds.{split_name} must contain unique values")
        combined = (*self.fit, *self.cal, *self.test)
        if len(set(combined)) != len(combined):
            raise ValueError("fit, cal and test seed splits must be pairwise disjoint")


@dataclass(frozen=True)
class ClassifierSpec:
    type: str = "gmm"
    params: dict[str, Any] = field(default_factory=lambda: {"n_components": 3})


@dataclass(frozen=True)
class FleetSpec:
    drone_fov_deg: float = 60.0
    initial_altitude_m: float = 3.0
    drone_energy_budget: float = 65.0
    rover_speed_m_per_tick: float = 0.7
    rover_energy_budget: float = 65.0
    rover_footprint: tuple[int, int] = (5, 5)

    def __post_init__(self):
        if not (0.0 < self.drone_fov_deg < 180.0):
            raise ValueError("fleet.drone_fov_deg must be in (0, 180)")
        if not isfinite(self.initial_altitude_m) or self.initial_altitude_m <= 0.0:
            raise ValueError("fleet.initial_altitude_m must be positive")
        if not isfinite(self.drone_energy_budget) or self.drone_energy_budget <= 0.0:
            raise ValueError("fleet.drone_energy_budget must be positive")
        if not isfinite(self.rover_speed_m_per_tick) or self.rover_speed_m_per_tick <= 0.0:
            raise ValueError("fleet.rover_speed_m_per_tick must be positive")
        if not isfinite(self.rover_energy_budget) or self.rover_energy_budget <= 0.0:
            raise ValueError("fleet.rover_energy_budget must be positive")
        if len(self.rover_footprint) != 2 or any(type(n) is not int or n < 1 for n in self.rover_footprint):
            raise ValueError("fleet.rover_footprint must be two positive integers")


@dataclass(frozen=True)
class VariantSpec:
    name: str
    label: str
    policy: str
    policy_params: dict[str, Any] = field(default_factory=dict)
    classifier: ClassifierSpec | None = None

    def __post_init__(self):
        if not _SLUG_RE.fullmatch(self.name):
            raise ValueError(f"variant name {self.name!r} must use letters, digits, underscores or hyphens")
        if not self.label.strip():
            raise ValueError(f"variant {self.name!r} needs a non-empty label")


@dataclass(frozen=True)
class BenchConfig:
    name: str
    description: str
    terrain: TerrainSpec
    seeds: SeedsSpec
    classifier: ClassifierSpec
    fleet: FleetSpec
    variants: tuple[VariantSpec, ...]
    save_replays_for_seeds: tuple[int, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _expand_seeds(value: Any, field_name: str) -> tuple[int, ...]:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict) and set(value) == {"start", "count"}:
        start, count = value["start"], value["count"]
        if type(start) is not int or type(count) is not int or count < 0:
            raise ValueError(f"{field_name}: start must be int and count must be nonnegative int")
        return tuple(range(start, start + count))
    raise ValueError(f"{field_name}: expected a list of ints or {{'start': int, 'count': int}}")


def _parse_classifier(raw: dict | None, default: ClassifierSpec | None = None) -> ClassifierSpec:
    if raw is None:
        return default or ClassifierSpec()
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        raise ValueError("classifier must be an object with a string 'type'")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("classifier.params must be an object")
    return ClassifierSpec(type=raw["type"], params=dict(params))


def parse_bench_config(raw: dict) -> BenchConfig:
    if not isinstance(raw, dict):
        raise ValueError("benchmark config must be a JSON object")
    name = str(raw.get("name", "scout-bench")).strip()
    if not name or not _SLUG_RE.fullmatch(name):
        raise ValueError("config 'name' must use letters, digits, underscores or hyphens")
    description = str(raw.get("description", ""))

    t_raw = raw.get("terrain", {})
    if not isinstance(t_raw, dict):
        raise ValueError("terrain must be a JSON object")
    shade_raw = t_raw.get("shade_box", [2, 2, 5, 4])
    shade_box = None if shade_raw is None else tuple(shade_raw)
    if shade_box is not None and (len(shade_box) != 4 or any(type(v) is not int for v in shade_box)):
        raise ValueError("terrain.shade_box must be null or 4 integers [x0, y0, x1, y1]")
    terrain = TerrainSpec(
        profile=t_raw.get("profile", "default"),
        width=t_raw.get("width", 24),
        height=t_raw.get("height", 18),
        cell_size_m=t_raw.get("cell_size_m", 0.5),
        patches_per_class=t_raw.get("patches_per_class", 3),
        shares_pct=t_raw.get("shares_pct"),
        shade_box=shade_box,
    )

    s_raw = raw.get("seeds", {})
    if not isinstance(s_raw, dict):
        raise ValueError("seeds must be a JSON object")
    seeds = SeedsSpec(
        fit=_expand_seeds(s_raw.get("fit", {"start": 11, "count": 20}), "seeds.fit"),
        cal=_expand_seeds(s_raw.get("cal", []), "seeds.cal"),
        test=_expand_seeds(s_raw.get("test", [2021, 2022, 2023]), "seeds.test"),
    )

    classifier = _parse_classifier(raw.get("classifier"))

    f_raw = raw.get("fleet", {})
    if not isinstance(f_raw, dict):
        raise ValueError("fleet must be a JSON object")
    fp = f_raw.get("rover_footprint", [5, 5])
    fleet = FleetSpec(
        drone_fov_deg=f_raw.get("drone_fov_deg", 60.0),
        initial_altitude_m=f_raw.get("initial_altitude_m", 3.0),
        drone_energy_budget=f_raw.get("drone_energy_budget", 65.0),
        rover_speed_m_per_tick=f_raw.get("rover_speed_m_per_tick", 0.7),
        rover_energy_budget=f_raw.get("rover_energy_budget", 65.0),
        rover_footprint=(fp[0], fp[1]),
    )

    v_raw = raw.get("variants")
    if not isinstance(v_raw, list) or not v_raw:
        raise ValueError("variants must be a nonempty list of variant definitions")
    variants: list[VariantSpec] = []
    seen_names: set[str] = set()
    for item in v_raw:
        if not isinstance(item, dict):
            raise ValueError("each variant must be a JSON object")
        v_name = item.get("name", "")
        if v_name in seen_names:
            raise ValueError(f"duplicate variant name: {v_name!r}")
        seen_names.add(v_name)
        v_clf = _parse_classifier(item.get("classifier"), None) if "classifier" in item else None
        params = item.get("policy_params", {})
        if not isinstance(params, dict):
            raise ValueError(f"variant {v_name!r}: policy_params must be a JSON object")
        variants.append(
            VariantSpec(
                name=v_name,
                label=item.get("label", v_name),
                policy=item.get("policy", ""),
                policy_params=dict(params),
                classifier=v_clf,
            )
        )

    save_raw = raw.get("save_replays_for_seeds", [seeds.test[0]])
    if isinstance(save_raw, int) and not isinstance(save_raw, bool):
        save_replays = tuple(seeds.test[:max(0, save_raw)])
    elif isinstance(save_raw, list):
        if any(type(s) is not int or s not in seeds.test for s in save_raw):
            raise ValueError("save_replays_for_seeds must contain test seeds")
        save_replays = tuple(dict.fromkeys(save_raw))
    else:
        raise ValueError("save_replays_for_seeds must be an integer count or a list of test seeds")

    return BenchConfig(
        name=name,
        description=description,
        terrain=terrain,
        seeds=seeds,
        classifier=classifier,
        fleet=fleet,
        variants=tuple(variants),
        save_replays_for_seeds=save_replays,
    )


def load_bench_config(path: Path) -> BenchConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_bench_config(data)


def list_terrain_profiles(profiles_dir: Path = DEFAULT_PROFILES_DIR) -> list[str]:
    profiles = ["default"]
    if profiles_dir.is_dir():
        for path in sorted(profiles_dir.glob("*.json")):
            profiles.append(path.stem)
    return profiles
