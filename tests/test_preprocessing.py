from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phdsim.core.identity import TargetRef
from phdsim.datasets import (
    ObservationPool, PoolRecord, prepare_pool, validate_records, write_json, write_lines,
)
from phdsim.datasets import AgentSlot, Schedule, allocate


def make_pool(root: Path, count: int = 400) -> ObservationPool:
    source = root / "input"
    source.mkdir()
    write_json(source / "value.json", 0.3)
    rows = [PoolRecord(f"{modality}-{tick}", "sequence-1", tick, TargetRef("frame", str(tick)),
                       "test", f"sensor-{modality}", modality, "value.json", "scalar-json-v1")
            for tick in range(count) for modality in ("rgb", "thermal")]
    write_lines(source / "observations.jsonl", (r.to_dict() for r in rows))
    return prepare_pool(source / "observations.jsonl", root / "pool", dataset_id="fixture", dataset_version="1")


class PreprocessingTests(unittest.TestCase):
    def test_pool_has_no_agents_or_labels_and_preserves_raw_values(self):
        with TemporaryDirectory() as temporary:
            pool = make_pool(Path(temporary), 2)
            self.assertEqual(len(pool.records), 4)
            for row in pool.records:
                self.assertEqual(json.loads(pool.read_payload(row.observation_id)), 0.3)
                self.assertNotIn("agent_id", row.to_dict())
                self.assertNotIn("label", row.to_dict())
            self.assertEqual(pool.read_labels(), {})
            self.assertEqual(pool.fingerprint, ObservationPool(pool.root).fingerprint)

    def test_opaque_image_and_calibration_assets_are_preserved(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Opaque image bytes are copied; the common preprocessor does not decode them.
            image = b"P6\n1 1\n255\n\x00\x80\xff"
            (root / "image.ppm").write_bytes(image)
            write_json(root / "calibration.json", {"intrinsics": [1, 1]})
            row = PoolRecord("image-1", "seq", 0, TargetRef("frame", "f1"), "test", "cam", "rgb",
                             "image.ppm", "rgb-ppm-v1", calibration_ref="calibration.json")
            write_lines(root / "input.jsonl", (row.to_dict(),))
            write_lines(root / "labels.jsonl", ({"target": {"kind": "frame", "id": "f1"}, "label": 1},))
            pool = prepare_pool(root / "input.jsonl", root / "pool", dataset_id="image-fixture", dataset_version="1",
                                labels=root / "labels.jsonl")
            self.assertEqual(pool.read_payload("image-1"), image)
            self.assertTrue((pool.root / pool.records[0].calibration_ref).exists())
            self.assertEqual(pool.read_labels(), {row.target: 1})
            self.assertNotIn("label", (pool.root / "observations.jsonl").read_text())

    def test_agent_assignment_and_labels_are_rejected_in_stage_a(self):
        row = PoolRecord("obs", "s", 0, TargetRef("frame", "f"), "test", "camera", "rgb", "x", "image").to_dict()
        for field in ("agent_id", "label", "prediction"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Unknown pool fields"):
                PoolRecord.from_dict({**row, field: 1})

    def test_explicit_pairing_and_sequence_split_are_validated(self):
        first = PoolRecord("r", "seq", 0, TargetRef("frame", "f0"), "test", "rgb-s", "rgb", "v", "scalar")
        thermal = replace(first, observation_id="t", stream_id="thermal-s", modality="thermal")
        validate_records((first, thermal))
        for invalid in (replace(thermal, target=TargetRef("frame", "different")),
                        replace(thermal, tick=1, split="train"),
                        replace(thermal, stream_id=first.stream_id)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_records((first, invalid))

    def test_400_observations_per_modality_six_agents_get_100_each(self):
        with TemporaryDirectory() as temporary:
            pool = make_pool(Path(temporary))
            agents = tuple(AgentSlot(f"rgb-{i}", "rgb") for i in range(2)) + tuple(
                AgentSlot(f"thermal-{i}", "thermal") for i in range(4))
            schedule = allocate(pool, agents)
            self.assertEqual(Counter(a.agent_id for a in schedule.assignments), {a.agent_id: 100 for a in agents})
            self.assertEqual(len(schedule.assignments), 600)
            self.assertEqual(len(schedule.unassigned_observation_ids), 200)
            self.assertTrue(all(pool.by_id[o].modality == "rgb" for o in schedule.unassigned_observation_ids))
            self.assertEqual(len({a.observation_id for a in schedule.assignments}), 600)
            self.assertTrue(all((a.sequence_id, a.tick) == pool.by_id[a.observation_id].frame for a in schedule.assignments))

    def test_limit_is_configurable_and_replication_requires_explicit_mode(self):
        with TemporaryDirectory() as temporary:
            pool = make_pool(Path(temporary), 8)
            full = allocate(pool, (AgentSlot("rgb", "rgb", None),))
            self.assertEqual(len(full.assignments), 8)
            agents = (AgentSlot("a", "rgb"), AgentSlot("b", "rgb"))
            partition, replicated = allocate(pool, agents), allocate(pool, agents, mode="replicate")
            self.assertEqual(len(partition.assignments), 8)
            self.assertEqual(len(replicated.assignments), 16)
            self.assertEqual(len({a.observation_id for a in replicated.assignments}), 8)
            self.assertEqual(partition, allocate(pool, agents))

    def test_schedule_roundtrip_and_rejection_of_retimed_or_wrong_modality_data(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = make_pool(root, 4)
            schedule = allocate(pool, (AgentSlot("rgb", "rgb"), AgentSlot("thermal", "thermal")))
            schedule.save(root / "schedule.json")
            self.assertEqual(schedule, Schedule.load(root / "schedule.json", pool))
            item = schedule.assignments[0]
            for invalid in (replace(item, tick=999), replace(item, agent_id="thermal")):
                changed = replace(schedule, assignments=(invalid,) + schedule.assignments[1:])
                with self.assertRaises(ValueError):
                    changed.validate(pool)
            with self.assertRaises(FileExistsError):
                schedule.save(root / "schedule.json")
            with self.assertRaises(ValueError):
                replace(schedule, pool_fingerprint="wrong").validate(pool)

    def test_corrupt_payload_and_escaping_package_reference_are_rejected(self):
        with TemporaryDirectory() as temporary:
            pool = make_pool(Path(temporary), 2)
            row = pool.records[0]
            pool.payload_path(row).write_text("0.8", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                pool.read_payload(row.observation_id)
            with self.assertRaisesRegex(ValueError, "inside"):
                pool._local_path("../input/value.json")


if __name__ == "__main__":
    unittest.main()
