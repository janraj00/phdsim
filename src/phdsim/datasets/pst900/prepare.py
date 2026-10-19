"""Import PST900 pixels and separate reference annotations into a shared pool."""

from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import shutil
import zlib

import numpy as np
from PIL import Image

from phdsim.artifacts import digest, write_json, write_lines
from phdsim.datasets.pool import PoolRecord, prepare_pool
from phdsim.core.identity import TargetRef
from .constants import MIRROR_BASE, MIRROR_REVISION, PST900_SIZE, PST900_SOURCE, PST900_URL


def _read_asset(root, kind, entry):
    """Validate path, source checksum and decoded format before importing pixels."""
    relative = PurePosixPath(entry['name'])
    path = root.joinpath(*relative.parts).resolve()
    if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
        raise ValueError('Unsafe source asset path')
    content = path.read_bytes()
    if len(content) != entry['bytes'] or zlib.crc32(content) != entry['crc32']:
        raise ValueError(f'Source checksum mismatch: {path}')
    with Image.open(BytesIO(content)) as image:
        image.load()
        expected_mode = 'RGB' if kind == 'rgb' else 'L'
        if image.format != 'PNG' or image.mode != expected_mode:
            raise ValueError(f'Expected PNG {expected_mode}, got {image.format}/{image.mode}: {path}')
        size = image.size
        class_pixels = None
        if kind == 'labels':
            classes, counts = np.unique(np.asarray(image), return_counts=True)
            if not set(classes) <= {0, 1, 2, 3, 4}:
                raise ValueError('Unexpected annotation class ID')
            class_pixels = {str(int(c)): int(n) for c, n in zip(classes, counts)}
    return path, size, class_pixels


def _prepare_frame(root, frame):
    """Map one verified triplet to two observations and an offline reference."""
    target = TargetRef('frame', frame['filename'].removesuffix('.png'))
    decoded = {kind: _read_asset(root, kind, frame['assets'][kind])
               for kind in ('rgb', 'thermal', 'labels')}
    if len({item[1] for item in decoded.values()}) != 1:
        raise ValueError('RGB, thermal and mask dimensions differ')
    class_pixels = decoded['labels'][2]
    records = [PoolRecord(f'{target.id}-{modality}', frame['sequence_id'], frame['tick'],
                          target, frame['split'], f'pst900-{modality}', modality,
                          str(decoded[modality][0]), f'{modality}-png-v1').to_dict()
               for modality in ('rgb', 'thermal')]
    reference = {'target': {'kind': target.kind, 'id': target.id},
                 'label': int(class_pixels.get('4', 0) > 0)}
    annotation = {'target': reference['target'], 'mask_source': decoded['labels'][0],
                  'mask_sha256': digest(decoded['labels'][0]), 'class_pixels': class_pixels}
    width, height = decoded['rgb'][1]
    provenance = {'target_id': target.id, 'source_split': frame['source_split'],
                  'split': frame['split'], 'sequence_id': frame['sequence_id'],
                  'tick': frame['tick'], 'width': width, 'height': height,
                  'source_assets': {k: e['name'] for k, e in frame.get('original_assets', frame['assets']).items()},
                  'delivery_assets': {k: e['name'] for k, e in frame['assets'].items()},
                  'mirror': frame.get('mirror')}
    return records, reference, annotation, provenance


def _copy_annotations(output, annotations):
    """Preserve mask bytes separately from the agent-visible observation assets."""
    (output / 'annotations').mkdir()
    references = []
    for annotation in annotations:
        row = dict(annotation)
        source = row.pop('mask_source')
        relative = f"annotations/{row['mask_sha256']}.png"
        if not (output / relative).exists():
            shutil.copyfile(source, output / relative)
        references.append({**row, 'mask_path': relative})
    return references


def _dataset_metadata(root, output, frames, records, labels, annotations, balance):
    """Describe provenance and physical file counts without changing the schema."""
    return {
        "source": PST900_SOURCE, "paper": "https://arxiv.org/abs/1909.10980", "download": PST900_URL,
        "archive_bytes": PST900_SIZE, "source_index_sha256": digest(root / "source-index.json"),
        "selection_sha256": digest(root / "selection.json"),
        "task": "presence of Survivor (class 4: human/thermal mannequin), any annotated pixel",
        "classes": {"0": "background", "1": "fire extinguisher", "2": "backpack", "3": "hand drill", "4": "Survivor / Rescue Randy"},
        "class_mapping_source": "https://github.com/ShreyasSkandanS/pst900_thermal_rgb/blob/master/pstnet/code/pst_inference.py",
        "frames": len(frames), "observations": len(records), "binary_label_counts": dict(balance),
        "selection": "uniformly spaced indices within each split, chosen before reading masks; 200/40/160",
        "validation_sequences": ["55_bag18", "56_bag19"],
        "alignment": "authors' registered RGB/thermal pairs; identical filename and image dimensions",
        "time": "source frame index; physical timestamps and frame interval unknown",
        "thermal": "authors' 8-bit AGC values; no conversion to temperature and no hole filling",
        "mirror": {"base": MIRROR_BASE, "revision": MIRROR_REVISION,
                   "conversion": "lossless RGBA channel extraction for missing originals; original masks verified by CRC32",
                   "original_pixel_comparisons": dict(Counter(m for f in frames for m in f.get('mirror', {}).get('original_pixel_comparisons', [])))},
        "source_count_note": "this archive contains 885 complete triplets (597 train, 288 test); publication describes 894",
        "pool_file_counts": {"metadata": 6, "image_pngs": len(list((output / 'assets').glob('*.png'))),
                             "mask_pngs": len(list((output / 'annotations').glob('*.png'))),
                             "observation_rows": len(records), "label_rows": len(labels), "mask_reference_rows": len(annotations)},
    }


def prepare_pst900(root: str | Path, output: str | Path):
    """Build an agent-independent PST900 pool; masks remain offline references."""
    root, output = Path(root).resolve(), Path(output).resolve()
    frames = json.loads((root / 'selection.json').read_text(encoding='utf-8'))
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Output directory is not empty: {output}')
    if not frames:
        raise ValueError('No selected frames')
    records, labels, annotations, provenance = [], [], [], []
    balance = defaultdict(Counter)
    for frame in frames:
        observations, reference, annotation, source = _prepare_frame(root, frame)
        records.extend(observations)
        labels.append(reference)
        annotations.append(annotation)
        provenance.append(source)
        balance[frame['split']][str(reference['label'])] += 1
    adapter = root / 'adapter-input'
    adapter.mkdir(exist_ok=True)
    write_lines(adapter / 'observations.jsonl', records)
    write_lines(adapter / 'labels.jsonl', labels)
    pool = prepare_pool(adapter / 'observations.jsonl', output, dataset_id='pst900-pilot-400',
                        dataset_version='authors-google-drive-pilot-v1', labels=adapter / 'labels.jsonl')
    write_lines(output / 'annotations.jsonl', _copy_annotations(output, annotations))
    write_lines(output / 'provenance.jsonl', provenance)
    write_json(output / 'dataset.json', _dataset_metadata(root, output, frames, records, labels, annotations, balance))
    pool.manifest['task'] = 'czy w kadrze występuje klasa Survivor (ID 4: człowiek/manekin termiczny)'
    write_json(output / 'pool.json', pool.manifest)
    print(f'Prepared {len(records)} original image observations, {len(labels)} labels and {len(annotations)} mask references', flush=True)
    return pool
