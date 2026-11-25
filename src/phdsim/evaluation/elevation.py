"""Compare a reported elevation model with simulator truth, for offline metrics."""

from math import sqrt

from phdsim.belief.elevation import ElevationTile
from phdsim.core.grid import Cell


def elevation_metrics(belief: dict[Cell, ElevationTile], truth_m: dict[Cell, tuple[float, ...]],
                      tolerance_m: float) -> dict[str, float]:
    errors = [abs(estimate - truth) for cell, tile in belief.items()
              for estimate, truth in zip(tile.heights_m, truth_m[cell], strict=True)]
    return {"actual_fraction": sum(error <= tolerance_m for error in errors) / len(errors),
            "rmse_m": sqrt(sum(error**2 for error in errors) / len(errors))}
