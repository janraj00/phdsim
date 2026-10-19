'Deterministic JSON conversion.'
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from math import isfinite

def jsonable(value: object) -> object:
    if is_dataclass(value) and (not isinstance(value, type)):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and (not isfinite(value)):
        raise ValueError('Nonfinite value cannot be exported')
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'Unsupported JSON value: {type(value).__name__}')
