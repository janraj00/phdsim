import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from test_urbaning_subsets import make_run
from phdsim.experiments import urbaning_frozen_full as full
from phdsim.experiments.urbaning_ap_replay import MODES, baseline_choices, metrics_both_orders
from phdsim.experiments.urbaning_subsets import digest, ensemble_summary, load_runs
from phdsim.learning.urbaning import TARGET
from phdsim.learning.urbaning_geometry import FEATURES as TREE_FEATURES, SCHEMA as GEOMETRY_SCHEMA
from phdsim.learning.urbaning_regions import FEATURES
from phdsim.decision.urbaning import random_subset

SEQ = '20241127_0009_crossing3_00'


def fixture(root):
    directory = root/'cache'/SEQ
    directory.mkdir(parents=True)
    run = make_run(directory/'run', SEQ)
    rows = list(map(json.loads, (run/'frames.jsonl').read_text().splitlines()))
    pose = directory/'poses.json'
    pose.write_text(json.dumps({'schema': GEOMETRY_SCHEMA, 'trace_sha256': digest(run/'frames.jsonl'),
        'metadata_assumption': 'fixture', 'frames': {r['frame_key']: {
            '200000': np.eye(4).tolist(), '-1': np.eye(4).tolist()} for r in rows}}))
    marker = {'sequence': SEQ, 'frames': 4, 'run_sha256': digest(run/'run.json'),
              'trace_sha256': digest(run/'frames.jsonl'), 'poses_sha256': digest(pose)}
    (directory/'completed.json').write_text(json.dumps(marker))
    frames, provenance = load_runs([run], [pose])
    models = {}
    for label in ('gain_ego', 'gain_geometry'):
        models[label] = {}
        for mode, order in MODES.items():
            policies = {}
            for action in full.ACTION_ORDER:
                choices = baseline_choices(frames, action)
                policies[action] = dict(metrics_both_orders(frames, choices)[mode],
                                        choices=dict(zip([f['key'] for f in frames], choices)))
            policies['learned_joint_gain'] = copy.deepcopy(policies['all'])
            random = ensemble_summary([metrics_both_orders(frames, [random_subset(f['source_ids'], f['key'], seed)
                        for f in frames])[mode] for seed in full.SEEDS], full.SEEDS)
            models[label][str(order)] = {'policies': policies, 'provenance': provenance,
                                         'independent_random_subsets_p_half': random}
    ref = {'status': 'completed', 'plan': {'test_sequences': [SEQ], 'expected_frames': 4,
           'detector': provenance['detector']}, 'completed': {SEQ: marker}, 'models': models}
    train, val = ['20241126_0001', '20241126_0017'], ['20241126_0004']
    tree = {'schema': 'phdsim-urbaning-boosted-gain-v1', 'feature_schema': GEOMETRY_SCHEMA,
        'target': TARGET, 'features': list(TREE_FEATURES), 'request_cost': .05,
        'train_sequences': ['20241126_0001_crossing2_00', '20241126_0017_crossing1_00'],
        'validation_sequences': ['20241126_0004_crossing2_00'],
        'train_recording_groups': train, 'validation_recording_groups': val,
        'detector': provenance['detector'], 'heads': {a: {'initial': v, 'learning_rate': .05,
            'trees': [{'left': [-1], 'right': [-1], 'feature': [-2], 'threshold': [-2.], 'value': [0.]}]}
            for a, v in zip(full.ACTION_ORDER[1:], [.1, .2, .5])}}
    regional = {'schema': 'phdsim-urbaning-regional-acquisition-v1', 'error_count_penalty': 8.,
        'validation_selected': True, 'dataset_manifest_sha256': 'fixture', 'model': {
        'schema': 'phdsim-urbaning-regional-ridge-v1', 'profile': 'full', 'alpha': .1,
        'dataset_manifest_sha256': 'fixture', 'training_recording_groups': train,
        'validation_recording_groups': val, 'input_features': list(FEATURES),
        'selected_indices': list(range(46)), 'selected_features': list(FEATURES),
        'heads': {a: {'mean': [0.]*46, 'scale': [1.]*46, 'weights': np.zeros((47,4)).tolist()}
                  for a in full.ACTION_ORDER[1:]}}}
    regional_report = {'status': 'completed', 'detector': provenance['detector'], 'dataset_manifest_sha256': 'fixture'}
    archives = []
    for n, members in enumerate(({'full-policy-report.json': ref}, {'tree-gain.json': tree},
                {'regional-policy.json': regional, 'regional-policy-report.json': regional_report})):
        path = root/f'input{n}.zip'
        with zipfile.ZipFile(path, 'x') as z:
            for name, value in members.items(): z.writestr(name, json.dumps(value))
        archives.append(path)
    return archives, (ref, tree, regional, regional_report)


class FrozenFullTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        for name, value in [('SEQUENCES', (SEQ,)), ('EXPECTED_FRAMES', 4), ('SEQUENCE_FRAMES', 4),
                            ('SEEDS', (0, 1, 2)), ('PURE_PROBABILITIES', (.5, .9))]:
            self.stack.enter_context(patch.object(full, name, value))
        self.addCleanup(self.stack.close)

    def test_end_to_end_two_metrics_orders_pure_random_and_portable_stats(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            inputs, _ = fixture(root)
            bundle = root/'inputs.zip'
            full.pack_inputs(*inputs, bundle)
            # The replay must remain functional without the detector or sklearn.
            with patch.dict('sys.modules', {'torch': None, 'opencood': None, 'sklearn': None}):
                full.run(bundle, digest(bundle), root/'cache', root/'output')
            report = json.loads((root/'output/report.json').read_text())
            self.assertEqual(report['frames'], 4)
            for mode in MODES:
                self.assertEqual(report['policies']['regional'][mode]['peer_requests'], 0)
                self.assertEqual(report['policies']['tree'][mode]['peer_requests'], 8)
                self.assertAlmostEqual(report['policies']['tree'][mode]['macro_ap']['0.5'], 1.)
                self.assertAlmostEqual(report['policies']['regional'][mode]['macro_ap']['0.5'], .25)
                self.assertEqual(set(report['pure_random']['0.5'][mode]['per_seed']), {'0','1','2'})
            rows = list(map(json.loads, (root/'output/offline-statistics.jsonl').read_text().splitlines()))
            self.assertEqual(len(rows), 4)
            self.assertNotIn('features', rows[0])
            with zipfile.ZipFile(root/'output/urbaning-frozen-full.zip') as z:
                self.assertIsNone(z.testzip())
                hashes = json.loads(z.read('files.json'))
                for name, expected in hashes.items(): self.assertEqual(full.sha(z.read(name)), expected)

    def test_header_rejects_split_cost_and_model_changes_before_cache_loading(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            archives, values = fixture(root)
            for mutate in (lambda v: v[1].update(request_cost=.01),
                           lambda v: v[1].update(train_recording_groups=['20241127_0009']),
                           lambda v: v[2].update(error_count_penalty=4.),
                           lambda v: v[2]['model'].update(validation_recording_groups=['20241127_0009']),
                           lambda v: v[2]['model'].update(selected_indices=[0])):
                broken = copy.deepcopy(values); mutate(broken)
                with self.assertRaises(ValueError): full.check_models(*broken)
            bundle = root/'inputs.zip'; full.pack_inputs(*archives, bundle)
            with patch.object(full, 'check_caches') as cache:
                with self.assertRaises(ValueError): full.run(bundle, 'incorrect', root/'cache', root/'out')
                cache.assert_not_called()
            # Any missing/modified completed cache fails without starting inference.
            (root/'cache'/SEQ/'poses.json').write_text('{}')
            with self.assertRaises(ValueError): full.check_caches(root/'cache', values[0])

    def test_replay_rejects_ap_and_prediction_provenance_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); _, values = fixture(root)
            ref = values[0]
            frames, p = load_runs([root/'cache'/SEQ/'run'], [root/'cache'/SEQ/'poses.json'])
            changed = copy.deepcopy(p)
            changed['inputs'][0]['predictions_sha256']['predictions/000000.npz'] = 'stale'
            with self.assertRaises(ValueError): full.provenance_equal(changed, p)
            ref['models']['gain_geometry']['True']['policies']['ego']['classes']['Vehicle']['ap']['0.5'] = .01
            with self.assertRaises(ValueError): full.score(frames, {'regional': ['ego']*4, 'tree': ['all']*4}, ref)


if __name__ == '__main__':
    unittest.main()
