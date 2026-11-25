"""Time-ordered simulation events, including capture and delivery."""

import heapq

class EventQueue:
    """Stable clock queue used for capture and delivery events; hidden from policies."""

    def __init__(self):
        self._items = []
        self._sequence = 0

    def schedule(self, tick, kind, payload):
        heapq.heappush(self._items, (tick, self._sequence, kind, payload))
        self._sequence += 1

    def due(self, tick):
        while self._items and self._items[0][0] <= tick:
            yield heapq.heappop(self._items)
