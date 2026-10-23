"""Opt-in tests against the real pinned weights; synthetic voxels, no dataset scores."""

import os
import unittest

UPSTREAM = os.environ.get('PHDSIM_URBANING_UPSTREAM')
BUNDLE = os.environ.get('PHDSIM_URBANING_MODEL')


@unittest.skipUnless(UPSTREAM and BUNDLE, 'Set PHDSIM_URBANING_UPSTREAM and PHDSIM_URBANING_MODEL')
class ReleasedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from phdsim.experiments.urbaning_stage1 import load_model, prepare_upstream
        prepare_upstream(UPSTREAM)
        torch.set_num_threads(2)
        cls.model, cls.config = load_model(BUNDLE, 'cpu')

    def test_frozen_release_with_one_two_and_three_sources(self):
        import torch
        from phdsim.perception.urbaning.cobevt import subset_inputs

        self.assertEqual(sum(p.numel() for p in self.model.parameters()), 9736008)
        self.assertFalse(self.model.training)
        self.assertTrue(all(not p.requires_grad for p in self.model.parameters()))
        self.assertEqual(self.config['model']['args']['point_pillar_scatter']['grid_size'], [512, 200, 1])
        batch = {'record_len': torch.tensor([3]), 'processed_lidar': {
            'voxel_coords': torch.tensor([[0, 0, 100, 200], [0, 0, 101, 200],
                                          [1, 0, 101, 201], [1, 0, 102, 201],
                                          [2, 0, 102, 202], [2, 0, 103, 202]]),
            'voxel_features': torch.zeros(6, 32, 4),
            'voxel_num_points': torch.ones(6, dtype=torch.int32)}}
        with torch.no_grad():
            for indices in ((0,), (0, 1), (0, 2), (0, 1, 2)):
                result = self.model(subset_inputs(batch, indices))
                self.assertEqual(tuple(result['psm'].shape), (1, 32, 100, 256))
                self.assertEqual(tuple(result['rm'].shape), (1, 56, 100, 256))
                self.assertTrue(all(bool(value.isfinite().all()) for value in result.values()))

    def test_perfect_and_empty_predictions_share_gt_and_evaluation_is_repeatable(self):
        import torch
        from phdsim.evaluation.urbaning import accumulate, empty_statistics, summarize

        square = torch.tensor([[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0],
                               [0, 0, 2], [2, 0, 2], [2, 2, 2], [0, 2, 2]], dtype=torch.float32)
        boxes = torch.stack([square + torch.tensor([10 + i * 5, 0, 0]) for i in range(4)])
        labels = torch.arange(1, 5)
        scores = torch.stack((torch.ones(4), labels.float()), dim=1)
        perfect, empty = empty_statistics(), empty_statistics()
        accumulate(perfect, boxes, scores, boxes, labels)
        accumulate(empty, boxes[:0], scores[:0], boxes, labels)
        first = summarize(perfect)
        self.assertEqual(first, summarize(perfect))
        self.assertAlmostEqual(first['macro_ap']['0.5'], 1.0, places=7)
        self.assertAlmostEqual(summarize(empty)['macro_ap']['0.5'], 0.0)
        for name in perfect:
            self.assertEqual(perfect[name][0.5]['gt'], empty[name][0.5]['gt'])
        self.assertIsNone(summarize(empty_statistics())['macro_ap']['0.5'])


if __name__ == '__main__':
    unittest.main()
