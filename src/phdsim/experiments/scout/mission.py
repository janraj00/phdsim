"""Compose the SCOUT world, selected acquisition strategy and mission engine."""

from phdsim.decision.acquisition.factory import make_policy
from phdsim.environments.corridors import generate_corridors
from phdsim.simulation.config import Config
from phdsim.simulation.mission import run_mission


def simulate(config: Config, policy=None) -> dict:
    world = generate_corridors(config.world.size, config.seed)
    policy = policy if policy is not None else make_policy(config.policy, config.acquisition)
    return run_mission(config, world, policy)
