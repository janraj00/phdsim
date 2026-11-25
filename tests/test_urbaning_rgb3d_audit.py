import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('rgb_audit', Path(__file__).parents[1]/'scripts/audit_urbaning_rgb3d_finetune.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def source_box(center=(10, 0, 0), length=4, width=2, height=2):
    # Independent pinned OpenCOOD boxes_to_corners_3d template (edge01=W).
    unit = np.array([[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,-1],
                     [1,-1,1],[1,1,1],[-1,1,1],[-1,-1,1]], float)/2
    return unit*np.array([length, width, height])+center


class AuditTests(unittest.TestCase):
    def test_portable_ap_tolerance_does_not_relax_counts_or_large_changes(self):
        self.assertLess(audit.metric_difference({'ap': .5+1e-9, 'gt': 5}, {'ap': .5, 'gt': 5}), 1e-7)
        for actual in ({'ap': .6, 'gt': 5}, {'ap': .5, 'gt': 6}, {'ap': float('nan'), 'gt': 5}):
            with self.assertRaises(ValueError):
                audit.metric_difference(actual, {'ap': .5, 'gt': 5})

    def test_source_native_width_length_semantics_mismatch_is_detectable(self):
        from phdsim.perception.urbaning.rgb3d_finetune import projected_targets
        e = np.array([[0., -1, 0, 0], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]])
        k = np.array([[100., 0, 160], [0, 100, 100], [0, 0, 1]])
        gt = source_box()[None]
        row = projected_targets(gt, [1], e, k, 320, 200)[0]
        # Audit the HISTORICAL labels; do not silently repair/retrain them here.
        np.testing.assert_allclose(row['dimensions'], [4, 2, 2])
        self.assertFalse(np.allclose(row['dimensions'], [2, 2, 4]))

    def test_audit_detects_a_historical_near_plane_skip(self):
        from phdsim.perception.urbaning.rgb3d_finetune import projected_targets
        e = np.array([[0., -1, 0, 0], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]])
        k = np.array([[100., 0, 160], [0, 100, 100], [0, 0, 1]])
        gt = np.array([source_box((0, 0, -1)), source_box((10, 0, 0))])
        blockers = audit.near_plane_blockers(gt, e, k, 320, 200)
        self.assertEqual([b['gt_index'] for b in blockers], [0])
        self.assertEqual(audit.near_plane_blockers(gt[1:], e, k, 320, 200), [])

        targets = projected_targets(gt, [1, 1], e, k, 320, 200)
        self.assertEqual([target['gt_index'] for target in targets], [0, 1])
        self.assertTrue(targets[0]['near_plane_ignore'])
        self.assertEqual(targets[1]['class'], 0)

    def test_fp_geometry_separates_duplicates_class_and_no_overlap(self):
        gt = source_box()[None]
        boxes = np.array([source_box(), source_box(), source_box(), source_box((30, 0, 0))])
        scores = np.array([[.9, 1], [.8, 1], [.7, 4], [.6, 1]])
        _, matched, _ = audit.match_frame(boxes, scores, gt, np.array([1]))
        rows = audit.fp_rows(boxes, scores, gt, np.array([1]), matched)
        self.assertEqual({r['prediction_index']:r['reason'] for r in rows},
            {1:'same_class_duplicate_at_05', 2:'other_class_overlap_at_05', 3:'no_gt_bev_overlap'})


if __name__ == '__main__':
    unittest.main()
