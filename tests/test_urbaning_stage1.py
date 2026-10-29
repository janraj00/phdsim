import copy
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

from phdsim.decision.urbaning import action_subsets, choose_one_peer
from phdsim.experiments.urbaning_stage1 import validate_selection
from phdsim.perception.urbaning.bundle import fetch_bundle, verify_bundle


class AcquisitionTests(unittest.TestCase):
    def test_source_view_preserves_native_time_and_does_not_overwrite(self):
        from phdsim.datasets.urbaning.opencood import create_source_view
        from phdsim.datasets.urbaning.source import DEFAULT_SEQUENCE, file_hashes
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'extracted' / DEFAULT_SEQUENCE
            native.mkdir(parents=True)
            (native / 'extraction.json').write_text(json.dumps({'sequence_relative_path': '.'}))
            (native / 'calibration.json').write_text('{}')
            original_sync = ',0,1\ntimestamp_ms,1732620000001,1732620000101\nvehicle1_middle_lidar,1732620000010,1732620000110\n'
            (native / 'timesync_info.csv').write_text(original_sync)
            (root / 'raw' / 'labels').mkdir(parents=True)
            (root / 'source').mkdir()
            files = []
            for relative in ('labels/' + DEFAULT_SEQUENCE + '.json', 'labels_av_track_ids.json'):
                path = root / 'raw' / relative
                path.write_text('{}')
                files.append({'relative_path': relative, **file_hashes(path)})
            (root / 'source' / (DEFAULT_SEQUENCE + '-download.json')).write_text(json.dumps({'files': files}))
            view = create_source_view(root, DEFAULT_SEQUENCE, root / 'view')
            record = json.loads((view / 'phdsim-conversion.json').read_text())
            association = record['sync_by_frame']['000000']
            self.assertEqual(association['timestamp_ns'], 1732620000001000000)
            self.assertEqual(association['members']['vehicle1_middle_lidar'], '1732620000010')
            self.assertEqual((view / 'dataset' / DEFAULT_SEQUENCE).resolve(), native)
            limited = create_source_view(root, DEFAULT_SEQUENCE, root / 'limited', max_frames=1)
            limited_record = json.loads((limited / 'phdsim-conversion.json').read_text())
            self.assertEqual(list(limited_record['sync_by_frame']), ['000000'])
            self.assertEqual((native / 'timesync_info.csv').read_text(), original_sync)
            self.assertNotEqual(limited_record['timesync_sha256'], limited_record['view_timesync_sha256'])
            later = create_source_view(root, DEFAULT_SEQUENCE, root / 'later', max_frames=1, start_frame=1)
            later_record = json.loads((later / 'phdsim-conversion.json').read_text())
            self.assertEqual(list(later_record['sync_by_frame']), ['000001'])
            self.assertEqual(later_record['sync_by_frame']['000001']['timestamp_ns'], 1732620000101000000)
            with self.assertRaises(FileExistsError):
                create_source_view(root, DEFAULT_SEQUENCE, view)
            (root / 'raw' / 'labels_av_track_ids.json').write_text('changed')
            with self.assertRaises(ValueError):
                create_source_view(root, DEFAULT_SEQUENCE, root / 'second-view')
            self.assertFalse((root / 'second-view').exists())

    def test_source_order_and_infrastructure_bundle(self):
        self.assertEqual(action_subsets(['100000', '200000', '-1']), {
            'ego': (0,), 'vehicle_peer': (0, 1), 'infrastructure': (0, 2), 'all': (0, 1, 2)})
        self.assertEqual(action_subsets(['200000', '-3'])['infrastructure'], (0, 1))
        self.assertEqual(action_subsets(['200000', '-3'])['vehicle_peer'], (0,))
        for invalid in ([], ['-1'], ['100000', '100000'], ['100000', '-1', '-2'], ['100000', 'pole1']):
            with self.assertRaises(ValueError):
                action_subsets(invalid)

    def test_gate_and_random_share_partner_and_respect_budget(self):
        ids = ['100000', '200000', '-1']
        self.assertEqual(choose_one_peer(ids, 'frame', 7, 0.2, 0.5), 'ego')
        random = choose_one_peer(ids, 'frame', 7)
        self.assertEqual(choose_one_peer(ids, 'frame', 7, 0.8, 0.5), random)
        self.assertEqual(choose_one_peer(['100000'], 'frame', 7, 0.8, 0.5), 'ego')
        self.assertEqual(len(action_subsets(ids)[random]), 2)
        for value in (float('nan'), -0.1, 1.1):
            with self.assertRaises(ValueError):
                choose_one_peer(ids, 'frame', 7, 0.5, value)

    def test_holdout_cannot_be_used_for_smoke(self):
        validate_selection('20241126_0017_crossing1_00', 'smoke', 10, 0, 100000)
        with self.assertRaises(ValueError):
            validate_selection('20241126_0017_crossing3_00', 'smoke', 10, 0, 100000)
        with self.assertRaises(ValueError):
            validate_selection('20241126_0017_crossing1_00', 'evaluation', 0, 0, 100000)

    def test_corrupted_or_existing_bundle_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'best_model.pth').write_bytes(b'wrong')
            with self.assertRaises(ValueError):
                verify_bundle(root)
            if importlib.util.find_spec('py7zr'):
                with self.assertRaises(ValueError):
                    fetch_bundle(root)
            self.assertEqual((root / 'best_model.pth').read_bytes(), b'wrong')


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional CPU torch required')
class ModelInputTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.batch = {'record_len': torch.tensor([3]), 'offline_ground_truth': 'must not leak',
                      'processed_lidar': {'voxel_coords': torch.tensor([[0, 0, 1, 1], [1, 0, 2, 2],
                                                                       [2, 0, 3, 3], [2, 0, 4, 4]]),
                                          'voxel_features': torch.arange(16).reshape(4, 1, 4).float(),
                                          'voxel_num_points': torch.ones(4, dtype=torch.int32)}}

    def test_noncontiguous_selection_remaps_without_mutation_or_gt(self):
        from phdsim.perception.urbaning.cobevt import subset_inputs
        before = copy.deepcopy(self.batch)
        selected = subset_inputs(self.batch, (0, 2))
        self.assertEqual(set(selected), {'processed_lidar', 'record_len'})
        self.assertEqual(selected['record_len'].tolist(), [2])
        self.assertEqual(selected['processed_lidar']['voxel_coords'][:, 0].tolist(), [0, 1, 1])
        self.assertTrue(self.torch.equal(selected['processed_lidar']['voxel_features'],
                                        before['processed_lidar']['voxel_features'][[0, 2, 3]]))
        selected['processed_lidar']['voxel_features'].zero_()
        self.assertTrue(self.torch.equal(self.batch['processed_lidar']['voxel_features'],
                                        before['processed_lidar']['voxel_features']))
        self.assertTrue(self.torch.equal(self.batch['processed_lidar']['voxel_coords'],
                                        before['processed_lidar']['voxel_coords']))

    def test_invalid_or_empty_agent_fails(self):
        from phdsim.perception.urbaning.cobevt import subset_inputs
        for indices in ((), (1,), (0, 0), (0, 3)):
            with self.assertRaises(ValueError):
                subset_inputs(self.batch, indices)
        self.batch['processed_lidar']['voxel_coords'][:, 0] = 0
        with self.assertRaises(ValueError):
            subset_inputs(self.batch, (0, 2))

    def test_entropy_extremes(self):
        from phdsim.perception.urbaning.cobevt import ego_entropy
        self.assertAlmostEqual(ego_entropy(self.torch.zeros(1, 32, 4, 4)), 1.0)
        self.assertLess(ego_entropy(self.torch.full((1, 32, 4, 4), 20.0)), 0.001)
        with self.assertRaises(ValueError):
            ego_entropy(self.torch.full((1, 32, 4, 4), float('nan')))


if __name__ == '__main__':
    unittest.main()
