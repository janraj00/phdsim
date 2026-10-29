"""Non-destructive one-sequence source layout for the official converter."""

import json
import csv
from pathlib import Path

from .archive import sequence_directory
from .catalog import read_sync
from .source import file_hashes


def create_source_view(root, sequence, output, max_frames=None, start_frame=0):
    root, output = Path(root).resolve(), Path(output).resolve()
    native = sequence_directory(root, sequence)
    labels = root / 'raw' / 'labels' / (sequence + '.json')
    track_ids = root / 'raw' / 'labels_av_track_ids.json'
    source_manifest = root / 'source' / (sequence + '-download.json')
    if max_frames is not None and max_frames < 1:
        raise ValueError('Source-view frame limit must be positive')
    if start_frame < 0:
        raise ValueError('Source-view start frame must be nonnegative')
    associations = read_sync(native / 'timesync_info.csv')
    if start_frame >= len(associations):
        raise ValueError('Source-view start exceeds the sequence length')
    manifest = json.loads(source_manifest.read_text())
    for path in (labels, track_ids):
        entry = next(item for item in manifest['files'] if item['relative_path'] == path.relative_to(root / 'raw').as_posix())
        if file_hashes(path)['sha256'] != entry['sha256']:
            raise ValueError('Source metadata changed: ' + str(path))
    if output.exists():
        raise FileExistsError('Choose a new source view directory: ' + str(output))
    output.mkdir(parents=True)
    (output / 'dataset').mkdir()
    (output / 'labels').mkdir()
    sequence_view = output / 'dataset' / sequence
    if max_frames is None and start_frame == 0:
        sequence_view.symlink_to(native, target_is_directory=True)
    else:
        sequence_view.mkdir()
        for source in native.iterdir():
            if source.name != 'timesync_info.csv':
                (sequence_view / source.name).symlink_to(source, target_is_directory=source.is_dir())
        with (native / 'timesync_info.csv').open(newline='') as handle:
            rows = list(csv.reader(handle))
        with (sequence_view / 'timesync_info.csv').open('w', newline='') as handle:
            end = start_frame + max_frames if max_frames is not None else len(associations)
            csv.writer(handle).writerows([row[0]] + row[start_frame + 1:end + 1] for row in rows)
    (output / 'labels' / labels.name).symlink_to(labels)
    (output / track_ids.name).symlink_to(track_ids)
    record = {'schema': 'phdsim-urbaning-opencood-source-v1', 'sequence': sequence,
              'source_root': str(root), 'native_sequence': str(native), 'source_manifest': manifest,
              'calibration_sha256': file_hashes(native / 'calibration.json')['sha256'],
              'timesync_sha256': file_hashes(native / 'timesync_info.csv')['sha256'],
              'view_timesync_sha256': file_hashes(sequence_view / 'timesync_info.csv')['sha256'],
              'max_frames': max_frames,
              'start_frame': start_frame,
              'sync_by_frame': {row['source_column'].zfill(6): row
                                for row in read_sync(sequence_view / 'timesync_info.csv')},
              'semantics': 'offline source association; may include post-anchor observations'}
    (output / 'phdsim-conversion.json').write_text(json.dumps(record, indent=2) + '\n')
    return output
