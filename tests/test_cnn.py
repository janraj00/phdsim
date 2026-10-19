from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from phdsim.datasets.pst900.review import recording_family, reviewed_split
from phdsim.perception import CnnConfig, ImagePayload, load_observation
from phdsim.datasets import PoolRecord, allocate, AgentSlot, digest, read_lines, write_lines
from phdsim.core.identity import TargetRef

try:
    import torch
except ImportError:
    torch = None


class ReviewedSplitTests(unittest.TestCase):
    def test_related_recordings_stay_together_test_is_fixed_and_one_pixel_is_quarantined(self):
        row = PoolRecord("obs", "37_bag7", 0, TargetRef("frame", "one"), "train", "rgb", "rgb", "a.png", "rgb-png-v1")
        self.assertEqual(recording_family("38_bag7a"), recording_family(row.sequence_id))
        self.assertEqual(reviewed_split(row, 200, (1, 7, 11)), "validation")
        self.assertEqual(reviewed_split(replace(row, sequence_id="38_bag7a"), 0, (1, 7, 11)), "validation")
        self.assertEqual(reviewed_split(replace(row, split="test"), 200, (1, 7, 11)), "test")
        self.assertIsNone(reviewed_split(row, 1, (1, 7, 11)))


@unittest.skipIf(torch is None, "Install the optional CNN dependencies to run neural checks")
class CnnTests(unittest.TestCase):
    def test_whole_frame_keeps_corners_and_thermal_is_only_grayscale(self):
        from phdsim.perception.cnn_input import image_tensor
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "rgb.png"
            image = np.zeros((32, 64, 3), dtype=np.uint8)
            image[:, :4, 0] = 255
            image[:, -4:, 1] = 255
            Image.fromarray(image).save(path)
            value = image_tensor(ImagePayload(str(path), digest(path)), "rgb", 32, 64)
            mean, std = torch.tensor((.485, .456, .406))[:, None, None], torch.tensor((.229, .224, .225))[:, None, None]
            reconstructed = (value * std + mean).permute(1, 2, 0).numpy()
            np.testing.assert_allclose(reconstructed, image / 255, atol=1e-6)
            thermal = Path(temporary) / "thermal.png"
            Image.fromarray(np.full((32, 64), 64, dtype=np.uint8)).save(thermal)
            value = image_tensor(ImagePayload(str(thermal), digest(thermal)), "thermal", 32, 64)
            raw = value * std + mean
            torch.testing.assert_close(raw, torch.full_like(raw, 64 / 255))

    def test_fine_tuning_changes_last_block_but_preserves_encoder_and_batchnorm_statistics(self):
        from phdsim.perception.resnet18_model import ResNet18Model
        torch.set_num_threads(2)
        torch.manual_seed(3)
        model = ResNet18Model("rgb").train()
        encoder = model.network.conv1.weight.detach().clone()
        block = model.network.layer4[0].conv1.weight.detach().clone()
        bn_before = {n: b.clone() for n, b in model.named_buffers() if "running_" in n or "num_batches" in n}
        images = torch.rand(2, 3, 32, 64)
        with torch.no_grad():
            encoded = model.encode(images)
        optimizer = torch.optim.SGD((p for p in model.parameters() if p.requires_grad), lr=.01)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(model.classify(encoded), torch.tensor([0., 1.]))
        loss.backward(); optimizer.step()
        self.assertTrue(torch.equal(encoder, model.network.conv1.weight))
        self.assertFalse(torch.equal(block, model.network.layer4[0].conv1.weight))
        for name, before in bn_before.items():
            self.assertTrue(torch.equal(before, dict(model.named_buffers())[name]), name)
        model.eval()
        with torch.inference_mode():
            torch.testing.assert_close(model(images), model.classify(model.encode(images)))

    def test_checkpoint_roundtrip_test_labels_cannot_affect_frozen_predictions(self):
        from phdsim.perception.cnn_training import train_cnn, load_cnn
        from phdsim.experiments.presence.replay import ProcessingConfig, run_replay
        from phdsim.fusion import FusionConfig
        from tests.test_images import image_pool
        config = CnnConfig(image_height=32, image_width=64, epochs=1, batch_size=4, cpu_threads=2)
        if not (Path(config.torch_cache) / "hub/checkpoints/resnet18-f37072fd.pth").is_file():
            self.skipTest("Official pretrained weights must already be cached; tests never download")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = image_pool(root)
            trained = train_cnn(pool, root / "models", config)
            row = next(r for r in pool.records if r.split == "test" and r.modality == "rgb")
            observation = load_observation(pool, row)
            before = trained.perception.process(observation)
            labels = read_lines(pool.root / "labels.jsonl")
            for value in labels:
                if value["target"]["id"].startswith("test_"):
                    value["label"] = 1 - value["label"]
            write_lines(pool.root / "labels.jsonl", labels)
            loaded = load_cnn(pool, root / "models")
            self.assertEqual(before, loaded.perception.process(observation))
            self.assertTrue(all(not p.requires_grad for model in loaded.perception._models.values() for p in model.parameters()))
            schedule = allocate(pool, (AgentSlot("rgb", "rgb", 4), AgentSlot("thermal", "thermal", 4)))
            settings = ProcessingConfig(FusionConfig("mean_probability"), ProcessingConfig.defaults().decisions)
            checkpoints_before = {p.name: digest(p) for p in (root / "models").glob("*.pt")}
            result = run_replay(pool, schedule, root / "result", trained=loaded, processing=settings)
            self.assertEqual(result["policies"]["no_acquisition"]["transfers"], 0)
            self.assertEqual(result["policies"]["always_acquire"]["transfers"], 8)
            self.assertEqual(checkpoints_before, {p.name: digest(p) for p in (root / "models").glob("*.pt")})
            for value in labels:
                if value["target"]["id"].startswith("train_"):
                    value["label"] = 1 - value["label"]
            write_lines(pool.root / "labels.jsonl", labels)
            with self.assertRaisesRegex(ValueError, "have changed"):
                load_cnn(pool, root / "models")


if __name__ == "__main__":
    unittest.main()
