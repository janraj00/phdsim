import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phdsim.experiments.urbaning_benchmark import make_plan, empty_stats, merge_stats, summarize, validate_complete, freeze


class BenchmarkTests(unittest.TestCase):
    def test_split_uses_every_crossing3_sequence_and_freezes_version(self):
        names = ['20241126_0001_crossing2_00', '20241127_0009_crossing3_00', '20241127_0002_crossing3_00']
        metadata = {'data': {'latestVersion': {'versionNumber': 1, 'versionMinorNumber': 0,
                    'files': [{'dataFile': {'filename': n + '.7z.001'}} for n in names]}}}
        with patch('phdsim.datasets.urbaning.source.sequence_files', return_value=[{'bytes': 100}]):
            plan = make_plan(metadata)
        self.assertEqual(plan['test_sequences'], sorted(names[1:]))
        self.assertEqual(plan['download_bytes_including_repeated_support'], 200)
        metadata['data']['latestVersion']['versionMinorNumber'] = 1
        with self.assertRaises(ValueError):
            make_plan(metadata)

    def test_non_sequence_split_archives_are_reported_and_not_selected(self):
        metadata = {'data': {'latestVersion': {'versionNumber': 1, 'versionMinorNumber': 0,
                    'files': [{'dataFile': {'filename': n}} for n in [
                        'digital_twin.7z.001', '20241127_0009_crossing3_00.7z.001',
                        '20241127_0009_crossing3_00.7z.002', 'readme.txt']]}}}
        with patch('phdsim.datasets.urbaning.source.sequence_files', return_value=[{'bytes': 100}]) as select:
            plan = make_plan(metadata)
        self.assertEqual(plan['test_sequences'], ['20241127_0009_crossing3_00'])
        self.assertEqual(plan['ignored_non_sequence_first_parts'], ['digital_twin.7z.001'])
        select.assert_called_once_with(metadata, '20241127_0009_crossing3_00')
        metadata['data']['latestVersion']['files'] = [{'dataFile': {'filename': 'maps.7z.001'}}]
        with self.assertRaisesRegex(ValueError, 'No valid sequence archives'):
            make_plan(metadata)

    def test_merge_preserves_frame_order_and_ap_modes_do_not_mutate_stats(self):
        a, b = empty_stats(), empty_stats()
        for c in a:
            for i in a[c]:
                a[c][i] = {'tp': [0], 'fp': [1], 'score': [.1], 'gt': 1}
                b[c][i] = {'tp': [1], 'fp': [0], 'score': [.9], 'gt': 1}
        merged = merge_stats([a, b])
        before = copy.deepcopy(merged)
        def fake_ap(stats, iou, sort):
            v = stats[iou]
            self.assertEqual(v['tp'], [0, 1])
            self.assertEqual(v['score'], [.1, .9])
            self.assertEqual(v['gt'], 2)
            v['tp'][0] = 999  # upstream evaluator mutates its statistics
            return (.5 if sort else .25), [], []
        # Each IoU has its own arrays, and each mode gets a fresh deep copy.
        self.assertEqual(summarize(merged, False, fake_ap)['macro_ap']['0.5'], .25)
        self.assertEqual(summarize(merged, True, fake_ap)['macro_ap']['0.5'], .5)
        self.assertEqual(merged, before)
        self.assertEqual(a['Vehicle']['0.5']['tp'], [0])

    def test_reject_incomplete_missing_or_mixed_protocol_before_reporting(self):
        plan = {'test_sequences': ['a', 'b']}
        records = [{'sequence': s, 'plan': plan, 'status': 'completed', 'frames': 200, 'dataset_frames': 200}
                   for s in ['a', 'b']]
        validate_complete(plan, records)
        with self.assertRaises(ValueError):
            validate_complete(plan, records[:1])
        with self.assertRaises(ValueError):
            validate_complete(plan, records[::-1])
        records[0]['frames'] = 199
        with self.assertRaises(ValueError):
            validate_complete(plan, records)
        records[0]['frames'] = 200
        records[0]['plan'] = {'test_sequences': ['a']}
        with self.assertRaises(ValueError):
            validate_complete(plan, records)

    def test_existing_plan_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'plan.json'
            freeze(p, {'seed': 42})
            freeze(p, {'seed': 42})
            with self.assertRaises(ValueError):
                freeze(p, {'seed': 43})
