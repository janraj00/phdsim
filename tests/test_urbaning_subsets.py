import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from phdsim.decision.urbaning import (
    action_subsets, available_subsets, choose_subset, matched_random_subsets, random_subset)
from phdsim.evaluation.urbaning_cached import (
    aggregate_statistics, frame_f1, frame_statistics, polygon_iou, summarize_cached)
from phdsim.experiments.urbaning_subsets import comparison, fit, load_runs, main
from phdsim.learning.urbaning import (
    FEATURES, assert_unseen_recordings, choose_learned_subset, ego_features,
    fit_joint_gain, predict_gains)

IDS = ['100000', '200000', '-1']


def box(x=0, y=0, angle=0):
    xy = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
    xy = xy @ np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
    xy += [x, y]
    return np.r_[np.c_[xy, np.zeros(4)], np.c_[xy, np.ones(4)]]


def make_run(root, sequence, frames=4):
    """Known outcomes: 1/2/3/4 correct classes for the four source subsets."""
    import hashlib
    root.mkdir()
    (root / 'predictions').mkdir()
    detector = {'files': {'best_model.pth': 'fixture-checkpoint'}, 'release': 'fixture'}
    (root / 'run.json').write_text(json.dumps({
        'schema': 'phdsim-urbaning-stage1-v1', 'status': 'completed', 'model': detector,
        'arguments': {'sequence': sequence, 'ego_id': 100000}}))
    gt, labels = np.array([box(x=5 * i) for i in range(4)]), np.arange(1, 5)
    stats, rows = {a: [] for a in action_subsets(IDS)}, []
    for i in range(frames):
        arrays = {'gt_boxes': gt, 'gt_labels': labels}
        for n, action in enumerate(action_subsets(IDS), start=1):
            pred, scores = gt[:n], np.c_[np.full(n, .9), labels[:n]]
            arrays[action + '_boxes'], arrays[action + '_scores'] = pred, scores
            stats[action].append(frame_statistics(pred, scores, gt, labels))
        name = 'predictions/{:06d}.npz'.format(i)
        np.savez_compressed(root / name, **arrays)
        rows.append({'frame_key': '{}:{:06d}:100000'.format(sequence, i), 'source_frame_id': '{:06d}'.format(i),
                     'sources': {'included_ids': IDS}, 'predictions': name, 'ego_entropy_bits': .2 + .15 * i,
                     'gt_sha256': hashlib.sha256(gt.tobytes() + labels.tobytes()).hexdigest(),
                     'native_association': {'timestamp_ns': 1732636213000000000 + i * 100000000}})
    (root / 'frames.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    (root / 'metrics.json').write_text(json.dumps({a: summarize_cached(aggregate_statistics(s)) for a, s in stats.items()}))
    return root


class SubsetDecisionTests(unittest.TestCase):
    def test_all_four_decisions_and_joint_synergy(self):
        cases = [({'vehicle_peer': -.1, 'infrastructure': -.2, 'all': -.3}, 'ego'),
                 ({'vehicle_peer': .3, 'infrastructure': .1, 'all': .31}, 'vehicle_peer'),
                 ({'vehicle_peer': .1, 'infrastructure': .3, 'all': .31}, 'infrastructure'),
                 ({'vehicle_peer': -.1, 'infrastructure': -.1, 'all': .5}, 'all')]
        for gains, expected in cases:
            self.assertEqual(choose_subset(IDS, gains, .05), expected)
        self.assertEqual(choose_subset(IDS, dict.fromkeys(('vehicle_peer', 'infrastructure', 'all'), 0.)), 'ego')
        self.assertEqual(tuple(available_subsets(['100000', '-1'])), ('ego', 'infrastructure'))
        self.assertEqual(choose_subset(['100000'], {}), 'ego')
        for cost in [-1, float('nan')]:
            with self.assertRaises(ValueError):
                choose_subset(IDS, {'vehicle_peer': 1., 'infrastructure': 1., 'all': 1.}, cost)

    def test_random_support_is_full_and_missing_peers_are_not_sampled(self):
        self.assertEqual({random_subset(IDS, 'frame', s) for s in range(100)}, set(action_subsets(IDS)))
        self.assertEqual(random_subset(IDS, 'frame', 0, 0), 'ego')
        self.assertEqual(random_subset(IDS, 'frame', 0, 1), 'all')
        self.assertEqual({random_subset(['100000', '-1'], 'frame', s) for s in range(100)}, {'ego', 'infrastructure'})
        self.assertEqual(random_subset(['100000'], 'frame', 0), 'ego')
        # Independent 50% draws give equal support to each of the four subsets.
        from collections import Counter
        counts = Counter(random_subset(IDS, 'frame', s) for s in range(2000))
        self.assertTrue(all(400 < n < 600 for n in counts.values()))

    def test_matched_controls_preserve_counts_and_allow_zero_and_two(self):
        from collections import Counter
        ids = [IDS] * 6 + [['100000', '-1']] * 2 + [['100000']]
        keys = ['f' + str(i) for i in range(len(ids))]
        ref = ['ego', 'vehicle_peer', 'all', 'ego', 'infrastructure', 'all', 'ego', 'infrastructure', 'ego']
        counts = lambda choices: [len(available_subsets(x)[c]) - 1 for x, c in zip(ids, choices)]
        saw_timing_change = False
        for seed in range(20):
            schedule = matched_random_subsets(ids, keys, ref, seed, 'schedule')
            self.assertEqual(counts(schedule), counts(ref))
            budget = matched_random_subsets(ids, keys, ref, seed, 'budget')
            for sl in (slice(0, 6), slice(6, 8), slice(8, 9)):
                self.assertEqual(Counter(counts(budget)[sl]), Counter(counts(ref)[sl]))
            saw_timing_change |= counts(budget) != counts(ref)
            reverse = matched_random_subsets(ids[::-1], keys[::-1], ref[::-1], seed, 'budget')
            self.assertEqual(reverse[::-1], budget)
        self.assertTrue(saw_timing_change)
        with self.assertRaises(ValueError):
            matched_random_subsets([IDS], ['f'], ['missing'], 0, 'budget')


class CachedMetricTests(unittest.TestCase):
    def test_oriented_iou_and_known_detection_errors(self):
        a, b = box(), box(angle=np.pi / 4)
        self.assertAlmostEqual(polygon_iou(a[:4, :2], b[:4, :2]), 1 / np.sqrt(2))
        self.assertEqual(polygon_iou(a[:4, :2], box(x=5)[:4, :2]), 0.)
        stats = frame_statistics(np.array([a, a]), np.array([[.9, 1], [.8, 1]]), np.array([a]), np.array([1]))
        self.assertAlmostEqual(frame_f1(stats), 2 / 3)
        report = summarize_cached(stats)
        self.assertAlmostEqual(report['classes']['Vehicle']['ap']['0.5'], 1.)
        self.assertIsNone(report['macro_ap']['0.5'])
        wrong = frame_statistics(np.array([a]), np.array([[.9, 2]]), np.array([a]), np.array([1]))
        self.assertEqual(frame_f1(wrong), 0.)
        empty = frame_statistics(np.empty((0, 8, 3)), np.empty((0, 2)), np.empty((0, 8, 3)), np.empty(0))
        self.assertEqual(frame_f1(empty), 1.)


class LearnedSubsetTests(unittest.TestCase):
    def test_joint_head_fit_is_not_sum_of_individual_heads(self):
        x = np.zeros((8, len(FEATURES)))
        x[:, 0] = np.linspace(.1, .9, 8)
        y = np.c_[-.1 * np.ones(8), -.1 * np.ones(8), .6 * np.ones(8)]
        model = fit_joint_gain(x, y, np.ones((8, 3), bool), 1., ['20241126_0001_crossing1_00'])
        gains = predict_gains(model, x[0])
        self.assertAlmostEqual(gains['all'], .6)
        self.assertAlmostEqual(gains['vehicle_peer'], -.1)
        self.assertEqual(choose_subset(IDS, gains, .1), 'all')
        model['scale'][0] = 0
        with self.assertRaises(ValueError):
            predict_gains(model, x[0])

    def test_fit_replay_recording_guards_and_output_protection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            train = make_run(root / 'train', '20241126_0001_crossing1_00')
            val = make_run(root / 'val', '20241126_0002_crossing2_00')
            test = make_run(root / 'test', '20241126_0003_crossing3_00')
            model_path, report_path = root / 'model.json', root / 'report.json'
            main(['fit', '--train-runs', str(train), '--validation-runs', str(val),
                  '--request-cost', '.05', '--output', str(model_path)])
            model = json.loads(model_path.read_text())
            self.assertEqual(choose_learned_subset(model, IDS, .4, np.array([[.9, 1]])), 'all')
            with self.assertRaises(ValueError):
                assert_unseen_recordings(model, ['20241126_0001_crossing2_01'])
            main(['compare', '--runs', str(test), '--model', str(model_path),
                  '--random-seeds', '0', '1', '2', '--output', str(report_path)])
            report = json.loads(report_path.read_text())
            self.assertAlmostEqual(report['policies']['learned_joint_gain']['macro_ap']['0.5'], 1.)
            reference = report['policies']['learned_joint_gain']['request_histogram']
            for mode in ('schedule', 'budget'):
                for sample in report['random_controls']['learned_joint_gain'][mode]['per_seed'].values():
                    self.assertEqual(sample['request_histogram'], reference)
            with self.assertRaises(FileExistsError):
                main(['compare', '--runs', str(test), '--model', str(model_path), '--output', str(report_path)])
            frames, provenance = load_runs([train])
            with self.assertRaises(ValueError):
                fit(frames, frames, [1.], .05)
            with self.assertRaises(ValueError):
                load_runs([train, train])
            heldout, p = load_runs([test])
            with self.assertRaises(ValueError):
                comparison(heldout, p, [0], diagnostic_cost=.05)
            # Corrupted original AP is rejected before using the cache for learning.
            metrics = json.loads((train / 'metrics.json').read_text())
            metrics['all']['classes']['Vehicle']['ap']['0.5'] = 0.
            (train / 'metrics.json').write_text(json.dumps(metrics))
            with self.assertRaises(ValueError):
                load_runs([train])


if __name__ == '__main__':
    unittest.main()
