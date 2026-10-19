"""RGB-only information available before requesting a peer image."""

from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class RgbAcquisitionView:
    features: tuple[float, ...]
    thermal_bytes: int


class SegmentationPolicy(Protocol):
    def acquire(self, view: RgbAcquisitionView) -> bool: ...

