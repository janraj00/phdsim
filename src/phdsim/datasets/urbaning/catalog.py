"""Experimental portable tables for one inspected UrbanIng source release.

This is a concrete adapter spike, not the final general observation-catalog v2.
Native samples, source synchronization memberships and offline labels stay separate.
"""

from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .archive import sequence_directory
from .geometry import read_lidar
from .labels import read_annotations
from .source import file_hashes

SCHEMA = 'phdsim-urbaning-inspection-catalog-v1'


def read_sync(path: str | Path) -> list[dict]:
    """Read the source's transposed CSV without converting timestamps to floats."""
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.reader(handle))
    if not rows or len(rows[0]) < 2:
        raise ValueError('Empty synchronization table')
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError('Ragged synchronization table')
    keys = [row[0] for row in rows[1:]]
    if len(set(keys)) != len(keys) or 'timestamp_ms' not in keys:
        raise ValueError('Missing or duplicated synchronization fields')
    result = []
    for column in range(1, width):
        cells = {row[0]: row[column] for row in rows[1:]}
        stamp = Decimal(cells.pop('timestamp_ms'))
        if not stamp.is_finite() or stamp != stamp.to_integral_value():
            raise ValueError('Source anchor is not integer milliseconds')
        result.append({'source_column': rows[0][column], 'timestamp_ns': int(stamp) * 1_000_000,
                       'members': {key: value if value and value.lower() not in ('nan', 'none') else None
                                   for key, value in cells.items()}})
    stamps = [row['timestamp_ns'] for row in result]
    if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
        raise ValueError('Source synchronization anchors are duplicated or unordered')
    return result


def stream_description(name: str) -> dict:
    if name.startswith('vehicle'):
        platform = name.split('_')[0]
        platform_kind, mount = 'vehicle', None
    elif name.startswith('crossing'):
        crossing, number, *_ = name.split('_')
        platform = crossing
        platform_kind = 'infrastructure_site'
        mount = f'{crossing}_{number[0]}'
    else:
        raise ValueError(f'Unknown source stream: {name}')
    if name.endswith('thermal_camera'):
        modality = 'thermal'
    elif name.endswith('camera'):
        modality = 'rgb'
    elif name.endswith('lidar'):
        modality = 'lidar'
    elif name.endswith('state'):
        modality = 'navigation_state'
    else:
        raise ValueError(f'Unknown source modality: {name}')
    return {'stream_id': name, 'sensor_id': name, 'platform_id': platform,
            'platform_kind': platform_kind, 'mount_group': mount,
            'mount_group_basis': 'source_name_prefix' if mount else None,
            'modality': modality,
            'role': 'auxiliary_navigation' if modality == 'navigation_state' else 'sensor_observation'}


def payload_profile(path: Path, modality: str) -> dict:
    if modality == 'lidar':
        return read_lidar(path)[1]
    if modality == 'navigation_state':
        value = json.loads(path.read_text(encoding='utf-8'))
        matrix = np.asarray(value['gTv'], dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError('Invalid vehicle state transform')
        return {'encoding': 'json', 'keys': sorted(value), 'gTv_shape': list(matrix.shape),
                'gTv_direction': 'vehicle_to_global'}
    with Image.open(path) as image:
        image.verify()
        profile = {'encoding': 'jpeg', 'width': image.width, 'height': image.height,
                   'mode': image.mode, 'dtype': 'uint8'}
    if modality == 'thermal':
        profile['value_semantics'] = 'published JPEG intensity; no temperature conversion inferred'
    return profile


def write_table(output: Path, name: str, rows: list[dict]) -> dict:
    import duckdb

    if not rows:
        raise ValueError(f'Table would be empty: {name}')
    json_path = output / f'{name}.jsonl'
    with json_path.open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + '\n')
    parquet = output / f'{name}.parquet'
    with duckdb.connect() as connection:
        relation = connection.read_json(str(json_path), format='newline_delimited', sample_size=-1)
        relation.write_parquet(str(parquet), compression='zstd')
        count = connection.read_parquet(str(parquet)).count('*').fetchone()[0]
        if count != len(rows):
            raise ValueError('Parquet row count differs from JSONL')
    return {'rows': len(rows), 'jsonl_sha256': file_hashes(json_path)['sha256'],
            'parquet_sha256': file_hashes(parquet)['sha256']}


def build_catalog(root: str | Path, sequence: str) -> Path:
    root = Path(root).resolve()
    directory = sequence_directory(root, sequence)
    source_path = root / 'source' / f'{sequence}-download.json'
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    release = json.loads(source_path.read_text(encoding='utf-8'))['dataset_version']
    output = root / 'prepared' / sequence / 'inspection-v1'
    marker = output / 'manifest.json'
    if marker.exists():
        value = json.loads(marker.read_text(encoding='utf-8'))
        if value['source_manifest_sha256'] != source_hash or value['schema'] != SCHEMA:
            raise ValueError('Existing catalog has a different source or schema')
        return output
    if output.exists():
        raise FileExistsError('Catalog exists without a completion manifest')
    partial = output.with_name(output.name + '.partial')
    if partial.exists():
        raise FileExistsError(f'Incomplete catalog retained: {partial}')
    partial.mkdir(parents=True)
    sync = read_sync(directory / 'timesync_info.csv')
    streams = [stream_description(name) for name in sync[0]['members']]
    observations, assets, by_source, missing = [], [], {}, []
    for stream in streams:
        name = stream['stream_id']
        native = sorted(path for path in (directory / name).iterdir() if path.is_file())
        if not native:
            raise ValueError(f'No native observations for {name}')
        stream['native_count'] = len(native)
        sample_paths = sorted({native[0], native[len(native)//2], native[-1]})
        profiles = [payload_profile(path, stream['modality']) for path in sample_paths]
        stream['payload_profile_json'] = json.dumps(profiles[0])
        stream['profile_checked_samples'] = len(sample_paths)
        stream['profile_check_scope'] = 'first_middle_last_native_samples'
        for profile in profiles[1:]:
            shape_keys = ('encoding', 'width', 'height', 'mode', 'dtype', 'channels', 'gTv_shape')
            if any(profile.get(key) != profiles[0].get(key) for key in shape_keys):
                raise ValueError(f'Payload format changes within stream {name}')
        for path in native:
            if not path.stem.isdigit():
                raise ValueError(f'Unexpected native filename: {path.name}')
            stamp_ms = int(path.stem)
            identity = f'urbaning-v2x@{release}/{sequence}/{name}/{path.name}'
            hashes = file_hashes(path)
            assets.append({'asset_id': identity, 'storage_root': 'urbaning-v2x',
                           'storage_key': path.relative_to(root).as_posix(),
                           'encoded_bytes': path.stat().st_size, 'sha256': hashes['sha256']})
            observations.append({'observation_id': identity, 'sequence_id': sequence,
                                 'stream_id': name, 'source_frame_id': path.name,
                                 'timestamp_ns': stamp_ms * 1_000_000,
                                 'timestamp_source_ms': str(stamp_ms), 'clock_id': 'UTC',
                                 'timestamp_kind': 'state_time' if stream['modality'] == 'navigation_state' else 'capture',
                                 'asset_id': identity})
            by_source[(name, path.name)] = observations[-1]
        print(f"Indexed {name}: {len(native)} native files", flush=True)
    memberships = []
    for frame_index, frame in enumerate(sync):
        for name, filename in frame['members'].items():
            if filename is None:
                missing.append({'anchor_index': frame_index, 'stream_id': name, 'reason': 'source_empty_cell'})
                continue
            if (name, filename) not in by_source:
                raise ValueError(f'Source synchronization references a missing file: {name}/{filename}')
            observation = by_source[(name, filename)]
            memberships.append({'association_id': f'{sequence}/anchor-{frame_index}',
                                'anchor_index': frame_index, 'anchor_timestamp_ns': frame['timestamp_ns'],
                                'stream_id': name, 'observation_id': observation['observation_id'],
                                'offset_ns': observation['timestamp_ns'] - frame['timestamp_ns'],
                                'method': 'provided_timesync_info_csv', 'pixel_alignment_implied': False})
    annotations = read_annotations(root / 'raw' / 'labels' / f'{sequence}.json', sequence)
    label_times = {row['timestamp_ns'] for row in annotations}
    anchor_times = {row['timestamp_ns'] for row in sync}
    # The source can retain an endpoint annotation beyond its synchronization table.
    # Preserve and explicitly flag it instead of inventing a frame or deleting labels.
    unmatched_label_times = sorted(label_times - anchor_times)
    for row in annotations:
        row['source_anchor_available'] = row['timestamp_ns'] in anchor_times
    calibration = json.loads((directory / 'calibration.json').read_text(encoding='utf-8'))
    geometry = [{'stream_id': name, 'parameters_json': json.dumps(value),
                 'source_key': (directory / 'calibration.json').relative_to(root).as_posix(),
                 'annotation_frame': f'{sequence}/global'} for name, value in calibration.items()]
    tables = {'observations': observations, 'assets': assets, 'streams': streams,
              'associations': memberships, 'annotations': annotations, 'geometry': geometry}
    checks = {name: write_table(partial, name, rows) for name, rows in tables.items()}
    metadata = json.loads((root / 'source' / 'dataverse-dataset.json').read_text(encoding='utf-8'))
    source_files = metadata['data']['latestVersion']['files']
    counts = Counter(next(s['modality'] for s in streams if s['stream_id'] == row['stream_id'])
                     for row in observations)
    manifest = {'schema': SCHEMA, 'status': 'adapter_spike_not_final_general_v2',
                'dataset_id': 'urbaning-v2x', 'release': release, 'sequence_id': sequence,
                'source_manifest_sha256': source_hash, 'storage_root_alias': 'urbaning-v2x',
                'tables': checks, 'native_counts_by_modality': dict(counts),
                'anchor_count': len(sync), 'annotated_anchor_count': len(label_times & anchor_times),
                'annotation_timestamp_count': len(label_times),
                'unmatched_annotation_timestamps_ns': unmatched_label_times,
                'missing_memberships': missing, 'profile_validation': 'three payloads per native stream',
                'native_integrity': 'all indexed files SHA256; source 7z part MD5 and SHA256 verified',
                'source_sequence_compressed_bytes': sum(row['dataFile']['filesize'] for row in source_files
                    if row['dataFile']['filename'].startswith(sequence + '.7z.')),
                'source_all_sequence_compressed_bytes': sum(row['dataFile']['filesize'] for row in source_files
                    if '_crossing' in row['dataFile']['filename'] and '.7z.' in row['dataFile']['filename']),
                'agent_assignment': None, 'task_model': None}
    (partial / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    partial.rename(output)
    return output
