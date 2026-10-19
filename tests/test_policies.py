"""The policy contract is enforced for incomplete and configured implementations."""

from types import SimpleNamespace
import unittest

from phdsim.decision import DecisionConfig, Policy


class PolicyContractTests(unittest.TestCase):
    def test_incomplete_policy_cannot_be_instantiated(self):
        class MissingConfiguration(Policy):
            def choose(self, view, candidates):
                return None

        with self.assertRaises(TypeError):
            Policy()
        with self.assertRaises(TypeError):
            MissingConfiguration()

    def test_every_configured_strategy_explicitly_implements_policy(self):
        bundle = SimpleNamespace(
            gain_models={'learned_gain': {}, 'learned_gain_confidence': {}},
            version='contract-test', gain_metric='classification_error')
        for method in ('no_acquisition', 'always_acquire', 'uncertainty_threshold',
                       'random_acquisition', 'learned_gain', 'learned_gain_confidence'):
            with self.subTest(method=method):
                policy = DecisionConfig(method).build(bundle)
                self.assertIsInstance(policy, Policy)
                self.assertFalse(type(policy).__abstractmethods__)
                self.assertEqual(policy.configuration()['name'], method)


if __name__ == '__main__':
    unittest.main()
