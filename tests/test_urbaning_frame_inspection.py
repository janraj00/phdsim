import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import frame_f1, frame_statistics
from phdsim.experiments.urbaning_frame_inspection import (
    audit_frame, category_evidence, main, match_objects, select_cases)
from phdsim.experiments.urbaning_subsets import digest, load_runs
from phdsim.learning.urbaning_geometry import SCHEMA
from test_urbaning_geometry import transform
from test_urbaning_subsets import box, make_run

try:
    import matplotlib
except ImportError:
    matplotlib = None


class ObjectMatchingTests(unittest.TestCase):
    def test_original_indices_duplicates_wrong_class_radius_and_metric_parity(self):
        gt = np.array([box(0), box(10), box(20), box(200)])
        labels = np.array([1, 2, 3, 4])
        boxes = np.array([box(0), box(0), box(10), box(20), box(50), box(200)])
        scores = np.array([[.7, 1], [.9, 1], [.8, 2], [.9, 4], [.4, 1], [.9, 4]])
        result = match_objects(boxes, scores, gt, labels)
        self.assertEqual(result['matched_gt_indices'], [0, 1])
        self.assertEqual(result['missed_gt_indices'], [2])
        self.assertEqual(result['false_positive_indices'], [0, 3, 4])
        self.assertEqual({m['prediction_index'] for m in result['matches']}, {1, 2})
        self.assertNotIn(3, result['gt_indices_considered'])
        self.assertNotIn(5, result['prediction_indices_considered'])
        reference = frame_statistics(boxes, scores, gt, labels)
        self.assertEqual(result['f1'], frame_f1(reference))
        for name in CLASSES:
            self.assertEqual(result['classes'][name]['tp'], sum(reference[name][.5]['tp']))
            self.assertEqual(result['classes'][name]['fp'], sum(reference[name][.5]['fp']))
            self.assertEqual(result['classes'][name]['fn'], reference[name][.5]['gt'] - sum(reference[name][.5]['tp']))
        empty = match_objects(np.empty((0, 8, 3)), np.empty((0, 2)), np.empty((0, 8, 3)), np.empty(0))
        self.assertEqual(empty['f1'], 1.)
        self.assertTrue(all(v['f1'] is None for v in empty['classes'].values()))

    def test_partial_overlaps_and_confidence_ties_match_frozen_evaluator(self):
        rng = np.random.default_rng(7)
        for _ in range(12):
            gt = np.array([box(i * 5, angle=float(rng.uniform(-.5, .5))) for i in range(5)])
            pred = gt.copy() + rng.uniform(-.8, .8, size=(5, 1, 3))
            boxes = np.concatenate([pred, pred[:2]])
            scores = np.c_[rng.choice([.3, .6, .9], size=7), rng.integers(1, 5, size=7)]
            labels = rng.integers(1, 5, size=5)
            traced = match_objects(boxes, scores, gt, labels)
            reference = frame_statistics(boxes, scores, gt, labels)
            self.assertEqual(traced['f1'], frame_f1(reference))
            for name in CLASSES:
                self.assertEqual(traced['classes'][name]['tp'], sum(reference[name][.5]['tp']))

    def test_exclusive_recoveries_joint_recoveries_and_harm_are_distinct(self):
        outcomes = {}
        for name, ids in [('ego', [0]), ('vehicle_peer', [0, 1]),
                          ('infrastructure', [0, 2]), ('all', [0, 1, 3])]:
            outcomes[name] = {'matched_gt_indices': ids, 'utility': .5,
                              'missed_gt_indices': list(set(range(4)) - set(ids))}
        evidence = category_evidence({'outcomes': outcomes})
        self.assertEqual(evidence['car2_recovery']['focus_gt_indices'], [1])
        self.assertEqual(evidence['infra_recovery']['focus_gt_indices'], [2])
        self.assertEqual(evidence['joint_recovery']['focus_gt_indices'], [3])
        self.assertEqual(evidence['lost_after_adding_car2']['focus_gt_indices'], [2])
        self.assertEqual(evidence['no_query_net_advantage']['score'], 0.)
        frames = [dict(sequence='s', frame_key=str(i), row_position=i, outcomes=outcomes) for i in range(10)]
        selected, omitted = select_cases(frames, min_gap=2)
        self.assertEqual(selected, select_cases(frames[::-1], min_gap=2)[0])
        self.assertEqual(len({f['frame_key'] for f, _, _ in selected}), len(selected))
        self.assertTrue(all(abs(a['row_position'] - b['row_position']) >= 2
                            for i, (a, _, _) in enumerate(selected) for b, _, _ in selected[i+1:]))
        self.assertIn('no_query_net_advantage', {v['category'] for v in omitted})


@unittest.skipIf(matplotlib is None, 'matplotlib required for figure export')
class InspectionExportTests(unittest.TestCase):
    def test_verified_cached_audit_figures_input_boundary_and_protected_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root / 'cache', '20241126_0004_crossing2_00')
            rows = [json.loads(line) for line in (run / 'frames.jsonl').read_text().splitlines()]
            sidecar = root / 'poses.json'
            sidecar.write_text(json.dumps({
                'schema': SCHEMA, 'trace_sha256': digest(run / 'frames.jsonl'),
                'metadata_assumption': 'fixture poses',
                'frames': {r['frame_key']: {'200000': transform(15).tolist(), '-1': transform(-20).tolist()}
                           for r in rows}}))
            out = root / 'inspection'
            argv = ['--run', str(run), '--geometry', str(sidecar), '--output-dir', str(out), '--min-frame-gap', '1']
            main(argv)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['frames'], 4)
            self.assertEqual(manifest['both_available_frames'], 4)
            self.assertEqual({c['category'] for c in manifest['cases']}, {'reference', 'infra_recovery', 'joint_recovery'})
            self.assertIn('car2_recovery', {v['category'] for v in manifest['omitted_categories']})
            from PIL import Image
            for case in manifest['cases']:
                folder = out / case['directory']
                self.assertEqual(digest(folder / 'predictions.npz'), case['payload_sha256'])
                local = json.loads((folder / 'local-evidence.json').read_text())
                self.assertEqual(set(local), {'frame_key', 'source_ids', 'ego_entropy', 'ego_boxes',
                                             'ego_scores', 'peer_to_ego', 'native_association', 'scope'})
                self.assertNotIn('outcomes', local)
                offline = json.loads((folder / 'offline-outcomes.json').read_text())
                self.assertIn('gt_boxes', offline)
                for action, result in offline['outcomes'].items():
                    self.assertEqual(result['tp'], list(offline['outcomes']).index(action) + 1)
                for image in ('scene.png', 'zoom.png'):
                    with Image.open(folder / image) as picture:
                        self.assertGreater(picture.width, 1500)
                        picture.verify()
            with zipfile.ZipFile(out / 'urbaning-frame-inspection.zip') as archive:
                self.assertIn('index.html', archive.namelist())
                self.assertIn('frame-summaries.jsonl', archive.namelist())
                self.assertFalse(any(n.endswith('.zip') for n in archive.namelist()))
            with self.assertRaises(FileExistsError):
                main(argv)
            # All source hashes remain unchanged after export.
            _, again = load_runs([run], [sidecar])
            self.assertEqual(manifest['provenance'], again)

    def test_test_recordings_rejected_before_prediction_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root / 'test', '20241127_0009_crossing3_00')
            with patch('phdsim.experiments.urbaning_frame_inspection.load_runs') as loader:
                with self.assertRaises(ValueError):
                    main(['--run', str(run), '--geometry', 'unused', '--output-dir', str(root / 'out')])
                loader.assert_not_called()
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
