"""Prepare a real-data catalog and a documented, offline geometry inspection."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import platform

import numpy as np

from .archive import sequence_directory
from .catalog import build_catalog, read_sync
from .labels import read_annotations
from .preview import render_previews


def inspect_sequence(root, sequence, output, frame_index=100):
    root, output = Path(root).resolve(), Path(output).resolve()
    if (output / 'report.md').exists():
        raise FileExistsError('Inspection output is already complete; choose a new output directory')
    directory = sequence_directory(root, sequence)
    frames = read_sync(directory / 'timesync_info.csv')
    if not 0 <= frame_index < len(frames):
        raise ValueError(f'Frame index must be in [0, {len(frames)-1}]')
    catalog = build_catalog(root, sequence)
    manifest = json.loads((catalog / 'manifest.json').read_text(encoding='utf-8'))
    calibration = json.loads((directory / 'calibration.json').read_text(encoding='utf-8'))
    annotations = read_annotations(root / 'raw' / 'labels' / f'{sequence}.json', sequence)
    frame = frames[frame_index]
    labels = [row for row in annotations if row['timestamp_ns'] == frame['timestamp_ns']]
    if not labels:
        raise ValueError('Selected source anchor has no annotations; choose an annotated frame')
    output.mkdir(parents=True, exist_ok=True)
    preview = render_previews(directory, calibration, frame, labels, output)
    offset_groups = defaultdict(list)
    with (catalog / 'associations.jsonl').open(encoding='utf-8') as handle:
        for line in handle:
            value = json.loads(line)
            offset_groups[value['stream_id']].append(value['offset_ns']/1e6)
    offsets = {name: {'min_ms': min(values), 'median_ms': float(np.median(values)),
                      'max_ms': max(values), 'membership_count': len(values)}
               for name, values in offset_groups.items()}
    streams = [json.loads(line) for line in (catalog / 'streams.jsonl').read_text(encoding='utf-8').splitlines()]
    report = {'schema': 'phdsim-urbaning-inspection-report-v1', 'sequence_id': sequence,
              'catalog': str(catalog), 'selected_anchor_index': frame_index,
              'selected_anchor_timestamp_ns': frame['timestamp_ns'],
              'selected_source_members': frame['members'], 'manifest': manifest,
              'native_streams': streams, 'source_offsets': offsets, 'preview': preview,
              'annotation_track_count': len({row['track_id'] for row in annotations}),
              'annotation_class_counts': dict(Counter(row['class_name'] for row in annotations)),
              'python': platform.python_version(),
              'limitations': ['No task model, training, acquisition policy or task-quality measurement.',
                              'No simulator agent ownership has been assigned.',
                              'Payload profiles checked at first, middle and last samples per stream; all indexed bytes hashed.',
                              'Projection uses source labels at association time and source camera pose at image time.',
                              'Roundtrip checks test matrix consistency, not independent physical calibration accuracy.',
                              'Mount groups are inferred from source names; the platform registry retains the infrastructure site.',
                              'Source assets remain unchanged; this catalog is an adapter spike, not the final generic v2.']}
    (output / 'inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = ['# UrbanIng-V2X: first real-sequence inspection', '', f'Sequence: `{sequence}`.', '',
             'This is an offline data and geometry inspection. It contains source measurements and',
             'ground truth, with no trained predictions or acquisition decisions.', '',
             '## Verified source and file counts', '',
             f"- Published dataset release: {manifest['release']}.",
             f"- Selected sequence archives: {manifest['source_sequence_compressed_bytes']/1e9:.3f} GB.",
             f"- All sequence archives in the source inventory: {manifest['source_all_sequence_compressed_bytes']/1e9:.3f} GB.",
             f"- Source association anchors: {manifest['anchor_count']}.",
             f"- Anchors with reference annotations: {manifest['annotated_anchor_count']}.",
             f"- Annotation timestamps without a source anchor (preserved): {len(manifest['unmatched_annotation_timestamps_ns'])}.",
             f"- Tracks in this sequence: {report['annotation_track_count']}.", '',
             '| Native data | Files |', '|---|---:|']
    lines += [f'| {name} | {count} |' for name, count in manifest['native_counts_by_modality'].items()]
    lines += ['', 'Native observations, asset records, association memberships and object annotations',
              'are different counts. The importer references original assets without copying images.', '',
              '## Preview', '', f"Selected anchor: {frame_index}, UTC nanoseconds `{frame['timestamp_ns']}`.", '',
              '![Rectified source views and reference boxes](camera_reference_overlay.png)', '',
              '![Source LiDAR geometry and reference boxes](lidar_reference_bev.png)', '',
              '![Distinct sensor capture times](sensor_time_offsets.png)', '',
              '## Synchronization', '',
              '| Stream | Minimum offset (ms) | Median (ms) | Maximum (ms) |', '|---|---:|---:|---:|']
    lines += [f"| {name} | {value['min_ms']:.1f} | {value['median_ms']:.1f} | {value['max_ms']:.1f} |"
              for name, value in sorted(offsets.items())]
    lines += ['', 'Offsets use the provided synchronization table and original filename timestamps.',
              'Association does not imply simultaneous measurement or pixel registration. Positive',
              'offsets require an explicit decision-time availability rule in a future replay.', '',
              '## Catalog and reproducibility', '',
              f'Catalog: `{catalog}`.', '',
              'Six logical tables are exported as JSONL for inspection and Parquet for SQL queries:',
              '`observations`, `assets`, `streams`, `associations`, `annotations`, `geometry`.',
              'UTC nanoseconds stay integer-valued. Asset keys are relative to a configured data root.',
              'Ground truth is isolated in the offline annotation table. Per-file hashes and the',
              'source snapshot identity are recorded in the completion manifest.', '',
              '## Limitations and schema findings', '']
    lines += [f'- {item}' for item in report['limitations']]
    lines += ['', 'The real sample requires independent sensor times, per-point time offsets,',
              'directed geometry, camera-model-specific intrinsics, variable track attributes,',
              'and explicit association memberships. These cannot be represented faithfully by',
              'a single common frame number and an opaque payload path alone.', '',
              '## Sources', '',
              '- [Dataset and SDK](https://github.com/thi-ad/UrbanIng-V2X)',
              '- [Published data](https://doi.org/10.7910/DVN/A9LPY7)',
              '- SDK reference inspected from PyPI `urbaning==1.0.1`; no full SDK import was required.', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return output / 'report.md'
