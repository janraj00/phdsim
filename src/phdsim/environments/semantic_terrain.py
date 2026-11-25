"""Seeded synthetic soil, rock and vegetation plots for offline mapping studies.

All rasters are indexed [y][x], with x increasing right and y down. Elevations
share a local vertical datum. Only PhysicalFields enter the sensor functions.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import cos, isfinite, sin

from phdsim.core.randomness import keyed_rng


RGB = tuple[float, float, float]
HeightGrid = tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class SurfaceProfile:
    """A material state with mean RGB reflectance and above-ground relief."""

    rgb: RGB
    height_m: float
    roughness_m: float

    def __post_init__(self):
        if len(self.rgb) != 3 or not all(0 <= channel <= 1 for channel in self.rgb):
            raise ValueError("rgb must contain three normalized reflectances")
        if not all(isfinite(v) and v >= 0 for v in (self.height_m, self.roughness_m)):
            raise ValueError("height and roughness must be finite and nonnegative")


@dataclass(frozen=True)
class TerrainClass:
    name: str
    profiles: tuple[SurfaceProfile, ...]

    def __post_init__(self):
        if not self.name.strip() or not self.profiles:
            raise ValueError("each terrain class needs a name and material profiles")


_DRY_RGB = (0.48, 0.39, 0.27)
_FLAT_BROWN = SurfaceProfile(_DRY_RGB, 0.012, 0.008)
_DEFAULT_CLASSES = (
    TerrainClass("exposed_soil", (
        _FLAT_BROWN, SurfaceProfile((0.53, 0.29, 0.20), 0.014, 0.01),
        SurfaceProfile((0.32, 0.28, 0.23), 0.024, 0.015),
    )),
    TerrainClass("rock", (
        SurfaceProfile((0.47, 0.46, 0.45), 0.24, 0.13),
        SurfaceProfile((0.64, 0.61, 0.55), 0.018, 0.009),
        SurfaceProfile((0.32, 0.28, 0.23), 0.25, 0.15),
    )),
    TerrainClass("low_vegetation", (
        SurfaceProfile((0.25, 0.45, 0.21), 0.11, 0.06),
        SurfaceProfile(_DRY_RGB, 0.16, 0.09), _FLAT_BROWN,
    )),
)


@dataclass(frozen=True)
class TerrainConfig:
    width: int = 24
    height: int = 18
    cell_size_m: float = 0.5
    patches_per_class: int = 3
    classes: tuple[TerrainClass, ...] = _DEFAULT_CLASSES
    shares_pct: tuple[float, ...] | None = None

    def __post_init__(self):
        if not all(type(n) is int and n > 0 for n in
                   (self.width, self.height, self.patches_per_class)):
            raise ValueError("grid dimensions and patch count must be positive integers")
        if not isfinite(self.cell_size_m) or self.cell_size_m <= 0:
            raise ValueError("cell_size_m must be positive and finite")
        if not self.classes or len({c.name for c in self.classes}) != len(self.classes):
            raise ValueError("configure at least one terrain class and use distinct names")
        if self.shares_pct is not None:
            if len(self.shares_pct) != len(self.classes) or not all(
                type(v) in (int, float) and 0 <= v <= 100 for v in self.shares_pct
            ):
                raise ValueError("provide one percentage from 0 to 100 per terrain class")
            if sum(Fraction(str(v)) for v in self.shares_pct) != 100:
                raise ValueError("terrain percentages must sum to 100")
        elif self.width * self.height < self.patches_per_class * len(self.classes):
            raise ValueError("each patch needs at least one grid cell")


@dataclass(frozen=True)
class PhysicalFields:
    width: int
    height: int
    cell_size_m: float
    ground_m: HeightGrid
    surface_m: HeightGrid
    reflectance: tuple[tuple[RGB, ...], ...]


@dataclass(frozen=True)
class SemanticTerrain:
    fields: PhysicalFields
    class_names: tuple[str, ...]
    labels: tuple[tuple[int, ...], ...]


def _cell_counts(config):
    total = config.width * config.height
    quotas = [total * Fraction(str(v)) / 100 for v in config.shares_pct]
    counts = [int(q) for q in quotas]
    order = sorted(range(len(quotas)), key=lambda i: quotas[i] - counts[i], reverse=True)
    for i in order[:total - sum(counts)]:
        counts[i] += 1
    return counts


def _material_grid(config, rng):
    """Choose the same material for the class label, reflectance and relief of a cell."""
    total = config.width * config.height

    def sites_for(label, indices):
        profiles = list(config.classes[label].profiles)
        rng.shuffle(profiles)
        return [(idx % config.width, idx // config.width, label, profiles[i % len(profiles)],
                 rng.uniform(0.9, 1.1)) for i, idx in enumerate(indices)]

    def closest(index, sites):
        y, x = divmod(index, config.width)
        return min(sites, key=lambda s: (x - s[0]) ** 2 + (y - s[1]) ** 2)

    if config.shares_pct is None:
        # Preserve the original unweighted Voronoi benchmark and RNG sequence.
        n = config.patches_per_class
        indices = rng.sample(range(total), n * len(config.classes))
        sites = [s for i in range(len(config.classes)) for s in sites_for(i, indices[i*n:(i+1)*n])]
        return [closest(index, sites) for index in range(total)]

    # Allocate smaller classes first so a rare material gets a compact patch.
    # Each class grows around seeds drawn from the cells still free.
    counts = _cell_counts(config)
    result = [None] * total
    remaining = list(range(total))
    for label in sorted(range(len(counts)), key=counts.__getitem__):
        count = counts[label]
        if not count:
            continue
        seeds = rng.sample(remaining, min(config.patches_per_class, count))
        sites = sites_for(label, seeds)
        candidates = []
        for index in remaining:
            site = closest(index, sites)
            y, x = divmod(index, config.width)
            candidates.append(((x - site[0]) ** 2 + (y - site[1]) ** 2, index, site))
        if count < len(candidates):
            candidates.sort()
        for _, index, site in candidates[:count]:
            result[index] = site
        remaining = [index for _, index, _ in candidates[count:]]
    return result


def generate_terrain(seed: int, config: TerrainConfig = TerrainConfig()) -> SemanticTerrain:
    """Grow patches on a smooth plot, optionally allocating exact whole-cell class quotas."""
    materials = _material_grid(config, keyed_rng(seed, "semantic patches"))
    ground_rng = keyed_rng(seed, "semantic topography")
    texture = keyed_rng(seed, "semantic texture")

    phase_x, phase_y = ground_rng.uniform(-3, 3), ground_rng.uniform(-3, 3)
    slope = ground_rng.uniform(-0.035, 0.035)
    labels, ground, surface, reflectance = [], [], [], []
    for y in range(config.height):
        label_row, ground_row, surface_row, rgb_row = [], [], [], []
        for x in range(config.width):
            _, _, label, profile, tone = materials[y * config.width + x]
            xm, ym = x * config.cell_size_m, y * config.cell_size_m
            base = slope * xm + 0.25 * sin(xm / 4 + phase_x) + 0.18 * cos(ym / 3 + phase_y)
            relief = max(0.0, texture.gauss(profile.height_m, profile.roughness_m))
            brightness = tone + texture.gauss(0, 0.045)
            rgb = tuple(min(1., max(0., v * brightness + texture.gauss(0, 0.011)))
                        for v in profile.rgb)
            label_row.append(label)
            ground_row.append(base)
            surface_row.append(base + relief)
            rgb_row.append(rgb)
        labels.append(tuple(label_row))
        ground.append(tuple(ground_row))
        surface.append(tuple(surface_row))
        reflectance.append(tuple(rgb_row))
    fields = PhysicalFields(config.width, config.height, config.cell_size_m,
                            tuple(ground), tuple(surface), tuple(reflectance))
    return SemanticTerrain(fields, tuple(c.name for c in config.classes), tuple(labels))
