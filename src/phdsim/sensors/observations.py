"""Delivered sensor evidence; contains neither a world nor a policy."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Observation:
    sensor: str
    captured_at: int
    cells: tuple[tuple[int, int, bool], ...]
    accuracy: float
