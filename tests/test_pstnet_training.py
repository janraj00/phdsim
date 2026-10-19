"""Meaningful checks for split isolation, weighted evaluation, and optimization."""

from dataclasses import replace
from pathlib import Path
import unittest
import numpy as np
import torch
from torch import nn

from phdsim.datasets.pst900.segmentation import SegmentationFrame
from phdsim.perception.pstnet.training.config import RgbTrainingConfig
from phdsim.perception.pstnet.training.data import make_rgb_plan, class_weights, load_rgb_samples
from phdsim.perception.pstnet.training.trainer import evaluate, fit_epoch


class RgbPilotTests(unittest.TestCase):
    def test_plan_is_family_disjoint_and_independent_of_input_order(self):
        frames = [SegmentationFrame(f'{split}/{group}/{i}', split, f'{group}_bag{group}', i,
                                    Path('unavailable-rgb'), Path('unavailable-thermal'), Path('unavailable-mask'), 3)
                  for split, group in [('train', 1), ('train', 2), ('train', 3), ('train', 4), ('test', 21)]
                  for i in range(4)]
        config = RgbTrainingConfig(train_frames=5, validation_frames=2, validation_families=('bag1',), acquisition_families=('bag4',))
        train, validation, plan = make_rgb_plan(frames, config)
        self.assertEqual(plan, make_rgb_plan(tuple(reversed(frames)), config)[2])
        self.assertEqual({f.sequence_id for f in train}, {'2_bag2', '3_bag3'})
        self.assertEqual({f.sequence_id for f in validation}, {'1_bag1'})
        self.assertEqual((plan['acquisition_reserved_frames'], plan['official_test_frames_unused']), (4, 4))
        self.assertEqual(set(plan['train_frame_ids']) & set(plan['validation_frame_ids']), set())
        with self.assertRaises(ValueError):
            load_rgb_samples([f for f in frames if f.split == 'test'])
        with self.assertRaises(ValueError):
            RgbTrainingConfig(validation_families=('bag1',), acquisition_families=('bag1',))

    def test_class_weights_use_pixel_frequencies(self):
        mask = torch.tensor([[[0, 0, 0, 0, 1, 2, 3, 4]]])
        weights, counts = class_weights([{'mask': mask}])
        self.assertEqual(counts, [4, 1, 1, 1, 1])
        np.testing.assert_allclose(weights.numpy(), 1 / np.log(1.02 + np.array(counts) / 8), rtol=1e-6)
        self.assertGreater(float(weights[1]), float(weights[0]))
        with self.assertRaises(ValueError):
            class_weights([{'mask': torch.zeros((1, 2, 2), dtype=torch.long)}])

    def test_real_gradient_updates_reduce_loss_on_separable_pixels(self):
        torch.set_num_threads(1)
        torch.manual_seed(3)
        # A tiny model isolates optimizer and evaluator behavior, independent of CNN quality.
        model = nn.Conv2d(3, 5, 1)
        rgb = torch.tensor([[[[0., 0., 1., 1.]], [[0., 1., 0., 1.]], [[1., 0., 0., 1.]]]])
        samples = [{'rgb': rgb, 'mask': torch.tensor([[[1, 2, 3, 4]]])}]
        weights = torch.tensor([1., 2., 3., 4., 5.])
        before = evaluate(model, samples, weights)
        initial = model.weight.detach().clone()
        optimizer = torch.optim.SGD(model.parameters(), lr=.4)
        config = RgbTrainingConfig(epochs=6)
        for epoch in range(1, 7):
            fit_epoch(model, samples, optimizer, weights, config, epoch)
        after = evaluate(model, samples, weights)
        self.assertFalse(torch.equal(initial, model.weight))
        self.assertLess(after['weighted_cross_entropy'], before['weighted_cross_entropy'])
        self.assertEqual(after['pixels'], 4)
        self.assertTrue(np.isfinite(after['miou']))


if __name__ == '__main__':
    unittest.main()
