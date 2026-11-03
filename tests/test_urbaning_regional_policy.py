"""Whole-frame choices, cost units, exact matched controls and F1 aggregation."""
import unittest
import numpy as np

from phdsim.decision.urbaning_regional import choose_regional_subset
from phdsim.decision.urbaning import matched_random_subsets
from phdsim.experiments.urbaning_regional_policy import evaluate


class RegionalPolicyTest(unittest.TestCase):
    def test_joint_head_cost_once_and_signed_cancellation(self):
        y = np.zeros((401, 3, 4))
        y[10, 0, 0] = 4
        y[10, 1, 0] = 3
        y[10, 2, 0] = 1  # both is worse; never sum singles
        ids = ['100000', '200000', '-2']
        self.assertEqual(choose_regional_subset(ids, y, 2), 'vehicle_peer')
        y[400, 0, 0] = -5  # overflow harm must not be discarded/clipped
        self.assertEqual(choose_regional_subset(ids, y, 2), 'infrastructure')
        self.assertEqual(choose_regional_subset(ids, y, 4), 'ego')
        y[:] = 1
        self.assertEqual(choose_regional_subset(ids, y, 500), 'vehicle_peer')  # not 500 per cell
        y[:] = 0
        self.assertEqual(choose_regional_subset(ids, y, 0), 'ego')

    def test_availability_and_invalid_predictions(self):
        y = np.ones((401, 3, 4))
        y[:, 1] *= 100
        self.assertEqual(choose_regional_subset(['100000', '200000'], y, 0), 'vehicle_peer')
        self.assertEqual(choose_regional_subset(['100000'], y, 0), 'ego')
        y[0, 0, 0] = np.nan
        with self.assertRaises(ValueError): choose_regional_subset(['100000'], y, 0)
        with self.assertRaises(ValueError): choose_regional_subset(['100000'], np.zeros((400, 3, 4)), 0)

    def test_random_histogram_and_schedule_semantics(self):
        ids = [['100000', '200000', '-2']]*8 + [['100000', '200000']]*4
        keys = [str(n) for n in range(12)]
        ref = ['ego', 'vehicle_peer', 'infrastructure', 'all']*2 + ['ego', 'vehicle_peer']*2
        def pulls(action): return {'ego': 0, 'vehicle_peer': 1, 'infrastructure': 1, 'all': 2}[action]
        for mode in ('schedule', 'budget'):
            for seed in range(10):
                actual = matched_random_subsets(ids, keys, ref, seed, mode)
                for group in (slice(0, 8), slice(8, 12)):
                    self.assertEqual(sorted(map(pulls, ref[group])), sorted(map(pulls, actual[group])))
                if mode == 'schedule': self.assertEqual(list(map(pulls, ref)), list(map(pulls, actual)))

    def test_f1_is_mean_per_frame_and_not_macro_cell_f1(self):
        counts = np.zeros((2, 4, 4, 3), int)
        counts[0, 0, 0] = [1, 0, 0]
        counts[1, 0, 0] = [0, 0, 9]
        r = evaluate(counts, [['100000']]*2, ['ego']*2)
        self.assertEqual(r['mean_frame_f1'], .5)
        self.assertAlmostEqual(r['micro_f1_all_frames'], 2/11)
        self.assertEqual(r['peer_requests'], 0)
        self.assertIsNone(r['map_0.5'])
        with self.assertRaises(ValueError): evaluate(counts, [['100000']]*2, ['all']*2)


if __name__ == '__main__': unittest.main()
