import contextlib
import inspect
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from phdsim.evaluation.urbaning_cached import (
    aggregate_statistics, frame_statistics, summarize_cached)
from phdsim.experiments.urbaning_rgb3d_additive import (
    compare_frame, NEW_VARIANTS, run)
from phdsim.experiments.urbaning_rgb3d_complementarity import audit_frame, sha
from phdsim.perception.urbaning.rgb3d_additive import additive_fuse
from phdsim.perception.urbaning.rgb3d_late import late_fuse


def box(x):
    unit = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                     [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], float)
    return unit+np.array([x, 0, 0])


def example():
    return {'lidar_boxes': np.array([box(10)]), 'lidar_scores': np.array([[.4, 1.]]),
            'rgb_baseline_boxes': np.array([box(10.9), box(20)]),
            'rgb_baseline_scores': np.array([[.9, 1.], [.8, 1.]]),
            'rgb_depth_boxes': np.array([box(10), box(20)]),
            'rgb_depth_scores': np.array([[.9, 1.], [.8, 1.]]),
            'gt_boxes': np.array([box(10), box(20), box(30), box(40), box(50)]),
            'gt_labels': np.array([1, 1, 2, 3, 4])}


class Additive(unittest.TestCase):
    def test_block_destructive_rgb_keep_lidar_and_accept_new_object(self):
        d = example()
        before = {k: v.copy() for k, v in d.items()}
        stats, traces, output = compare_frame(d)
        t = traces['baseline_additive_raw']
        self.assertEqual(t['rgb_added'], 1)
        self.assertEqual(len(t['losses']), 0)
        self.assertEqual(len(t['fusion_gained_objects']), 1)
        b, s, keep, decisions = output['baseline_additive_raw']
        np.testing.assert_array_equal(b[0], d['lidar_boxes'][0])
        np.testing.assert_array_equal(s[0], d['lidar_scores'][0])
        self.assertEqual(keep.tolist(), [0, 2])
        self.assertEqual(decisions[0]['decision'], 'overlaps_lidar')
        self.assertEqual(decisions[1]['decision'], 'accepted')
        for v, (b, s, _, _) in output.items():
            self.assertEqual(stats[v], frame_statistics(b, s, d['gt_boxes'], d['gt_labels']))
        for k in d:
            np.testing.assert_array_equal(d[k], before[k])
        self.assertEqual(set(inspect.signature(additive_fuse).parameters),
                         {'lidar_boxes', 'lidar_scores', 'rgb_boxes', 'rgb_scores', 'lidar_first'})

    def test_keep_mutually_overlapping_lidar_and_handle_empty_sources(self):
        lb = np.array([box(10), box(10.1)])
        ls = np.array([[.4, 1.], [.8, 1.]])
        empty_b, empty_s = np.empty((0, 8, 3)), np.empty((0, 2))
        b, s, keep, _ = additive_fuse(lb, ls, empty_b, empty_s)
        np.testing.assert_array_equal(b, lb)
        np.testing.assert_array_equal(s, ls)
        self.assertEqual(keep.tolist(), [0, 1])
        b, s, keep, decisions = additive_fuse(empty_b, empty_s, lb, ls)
        self.assertEqual(keep.tolist(), [1])
        self.assertEqual([d['decision'] for d in decisions], ['accepted', 'overlaps_rgb'])
        b, s, keep, _ = additive_fuse(empty_b, empty_s, empty_b, empty_s)
        self.assertEqual(b.shape, (0, 8, 3))
        self.assertEqual(s.shape, (0, 2))

    def test_same_class_filter_stable_ties_and_lidar_first_rank_range(self):
        lb, ls = np.array([box(10)]), np.array([[0., 1.]])
        rb, rs = np.array([box(10), box(20), box(20.1)]), np.array([[1., 4.], [1., 1.], [1., 1.]])
        b, s, keep, decisions = additive_fuse(lb, ls, rb, rs, lidar_first=True)
        self.assertEqual(keep.tolist(), [0, 1, 2])
        np.testing.assert_array_equal(s[:, 0], [.5, .49, .49])
        self.assertEqual(decisions[-1]['decision'], 'overlaps_rgb')
        np.testing.assert_array_equal(ls, [[0., 1.]])
        np.testing.assert_array_equal(rs[:, 0], [1., 1., 1.])

    def test_false_positive_addition_can_lower_raw_ap_but_priority_masks_that_ap_loss(self):
        gt = np.array([box(10)]); labels = np.array([1])
        lb, ls = gt.copy(), np.array([[.8, 1.]])
        rb, rs = np.array([box(30)]), np.array([[.99, 1.]])
        results = []
        for first in (False, True):
            b, s, _, _ = additive_fuse(lb, ls, rb, rs, lidar_first=first)
            stat = frame_statistics(b, s, gt, labels)
            m = summarize_cached(stat)['classes']['Vehicle']['ap']['0.5']
            self.assertEqual(sum(stat['Vehicle'][.5]['fp']), 1)
            results.append(m)
        self.assertAlmostEqual(results[0], .5, places=6)
        self.assertAlmostEqual(results[1], 1., places=6)
        # Priority AP must not be presented as calibrated precision or as proof
        # that added proposals are useful: this RGB proposal is simply false.

    def test_priority_can_change_greedy_assignments_without_changing_boxes(self):
        def wide(x):
            b = box(x); b[:, 0] = x+2*(b[:, 0]-x); return b
        gt, labels = np.array([wide(10), wide(12)]), np.array([1, 1])
        lb, ls = np.array([box(9)]), np.array([[.4, 1.]])
        rb, rs = np.array([box(11)]), np.array([[.9, 1.]])
        hits = []
        for first in (False, True):
            b, s, _, _ = additive_fuse(lb, ls, rb, rs, lidar_first=first)
            np.testing.assert_array_equal(b, np.r_[lb, rb])
            hits.append(sum(frame_statistics(b, s, gt, labels)['Vehicle'][.5]['tp']))
        self.assertEqual(hits, [1, 2])

    def test_cached_archive_guards_and_new_outcome_replay(self):
        d = example()
        metrics = {}
        rb, rs = d['rgb_baseline_boxes'], d['rgb_baseline_scores']
        db, ds = d['rgb_depth_boxes'], d['rgb_depth_scores']
        b, s, _ = late_fuse(d['lidar_boxes'], d['lidar_scores'], rb, rs)
        nb, ns, _ = late_fuse(d['lidar_boxes'], d['lidar_scores'], db, ds)
        arrays = {'lidar': (d['lidar_boxes'], d['lidar_scores']), 'rgb_baseline': (rb, rs),
                  'rgb_depth_finetuned': (db, ds), 'lidar_rgb_baseline': (b, s),
                  'lidar_rgb_depth_finetuned': (nb, ns)}
        for v, (b, s) in arrays.items():
            stat = aggregate_statistics([frame_statistics(b, s, d['gt_boxes'], d['gt_labels'])])
            metrics[v] = {name: summarize_cached(stat, glob) for name, glob in (
                ('global_confidence_sort', True), ('upstream_default_frame_order', False))}
        source_report = {'schema': 'phdsim-rgb3d-native-depth-controlled-v1',
                         'train_metrics': metrics, 'validation_metrics': metrics}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'source.zip'
            def write_source():
                with zipfile.ZipFile(source, 'w') as z:
                    z.writestr('report.json', json.dumps(source_report))
                    for split, seq in [('train', '0001'), ('validation', '0004')]:
                        f = io.BytesIO(); np.savez_compressed(f, **d)
                        z.writestr('frames-'+split+'/20241126_'+seq+'_crossing2_00_000001_100000.npz', f.getvalue())
            write_source(); original = source.read_bytes()
            done = root/'completed.json'; done.write_text(json.dumps({'sha256': sha(original)}))
            with contextlib.redirect_stdout(io.StringIO()):
                archive = run(source, root/'output', expected_counts=(1, 1))
            self.assertEqual(source.read_bytes(), original)
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                r = json.loads(z.read('report.json'))
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.npz')]), 2)
                for split in ('train', 'validation'):
                    row = r['splits'][split]
                    self.assertTrue(row['source_ap_reproduced'])
                    self.assertTrue(row['saved_new_ap_reproduced'])
                    for v in NEW_VARIANTS:
                        self.assertEqual(row['variants'][v]['total']['fusion_lost'], 0)
            with self.assertRaisesRegex(ValueError, 'fresh'):
                run(source, root/'output', expected_counts=(1, 1))
            source_report['validation_metrics']['lidar']['global_confidence_sort']['macro_ap']['0.5'] += .01
            write_source()
            with self.assertRaisesRegex(ValueError, 'checksum'):
                run(source, root/'bad-checksum', expected_counts=(1, 1))
            done.unlink()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'AP parity'):
                run(source, root/'bad-ap', expected_counts=(1, 1))
            self.assertFalse((root/'bad-ap/report.json').exists())


if __name__ == '__main__':
    unittest.main()
