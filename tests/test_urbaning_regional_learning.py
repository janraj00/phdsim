"""Regional regression masks, deployment boundary and dataset label integrity."""
import copy
import unittest

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER
from phdsim.evaluation.urbaning import CLASSES
from phdsim.experiments.urbaning_regional_learning import metrics, validate_arrays, validate_headers
from phdsim.learning.urbaning_regions import FEATURES, SCHEMA, cell_centers
from phdsim.learning.urbaning_regional_gain import PROFILES, fit_candidates, predict


class RegionalLearningTest(unittest.TestCase):
    def example(self):
        rng = np.random.default_rng(10)
        x = rng.normal(size=(4, 401, 46))
        mask = np.array([[1, 1, 1, 1], [1, 1, 1, 1], [1, 0, 1, 0], [1, 0, 1, 0]], bool)
        x[:, :, 30] = mask[:, 1, None]; x[:, :, 38] = mask[:, 2, None]
        y = np.zeros((4, 401, 3, 4))
        y[:, :, 0, 0] = x[:, :, 5] * 2 - 1
        y[:, :, 1, 0] = x[:, :, 5] * -3
        y[:, :, 2, 0] = x[:, :, 5] * .5 + .25  # explicit nonadditive joint head
        return x, mask, y

    def test_unavailable_labels_cannot_change_fit(self):
        x, mask, y = self.example()
        a = fit_candidates(x, mask, y, 'local')[0]
        poisoned = y.copy()
        for j in range(3): poisoned[~mask[:, j+1], :, j] = 1e12
        b = fit_candidates(x, mask, poisoned, 'local')[0]
        self.assertEqual(a, b)
        p = predict(a, x, mask)
        self.assertTrue((p[~mask[:, 1], :, 0] == 0).all())
        self.assertTrue((p[:2, :, 0, 0] < 0).any())  # signed harm retained
        self.assertFalse(np.allclose(p[:2, :, 2], p[:2, :, 0] + p[:2, :, 1]))

    def test_validation_only_inputs_do_not_mutate_model_or_fit_scaling(self):
        x, mask, y = self.example()
        model = fit_candidates(x, mask, y, 'full')[0]
        before = copy.deepcopy(model)
        shifted = x.copy(); shifted[:, :, 5] += 100
        predict(model, shifted, mask)
        self.assertEqual(before, model)
        broken = copy.deepcopy(model); broken['input_features'].reverse()
        with self.assertRaises(ValueError): predict(broken, x, mask)
        with self.assertRaises(ValueError): predict(model, x, ~mask)
        self.assertEqual([len(v) for v in PROFILES.values()], [20, 10, 27, 30, 46])
        self.assertTrue(set(PROFILES['geometry']) <= set(PROFILES['geometry_local']))

    def manifest(self):
        return {'schema': SCHEMA, 'status': 'completed', 'features': list(FEATURES),
                'actions': list(ACTION_ORDER), 'classes': list(CLASSES), 'count_order': ['tp', 'fp', 'fn'],
                'grid': {'cell_size_m': 10., 'min_xy': -100., 'max_xy_exclusive': 100.,
                         'shape': [20, 20], 'spatial_cells': 400, 'overflow_cell': 400},
                'sequences': [{'split': 'train', 'sequence': '20241126_0001_crossing2_00'},
                              {'split': 'validation', 'sequence': '20241126_0004_crossing2_00'}],
                'recording_groups': {'train': ['20241126_0001'], 'validation': ['20241126_0004']}}

    def test_split_headers_reject_test_and_original_recording_overlap(self):
        m = self.manifest(); validate_headers(m)
        for seq in ('20241126_0001_crossing2_01', '20241127_0009_crossing3_00'):
            invalid = copy.deepcopy(m); invalid['sequences'][1]['sequence'] = seq
            with self.assertRaises(ValueError): validate_headers(invalid)

    def test_count_conservation_and_mask_integrity(self):
        x, _, _ = self.example()
        x = x[:1]; x[:, :, 30] = 1; x[:, :, 38] = 0
        mask = np.array([[1, 1, 0, 0]], bool)
        seq = '20241126_0001_crossing2_00'; keys = np.array([seq + ':000001:100000'])
        inputs = {'features': x, 'available': mask, 'frame_keys': keys, 'cell_centers': cell_centers()}
        counts = np.zeros((1, 401, 4, 4, 3), dtype=np.int32); counts[:, :, 2:] = -1
        counts[0, 2, 0, 0, 2] = 1; counts[0, 2, 1, 0, 0] = 1
        delta = np.zeros_like(counts); delta[:, :, 1] = counts[:, :, 1] - counts[:, :, 0]
        rec = np.zeros((1, 401, 4, 4), dtype=np.int32); rec[:, :, 2:] = -1
        lost = rec.copy(); rec[0, 2, 1, 0] = 1
        gt = np.zeros((1, 401, 4), dtype=np.int32); gt[0, 2, 0] = 1
        labels = {'counts': counts, 'delta_vs_ego': delta, 'recovered_gt': rec, 'lost_gt': lost,
                  'gt_counts': gt, 'available': mask, 'frame_keys': keys}
        metadata = [{'frame_key': keys[0], 'sequence': seq, 'recording_group': '20241126_0001',
                     'source_ids': ['100000', '200000']}]
        data = validate_arrays(inputs, labels, metadata, seq)
        self.assertEqual(data['gain'][0, 2, 0, 0], 1)
        invalid = copy.deepcopy(labels); invalid['delta_vs_ego'][0, 2, 2, 0, 0] = 1
        with self.assertRaises(ValueError): validate_arrays(inputs, invalid, metadata, seq)
        invalid = copy.deepcopy(labels); invalid['gt_counts'][0, 2, 0] = 0
        with self.assertRaises(ValueError): validate_arrays(inputs, invalid, metadata, seq)

    def test_sparse_targets_and_rank_controls_are_explicit(self):
        _, mask, y = self.example()
        m = metrics(np.zeros_like(y), y, mask)
        a = m['heads']['vehicle_peer']
        self.assertEqual(a['available_frames'], 2)
        self.assertEqual(a['classes']['Vehicle']['all']['cells'], 802)
        self.assertEqual(a['classes']['Heavy_Vehicle']['changed']['cells'], 0)
        self.assertIsNone(a['classes']['Heavy_Vehicle']['changed']['mae'])
        actual = y[:2, :400, 0].sum(axis=2)
        self.assertAlmostEqual(a['ranking']['random_top10_expected_gain'], actual.sum(axis=1).mean()/40)


if __name__ == '__main__':
    unittest.main()
