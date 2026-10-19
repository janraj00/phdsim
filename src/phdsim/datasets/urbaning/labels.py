"""Normalize track-wise source labels into offline, timestamped 3D annotations."""

from decimal import Decimal
import json
import math
from pathlib import Path


def seconds_to_ns(value) -> int:
    converted = Decimal(str(value)) * 1_000_000_000
    if not converted.is_finite() or converted != converted.to_integral_value():
        raise ValueError('Timestamp cannot be represented as integer nanoseconds')
    return int(converted)


def read_annotations(path: str | Path, sequence: str) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding='utf-8'), parse_float=Decimal)
    result, seen = [], set()
    for track in value['tracks']:
        count = len(track['timestamps'])
        if len(track['positions']) != count or len(track['orientations']) != count:
            raise ValueError('Track positions/orientations do not match timestamps')
        if len(track['dimensions']) not in (1, count):
            raise ValueError('Track dimensions must be static or timestamp-specific')
        for name, attribute in track.get('attributes', {}).items():
            if isinstance(attribute, list) and len(attribute) != count:
                raise ValueError(f'Track attribute length mismatch: {name}')
        for index, timestamp in enumerate(track['timestamps']):
            ns = seconds_to_ns(timestamp)
            key = (track['track_id'], ns)
            if key in seen:
                raise ValueError('Duplicate track annotation at a timestamp')
            seen.add(key)
            dimensions = track['dimensions'][0 if len(track['dimensions']) == 1 else index]
            position = [float(x) for x in track['positions'][index]]
            dimensions = [float(x) for x in dimensions]
            yaw = float(track['orientations'][index])
            if len(position) != 3 or len(dimensions) != 3 or not all(
                    math.isfinite(x) for x in position + dimensions + [yaw]) or min(dimensions) <= 0:
                raise ValueError('Invalid 3D box geometry')
            attributes = {k: v[index] if isinstance(v, list) else v
                          for k, v in track.get('attributes', {}).items()}
            result.append({'annotation_id': f'{sequence}/track-{track["track_id"]}/{ns}',
                           'sequence_id': sequence, 'timestamp_ns': ns,
                           'track_id': str(track['track_id']), 'class_name': track['object_type'],
                           'position_m': position, 'dimensions_lwh_m': dimensions,
                           'yaw_rad': yaw, 'coordinate_frame': f'{sequence}/global',
                           'attributes_json': json.dumps(attributes, default=float),
                           'access': 'offline_ground_truth'})
    return sorted(result, key=lambda item: (item['timestamp_ns'], item['track_id']))
