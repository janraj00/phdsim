"""Restore original modality pixels from the pinned RGBA mirror with provenance."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
import time
import zlib

import numpy as np
from PIL import Image

from .constants import MIRROR_BASE, MIRROR_REVISION


def _download_public(url: str, target: Path, max_bytes: int = 8_000_000) -> bytes:
    if target.exists():
        return target.read_bytes()
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "PHDSIM-research/0.5"}), timeout=30) as response:
                content = response.read(max_bytes + 1)
                if len(content) > max_bytes or not content.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Mirror did not return an expected PNG")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".partial")
            partial.write_bytes(content)
            partial.replace(target)
            return content
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def _restore_modality(root, frame, split, modality, values):
    """Reuse verified original bytes, or save and verify a lossless channel extraction."""
    entry = frame['assets'][modality]
    path = root / entry['name']
    if path.exists():
        raw = path.read_bytes()
        if len(raw) == entry['bytes'] and zlib.crc32(raw) == entry['crc32']:
            with Image.open(BytesIO(raw)) as original:
                if not np.array_equal(np.asarray(original), values):
                    raise ValueError(f"Mirror differs from original {modality} pixels: {frame['filename']}")
            return entry, True
    relative = f"derived/{split}/{modality}/{frame['filename']}"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(values).save(path, format='PNG')
    raw = path.read_bytes()
    with Image.open(BytesIO(raw)) as decoded:
        if not np.array_equal(np.asarray(decoded), values):
            raise ValueError('Lossless channel extraction failed')
    return {'name': relative, 'bytes': len(raw), 'crc32': zlib.crc32(raw)}, False


def _restore_mask(root, frame, split):
    """Require a mirror mask to match the original archive size and CRC32."""
    entry = frame['assets']['labels']
    path = root / entry['name']
    annotation_url = f"{MIRROR_BASE}/annotations/{split}/{frame['filename']}"
    if path.exists():
        mask = path.read_bytes()
        if len(mask) == entry['bytes'] and zlib.crc32(mask) == entry['crc32']:
            return mask, annotation_url
    cache = root / 'mirror' / MIRROR_REVISION / 'annotations' / split / frame['filename']
    mask = _download_public(annotation_url, cache)
    if len(mask) != entry['bytes'] or zlib.crc32(mask) != entry['crc32']:
        raise ValueError(f"Mirror mask differs from original archive: {frame['filename']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mask)
    return mask, annotation_url


def _fetch_frame(root, frame):
    split = 'train' if frame['source_split'] == 'train' else 'val'
    filename = frame['filename']
    image_url = f'{MIRROR_BASE}/images/{split}/{filename}'
    cache = root / 'mirror' / MIRROR_REVISION / 'images' / split / filename
    content = _download_public(image_url, cache)
    with Image.open(BytesIO(content)) as image:
        if image.mode != 'RGBA':
            raise ValueError('Expected mirror RGBA: R,G,B,thermal in the fourth channel')
        pixels = np.asarray(image)
    assets, checked = {}, []
    for modality, values in (('rgb', pixels[..., :3]), ('thermal', pixels[..., 3])):
        assets[modality], is_original = _restore_modality(root, frame, split, modality, values)
        if is_original:
            checked.append(modality)
    mask, annotation_url = _restore_mask(root, frame, split)
    assets['labels'] = frame['assets']['labels']
    return {**frame, 'original_assets': frame['assets'], 'assets': assets,
            'mirror': {'image_url': image_url, 'image_sha256': sha256(content).hexdigest(),
                       'annotation_url': annotation_url, 'mask_sha256': sha256(mask).hexdigest(),
                       'original_pixel_comparisons': checked,
                       'conversion': 'RGBA channels 0:3 -> RGB; channel 3 -> thermal, lossless PNG'}}


def fetch_mirror(root: Path, frames: list[dict]) -> list[dict]:
    """Fetch frames concurrently while preserving their original selection order."""
    result = [None] * len(frames)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_fetch_frame, root, frame): i for i, frame in enumerate(frames)}
        for done, future in enumerate(as_completed(futures), 1):
            result[futures[future]] = future.result()
            if done % 20 == 0 or done == len(frames):
                print(f'Verified mirror {done}/{len(frames)} paired frames', flush=True)
    return result
