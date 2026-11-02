import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from phdsim.experiments.urbaning_subsets import digest
from phdsim.experiments.urbaning_tree_pilot import (
    COST, choose_candidate, constant_choices, main, select_models, validate_splits)
from phdsim.learning.urbaning import HEADS
from phdsim.learning.urbaning_geometry import FEATURES, SCHEMA as FEATURE_SCHEMA
from phdsim.learning.urbaning_trees import (
    export_regressor, fit_tree_gain, predict_regressor, predict_tree_gains)
from test_urbaning_geometry import transform
from test_urbaning_subsets import make_run

try:
    from sklearn.ensemble import GradientBoostingRegressor
except ImportError:
    GradientBoostingRegressor = None

TRAIN = '20241126_0017_crossing1_00'
VAL = '20241126_0004_crossing2_00'


@unittest.skipIf(GradientBoostingRegressor is None, 'scikit-learn is optional outside this pilot')
class TreeGainTests(unittest.TestCase):
    def test_json_prediction_matches_sklearn_including_float32_boundaries(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(100, len(FEATURES)))
        y = np.where(x[:, 0] < 0, .4, -.2) + np.where(x[:, 1] > .5, .2, 0)
        estimator = GradientBoostingRegressor(n_estimators=25, max_depth=2, random_state=42).fit(x, y)
        head = json.loads(json.dumps(export_regressor(estimator), allow_nan=False))
        evidence = list(x[:20])
        tree = head['trees'][0]
        for direction in (-np.inf, np.inf):
            row = x[0].copy()
            row[tree['feature'][0]] = np.nextafter(np.float32(tree['threshold'][0]), np.float32(direction))
            evidence.append(row)
        np.testing.assert_allclose([predict_regressor(head, row) for row in evidence],
                                   estimator.predict(evidence), rtol=1e-12, atol=1e-12)
        corrupt = copy.deepcopy(head)
        corrupt['trees'][0]['left'][0] = 0
        with self.assertRaises(ValueError):
            predict_regressor(corrupt, x[0])

    def test_nonlinear_signal_masked_targets_and_joint_head(self):
        x = np.zeros((120, len(FEATURES)))
        x[:, 0] = np.linspace(-1, 1, len(x))
        y = np.c_[np.where(np.abs(x[:, 0]) > .45, .4, -.1),
                  np.full(len(x), -.2), np.full(len(x), .7)]
        mask = np.ones_like(y, dtype=bool)
        mask[::3, 0] = False
        params = dict(max_depth=2, min_samples_leaf=5, n_estimators=100)
        model = fit_tree_gain(x, y, mask, [TRAIN], FEATURE_SCHEMA, **params)
        changed = y.copy(); changed[~mask] = 999.
        other = fit_tree_gain(x, changed, mask, [TRAIN], FEATURE_SCHEMA, **params)
        self.assertEqual(model['heads'], other['heads'])
        self.assertEqual(model['feasible_training_frames']['vehicle_peer'], 80)
        predicted = np.array([predict_tree_gains(model, row)['vehicle_peer'] for row in x])
        linear = np.linalg.lstsq(np.c_[np.ones(len(x)), x[:, 0]], y[:, 0], rcond=None)[0]
        linear_prediction = np.c_[np.ones(len(x)), x[:, 0]] @ linear
        # Missing training points near a step can shift its learned boundary;
        # still require at least 90% less error than the linear fit.
        self.assertLess(np.mean((predicted - y[:, 0]) ** 2), .1 * np.mean((linear_prediction - y[:, 0]) ** 2))
        gains = predict_tree_gains(model, x[0])
        self.assertAlmostEqual(gains['all'], .7)
        self.assertGreater(abs(gains['all'] - gains['vehicle_peer'] - gains['infrastructure']), .3)
        broken = dict(model, features=list(reversed(FEATURES)))
        with self.assertRaises(ValueError):
            predict_tree_gains(broken, x[0])
        with self.assertRaises(ValueError):
            fit_tree_gain(x, y, np.zeros_like(mask), [TRAIN], FEATURE_SCHEMA, **params)
        with self.assertRaises(ValueError):
            fit_tree_gain(x, y, mask, ['20241127_0009_crossing3_00'], FEATURE_SCHEMA, **params)

    def test_end_to_end_verified_caches_models_controls_and_protected_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = []
            for role, sequence in (('train', TRAIN), ('validation', VAL)):
                run = make_run(root / role, sequence)
                rows = [json.loads(line) for line in (run / 'frames.jsonl').read_text().splitlines()]
                pose = root / (role + '-poses.json')
                pose.write_text(json.dumps({
                    'schema': FEATURE_SCHEMA, 'trace_sha256': digest(run / 'frames.jsonl'),
                    'metadata_assumption': 'fixture poses',
                    'frames': {r['frame_key']: {'200000': transform(15).tolist(), '-1': transform(-20).tolist()}
                               for r in rows}}))
                arguments.extend(['--' + role + '-runs', str(run), '--' + role + '-geometry', str(pose)])
            out = root / 'pilot'
            arguments.extend(['--output-dir', str(out)])
            main(arguments)
            report = json.loads((out / 'validation-report.json').read_text())
            self.assertEqual(report['selected_constant'], 'all')
            # Perfect tied learners cannot displace an equally good constant.
            self.assertEqual(report['validation_selected_policy'], 'all')
            self.assertFalse(report['protocol']['test_access'])
            self.assertEqual(report['protocol']['request_cost'], COST)
            self.assertEqual(report['splits']['training_frames'], 4)
            self.assertEqual(len(report['grids']['tree']['candidates']), 4)
            self.assertEqual(report['runtime']['scikit_learn'], __import__('sklearn').__version__)
            for family in ('ridge', 'tree'):
                frozen = json.loads((out / (family + '-gain.json')).read_text())
                self.assertEqual(frozen['validation_recording_groups'], ['20241126_0004'])
                self.assertEqual(report['models'][family]['sha256'], digest(out / (family + '-gain.json')))
                expected = report['validation_policies'][family]['global_confidence_sort']['request_histogram']
                for mode in ('schedule', 'budget'):
                    for sample in report['random_controls'][family][mode]['per_seed'].values():
                        self.assertEqual(sample['request_histogram'], expected)
            import zipfile
            with zipfile.ZipFile(out / 'urbaning-tree-pilot.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'validation-report.json', 'ridge-gain.json', 'tree-gain.json'})
            with self.assertRaises(FileExistsError):
                main(arguments)


class PilotGuardTests(unittest.TestCase):
    def test_recording_not_segment_split_and_no_test_cache_load(self):
        with self.assertRaises(ValueError):
            validate_splits([TRAIN], ['20241126_0017_crossing2_08'])
        with self.assertRaises(ValueError):
            validate_splits([TRAIN], ['20241127_0010_crossing3_08'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = make_run(root / 'train', TRAIN)
            test = make_run(root / 'test', '20241127_0010_crossing3_08')
            with patch('phdsim.experiments.urbaning_tree_pilot.load_runs') as loader:
                with self.assertRaises(ValueError):
                    main(['--train-runs', str(train), '--validation-runs', str(test),
                          '--train-geometry', 'unused', '--validation-geometry', 'unused',
                          '--output-dir', str(root / 'pilot')])
                loader.assert_not_called()
            self.assertFalse((root / 'pilot').exists())

    def test_fixed_baseline_fallback_and_conservative_ties(self):
        frames = [{'source_ids': ['100000', '-1']}, {'source_ids': ['100000']}]
        self.assertEqual(constant_choices(frames, 'vehicle_peer'), ['ego', 'ego'])
        self.assertEqual(constant_choices(frames, 'all'), ['infrastructure', 'ego'])
        rows = [{'validation': {'mean_frame_utility': .4, 'peer_requests': n}} for n in [20, 10, 10]]
        self.assertEqual(choose_candidate(rows), 1)
        with self.assertRaises(ValueError):
            select_models([{'key': 'a', 'sequence': TRAIN}], [{'key': 'b', 'sequence': VAL}])


if __name__ == '__main__':
    unittest.main()
