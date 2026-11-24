import hashlib
import random


def rng(seed: int, namespace: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(f"{seed}:{namespace}".encode()).digest(), "big"))
