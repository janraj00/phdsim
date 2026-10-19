"""Extract a verified split 7z source into a bounded, separately published directory."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import shutil

from .source import SEQUENCE_PATTERN, file_hashes


def checked_member(name: str) -> str:
    name = name.replace('\\', '/')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or re.match(r'^[A-Za-z]:', name):
        raise ValueError(f'Unsafe archive member: {name}')
    return name


def extract_sequence(root: str | Path, sequence: str) -> Path:
    import multivolumefile
    import py7zr

    if not SEQUENCE_PATTERN.fullmatch(sequence):
        raise ValueError('Invalid UrbanIng sequence name')
    root = Path(root).resolve()
    manifest_path = root / 'source' / f'{sequence}-download.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    parts = sorted((item for item in manifest['files'] if '.7z.' in item['name']),
                   key=lambda item: item['name'])
    for item in parts:
        path = root / 'raw' / item['relative_path']
        if path.stat().st_size != item['bytes'] or file_hashes(path)['sha256'] != item['sha256']:
            raise ValueError('Source archive changed after download verification')
    output = root / 'extracted' / sequence
    marker = output / 'extraction.json'
    source_identity = [item['sha256'] for item in parts]
    if marker.exists():
        value = json.loads(marker.read_text(encoding='utf-8'))
        if value['archive_sha256'] != source_identity:
            raise ValueError('Extraction belongs to a different archive')
        return output
    if output.exists():
        raise FileExistsError('Unmarked extraction directory already exists')
    partial = output.with_name(output.name + '.partial')
    if partial.exists():
        raise FileExistsError(f'Incomplete extraction retained at {partial}; choose a new root to retry')
    partial.mkdir(parents=True)
    base = root / 'raw' / 'dataset' / f'{sequence}.7z'
    with multivolumefile.open(str(base), mode='rb') as volumes:
        with py7zr.SevenZipFile(volumes, mode='r') as archive:
            entries = archive.list()
            if any(item.is_symlink or not (item.is_file or item.is_directory) for item in entries):
                raise ValueError('Only regular source files and directories may be extracted')
            names = [checked_member(item.filename) for item in entries]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate archive members')
            total = sum(item.uncompressed or 0 for item in entries)
            if shutil.disk_usage(root).free < total + 2 * 1024 ** 3:
                raise OSError('Insufficient space for archive extraction and reserve')
            print(f'Extracting {len(entries)} entries; {total/1e9:.3f} GB unpacked', flush=True)
            archive.extractall(path=partial)
    calibration_files = list(partial.rglob('calibration.json'))
    if len(calibration_files) != 1 or not (calibration_files[0].parent / 'timesync_info.csv').is_file():
        raise ValueError('Expected exactly one sequence calibration and synchronization table')
    sequence_relative = calibration_files[0].parent.relative_to(partial).as_posix()
    record = {'schema': 'phdsim-urbaning-extraction-v1', 'sequence_id': sequence,
              'archive_sha256': source_identity, 'sequence_relative_path': sequence_relative,
              'archive_file_count': sum(not item.is_directory for item in entries),
              'unpacked_bytes': total}
    (partial / 'extraction.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    partial.rename(output)
    return output


def sequence_directory(root: str | Path, sequence: str) -> Path:
    if not SEQUENCE_PATTERN.fullmatch(sequence):
        raise ValueError('Invalid UrbanIng sequence name')
    output = Path(root).resolve() / 'extracted' / sequence
    marker = json.loads((output / 'extraction.json').read_text(encoding='utf-8'))
    relative = checked_member(marker['sequence_relative_path'])
    directory = (output / relative).resolve()
    if not directory.is_relative_to(output) or not directory.is_dir():
        raise ValueError('Invalid extracted sequence root')
    return directory
