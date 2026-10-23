"""Non-destructive one-sequence source layout for the official converter."""

import json
from pathlib import Path

from .archive import sequence_directory
from .catalog import read_sync
from .source import file_hashes


def create_source_view(root, sequence, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    native = sequence_directory(root, sequence)
    labels = root / 'raw' / 'labels' / (sequence + '.json')
    track_ids = root / 'raw' / 'labels_av_track_ids.json'
    source_manifest = root / 'source' / (sequence + '-download.json')
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
    (output / 'dataset' / sequence).symlink_to(native, target_is_directory=True)
    (output / 'labels' / labels.name).symlink_to(labels)
    (output / track_ids.name).symlink_to(track_ids)
    record = {'schema': 'phdsim-urbaning-opencood-source-v1', 'sequence': sequence,
              'source_root': str(root), 'native_sequence': str(native), 'source_manifest': manifest,
              'calibration_sha256': file_hashes(native / 'calibration.json')['sha256'],
              'timesync_sha256': file_hashes(native / 'timesync_info.csv')['sha256'],
              'sync_by_frame': {row['source_column'].zfill(6): row
                                for row in read_sync(native / 'timesync_info.csv')},
              'semantics': 'offline source association; may include post-anchor observations'}
    (output / 'phdsim-conversion.json').write_text(json.dumps(record, indent=2) + '\n')
    return output
