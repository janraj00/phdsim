import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets
from phdsim.evaluation.urbaning_cached import frame_f1, frame_statistics
from phdsim.experiments.urbaning_frame_inspection import audit_frame
from phdsim.experiments.urbaning_regional_dataset import main, regional_targets, validate_split_headers
from phdsim.experiments.urbaning_subsets import digest, load_runs
from phdsim.learning.urbaning_geometry import SCHEMA as POSE_SCHEMA
from phdsim.learning.urbaning_regions import (
    CELL_COUNT, FEATURES, OVERFLOW, assign_cells, cell_centers, regional_features)
from test_urbaning_geometry import transform
from test_urbaning_subsets import IDS, box, make_run

try:
    import matplotlib
except ImportError:
    matplotlib = None


class RegionalInputTests(unittest.TestCase):
    def test_grid_boundaries_overflow_and_fixed_no_detection_cells(self):
        np.testing.assert_array_equal(assign_cells([[-100, -100], [99.9, 99.9], [100, 0], [-101, 5]]),
                                      [0, 399, OVERFLOW, OVERFLOW])
        self.assertEqual(cell_centers().shape, (401, 2))
        boxes = np.array([box(-95, -95), box(-94, -94), box(103, 0)])
        scores = np.array([[.3, 1], [.9, 4], [.7, 2]])
        x, mask = regional_features(IDS, .8, boxes, scores,
                                    {'200000': transform(-30), '-1': transform(-60)})
        self.assertEqual(x.shape, (CELL_COUNT, 46))
        self.assertTrue(mask.all())
        features = lambda name: x[:, FEATURES.index(name)]
        self.assertAlmostEqual(features('ego_count_over_10')[0], .2)
        self.assertAlmostEqual(features('ego_score_mean')[0], .6)
        self.assertAlmostEqual(features('ego_score_min')[0], .3)
        self.assertAlmostEqual(features('ego_score_std')[0], .3)
        self.assertEqual(features('ego_empty')[200], 1.)
        self.assertEqual(features('overflow_cell')[OVERFLOW], 1.)
        self.assertAlmostEqual(features('ego_count_over_10')[OVERFLOW], .1)
        self.assertAlmostEqual(features('neighbor_count_over_10')[1], .2)
        self.assertEqual(features('neighbor_count_over_10')[399], 0.)  # no grid-edge wrap
        self.assertEqual(features('car2_distance_over_100')[OVERFLOW], 0.)
        self.assertEqual(features('car2_available')[OVERFLOW], 1.)
        other, _ = regional_features(IDS, .8, boxes[::-1], scores[::-1],
                                    {'200000': transform(-30), '-1': transform(-60)})
        np.testing.assert_allclose(x, other, atol=1e-7)

    def test_missing_peers_empty_boxes_and_input_allowlist(self):
        x, mask = regional_features(['100000', '-1'], .4, np.empty((0, 8, 3)),
                                    np.empty((0, 2)), {'-1': transform(10)})
        np.testing.assert_array_equal(mask, [True, False, True, False])
        self.assertTrue(np.all(x[:, FEATURES.index('ego_empty')] == 1))
        self.assertTrue(np.all(x[:, FEATURES.index('car2_available')] == 0))
        self.assertTrue(np.isfinite(x).all())
        with self.assertRaises(ValueError):
            regional_features(IDS, .4, np.empty((0, 8, 3)), np.empty((0, 2)), {})
        with self.assertRaises(TypeError):
            regional_features(['100000'], .4, np.empty((0, 8, 3)), np.empty((0, 2)), {}, gt_boxes=[])


def audit_data(data, ids=IDS):
    quality = {a: frame_f1(frame_statistics(data[a+'_boxes'], data[a+'_scores'],
                                           data['gt_boxes'], data['gt_labels'])) for a in available_subsets(ids)}
    return audit_frame({'key': 'fixture', 'sequence': 'fixture', 'source_ids': ids, 'quality': quality}, data)


class RegionalTargetTests(unittest.TestCase):
    def test_cross_cell_matches_overflow_and_radius_exclusion_conserve_counts(self):
        gt = np.array([box(-.2, 0), box(100.5, 0), box(200, 0)])
        data = {'gt_boxes': gt, 'gt_labels': np.array([1, 2, 3])}
        for action in ACTION_ORDER:
            data[action+'_boxes'] = np.array([box(.2, 0), box(100.5, 0), box(200, 0)])
            data[action+'_scores'] = np.array([[.9, 1], [.8, 2], [.7, 3]])
        audit = audit_data(data)
        target = regional_targets(data, audit)
        gt_cell = assign_cells([[-.2, 0]])[0]
        pred_cell = assign_cells([[.2, 0]])[0]
        self.assertNotEqual(gt_cell, pred_cell)
        self.assertEqual(target['counts'][gt_cell, 0, 0, 0], 1)
        self.assertEqual(target['counts'][pred_cell, 0, 0, 0], 0)
        self.assertEqual(target['counts'][OVERFLOW, 0, 1, 0], 1)
        self.assertEqual(int(target['gt_counts'].sum()), 2)  # far GT excluded by frozen radius filter
        np.testing.assert_array_equal(target['delta_vs_ego'], 0)
        for j in range(4):
            np.testing.assert_array_equal(target['counts'][:, j].sum(axis=(0, 1)), [2, 0, 0])

    def test_recoveries_losses_false_alarms_and_unavailable_actions(self):
        gt = np.array([box(10), box(30)])
        data = {'gt_boxes': gt, 'gt_labels': np.array([1, 2])}
        selections = {'ego': ([gt[0]], [[.9, 1]]),
                      'vehicle_peer': ([gt[1], box(50)], [[.9, 2], [.8, 4]]),
                      'infrastructure': (list(gt), [[.9, 1], [.8, 2]]),
                      'all': ([], [])}
        for action, (boxes, scores) in selections.items():
            data[action+'_boxes'] = np.array(boxes).reshape(-1, 8, 3)
            data[action+'_scores'] = np.array(scores).reshape(-1, 2)
        target = regional_targets(data, audit_data(data))
        self.assertEqual(int(target['recovered_gt'][:, 1].sum()), 1)
        self.assertEqual(int(target['lost_gt'][:, 1].sum()), 1)
        self.assertEqual(int(target['delta_vs_ego'][:, 1, :, 1].sum()), 1)
        self.assertEqual(int(target['delta_vs_ego'][:, 3, :, 2].sum()), 1)
        missing = regional_targets(data, audit_data(data, ['100000']))
        np.testing.assert_array_equal(missing['available'], [True, False, False, False])
        self.assertTrue(np.all(missing['counts'][:, 1:] == -1))
        self.assertTrue(np.all(missing['recovered_gt'][:, 1:] == -1))
        self.assertTrue(np.all(missing['delta_vs_ego'][:, 1:] == 0))


@unittest.skipIf(matplotlib is None, 'matplotlib required for validation map')
class RegionalExportTests(unittest.TestCase):
    def test_complete_export_input_boundary_join_keys_hashes_and_output_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequences = ['20241126_0017_crossing1_00', '20241126_0001_crossing2_00', '20241126_0004_crossing2_00']
            runs, poses = [], []
            for i, sequence in enumerate(sequences):
                run = make_run(root / ('run'+str(i)), sequence, frames=3)
                rows = [json.loads(s) for s in (run / 'frames.jsonl').read_text().splitlines()]
                pose = root / ('pose'+str(i)+'.json')
                pose.write_text(json.dumps({'schema': POSE_SCHEMA, 'trace_sha256': digest(run/'frames.jsonl'),
                    'metadata_assumption': 'fixture poses', 'frames': {r['frame_key']: {
                        '200000': transform(15).tolist(), '-1': transform(-20).tolist()} for r in rows}}))
                runs.append(str(run)); poses.append(str(pose))
            out = root / 'regional'
            argv = ['--train-runs', *runs[:2], '--validation-runs', runs[2], '--train-geometry', *poses[:2],
                    '--validation-geometry', poses[2], '--output-dir', str(out)]
            main(argv)
            report = json.loads((out / 'regional-dataset-report.json').read_text())
            self.assertEqual(report['frames'], {'train': 6, 'validation': 3})
            self.assertEqual(report['recording_groups']['train'], ['20241126_0001', '20241126_0017'])
            for record in report['sequences']:
                folder = out / record['split'] / record['sequence']
                with np.load(folder/'inputs.npz', allow_pickle=False) as inputs, \
                     np.load(folder/'offline-targets.npz', allow_pickle=False) as targets:
                    self.assertEqual(set(inputs.files), {'features', 'available', 'frame_keys', 'cell_centers'})
                    self.assertEqual(inputs['features'].shape, (3, CELL_COUNT, len(FEATURES)))
                    self.assertEqual(targets['counts'].shape, (3, CELL_COUNT, 4, 4, 3))
                    np.testing.assert_array_equal(inputs['frame_keys'], targets['frame_keys'])
                    np.testing.assert_array_equal(inputs['available'], targets['available'])
                    for j in range(4):
                        np.testing.assert_array_equal(targets['counts'][0, :, j].sum(axis=(0, 1)), [j+1, 0, 3-j])
                for relative, expected in record['files'].items():
                    self.assertEqual(digest(out/relative), expected)
                _, provenance = load_runs([record['provenance']['inputs'][0]['directory']], [poses[sequences.index(record['sequence'])]])
                self.assertEqual(provenance, record['provenance'])
            with zipfile.ZipFile(out/'urbaning-regional-dataset.zip') as archive:
                self.assertIn('regional-dataset-report.json', archive.namelist())
                self.assertIn('validation/'+sequences[2]+'/regional-example.png', archive.namelist())
            with self.assertRaises(FileExistsError):
                main(argv)

    def test_recording_overlap_and_crossing3_rejected_before_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = make_run(root/'train', '20241126_0017_crossing1_00')
            overlap = make_run(root/'overlap', '20241126_0017_crossing2_08')
            test = make_run(root/'test', '20241127_0009_crossing3_00')
            with self.assertRaises(ValueError):
                validate_split_headers([train], [overlap])
            with patch('phdsim.experiments.urbaning_regional_dataset.load_runs') as loader:
                with self.assertRaises(ValueError):
                    main(['--train-runs', str(train), '--validation-runs', str(test),
                          '--train-geometry', 'unused', '--validation-geometry', 'unused',
                          '--output-dir', str(root/'out')])
                loader.assert_not_called()
            self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()
