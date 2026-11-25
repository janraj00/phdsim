"""Synthetic nadir captures on the plot's known grid. No pose error is modeled.

An observation exports JSON-native data with to_dict(). Footprint [x,y,w,h]
is clipped to the grid. Both masks are flat row-major arrays of length w*h.
visible_mask excludes occlusions; valid_mask identifies cells with a sample.
A blocked cell affects both modalities in a paired capture. Read noise and
LiDAR dropout use independent streams, conditional on the scene and pose.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import exp, floor, hypot, isfinite, radians, sqrt, tan

from phdsim.core.grid import Cell
from phdsim.core.randomness import keyed_rng
from phdsim.environments.semantic_terrain import (
    RGB, PhysicalFields, SemanticTerrain, TerrainConfig, generate_terrain,
)


@dataclass(frozen=True)
class CapturePose:
    """x and y in cell-centre coordinates, standoff above the local plot in metres."""

    x: float
    y: float
    standoff_m: float = 3.0

    def __post_init__(self):
        if not all(isfinite(v) for v in (self.x, self.y, self.standoff_m)) or self.standoff_m <= 0:
            raise ValueError("pose must be finite with positive standoff_m")


@dataclass(frozen=True)
class CaptureConditions:
    illumination: float = 1.0
    occluded_cells: frozenset[Cell] = frozenset()

    def __post_init__(self):
        if not isfinite(self.illumination) or self.illumination <= 0:
            raise ValueError("illumination must be positive and finite")


def _check_footprint(wh):
    if len(wh) != 2 or not all(type(n) is int and n > 0 for n in wh):
        raise ValueError("footprint_wh must contain two positive integers")


@dataclass(frozen=True)
class RGBConfig:
    footprint_wh: Cell = (7, 7)
    resolution_cells: int = 1
    read_noise: float = 0.018

    def __post_init__(self):
        _check_footprint(self.footprint_wh)
        if type(self.resolution_cells) is not int or self.resolution_cells <= 0:
            raise ValueError("resolution_cells must be a positive integer")
        if not isfinite(self.read_noise) or self.read_noise < 0:
            raise ValueError("read_noise must be finite and nonnegative")


@dataclass(frozen=True)
class LidarConfig:
    footprint_wh: Cell = (7, 7)
    return_probability: float = 0.85
    dropout_per_m: float = 0.035
    base_std_m: float = 0.008
    std_per_m: float = 0.004

    def __post_init__(self):
        _check_footprint(self.footprint_wh)
        if not 0 <= self.return_probability <= 1:
            raise ValueError("return_probability must be in [0,1]")
        if not all(isfinite(v) and v >= 0 for v in
                   (self.dropout_per_m, self.base_std_m, self.std_per_m)):
            raise ValueError("dropout and noise parameters must be finite and nonnegative")


@dataclass(frozen=True)
class RGBSample:
    xy: Cell
    rgb: RGB


@dataclass(frozen=True)
class LidarSample:
    xy: Cell
    surface_m: float


@dataclass(frozen=True)
class TerrainObservation:
    observation_id: str
    sensor_id: str
    modality: str
    capture_tick: int
    pose: CapturePose
    width: int
    height: int
    cell_size_m: float
    footprint: tuple[int, int, int, int]
    visible_mask: tuple[bool, ...]
    valid_mask: tuple[bool, ...]
    samples: tuple[RGBSample | LidarSample, ...]

    def to_dict(self) -> dict:
        samples = []
        for sample in self.samples:
            values = ({"rgb": list(sample.rgb)} if isinstance(sample, RGBSample)
                      else {"surface_m": sample.surface_m})
            samples.append({"xy": list(sample.xy), **values})
        return {
            "observation_id": self.observation_id, "sensor_id": self.sensor_id,
            "modality": self.modality, "capture_tick": self.capture_tick, "pose": asdict(self.pose),
            "grid": {"width": self.width, "height": self.height, "cell_size_m": self.cell_size_m},
            "footprint": list(self.footprint), "visible_mask": list(self.visible_mask),
            "valid_mask": list(self.valid_mask), "samples": samples,
        }


def nadir_footprint_side(standoff_m: float, fov_deg: float, cell_size_m: float) -> int:
    """Count cell centres within the projected width on a flat reference plane."""
    if not (isfinite(standoff_m) and standoff_m > 0 and 0 < fov_deg < 180
            and isfinite(cell_size_m) and cell_size_m > 0):
        raise ValueError("expected positive standoff and cell size, and FOV between 0 and 180 degrees")
    return 2 * floor(standoff_m * tan(radians(fov_deg / 2)) / cell_size_m) + 1


def footprint_bounds(width: int, height: int, pose: CapturePose, footprint_wh: Cell
                     ) -> tuple[tuple[int, int, int, int], Cell]:
    """Return the clipped measurement rectangle and the unclipped detector origin."""
    # Choose nearest centred cell window; half-cell ties round right/down.
    w, h = footprint_wh
    x = floor(pose.x - (w - 1) / 2 + 0.5)
    y = floor(pose.y - (h - 1) / 2 + 0.5)
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + w), min(height, y + h)
    if right <= left or bottom <= top:
        raise ValueError("footprint does not intersect terrain")
    return (left, top, right - left, bottom - top), (x, y)


def _support(fields, pose, footprint_wh, sensor_id, capture_tick):
    if type(capture_tick) is not int or capture_tick < 0 or not sensor_id:
        raise ValueError("capture requires a sensor ID and a nonnegative integer tick")
    rect, origin = footprint_bounds(fields.width, fields.height, pose, footprint_wh)
    left, top, w, h = rect
    cells = tuple((x, y) for y in range(top, top + h) for x in range(left, left + w))
    return rect, cells, origin


def _observation(fields, pose, seed, tick, sensor_id, modality, rect, cells, visible, samples):
    valid = {sample.xy for sample in samples}
    grid = (fields.width, fields.height, fields.cell_size_m)
    # Include the realized evidence so changed conditions cannot alias a
    # different payload. The seed itself is never included in the export.
    identity = (seed, sensor_id, modality, tick, pose, grid, rect, visible, samples)
    observation_id = sha256(repr(identity).encode()).hexdigest()
    return TerrainObservation(observation_id, sensor_id, modality, tick, pose, *grid, rect,
                              visible, tuple(cell in valid for cell in cells), tuple(samples))


def _slant_range(fields, pose, x, y):
    return hypot((x - pose.x) * fields.cell_size_m, (y - pose.y) * fields.cell_size_m,
                 pose.standoff_m)


def capture_rgb(fields: PhysicalFields, pose: CapturePose, *, seed: int, capture_tick: int,
                sensor_id: str = "rgb", config: RGBConfig = RGBConfig(),
                conditions: CaptureConditions = CaptureConditions()) -> TerrainObservation:
    """Average visible reflectance within each detector pixel, then expose and add read noise.

    At coarser resolution all visible cells within the same pixel share its
    measured colour. Range and low light increase normalized-channel noise.
    """
    rect, cells, origin = _support(fields, pose, config.footprint_wh, sensor_id, capture_tick)
    visible = tuple(cell not in conditions.occluded_cells for cell in cells)
    groups = {}
    for (x, y), seen in zip(cells, visible):
        if seen:
            pixel = ((x - origin[0]) // config.resolution_cells,
                     (y - origin[1]) // config.resolution_cells)
            groups.setdefault(pixel, []).append((x, y))

    measurements = {}
    for pixel, members in groups.items():
        rng = keyed_rng(seed, "semantic rgb", sensor_id, capture_tick, pose, pixel)
        count = len(members)
        distance = sum(_slant_range(fields, pose, x, y) for x, y in members) / count
        noise = config.read_noise * (1 + distance / 10) / sqrt(conditions.illumination)
        means = [sum(fields.reflectance[y][x][c] for x, y in members) / count for c in range(3)]
        rgb = tuple(min(1., max(0., v * conditions.illumination + rng.gauss(0, noise)))
                    for v in means)
        for cell in members:
            measurements[cell] = rgb
    samples = [RGBSample(cell, measurements[cell]) for cell in cells if cell in measurements]
    return _observation(fields, pose, seed, capture_tick, sensor_id, "rgb",
                        rect, cells, visible, samples)


def capture_lidar(fields: PhysicalFields, pose: CapturePose, *, seed: int, capture_tick: int,
                  sensor_id: str = "lidar", config: LidarConfig = LidarConfig(),
                  conditions: CaptureConditions = CaptureConditions()) -> TerrainObservation:
    """Return sparse surface elevations in metres. Range degrades precision and return rate."""
    rect, cells, _ = _support(fields, pose, config.footprint_wh, sensor_id, capture_tick)
    visible = tuple(cell not in conditions.occluded_cells for cell in cells)
    samples = []
    for (x, y), seen in zip(cells, visible):
        if not seen:
            continue
        distance = _slant_range(fields, pose, x, y)
        rng = keyed_rng(seed, "semantic lidar", sensor_id, capture_tick, pose, x, y)
        if rng.random() < config.return_probability * exp(-config.dropout_per_m * distance):
            std = config.base_std_m + config.std_per_m * distance
            samples.append(LidarSample((x, y), fields.surface_m[y][x] + rng.gauss(0, std)))
    return _observation(fields, pose, seed, capture_tick, sensor_id, "lidar",
                        rect, cells, visible, samples)


def sample_pair(seed: int = 42) -> tuple[SemanticTerrain, TerrainObservation, TerrainObservation]:
    """Recreate a 12x9 offline reference and two co-registered full-plot captures at tick 1."""
    terrain = generate_terrain(seed, TerrainConfig(width=12, height=9))
    pose = CapturePose(5.5, 4)
    conditions = CaptureConditions(occluded_cells=frozenset({(2, 2), (2, 3)}))
    args = dict(seed=seed, capture_tick=1, conditions=conditions)
    rgb = capture_rgb(terrain.fields, pose, config=RGBConfig(footprint_wh=(12, 9)), **args)
    lidar = capture_lidar(terrain.fields, pose, config=LidarConfig(footprint_wh=(12, 9)), **args)
    return terrain, rgb, lidar
