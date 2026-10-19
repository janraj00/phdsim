"""Stable identifiers and the shared identity of a prediction target."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


def stable_id(prefix: str, *parts: str) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(',', ':'))
    return f"{prefix}-{sha256(encoded.encode('utf-8')).hexdigest()[:20]}"


@dataclass(frozen=True)
class TargetRef:
    kind: str
    id: str

    def __post_init__(self) -> None:
        if not self.kind or not self.id:
            raise ValueError('Target kind and id must be nonempty')
