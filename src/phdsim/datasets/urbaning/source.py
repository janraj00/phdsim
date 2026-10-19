"""Download one explicitly selected public Dataverse sequence with integrity checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import urllib.request

DOI = 'doi:10.7910/DVN/A9LPY7'
HOST = 'https://dataverse.harvard.edu'
DEFAULT_SEQUENCE = '20241126_0017_crossing1_00'
SEQUENCE_PATTERN = re.compile(r'2024\d{4}_\d{4}_crossing[123]_\d{2}\Z')
SUPPORT_FILES = frozenset(('av_vehicle_data.json', 'labels_av_track_ids.json',
                           'crossings_lanelet2map.osm'))


def file_hashes(path: Path) -> dict[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            md5.update(chunk)
            sha.update(chunk)
    return {'md5': md5.hexdigest(), 'sha256': sha.hexdigest()}


def sequence_files(metadata: dict, sequence: str) -> list[dict]:
    """Select parts, labels and supporting metadata, excluding other sequences."""
    if not SEQUENCE_PATTERN.fullmatch(sequence):
        raise ValueError('Invalid UrbanIng sequence name')
    version = metadata['data']['latestVersion']
    result = []
    for entry in version['files']:
        value = entry['dataFile']
        name = value['filename']
        if name not in SUPPORT_FILES and name != sequence + '.json' and not re.fullmatch(
                re.escape(sequence) + r'\.7z\.\d{3}', name):
            continue
        if entry.get('restricted', False):
            raise ValueError(f'Source file is restricted: {name}')
        directory = entry.get('directoryLabel') or ''
        if directory not in ('', 'dataset', 'labels') or Path(name).name != name:
            raise ValueError('Unexpected source path')
        checksum = value['checksum']
        if checksum['type'].upper() != 'MD5':
            raise ValueError('Unexpected source checksum type')
        result.append({'source_id': value['id'], 'name': name,
                       'relative_path': str(Path(directory) / name).replace('\\', '/'),
                       'bytes': value['filesize'], 'md5': checksum['value'].lower()})
    parts = sorted(row['name'] for row in result if '.7z.' in row['name'])
    if not parts or parts != [f'{sequence}.7z.{i:03}' for i in range(1, len(parts) + 1)]:
        raise ValueError('Missing or discontinuous sequence archive parts')
    if not any(row['name'] == sequence + '.json' for row in result):
        raise ValueError('Sequence labels are missing')
    if not SUPPORT_FILES.issubset(row['name'] for row in result):
        raise ValueError('Supporting metadata is missing')
    return result


def _download(root: Path, item: dict) -> dict:
    path = root / item['relative_path']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        hashes = file_hashes(path)
        if path.stat().st_size != item['bytes'] or hashes['md5'] != item['md5']:
            raise ValueError(f'Existing source file does not match published identity: {path}')
        return {**item, **hashes}
    partial = path.with_name(path.name + '.partial')
    url = f"{HOST}/api/access/datafile/{item['source_id']}"
    for attempt in range(4):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > item['bytes']:
            raise ValueError('Partial source exceeds published byte count')
        if offset == item['bytes']:
            break
        headers = {'User-Agent': 'PHDSIM-UrbanIng-import/0.1', 'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                if offset and (response.status != 206 or not response.headers.get(
                        'Content-Range', '').startswith(f'bytes {offset}-')):
                    raise ValueError('Server did not honor resume range; partial file retained')
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' in content_type or ('application/json' in content_type
                                                  and not item['name'].endswith('.json')):
                    raise ValueError(f'Download returned metadata rather than source bytes: {content_type}')
                last = time.monotonic()
                with partial.open('ab' if offset else 'wb') as handle:
                    for chunk in iter(lambda: response.read(1024 * 1024), b''):
                        offset += len(chunk)
                        if offset > item['bytes']:
                            raise ValueError('Server returned more data than published')
                        handle.write(chunk)
                        if time.monotonic() - last > 15:
                            print(f"{item['name']}: {offset / 1e6:.0f}/{item['bytes'] / 1e6:.0f} MB", flush=True)
                            last = time.monotonic()
            if offset == item['bytes']:
                break
        except (OSError, TimeoutError) as error:
            if attempt == 3:
                raise
            print(f"Retry {item['name']}: {type(error).__name__}", flush=True)
    if not partial.exists() or partial.stat().st_size != item['bytes']:
        raise ValueError('Download ended before the published byte count')
    hashes = file_hashes(partial)
    if hashes['md5'] != item['md5']:
        raise ValueError(f"Published MD5 does not match {item['name']}; partial retained")
    partial.replace(path)
    print(f"Verified {item['name']}", flush=True)
    return {**item, **hashes}


def fetch_sequence(root: str | Path, sequence: str = DEFAULT_SEQUENCE) -> dict:
    root = Path(root).resolve()
    snapshot = root / 'source' / 'dataverse-dataset.json'
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(f'{HOST}/api/datasets/:persistentId/?persistentId={DOI}',
                                         headers={'User-Agent': 'PHDSIM-UrbanIng-import/0.1'})
        with urllib.request.urlopen(request, timeout=40) as response:
            metadata = json.load(response)
        snapshot.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    metadata = json.loads(snapshot.read_text(encoding='utf-8'))
    items = sequence_files(metadata, sequence)
    raw = root / 'raw'
    raw.mkdir(exist_ok=True)
    remaining = sum(max(0, item['bytes'] - (raw / item['relative_path']).with_name(
        item['name'] + '.partial').stat().st_size) if (raw / item['relative_path']).with_name(
        item['name'] + '.partial').exists() else item['bytes']
        for item in items if not (raw / item['relative_path']).exists())
    if shutil.disk_usage(root).free < remaining + 2 * 1024 ** 3:
        raise OSError('Insufficient disk space for the selected download and reserve')
    print(f'Download selection: {sequence}; {len(items)} files; {sum(i["bytes"] for i in items)/1e9:.3f} GB', flush=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        files = list(executor.map(lambda item: _download(raw, item), items))
    version = metadata['data']['latestVersion']
    manifest = {'schema': 'phdsim-urbaning-source-v1', 'doi': DOI,
                'dataset_version': f"{version['versionNumber']}.{version.get('versionMinorNumber', 0)}",
                'sequence_id': sequence, 'metadata_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                'files': files}
    path = root / 'source' / f'{sequence}-download.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
