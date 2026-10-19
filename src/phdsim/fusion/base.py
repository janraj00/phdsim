"""Fusion component."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, log2
from typing import Protocol
from phdsim.probability import binary_entropy, logit, sigmoid
from phdsim.perception.results import TaskResult
from phdsim.core.identity import stable_id


class Fusion(Protocol):
    version: str

    def update(self, previous: TaskResult | None, incoming: TaskResult) -> TaskResult:
        ...
