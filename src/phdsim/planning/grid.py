"""Navigation using only the rover's belief, with a fixed risk surrogate."""

import heapq

from dataclasses import dataclass
from phdsim.core.grid import Cell

@dataclass(frozen=True)
class PlanningConfig:
    risk_weight: float = 8.0
    blocked_threshold: float = 0.97



def plan_path(probabilities, start: Cell, goal: Cell, config: PlanningConfig) -> tuple[Cell, ...]:
    w, h = len(probabilities[0]), len(probabilities)
    queue = [(0.0, start)]
    distances, parent = {start: 0.0}, {}
    while queue:
        cost, cell = heapq.heappop(queue)
        if cost > distances[cell]:
            continue
        if cell == goal:
            path = [cell]
            while cell != start:
                cell = parent[cell]
                path.append(cell)
            return tuple(reversed(path))
        x, y = cell
        for nxt in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            nx, ny = nxt
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            p = probabilities[ny][nx]
            if p >= config.blocked_threshold:
                continue
            candidate = cost + 1 + config.risk_weight*p
            if candidate < distances.get(nxt, float("inf")):
                distances[nxt], parent[nxt] = candidate, cell
                heapq.heappush(queue, (candidate, nxt))
    return ()
