"""Behavior and numerical parity for authors' segmentation + acquisition."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from hashlib import sha256
from dataclasses import replace

import numpy as np
from PIL import Image
import torch
from torch import nn

from phdsim.datasets.pst900.segmentation import SegmentationFrame, load_frames
from phdsim.decision.pstnet import FixedPstPolicy, LearnedPstPolicy, RgbAcquisitionView
from phdsim.evaluation.segmentation import confusion_matrix, segmentation_metrics
from phdsim.fusion.pstnet import PstFusion
from phdsim.models.linear import LinearModel
from phdsim.perception.pstnet.features import FEATURE_NAMES, rgb_features
from phdsim.learning.pstnet.training import fit_acquisition
from phdsim.evaluation.segmentation import summarize_choices as summarize
from phdsim.perception.pstnet.checkpoint import load_state, load_models
from phdsim.perception.pstnet.input import rgb_tensor, thermal_tensor, reference_mask
from phdsim.perception.pstnet.rgb import PstRgb
from phdsim.runtime.segmentation import SegmentationReplay


REFERENCE = Path(__file__).resolve().parents[1] / 'third_party/pst900/reference'


def reference_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, REFERENCE / filename)
    module = importlib.util.module_from_spec(spec)
    before = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


class PstNetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(4)

    def test_forward_matches_unmodified_authors_rgb_and_fusion(self):
        """Random weights only test mathematical parity, never benchmark accuracy."""
        original_rgb = reference_module('pst_rgb_reference', 'pstnet.py')
        original_fusion = reference_module('pst_fusion_reference', 'pstnet_thermal.py')
        torch.manual_seed(123)
        rgb = PstRgb(3, 5).eval()
        reference_rgb = original_rgb.Net(3, 5).eval()
        reference_rgb.load_state_dict(rgb.state_dict(), strict=True)
        checkpoint = {'module.' + k: v for k, v in rgb.state_dict().items()}
        with patch.dict(sys.modules, {'architectures.pstnet.pstnet': original_rgb}), \
                patch('torch.load', return_value=checkpoint), \
                patch.object(nn.Module, 'cuda', lambda self: self):
            reference_fusion = original_fusion.Net(4, 5).eval()
        fusion = PstFusion(rgb).eval()
        normalized = {k.replace('rgb_net.module.', 'rgb_net.'): v
                      for k, v in reference_fusion.state_dict().items()}
        fusion.load_state_dict(normalized, strict=True)
        image = torch.rand(1, 3, 360, 640)
        thermal = torch.rand(1, 1, 360, 640)
        with torch.inference_mode():
            rgb_output = rgb(image)
            torch.testing.assert_close(rgb_output, reference_rgb(image), rtol=0, atol=0)
            expected = reference_fusion(torch.cat((image, thermal), dim=1))
            cached = fusion(image, thermal, rgb_logits=rgb_output)
            normal = fusion(image, thermal)
        torch.testing.assert_close(cached, expected, rtol=0, atol=0)
        torch.testing.assert_close(normal, expected, rtol=0, atol=0)
        self.assertEqual(cached.shape, (1, 5, 360, 640))
        self.assertTrue(all(not p.requires_grad for p in fusion.rgb_net.parameters()))

    def test_preprocessing_matches_official_operations(self):
        import cv2
        from torchvision.transforms import Resize, ToTensor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rng = np.random.default_rng(9)
            rgb = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
            thermal = rng.integers(0, 256, (720, 1280), dtype=np.uint8)
            thermal[80:180, 200:300] = 0
            mask = rng.integers(0, 5, (720, 1280), dtype=np.uint8)
            for name, values in [('rgb', rgb), ('thermal', thermal), ('mask', mask)]:
                Image.fromarray(values).save(root / f'{name}.png')
            expected_rgb = ToTensor()(Resize(360, Image.Resampling.BILINEAR)(Image.fromarray(rgb)))
            resized = np.asarray(Resize(360, Image.Resampling.BILINEAR)(Image.fromarray(thermal)))
            expected_t = cv2.inpaint(resized, (resized == 0).astype(np.uint8), 10, cv2.INPAINT_NS) / 255.
            torch.testing.assert_close(rgb_tensor(root / 'rgb.png')[0], expected_rgb, rtol=0, atol=0)
            np.testing.assert_array_equal(thermal_tensor(root / 'thermal.png')[0, 0].numpy(), expected_t.astype(np.float32))
            np.testing.assert_array_equal(reference_mask(root / 'mask.png'), mask[1::2, 1::2])

    def test_global_iou_matches_authors_evaluator(self):
        module = reference_module('pst_iou_reference', 'eval_iou.py')
        evaluator = module.iouEval(5)
        predictions = [np.array([[0, 1, 1], [0, 2, 4]]), np.array([[3, 4], [0, 4]])]
        references = [np.array([[0, 1, 2], [0, 2, 3]]), np.array([[3, 4], [4, 4]])]
        matrix = np.zeros((5, 5), dtype=np.int64)
        for p, r in zip(predictions, references):
            evaluator.addBatch(torch.tensor(p)[None, None], torch.tensor(r)[None, None])
            matrix += confusion_matrix(p, r)
        expected_mean, expected_iou = evaluator.getIoU()
        actual = segmentation_metrics(matrix)
        np.testing.assert_allclose(list(actual['class_iou'].values()), expected_iou.numpy(), atol=1e-15)
        self.assertAlmostEqual(actual['miou'], expected_mean.item(), places=14)
        per_frame_mean = np.mean([segmentation_metrics(confusion_matrix(p, r))['miou'] for p, r in zip(predictions, references)])
        self.assertNotAlmostEqual(actual['miou'], per_frame_mean)

    def test_uncertainty_features_use_full_multiclass_distribution(self):
        rgb = torch.full((1, 3, 360, 640), .4)
        uniform = rgb_features(rgb, torch.zeros(1, 5, 360, 640))
        logits = torch.zeros(1, 5, 360, 640)
        logits[:, 4] = 20
        certain = rgb_features(rgb, logits)
        self.assertEqual(len(uniform), len(FEATURE_NAMES))
        self.assertAlmostEqual(uniform[0], 1., places=5)
        self.assertLess(certain[0], .001)
        self.assertEqual(certain[10], 1.)  # predicted survivor fraction

    def test_skipped_pull_opens_neither_thermal_nor_labels(self):
        class Rgb(nn.Module):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def forward(self, image):
                self.calls += 1
                return torch.cat((image[:, :1] + 1, image, image[:, :1]), dim=1)

        class Fusion(nn.Module):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def forward(self, rgb, thermal, rgb_logits=None):
                self.calls += 1
                assert rgb_logits is not None
                return rgb_logits.flip(1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.fromarray(np.full((720, 1280, 3), 100, dtype=np.uint8)).save(root / 'rgb.png')
            assets = {name: {'path': str(path), 'bytes': 123,
                             'sha256': sha256(path.read_bytes()).hexdigest() if name == 'rgb' else '0' * 64}
                      for name, path in [('rgb', root / 'rgb.png'), ('thermal', root / 'unavailable-thermal.png'),
                                         ('labels', root / 'unavailable-mask.png')]}
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'schema': 'phdsim-pst900-segmentation-v1',
                                             'records': [{'frame_id': 'test/x', 'split': 'test',
                                                          'sequence_id': '58_bag21', 'tick': 1, 'assets': assets}]}))
            # Metadata parsing must also leave missing peer images and labels unopened.
            frame = load_frames(manifest, verify=False)[0]
            rgb, fusion = Rgb(), Fusion()
            skipped = SegmentationReplay(rgb, fusion, FixedPstPolicy(False)).predict(frame)
            self.assertEqual((rgb.calls, fusion.calls, skipped.transferred_bytes), (1, 0, 0))
            np.testing.assert_array_equal(skipped.rgb_mask, skipped.final_mask)
            # Only the peer image becomes available; labels remain unavailable.
            Image.fromarray(np.ones((720, 1280), dtype=np.uint8)).save(frame.thermal_path)
            frame = replace(frame, thermal_sha256=sha256(frame.thermal_path.read_bytes()).hexdigest())
            pulled = SegmentationReplay(rgb, fusion, FixedPstPolicy(True)).predict(frame)
            self.assertEqual((rgb.calls, fusion.calls, pulled.transferred_bytes), (2, 1, 123))
            self.assertTrue(pulled.acquired)
            corrupted = replace(frame, thermal_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch at delivery'):
                SegmentationReplay(rgb, fusion, FixedPstPolicy(True)).predict(corrupted)

    def test_training_keeps_harmful_targets_and_rejects_test(self):
        good = np.diag([90, 4, 3, 2, 1]).tolist()
        bad = np.array([[85, 1, 1, 2, 1], [4, 0, 0, 0, 0], [3, 0, 0, 0, 0],
                        [2, 0, 0, 0, 0], [1, 0, 0, 0, 0]]).tolist()
        rows = [{'frame_id': f'train/{i}', 'split': 'train', 'group': f'bag{i//2}',
                 'features': [float(i % 2)] * len(FEATURE_NAMES),
                 'rgb_confusion': bad if i % 2 else good, 'fusion_confusion': good if i % 2 else bad}
                for i in range(6)]
        fitted = fit_acquisition(rows)
        self.assertEqual((fitted['positive_targets'], fitted['negative_targets']), (3, 3))
        policy = LearnedPstPolicy(LinearModel.from_dict(fitted['model']))
        self.assertFalse(policy.acquire(RgbAcquisitionView(tuple(rows[0]['features']), 50)))
        self.assertTrue(policy.acquire(RgbAcquisitionView(tuple(rows[1]['features']), 50)))
        with self.assertRaises(ValueError):
            fit_acquisition([*rows, {**rows[0], 'split': 'test'}])

    def test_missing_weights_fail_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                load_models(Path(directory) / 'rgb.pth', Path(directory) / 'fusion.pth')
            weights = Path(directory) / 'toy.pth'
            torch.save({'module.rgb_net.module.x': torch.ones(2)}, weights)
            self.assertEqual(set(load_state(weights, fusion=True)), {'rgb_net.x'})

    def test_selective_metrics_sum_chosen_pixel_counts(self):
        a, b = np.diag([10, 2, 3, 1, 2]), np.diag([20, 3, 3, 2, 1])
        rows = [{'rgb_confusion': a.tolist(), 'fusion_confusion': b.tolist(), 'thermal_bytes': 123}] * 2
        result = summarize(rows, [True, False])
        self.assertEqual((result['pulls'], result['transferred_bytes']), (1, 123))
        self.assertEqual(result['confusion'], (a + b).tolist())

    def test_training_report_and_gated_execution_share_provenance(self):
        """Small fixture exercises orchestration, never writes research results."""
        from phdsim.experiments.pstnet.cache import collect_cache
        from phdsim.experiments.pstnet.acquisition import train_and_compare
        from phdsim.experiments.pstnet.replay import run_gated

        class Rgb(nn.Module):
            def forward(self, image):
                return torch.cat((image[:, :1] + 1, image, image[:, :1]), dim=1)

        class Fusion(nn.Module):
            def forward(self, rgb, thermal, rgb_logits=None):
                return rgb_logits.flip(1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifest.json'
            manifest.write_text('{"unit_test_fixture":true}')
            rgb, fusion = Rgb(), Fusion()
            frames = []
            for i in range(8):
                image, thermal, mask = (root / f'{i}-{name}.png' for name in ('rgb', 'thermal', 'mask'))
                Image.fromarray(np.full((720, 1280, 3), 20 * i, dtype=np.uint8)).save(image)
                Image.fromarray(np.full((720, 1280), 90, dtype=np.uint8)).save(thermal)
                Image.fromarray(np.full((720, 1280), 4 if i % 2 else 0, dtype=np.uint8)).save(mask)
                frames.append(SegmentationFrame(f'{"train" if i < 6 else "test"}/{i}',
                                                 'train' if i < 6 else 'test', f'{i}_bag{i//2+1}', i,
                                                 image, thermal, mask, thermal.stat().st_size))
            provenance = {'unit_test_only': True}
            with patch('phdsim.experiments.pstnet.cache.load_models', return_value=(rgb, fusion, provenance)), \
                    patch('phdsim.experiments.pstnet.replay.load_models', return_value=(rgb, fusion, provenance)), \
                    patch('phdsim.experiments.pstnet.cache.load_frames', return_value=frames), \
                    patch('phdsim.experiments.pstnet.replay.load_frames', return_value=frames) as frame_loader, \
                    patch('phdsim.experiments.pstnet.cache.require_benchmark_split'), \
                    patch('phdsim.experiments.pstnet.replay.require_benchmark_split'):
                cached = collect_cache(manifest, 'unused-rgb', 'unused-fusion', root / 'cache.json')
                self.assertEqual(len(cached['rows']), 8)
                with patch('phdsim.experiments.pstnet.acquisition.load_cache', return_value=cached):
                    report = train_and_compare(root / 'cache.json', root / 'experiment', costs=(0., .01))
                self.assertFalse(report['numerical_reproduction_verified'])
                self.assertEqual(report['test_frames'], 2)
                result = run_gated(manifest, 'unused-rgb', 'unused-fusion', root / 'experiment/acquisition.json',
                                   root / 'replay.json')
                frame_loader.assert_called_with(manifest, verify=False)
                self.assertEqual(result['frames'], 2)
                bundle = json.loads((root / 'experiment/acquisition.json').read_text())
                self.assertEqual(len(bundle['training_frame_ids']), 6)
                self.assertTrue(all(f.startswith('train/') for f in bundle['training_frame_ids']))
                bundle['vision_and_data']['models'] = {'changed': True}
                (root / 'experiment/acquisition.json').write_text(json.dumps(bundle))
                with self.assertRaisesRegex(ValueError, 'different vision weights'):
                    run_gated(manifest, 'unused-rgb', 'unused-fusion', root / 'experiment/acquisition.json',
                              root / 'changed-replay.json')


if __name__ == '__main__':
    unittest.main()
