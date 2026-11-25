"""Independent deterministic random streams for reproducible simulations."""

import hashlib
import random

def keyed_rng(seed: int, *key) -> random.Random:
    digest = hashlib.sha256(repr((seed, key)).encode()).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))
