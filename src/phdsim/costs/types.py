"""Cost quantities and their inclusion status; independent of charging and budgets."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

CostStatus = Literal['included', 'unmeasured', 'excluded']


@dataclass(frozen=True)
class CostComponent:
    name: str
    unit: str
    value: float | None
    status: CostStatus = 'included'

    def __post_init__(self) -> None:
        if not self.name or not self.unit:
            raise ValueError('Cost name and unit are required')
        if self.status not in ('included', 'unmeasured', 'excluded'):
            raise ValueError('Unknown cost status')
        if self.status == 'included':
            if self.value is None or not isfinite(self.value) or self.value < 0:
                raise ValueError('Included cost must be finite and nonnegative')
        elif self.value is not None:
            raise ValueError('Unmeasured/excluded costs must have value=None')


@dataclass(frozen=True)
class CostVector:
    components: tuple[CostComponent, ...] = ()

    def __post_init__(self) -> None:
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError('Cost component names must be unique')

    def get(self, name: str) -> CostComponent | None:
        return next((c for c in self.components if c.name == name), None)
