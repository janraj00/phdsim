import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from phdsim.evaluation.urbaning_cached import frame_statistics, summarize_cached, aggregate_statistics
from phdsim.experiments.urbaning_rgb3d_complementarity import (
    audit_frame, combine, match_frame, run, sha, VARIANTS)
from phdsim.experiments.urbaning_rgb3d_depth import variants_from_arrays


def box(x, y=0):
    unit = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                     [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], float)
    return unit+np.array([x, y, 0])


def example():
    return {'lidar_boxes': np.array([box(10)]), 'lidar_scores': np.array([[.4, 1.]]),
            'rgb_baseline_boxes': np.array([box(10.9), box(20)]),
            'rgb_baseline_scores': np.array([[.9, 1.], [.8, 1.]]),
            'rgb_depth_boxes': np.array([box(10), box(20)]),
            'rgb_depth_scores': np.array([[.9, 1.], [.8, 1.]]),
            'gt_boxes': np.array([box(10), box(20), box(30), box(40), box(50)]),
            'gt_labels': np.array([1, 1, 2, 3, 4])}


class Complementarity(unittest.TestCase):
    def test_new_rgb_gt_and_destructive_rgb_nms_are_distinct(self):
        data = example()
        stats, pairs = audit_frame(data)
        row = combine([pairs['baseline']])['total']
        self.assertEqual(row['lidar_tp'], 1)
        self.assertEqual(row['rgb_tp'], 1)
        self.assertEqual(row['rgb_additional'], 1)
        self.assertEqual(row['fusion_gained'], 1)
        self.assertEqual(row['fusion_lost'], 1)
        self.assertEqual(row['lost_lidar_suppressed_by_rgb'], 1)
        self.assertEqual(row['rgb_fp'], 1)
        loss = pairs['baseline']['losses'][0]
        self.assertLess(loss['blocker_gt_iou'], .5)
        self.assertGreater(loss['lidar_gt_iou'], .5)
        self.assertEqual(pairs['baseline']['rgb_additional_objects'][0]['gt_index'], 1)
        corrected = combine([pairs['depth_finetuned']])['total']
        self.assertEqual(corrected['fusion_lost'], 0)
        self.assertEqual(corrected['fusion_tp'], 2)
        # The unchanged score rule is the same; only RGB geometry differs.
        for v, (b, s) in variants_from_arrays(data).items():
            self.assertEqual(stats[v], frame_statistics(b, s, data['gt_boxes'], data['gt_labels']))

    def test_tied_scores_lidar_precedes_rgb_and_empty_rgb(self):
        d = example()
        d['rgb_baseline_scores'][0, 0] = .4
        _, pairs = audit_frame(d)
        self.assertEqual(combine([pairs['baseline']])['total']['fusion_lost'], 0)
        d['rgb_baseline_boxes'] = np.empty((0, 8, 3))
        d['rgb_baseline_scores'] = np.empty((0, 2))
        _, pairs = audit_frame(d)
        row = combine([pairs['baseline']])['total']
        self.assertEqual(row['rgb_additional'], 0)
        self.assertEqual(row['fusion_lost'], 0)
        self.assertEqual(row['lidar_only'], 1)

    def test_identity_matches_reproduce_all_thresholds_and_radius_class_filters(self):
        gt = np.array([box(10), box(10, 3), box(200)])
        labels = np.array([1, 4, 1])
        b = np.array([box(10+2/3), box(10), box(10, 3), box(200), box(30)])
        s = np.array([[.8, 1], [.7, 1], [.8, 4], [.99, 1], [.9, 2]])
        stats, matches, ids = match_frame(b, s, gt, labels)
        self.assertEqual(stats, frame_statistics(b, s, gt, labels))
        self.assertEqual(set(matches), {0, 1})
        self.assertNotIn(3, ids)
        self.assertEqual(stats['Vehicle'][.5]['tp'], [1, 0])
        # Two appearances of one frame are counted twice, not as one track.
        _, pairs = audit_frame(example())
        self.assertEqual(combine([pairs['baseline']]*2)['total']['rgb_additional'], 2)

    def test_retained_lidar_prediction_can_change_gt_identity(self):
        # Two small, adjacent LiDAR boxes match two overlapping wider GTs.
        # A bad RGB box suppresses the first LiDAR box. The retained second
        # LiDAR box then greedily switches GT identity; this is NOT its NMS loss.
        def wide(center):
            b = box(center)
            b[:, 0] = center+(b[:, 0]-center)*2
            return b
        d = example()
        d.update(lidar_boxes=np.array([box(9), box(11)]),
                 lidar_scores=np.array([[.8, 1.], [.7, 1.]]),
                 rgb_baseline_boxes=np.array([box(8.2)]),
                 rgb_baseline_scores=np.array([[.9, 1.]]),
                 gt_boxes=np.array([wide(10), wide(12)]), gt_labels=np.array([1, 1]))
        _, pairs = audit_frame(d)
        c = combine([pairs['baseline']])['total']
        self.assertEqual(c['lidar_tp'], 2)
        self.assertEqual(c['fusion_tp'], 1)
        self.assertEqual(c['lost_lidar_retained_matching_changed'], 1)
        self.assertEqual(c['lost_lidar_suppressed_by_rgb'], 0)

    def test_archive_ap_guard_source_preservation_and_portable_results(self):
        d = example()
        metrics = {}
        for v, (b, s) in variants_from_arrays(d).items():
            stats = aggregate_statistics([frame_statistics(b, s, d['gt_boxes'], d['gt_labels'])])
            metrics[v] = {name: summarize_cached(stats, glob) for name, glob in
                          [('global_confidence_sort', True), ('upstream_default_frame_order', False)]}
        source_report = {'schema': 'phdsim-rgb3d-native-depth-controlled-v1',
                         'train_metrics': metrics, 'validation_metrics': metrics}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'source.zip'
            def write_source(report):
                with zipfile.ZipFile(source, 'w') as z:
                    z.writestr('report.json', json.dumps(report))
                    for split in ('train', 'validation'):
                        p = io.BytesIO()
                        np.savez_compressed(p, **d)
                        z.writestr('frames-'+split+'/20241126_0004_crossing2_00_000001_100000.npz', p.getvalue())
            write_source(source_report)
            initial = source.read_bytes()
            (root/'completed.json').write_text(json.dumps({'sha256': sha(initial)}))
            with contextlib.redirect_stdout(io.StringIO()):
                result = run(source, root/'audit', expected_counts=(1, 1))
            self.assertEqual(source.read_bytes(), initial)
            with zipfile.ZipFile(result) as z:
                self.assertIsNone(z.testzip())
                r = json.loads(z.read('report.json'))
                val = r['splits']['validation']
                self.assertTrue(val['source_ap_reproduced'])
                self.assertEqual(val['metrics'], metrics)
                self.assertEqual(val['stages']['baseline']['total']['rgb_additional'], 1)
            with self.assertRaisesRegex(ValueError, 'fresh'):
                run(source, root/'audit', expected_counts=(1, 1))
            source_report['validation_metrics']['lidar']['global_confidence_sort']['macro_ap']['0.5'] += .01
            write_source(source_report)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                run(source, root/'bad-checksum', expected_counts=(1, 1))
            (root/'completed.json').unlink()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'AP parity'):
                run(source, root/'bad-ap', expected_counts=(1, 1))
            self.assertFalse((root/'bad-ap/report.json').exists())


if __name__ == '__main__':
    unittest.main()
