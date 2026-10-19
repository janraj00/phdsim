"""Always/never request a thermal image, for baseline comparisons."""

from dataclasses import dataclass

@dataclass(frozen=True)
class FixedPstPolicy:
    pull: bool

    def acquire(self, view):
        return self.pull

