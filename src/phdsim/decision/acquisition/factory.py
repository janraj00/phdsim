"""Explicit registry of the implemented acquisition baselines."""

from .no_scouting import NoScouting
from .uncertainty import UncertaintyScouting

def make_policy(name, config):
    if name == "no_scouting":
        return NoScouting()
    if name == "uncertainty_scouting":
        return UncertaintyScouting(config)
    raise ValueError(f"Unknown policy: {name}")
