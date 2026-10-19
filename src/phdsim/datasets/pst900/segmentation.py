"""Full original split, paired modalities, mask references, no agent assignment."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .source import source_index, paired_frames
from .mirror import fetch_mirror


@dataclass(frozen=True)
class SegmentationFrame:
    frame_id: str
    split: str
    sequence_id: str
    tick: int
    rgb_path: Path
    thermal_path: Path
    mask_path: Path
    thermal_bytes: int
    rgb_sha256: str | None = None
    thermal_sha256: str | None = None
    mask_sha256: str | None = None


def prepare_full_dataset(root):
    root = Path(root).resolve()
    path = root / 'segmentation' / 'manifest.json'
    if path.exists():
        return load_frames(path)
    original = paired_frames(source_index(root))
    if Counter(f['source_split'] for f in original) != {'train': 597, 'test': 288}:
        raise ValueError('Unexpected original archive split; refusing silent benchmark changes')
    frames = fetch_mirror(root, original)
    records = []
    for frame in frames:
        assets = {k: {'path': str((root / v['name']).resolve()),
                      'sha256': sha256((root / v['name']).read_bytes()).hexdigest(),
                      'bytes': (root / v['name']).stat().st_size}
                  for k, v in frame['assets'].items()}
        records.append({'frame_id': frame['source_split'] + '/' + frame['filename'],
                        'split': frame['source_split'], 'sequence_id': frame['sequence_id'],
                        'tick': frame['tick'], 'assets': assets, 'mirror': frame['mirror']})
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.json.partial')
    partial.write_text(json.dumps({'schema': 'phdsim-pst900-segmentation-v1',
                                  'pairs': len(records), 'source_split': {'train': 597, 'test': 288},
                                  'quarantine': 'none; original benchmark masks retained',
                                  'records': records}, indent=2), encoding='utf-8')
    partial.replace(path)
    return load_frames(path)


def load_frames(manifest, *, verify=True):
    manifest = Path(manifest)
    value = json.loads(manifest.read_text(encoding='utf-8'))
    if value.get('schema') != 'phdsim-pst900-segmentation-v1':
        raise ValueError('Unknown segmentation manifest')
    result, seen = [], set()
    for row in value['records']:
        if row['frame_id'] in seen or row['split'] not in ('train', 'test'):
            raise ValueError('Duplicate frame or invalid split')
        seen.add(row['frame_id'])
        assets = row['assets']
        for asset in assets.values():
            path = Path(asset['path'])
            if verify and (not path.is_file() or path.stat().st_size != asset['bytes']
                           or sha256(path.read_bytes()).hexdigest() != asset['sha256']):
                raise ValueError(f'Segmentation input fingerprint mismatch: {path}')
        result.append(SegmentationFrame(row['frame_id'], row['split'], row['sequence_id'], row['tick'],
                                       *(Path(assets[k]['path']) for k in ('rgb', 'thermal', 'labels')),
                                       assets['thermal']['bytes'],
                                       *(assets[k]['sha256'] for k in ('rgb', 'thermal', 'labels'))))
    return tuple(result)


def require_benchmark_split(frames):
    if Counter(f.split for f in frames) != {'train': 597, 'test': 288}:
        raise ValueError('Benchmark requires all 597 original train and 288 original test frames')

