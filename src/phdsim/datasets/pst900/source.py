"""Index, pair and select source frames before reading reference labels."""

from collections import Counter, defaultdict
from pathlib import Path
import json
import re
import zipfile
from .archive import RemoteZipFile
from .constants import PST900_SIZE, PST900_URL


def source_index(root: str | Path) -> list[dict]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "source-index.json"
    if cache.exists():
        value = json.loads(cache.read_text(encoding="utf-8"))
        if value["url"] != PST900_URL or value["archive_bytes"] != PST900_SIZE:
            raise ValueError("Source index belongs to another archive")
        return value["entries"]
    with zipfile.ZipFile(RemoteZipFile()) as archive:
        entries = [{"name": i.filename, "offset": i.header_offset, "compressed_bytes": i.compress_size,
                    "bytes": i.file_size, "crc32": i.CRC, "compression": i.compress_type}
                   for i in archive.infolist() if not i.is_dir()]
    cache.write_text(json.dumps({"url": PST900_URL, "archive_bytes": PST900_SIZE, "entries": entries}, indent=2), encoding="utf-8")
    return entries


def paired_frames(entries: list[dict]) -> list[dict]:
    frames = defaultdict(dict)
    pattern = re.compile(r"PST900_RGBT_Dataset/(train|test)/(rgb|thermal|labels)/(.+_frame(\d+)\.png)$")
    for entry in entries:
        match = pattern.fullmatch(entry["name"])
        if match:
            split, modality, filename, tick = match.groups()
            frames[split, filename][modality] = entry
    result = []
    for (split, filename), assets in sorted(frames.items()):
        if set(assets) != {"rgb", "thermal", "labels"}:
            raise ValueError(f"Incomplete RGB/thermal/mask pair: {split}/{filename}")
        group = filename.split("_rect_rgb_frame")[0]
        tick = int(re.search(r"_frame(\d+)\.png$", filename).group(1))
        result.append({"source_split": split, "filename": filename, "sequence_id": group, "tick": tick, "assets": assets})
    if not result:
        raise ValueError("No expected PST900 frame triplets in source archive")
    return result


def inspect_source(root: str | Path) -> dict:
    frames = paired_frames(source_index(root))
    return {"pairs": len(frames), "splits": dict(Counter(f["source_split"] for f in frames)),
            "groups": {g: dict(Counter(f["source_split"] for f in frames if f["sequence_id"] == g))
                       for g in sorted({f["sequence_id"] for f in frames})}}


def select_pilot(frames: list[dict]) -> list[dict]:
    """400 triplets selected by names alone; reserve complete recordings for validation."""
    validation_groups = {"55_bag18", "56_bag19"}
    buckets = {
        "train": [f for f in frames if f["source_split"] == "train" and f["sequence_id"] not in validation_groups],
        "validation": [f for f in frames if f["sequence_id"] in validation_groups],
        "test": [f for f in frames if f["source_split"] == "test"],
    }
    result = []
    for split, count in (("train", 200), ("validation", 40), ("test", 160)):
        rows = buckets[split]
        if len(rows) < count:
            raise ValueError(f"Not enough source frames for {split}")
        result.extend({**rows[i * len(rows) // count], "split": split} for i in range(count))
    return result
