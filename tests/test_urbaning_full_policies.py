import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from phdsim.evaluation.urbaning_cached import summarize_cached
from phdsim.experiments.urbaning_benchmark import CLASSES
from phdsim.experiments.urbaning_subsets import comparison
from phdsim.experiments.urbaning_full_policies import make_plan, checked_plan
from test_urbaning_subsets import make_run
from phdsim.experiments.urbaning_subsets import load_runs, fit


class FullPolicyTests(unittest.TestCase):
    def test_ap_mode_changes_order_only_not_support_and_keeps_default(self):
        stats = {c: {i: {'gt': 1, 'tp': [0, 1], 'fp': [1, 0], 'score': [.1, .9]}
                     for i in (.3, .5, .7)} for c in CLASSES}
        before = copy.deepcopy(stats)
        self.assertAlmostEqual(summarize_cached(stats, False)['macro_ap']['0.5'], .5)
        self.assertAlmostEqual(summarize_cached(stats, True)['macro_ap']['0.5'], 1.)
        self.assertEqual(summarize_cached(stats), summarize_cached(stats, True))
        self.assertEqual(stats, before)

    def test_comparison_keeps_choices_f1_cost_and_random_budget_for_both_ap_modes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            train, provenance = load_runs([make_run(root / 'train', '20241126_0001_crossing2_00')])
            val, _ = load_runs([make_run(root / 'val', '20241126_0004_crossing2_00')])
            test, provenance = load_runs([make_run(root / 'test', '20241127_0009_crossing3_00')])
            model = fit(train, val, [1.], .05)
            model['detector'] = provenance['detector']
            a = comparison(test, provenance, [0, 1], model=model, global_sort=False)
            b = comparison(test, provenance, [0, 1], model=model, global_sort=True)
            for policy in a['policies']:
                for field in ('choices', 'mean_frame_f1', 'mean_frame_utility', 'peer_requests'):
                    self.assertEqual(a['policies'][policy][field], b['policies'][policy][field])
            for mode in ('schedule', 'budget'):
                for seed in ('0', '1'):
                    x = a['random_controls']['learned_joint_gain'][mode]['per_seed'][seed]
                    y = b['random_controls']['learned_joint_gain'][mode]['per_seed'][seed]
                    self.assertEqual(x['peer_requests'], y['peer_requests'])

    def test_plan_freezes_models_and_rejects_test_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ref = root / 'reference.json'
            ref.write_text(json.dumps({'status': 'completed', 'frames': 200,
                'plan': {'test_sequences': ['20241127_0009_crossing3_00']},
                'sequence_results_sha256': {'20241127_0009_crossing3_00': 'hash'}}))
            paths = [root / 'ego.json', root / 'geometry.json']
            for path, schema in zip(paths, ['phdsim-urbaning-joint-gain-v1', 'phdsim-urbaning-joint-gain-geometry-v1']):
                path.write_text(json.dumps({'schema': schema, 'detector': {'id': 'fixed'}, 'request_cost': .05,
                    'train_sequences': ['20241126_0001_crossing2_00'], 'validation_sequences': ['20241126_0004_crossing2_00']}))
            with patch('phdsim.experiments.urbaning_full_policies.verify_bundle', return_value={'id': 'fixed'}):
                plan = make_plan(ref, *paths, root)
                p = root / 'plan.json'; p.write_text(json.dumps(plan))
                self.assertEqual(checked_plan(p), plan)
                bad = json.loads(paths[0].read_text()); bad['train_sequences'] = ['20241127_0009_crossing3_08']
                paths[0].write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, 'Frozen policy changed'):
                    checked_plan(p)
                with self.assertRaisesRegex(ValueError, 'overlaps'):
                    make_plan(ref, *paths, root)
