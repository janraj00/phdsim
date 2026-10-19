"""Information boundaries and recording-level validation of learned acquisition."""

from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from phdsim.decision import DecisionConfig
from phdsim.decision.policies.expected_gain import ExpectedGain
from phdsim.experiments.presence.replay import ProcessingConfig, run_replay
from phdsim.fusion import FusionConfig, MeanProbabilityFusion
from phdsim.fusion.learned_probability import LearnedProbabilityFusion
from phdsim.learning.bundle import LearningBundle
from phdsim.learning.acquisition.features import acquisition_features
from phdsim.models.linear import LinearModel
from phdsim.learning.plan import make_plan
from phdsim.learning.acquisition.objectives import task_loss
from phdsim.learning.samples import collect_meta_samples
from phdsim.learning.fusion.training import crossfit_fusion
from phdsim.learning.training import fit_gain_bundle
from phdsim.learning.acquisition.objectives import gains
from phdsim.perception import TrainingResult
from phdsim.datasets import AgentSlot, ObservationPool, PoolRecord, allocate, prepare_pool, read_lines, write_json, write_lines
from phdsim.probability import binary_entropy, sigmoid
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.costs.types import CostVector
from phdsim.decision.view import DecisionView
from phdsim.perception.results import PerceptionEvidence, TaskResult
from phdsim.core.identity import TargetRef
from phdsim.runtime.presence import transfer_cost


class FixedPerception:
    version = 'test-fixed-perception'
    supported_modalities = ('rgb', 'thermal')

    def process(self, observation):
        value = float(observation.payload)
        p = sigmoid(value)
        features = (value, abs(value), value * value, 0., 0., 0., value, value)
        evidence = PerceptionEvidence(observation.observation_id, observation.modality, p, features)
        return TaskResult(observation.target, p, binary_entropy(p), (observation.observation_id,),
                          (self.version,), (evidence,))


def learning_fixture(root):
    source = root / 'source'
    source.mkdir()
    observations, labels = [], []
    for bag in range(2, 9):
        split = 'train' if bag < 7 else 'validation' if bag == 7 else 'test'
        sequence = f'31_bag{bag}'
        for tick in range(4):
            y = tick % 2
            target = TargetRef('frame', f'{sequence}-{tick}')
            labels.append({'target': {'kind': target.kind, 'id': target.id}, 'label': y})
            for modality in ('rgb', 'thermal'):
                name = f'{target.id}-{modality}'
                value = (2 * y - 1) * (0.6 if modality == 'rgb' else 1.3) + (bag % 3 - 1) * 0.7
                write_json(source / f'{name}.json', value)
                observations.append(PoolRecord(name, sequence, tick, target, split, f'{modality}-sensor',
                                    modality, f'{name}.json', 'scalar-json-v1').to_dict())
    write_lines(source / 'observations.jsonl', observations)
    write_lines(source / 'labels.jsonl', labels)
    pool = prepare_pool(source / 'observations.jsonl', root / 'pool', dataset_id='learning-test',
                        dataset_version='1', labels=source / 'labels.jsonl')
    plan = make_plan(pool, meta_fraction=0.6)
    trained = TrainingResult(FixedPerception(), 0.5,
                            {'fit': {}, 'training_sequences': plan['sequences']['cnn_train']})
    return pool, plan, trained


class LearningTests(unittest.TestCase):
    def test_classification_gain_rewards_repairs_penalizes_damage_and_ignores_confidence_only_changes(self):
        own = (0.2, 0.8, 0.1, 0.6, 0.5, 0.49)
        after = (0.8, 0.2, 0.4, 0.9, 0.49, 0.5)
        labels = (1, 1, 1, 1, 1, 0)
        samples = [{'label': label, 'rgb': PerceptionEvidence(str(i), 'rgb', p)}
                   for i, (p, label) in enumerate(zip(own, labels))]
        self.assertEqual(list(gains(samples, after, 'rgb', 'classification_error')), [1., -1., 0., 0., -1., -1.])
        self.assertGreater(gains(samples, after, 'rgb', 'brier')[2], 0)
        self.assertEqual(task_loss(0.5, 1, 'classification_error'), 0)
        self.assertEqual(task_loss(0.5, 0, 'classification_error'), 1)
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            task_loss(0.5, 0, 'typo')

    def test_changing_acquisition_objective_preserves_fusion_and_does_not_use_test_labels(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool, plan, trained = learning_fixture(root)
            samples = collect_meta_samples(pool, trained, plan)
            brier = fit_gain_bundle(pool, trained, plan, samples, root / 'brier', fusion_method='learned_probability')
            accuracy = fit_gain_bundle(pool, trained, plan, samples, root / 'accuracy',
                                       fusion_method='learned_probability', gain_metric='classification_error')
            self.assertEqual(brier.manifest['fusion_model'], accuracy.manifest['fusion_model'])
            self.assertEqual(accuracy.gain_metric, 'classification_error')
            teacher = read_lines(root / 'accuracy/meta_samples.jsonl')
            self.assertTrue(all(r['rgb_gain'] in (-1, 0, 1) and r['thermal_gain'] in (-1, 0, 1) for r in teacher))
            with self.assertRaisesRegex(ValueError, 'objective'):
                accuracy.validate(pool, trained, 'learned_probability', 'brier')
            test_ids = {r.target.id for r in pool.records if r.split == 'test'}
            labels = read_lines(pool.root / 'labels.jsonl')
            write_lines(pool.root / 'labels.jsonl', [{**r, 'label': 1 - r['label']} if r['target']['id'] in test_ids else r for r in labels])
            changed = ObservationPool(pool.root)
            changed_samples = collect_meta_samples(changed, trained, plan)
            again = fit_gain_bundle(changed, trained, plan, changed_samples, root / 'changed',
                                    fusion_method='learned_probability', gain_metric='classification_error')
            self.assertEqual(accuracy.manifest, again.manifest)
            # Existing saved bundles without an objective field retain their Brier meaning.
            legacy = {k: v for k, v in brier.manifest.items() if k not in ('version', 'gain_metric', 'classification_threshold')}
            from phdsim.learning.bundle import save_bundle
            loaded = save_bundle(root / 'legacy.json', legacy)
            self.assertEqual(loaded.gain_metric, 'brier')

    def test_plan_preserves_families_and_does_not_inspect_labels(self):
        records = [SimpleNamespace(sequence_id=f'31_bag{i}{suffix}', split='train', target=TargetRef('frame', f'{i}{suffix}'))
                   for i in range(2, 9) for suffix in ('', 'a')]
        records += [SimpleNamespace(sequence_id='31_bag10', split='validation', target=TargetRef('frame', 'val')),
                    SimpleNamespace(sequence_id='31_bag11', split='test', target=TargetRef('frame', 'test'))]
        class MetadataOnly:
            fingerprint = 'fixed'
            def read_labels(self):
                raise AssertionError('Splitting must not read labels')
        pool = MetadataOnly()
        pool.records = records
        plan = make_plan(pool, meta_fraction=0.4)
        groups = list(map(set, plan['recording_families'].values()))
        for i, first in enumerate(groups):
            for second in groups[i + 1:]:
                self.assertFalse(first & second)
        for names in plan['sequences'].values():
            for i in range(2, 9):
                self.assertEqual(f'31_bag{i}' in names, f'31_bag{i}a' in names)
        self.assertEqual(plan, make_plan(pool, meta_fraction=0.4))

    def test_learned_fusion_is_order_independent_and_waits_for_delivery(self):
        model = LinearModel('logistic', (0.,) * 4, (1.,) * 4, (1., 2., 0., 0.), 0., 10.)
        fusion = LearnedProbabilityFusion(model, 'learned-test')
        target = TargetRef('frame', 'one')
        rgb = TaskResult(target, 0.6, binary_entropy(0.6), ('rgb',), ('model-rgb',),
                         (PerceptionEvidence('rgb', 'rgb', 0.6),))
        thermal = TaskResult(target, 0.8, binary_entropy(0.8), ('thermal',), ('model-thermal',),
                             (PerceptionEvidence('thermal', 'thermal', 0.8),))
        self.assertEqual(fusion.update(None, rgb), rgb)
        self.assertAlmostEqual(fusion.update(rgb, thermal).prediction, fusion.update(thermal, rgb).prediction)
        self.assertEqual(MeanProbabilityFusion().update(rgb, thermal).evidence, rgb.evidence + thermal.evidence)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            fusion.update(rgb, rgb)
        with self.assertRaisesRegex(ValueError, 'targets'):
            fusion.update(rgb, replace(thermal, target=TargetRef('frame', 'other')))
        with self.assertRaisesRegex(ValueError, 'exactly'):
            fusion.update(rgb, replace(thermal, evidence=(PerceptionEvidence('thermal', 'rgb', 0.8),)))

    def test_gain_policy_uses_expected_value_and_cost_rather_than_entropy_alone(self):
        model = LinearModel('ridge', (0.,) * 3, (1.,) * 3, (1., 0., 0.), -0.2, 10.)
        policy = ExpectedGain({('rgb', 'thermal'): model}, 'version', False, transfer_penalty=0.1)
        target = TargetRef('frame', 'one')
        candidate = ActionEstimate(Acquire('pull', 'a', 'b', target, 'thermal'), transfer_cost(1000))
        def view(p):
            result = TaskResult(target, p, binary_entropy(p), ('own',), ('model',),
                                (PerceptionEvidence('own', 'rgb', p),))
            return DecisionView('a', target, result, (), (), ('rgb',), ('b',), CostVector())
        self.assertAlmostEqual(view(0.1).result.uncertainty, view(0.9).result.uncertainty)
        self.assertIsInstance(policy.choose(view(0.1), (candidate,)), Stop)
        self.assertIsInstance(policy.choose(view(0.9), (candidate,)), Acquire)
        expensive = replace(policy, transfer_penalty=0.8)
        self.assertIsInstance(expensive.choose(view(0.9), (candidate,)), Stop)
        priced_bytes = replace(policy, transfer_penalty=0., megabyte_penalty=0.1)
        large = replace(candidate, action=replace(candidate.action, action_id='a-large'), cost=transfer_cost(10_000_000))
        small = replace(candidate, action=replace(candidate.action, action_id='z-small'), cost=transfer_cost(1000))
        self.assertEqual(priced_bytes.choose(view(0.9), (large, small)), small.action)
        self.assertIsInstance(policy.choose(view(0.9), ()), Stop)
        self.assertIsInstance(policy.choose(view(0.9), (replace(candidate, action=replace(candidate.action, modality='rgb')),)), Stop)

    def test_crossfit_fusion_never_fits_the_held_out_recording_label(self):
        samples = []
        for group in range(4):
            for tick in range(4):
                y = tick % 2
                samples.append({'group': str(group), 'label': y,
                                'rgb': PerceptionEvidence(f'{group}-{tick}-rgb', 'rgb', 0.3 + 0.4 * y),
                                'thermal': PerceptionEvidence(f'{group}-{tick}-thermal', 'thermal', 0.2 + 0.6 * y)})
        first = crossfit_fusion(samples, 'learned_probability', 10.)
        changed = [{**s, 'label': 1 - s['label']} if s['group'] == '0' else s for s in samples]
        second = crossfit_fusion(changed, 'learned_probability', 10.)
        self.assertEqual(list(first[:4]), list(second[:4]))
        self.assertTrue(any(abs(a - b) > 1e-6 for a, b in zip(first[4:], second[4:])))

    def test_bundle_roundtrip_meta_scope_and_test_label_isolation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool, plan, trained = learning_fixture(root)
            samples = collect_meta_samples(pool, trained, plan)
            bundle = fit_gain_bundle(pool, trained, plan, samples, root / 'models',
                                     fusion_method='learned_probability', gain_regularizations=(1., 10.))
            loaded = LearningBundle.load(root / 'models/learning.json')
            self.assertEqual(bundle.manifest, loaded.manifest)
            scope = {r.sequence_id for r in pool.records if r.split == 'train'}
            bad = replace(trained, model_snapshot={**trained.model_snapshot, 'training_sequences': sorted(scope)})
            with self.assertRaisesRegex(ValueError, 'Meta recordings|scope'):
                loaded.validate(pool, bad, 'learned_probability')
            with self.assertRaisesRegex(ValueError, 'fresh CNNs'):
                collect_meta_samples(pool, bad, plan)
            with self.assertRaisesRegex(ValueError, 'fusion'):
                loaded.validate(pool, trained, 'mean_probability')
            processing = ProcessingConfig(FusionConfig('learned_probability'),
                         (DecisionConfig('learned_gain'), DecisionConfig('learned_gain_confidence'),
                          DecisionConfig('random_acquisition', probability=0.5)))
            schedule = allocate(pool, (AgentSlot('rgb', 'rgb', 4), AgentSlot('thermal', 'thermal', 4)))
            run_replay(pool, schedule, root / 'first', processing=processing, trained=trained, learned=loaded)
            label_path = pool.root / 'labels.jsonl'
            rows = read_lines(label_path)
            test_ids = {r.target.id for r in pool.records if r.split == 'test'}
            changed = [{**r, 'label': 1 - r['label']} if r['target']['id'] in test_ids else r for r in rows]
            write_lines(label_path, changed)
            changed_pool = ObservationPool(pool.root)
            loaded.validate(changed_pool, trained, 'learned_probability')
            second_samples = collect_meta_samples(changed_pool, trained, plan)
            fit_gain_bundle(changed_pool, trained, plan, second_samples, root / 'second_models',
                            fusion_method='learned_probability', gain_regularizations=(1., 10.))
            self.assertEqual((root / 'models/learning.json').read_bytes(),
                             (root / 'second_models/learning.json').read_bytes())
            run_replay(changed_pool, schedule, root / 'second', processing=processing, trained=trained, learned=loaded)
            for name in ('decisions.jsonl', 'transfers.jsonl', 'models.json'):
                self.assertEqual((root / 'first' / name).read_bytes(), (root / 'second' / name).read_bytes())
            meta_ids = {r.target.id for r in pool.records if r.sequence_id in plan['sequences']['meta_train']}
            write_lines(label_path, [{**r, 'label': 1 - r['label']} if r['target']['id'] in meta_ids else r for r in rows])
            with self.assertRaisesRegex(ValueError, 'Meta labels'):
                loaded.validate(ObservationPool(pool.root), trained, 'learned_probability')
            stored = json.loads((root / 'models/learning.json').read_text())
            stored['fusion_model']['intercept'] += 1
            write_json(root / 'models/tampered.json', stored)
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                LearningBundle.load(root / 'models/tampered.json')


if __name__ == '__main__':
    unittest.main()
