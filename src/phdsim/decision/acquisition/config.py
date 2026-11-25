"""Parameters for the route-entropy acquisition baseline."""

from dataclasses import dataclass

@dataclass(frozen=True)
class AcquisitionConfig:
    entropy_threshold: float = 0.35
    lookahead: int = 12
    cooldown_ticks: int = 12
    max_requests: int = 4
