from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
import zipfile
import zlib

import numpy as np
from PIL import Image

from phdsim.datasets.pst900.archive import RemoteZipFile, _fetch_entry
from phdsim.datasets.pst900.prepare import prepare_pst900
from phdsim.experiments.presence.replay import ProcessingConfig, run_replay
from phdsim.fusion import FusionConfig
from phdsim.perception import FitConfig, ImagePayload, image_features, train_image_perception
from phdsim.datasets import AgentSlot, allocate, read_lines, write_json, write_lines


def image_pool(root):
    frames = []
    for split, count in (("train", 8), ("validation", 2), ("test", 4)):
        for tick in range(count):
            label = tick % 2
            filename = f"{split}_rect_rgb_frame{tick:010d}.png"
            assets = {}
            for kind in ("rgb", "thermal", "labels"):
                path = root / split / kind / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                values = np.full((12, 16, 3) if kind == "rgb" else (12, 16),
                                 (50 + 150 * label) if kind != "labels" else 4 * label, dtype=np.uint8)
                Image.fromarray(values).save(path)
                content = path.read_bytes()
                assets[kind] = {"name": path.relative_to(root).as_posix(), "bytes": len(content),
                                "crc32": zlib.crc32(content)}
            frames.append({"source_split": "train" if split != "test" else "test", "split": split,
                           "filename": filename, "sequence_id": split, "tick": tick, "assets": assets})
    write_json(root / "selection.json", frames)
    write_json(root / "source-index.json", {"test_fixture": True})
    return prepare_pst900(root, root / "pool")


class ImageTests(unittest.TestCase):
    def test_import_preserves_images_and_keeps_masks_out_of_observations(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = image_pool(root)
            self.assertEqual(len(pool.records), 28)
            self.assertEqual(len(pool.read_labels()), 14)
            self.assertEqual(len(read_lines(pool.root / "annotations.jsonl")), 14)
            self.assertFalse(any("mask" in r.to_dict() or "label" in r.to_dict() for r in pool.records))
            for frame in json.loads((root / "selection.json").read_text()):
                for modality in ("rgb", "thermal"):
                    source = root / frame["assets"][modality]["name"]
                    observation_id = frame["filename"].removesuffix(".png") + "-" + modality
                    self.assertEqual(source.read_bytes(), pool.read_payload(observation_id))

    def test_test_and_validation_labels_cannot_change_image_models(self):
        with TemporaryDirectory() as temporary:
            pool = image_pool(Path(temporary))
            settings = FitConfig(epochs=20)
            before = train_image_perception(pool, ("rgb", "thermal"), settings)
            labels = read_lines(pool.root / "labels.jsonl")
            for row in labels:
                if not row["target"]["id"].startswith("train_"):
                    row["label"] = 1 - row["label"]
            write_lines(pool.root / "labels.jsonl", labels)
            after = train_image_perception(pool, ("rgb", "thermal"), settings)
            self.assertEqual(asdict(before), asdict(after))
            self.assertTrue(all(m.train_count == 8 and m.final_log_loss < m.initial_log_loss
                                for m in before.perception.models))
            schedule = allocate(pool, (AgentSlot("rgb", "rgb", 4), AgentSlot("thermal", "thermal", 4)))
            config = ProcessingConfig(FusionConfig("mean_probability"), ProcessingConfig.defaults().decisions)
            result = run_replay(pool, schedule, Path(temporary) / "result", fit=settings, processing=config)
            self.assertEqual(result["policies"]["no_acquisition"]["transfers"], 0)
            self.assertEqual(result["policies"]["always_acquire"]["transfers"], 8)
            transfers = read_lines(Path(temporary) / "result" / "transfers.jsonl")
            for row in transfers:
                payload = row["observation"]["payload"]
                self.assertEqual(row["settled_cost"]["components"][1]["value"], Path(payload["path"]).stat().st_size)

    def test_image_adapter_detects_corrupt_bytes_before_features(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.png"
            Image.new("RGB", (8, 8)).save(path)
            fingerprint = sha256(path.read_bytes()).hexdigest()
            path.write_bytes(b"broken image")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                image_features(ImagePayload(str(path), fingerprint), "rgb")

    def test_remote_zip_ranges_extract_exact_bytes_and_reject_escaping_paths(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "fixture.zip"
            content = b"an original observation" * 100
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("safe/image.png", content)
            raw = source.read_bytes()
            with patch("phdsim.datasets.pst900.archive._range", side_effect=lambda url, start, length, size: raw[start:start + length]), patch("phdsim.datasets.pst900.archive.PST900_SIZE", len(raw)):
                with zipfile.ZipFile(RemoteZipFile(size=len(raw))) as archive:
                    info = archive.infolist()[0]
                entry = {"name": info.filename, "offset": info.header_offset, "compressed_bytes": info.compress_size,
                         "bytes": info.file_size, "crc32": info.CRC, "compression": info.compress_type}
                path = _fetch_entry(entry, root / "download")
                self.assertEqual(path.read_bytes(), content)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    _fetch_entry({**entry, "name": "../escape.png"}, root / "download")


if __name__ == "__main__":
    unittest.main()
