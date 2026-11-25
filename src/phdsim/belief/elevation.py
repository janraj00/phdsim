"""Per-cell elevation estimates with a common precision within each tile."""

from dataclasses import dataclass
from math import erf, sqrt

from phdsim.core.grid import Cell
from phdsim.sensors.elevation import ElevationReading


def probability_within(precision: float, tolerance_m: float) -> float:
    return erf(tolerance_m * sqrt(precision / 2))


@dataclass(frozen=True)
class ElevationTile:
    heights_m: tuple[float, ...]
    precision: float
    poor_imaging: bool | None = None

    def update(self, reading: ElevationReading) -> "ElevationTile":
        total = self.precision + reading.precision
        means = tuple((self.precision * a + reading.precision * b) / total
                      for a, b in zip(self.heights_m, reading.heights_m, strict=True))
        poor = self.poor_imaging if reading.poor_imaging is None else reading.poor_imaging
        return ElevationTile(means, total, poor)


def qualified_fraction(belief: dict[Cell, ElevationTile], tolerance_m: float,
                       confidence: float) -> float:
    return sum(probability_within(tile.precision, tolerance_m) >= confidence
               for tile in belief.values()) / len(belief)


def expected_coverage(belief: dict[Cell, ElevationTile], tolerance_m: float) -> float:
    """Average the marginal probabilities over cells, regardless of correlation."""
    return sum(len(tile.heights_m) * probability_within(tile.precision, tolerance_m)
               for tile in belief.values()) / sum(len(tile.heights_m) for tile in belief.values())
