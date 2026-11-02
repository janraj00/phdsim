import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phdsim.decision.urbaning import available_subsets
from phdsim.experiments.urbaning_diagnostics import (
    availability, marginal_gains, prediction_errors, diagnose_model, analyze)
from phdsim.experiments.urbaning_subsets import load_runs, fit, comparison
from test_urbaning_subsets import make_run


class DiagnosticsTests(unittest.TestCase):
    def test_availability_and_marginal_gain_are_conditioned_on_feasible_pairs(self):
        frames = [
            {'source_ids': ['100000', '-3'], 'quality': {'ego': .4, 'infrastructure': .6}},
            {'source_ids': ['100000', '200000', '-3'],
             'quality': {'ego': .4, 'vehicle_peer': .5, 'infrastructure': .6, 'all': .7}},
            {'source_ids': ['100000', '200000', '-3'],
             'quality': {'ego': .4, 'vehicle_peer': .5, 'infrastructure': .6, 'all': .5}},
            {'source_ids': ['100000'], 'quality': {'ego': .4}}]
        self.assertEqual([availability(f) for f in frames], ['infra_only', 'both', 'both', 'none'])
        g = marginal_gains(frames, .05)
        self.assertEqual(g['infra_over_ego']['n'], 3)
        self.assertEqual(g['car2_given_infra']['n'], 2)
        self.assertAlmostEqual(g['car2_given_infra']['mean'], 0.)
        self.assertEqual(g['car2_given_infra']['negative_fraction'], .5)
        self.assertEqual(g['car2_given_infra']['above_frozen_cost_fraction'], .5)
        self.assertEqual(marginal_gains(frames[-1:], .05)['both_over_ego'], {'n': 0})

    def test_error_sign_and_undefined_correlation(self):
        d = prediction_errors([.2, .4], [.1, .3])
        self.assertAlmostEqual(d['bias_predicted_minus_observed'], .1)
        self.assertAlmostEqual(d['mae'], .1)
        self.assertAlmostEqual(d['pearson'], 1.)
        self.assertIsNone(prediction_errors([.2, .2], [.1, .3])['pearson'])
        self.assertEqual(prediction_errors([], []), {'n': 0})

    def test_regret_uses_actual_utility_and_verifies_frozen_choices(self):
        f = {'key': 'f', 'source_ids': ['100000', '-3'], 'features': [],
             'quality': {'ego': .5, 'infrastructure': .52}}
        model = {'request_cost': .05}
        with patch('phdsim.experiments.urbaning_diagnostics.predict_gains', return_value={
                'infrastructure': .2, 'vehicle_peer': 1., 'all': 1.}):
            result = diagnose_model([f], model, ['infrastructure'])
            self.assertAlmostEqual(result['utility_regret_vs_hindsight']['mean'], .03)
            self.assertEqual(result['chosen_worse_utility_than_ego_fraction'], 1.)
            self.assertEqual(result['gain_heads']['vehicle_peer']['n'], 0)
            with self.assertRaisesRegex(ValueError, 'does not reproduce'):
                diagnose_model([f], model, ['ego'])

    def test_analysis_grouping_and_saved_report_parity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            train, p = load_runs([make_run(root / 'train', '20241126_0001_crossing2_00')])
            val, _ = load_runs([make_run(root / 'val', '20241126_0004_crossing2_00')])
            frames, p = load_runs([make_run(root / 'a', '20241127_0010_crossing3_08'),
                                   make_run(root / 'b', '20241127_0010_crossing3_09')])
            # Two segments of one original recording must not become two independent groups.
            model = fit(train, val, [1.], .05); model['detector'] = p['detector']
            saved = {str(mode): comparison(frames, p, [0, 1], model=model, global_sort=mode)
                     for mode in (False, True)}
            result = analyze(frames, model, saved, [0, 1])
            self.assertEqual(list(result['recordings']), ['20241127_0010'])
            self.assertEqual(result['recordings']['20241127_0010']['frames'], 8)
            self.assertEqual(result['availability']['both']['frames'], 8)
            self.assertEqual(result['availability']['infra_only']['frames'], 0)
            self.assertEqual(result['marginal_f1_gains']['car2_given_infra']['n'], 8)
            json.dumps(result, allow_nan=False)
            bad = copy.deepcopy(saved)
            bad['False']['policies']['all']['macro_ap']['0.5'] = 0.
            with self.assertRaisesRegex(ValueError, 'Analysis AP differs'):
                analyze(frames, model, bad, [0, 1])
