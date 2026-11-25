"""Alternative-passage world generator for diagnostic missions."""

from phdsim.core.randomness import keyed_rng
from .grid import World

def generate_corridors(size: tuple[int, int], seed: int) -> World:
    w, h = size
    rng = keyed_rng(seed, "world")
    wall = w // 2
    gaps = (h // 4 + rng.randint(-1, 1), 3 * h // 4 + rng.randint(-1, 1))
    open_gap = rng.randrange(2)
    blocked = [[False] * w for _ in range(h)]
    prior = [[0.08] * w for _ in range(h)]
    for y in range(h):
        blocked[y][wall] = True
        prior[y][wall] = 0.99
    for index, center in enumerate(gaps):
        for y in range(center-1, center+2):
            blocked[y][wall] = index != open_gap
            prior[y][wall] = 0.5
    start, goal = (3, h // 2 - 3), (w-4, h // 2 - 3)
    return World(tuple(map(tuple, blocked)), tuple(map(tuple, prior)), start, goal, seed)
