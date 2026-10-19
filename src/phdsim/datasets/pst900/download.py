"""Fetch a fixed pilot while preserving source selection and provenance."""

from pathlib import Path
import json
from .mirror import fetch_mirror
from .source import paired_frames, select_pilot, source_index


def fetch_pilot(root: str | Path) -> list[dict]:
    root = Path(root).resolve()
    frames = select_pilot(paired_frames(source_index(root)))
    selection = root / "selection.json"
    if selection.exists() and [(f['filename'], f['split']) for f in json.loads(selection.read_text(encoding="utf-8"))] != [(f['filename'], f['split']) for f in frames]:
        raise ValueError("Existing selection differs from this pilot; use a separate directory")
    # The author's Drive link has a per-file quota. Use a pinned public copy,
    # checking every available original pixel array and original mask CRC.
    frames = fetch_mirror(root, frames)
    selection.write_text(json.dumps(frames, indent=2) + "\n", encoding="utf-8")
    return frames
