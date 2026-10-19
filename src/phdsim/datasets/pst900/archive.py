"""Read and verify selected entries from the original PST900 ZIP."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import RawIOBase
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen
import struct
import time
import zipfile
import zlib
from .constants import PST900_SIZE, PST900_URL


def _range(url: str, start: int, length: int, size: int) -> bytes:
    if start < 0 or length < 1 or start + length > size:
        raise ValueError("Invalid archive byte range")
    for attempt in range(4):
        try:
            request = Request(url, headers={"Range": f"bytes={start}-{start + length - 1}",
                                           "User-Agent": "PHDSIM-research/0.5", "Cache-Control": "no-cache"})
            with urlopen(request, timeout=60) as response:
                expected = f"bytes {start}-{start + length - 1}/{size}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise ValueError("Source did not honor byte range; refusing full archive download")
                content = response.read(length + 1)
                if len(content) != length:
                    raise ValueError("Incomplete archive range")
                return content
        except (OSError, ValueError):
            if attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


class RemoteZipFile(RawIOBase):
    """Seekable metadata reader. Download only requested ZIP directory ranges."""

    def __init__(self, url=PST900_URL, size=PST900_SIZE):
        self.url, self.size, self.position = url, size, 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if self.position < 0:
            raise ValueError("Negative seek")
        return self.position

    def read(self, size=-1):
        length = max(0, self.size - self.position) if size < 0 else min(size, max(0, self.size - self.position))
        if length > 8_000_000:
            raise ValueError("ZIP metadata unexpectedly large")
        if not length:
            return b""
        value = _range(self.url, self.position, length, self.size)
        self.position += length
        return value


def _fetch_entry(entry: dict, root: Path) -> Path:
    relative = PurePosixPath(entry["name"])
    target = root.joinpath(*relative.parts).resolve()
    if relative.is_absolute() or not target.is_relative_to(root.resolve()) or ".." in relative.parts:
        raise ValueError("Unsafe archive path")
    if target.exists():
        content = target.read_bytes()
        if len(content) == entry["bytes"] and zlib.crc32(content) == entry["crc32"]:
            return target
    start = entry["offset"]
    length = min(30 + len(entry["name"].encode("utf-8")) + 4096 + entry["compressed_bytes"], PST900_SIZE - start)
    raw = _range(PST900_URL, start, length, PST900_SIZE)
    header = struct.unpack("<4s5H3L2H", raw[:30])
    if header[0] != b"PK\x03\x04" or header[2] & 1 or header[3] != entry["compression"]:
        raise ValueError("Unsupported or inconsistent local ZIP header")
    data_start = 30 + header[-2] + header[-1]
    data_end = data_start + entry["compressed_bytes"]
    if data_end > len(raw):
        raw = _range(PST900_URL, start, data_end, PST900_SIZE)
    compressed = raw[data_start:data_end]
    if entry["compression"] == zipfile.ZIP_DEFLATED:
        content = zlib.decompress(compressed, -15)
    elif entry["compression"] == zipfile.ZIP_STORED:
        content = compressed
    else:
        raise ValueError("Unsupported ZIP compression")
    if len(content) != entry["bytes"] or zlib.crc32(content) != entry["crc32"]:
        raise ValueError("Source entry size/CRC32 mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    partial.write_bytes(content)
    partial.replace(target)
    return target


def fetch_frames(root: str | Path, frames: list[dict], *, workers: int = 6) -> None:
    root = Path(root).resolve()
    entries = [entry for frame in frames for entry in frame["assets"].values()]
    total = sum(e["compressed_bytes"] for e in entries)
    print(f"Selected {len(frames)} paired frames, {len(entries)} PNGs, {total / 1024**2:.1f} MiB compressed", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_fetch_entry, entry, root) for entry in entries]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            if done % 60 == 0 or done == len(entries):
                print(f"Verified {done}/{len(entries)} files", flush=True)
