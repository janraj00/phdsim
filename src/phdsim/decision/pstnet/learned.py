"""Predict acquisition gain from local RGB evidence."""

from dataclasses import dataclass
import math
from phdsim.models.linear import LinearModel

@dataclass(frozen=True)
class LearnedPstPolicy:
    model: LinearModel
    cost: float = 0.

    def __post_init__(self):
        if self.model.kind != 'ridge' or not math.isfinite(self.cost) or self.cost < 0:
            raise ValueError('Expected Ridge gain model and nonnegative acquisition cost')

    def expected_gain(self, view):
        return self.model.predict(view.features)

    def acquire(self, view):
        # cost is the utility penalty per original thermal image, in IoU units.
        return self.expected_gain(view) > self.cost

