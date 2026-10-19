"""A controlled comparison: same CNNs and allocation, two fusion methods."""

from dataclasses import asdict
import csv
import json
from pathlib import Path

from phdsim.decision import DecisionConfig
from phdsim.experiments.presence.replay import ProcessingConfig, evaluation_fingerprint, run_replay
from phdsim.fusion import FusionConfig
from phdsim.learning.bundle import LearningBundle
from phdsim.learning.config import LearningConfig
from phdsim.learning.plan import make_plan
from phdsim.learning.samples import collect_meta_samples
from phdsim.learning.training import fit_gain_bundle
from phdsim.experiments.presence.report import write_report
from phdsim.perception.cnn_training import load_cnn, train_cnn
from phdsim.datasets import AgentSlot, Schedule, allocate, write_json


def decision_configs(config):
    choices = [DecisionConfig('no_acquisition'), DecisionConfig('always_acquire')]
    for value in config.entropy_thresholds:
        choices.append(DecisionConfig('uncertainty_threshold', threshold=value, name=f'entropy_{value:g}'.replace('.', '_')))
    for rate in config.random_probabilities:
        for seed in config.random_seeds:
            choices.append(DecisionConfig('random_acquisition', name=f'random_{rate:g}_seed_{seed}'.replace('.', '_'),
                                          probability=rate, seed=seed))
    for method in ('learned_gain_confidence', 'learned_gain'):
        for penalty in config.transfer_penalties:
            choices.append(DecisionConfig(method, name=f'{method}_cost_{penalty:g}'.replace('.', '_'),
                                          transfer_penalty=penalty, megabyte_penalty=config.megabyte_penalty))
    return tuple(choices)


def _write_fixed(path, value, *, legacy_defaults=None):
    normalized = json.loads(json.dumps(value))
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if {**(legacy_defaults or {}), **saved} != normalized:
            raise ValueError(f'Existing configuration differs: {path}; choose a new output directory')
    else:
        write_json(path, value)


def run_learning_experiment(pool, output, cnn_directory, cnn_config, config, *, trace=False, reference_run=None):
    output, cnn_directory = Path(output).resolve(), Path(cnn_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = make_plan(pool, config.seed, config.meta_fraction)
    _write_fixed(output / 'plan.json', plan)
    _write_fixed(output / 'learning_config.json', asdict(config), legacy_defaults={'gain_metric': 'brier'})
    if (cnn_directory / 'models.json').exists():
        trained = load_cnn(pool, cnn_directory)
        if trained.model_snapshot['fit'] != asdict(cnn_config):
            raise ValueError('CNN bundle configuration differs; choose a new model directory')
    else:
        trained = train_cnn(pool, cnn_directory, cnn_config, training_sequences=plan['sequences']['cnn_train'])
    if set(trained.model_snapshot.get('training_sequences') or ()) != set(plan['sequences']['cnn_train']):
        raise ValueError('CNNs must be trained without meta recordings; choose a new model directory')
    choices, bundles = decision_configs(config), {}
    methods = ('mean_probability', 'learned_probability')
    samples = None
    # Complete and freeze ALL fitting before replaying any test images.
    for method in methods:
        directory = output / method / 'models'
        if (directory / 'learning.json').exists():
            bundle = LearningBundle.load(directory / 'learning.json')
            bundle.validate(pool, trained, method, config.gain_metric)
        else:
            if samples is None:
                samples = collect_meta_samples(pool, trained, plan)
            bundle = fit_gain_bundle(pool, trained, plan, samples, directory, fusion_method=method,
                                     fusion_regularization=config.fusion_regularization,
                                     gain_regularizations=config.gain_regularizations, gain_metric=config.gain_metric)
        bundles[method] = bundle
    if reference_run is not None:
        reference_run = Path(reference_run).resolve()
        if reference_run == output:
            raise ValueError('Reference and new run must use different output directories')
        reference_plan = json.loads((reference_run / 'plan.json').read_text(encoding='utf-8'))
        previous_config = asdict(LearningConfig.load(reference_run / 'learning_config.json'))
        new_config = asdict(config)
        previous_config.pop('gain_metric')
        new_config.pop('gain_metric')
        if reference_plan != plan or previous_config != new_config:
            raise ValueError('Objective comparison requires identical data roles and all other learning settings')
        for method in methods:
            previous = LearningBundle.load(reference_run / method / 'models/learning.json')
            previous.validate(pool, trained, method)
            if previous.manifest['fusion_model'] != bundles[method].manifest['fusion_model']:
                raise ValueError('Objective comparison must preserve the exact fusion model')
        _write_fixed(output / 'reference.json', {'path': str(reference_run),
                     'checks': 'same CNN version, plan, meta references, fusion weights and settings except acquisition objective'})
    _write_fixed(output / 'frozen.json', {'perception_version': trained.perception.version,
                 'learning_versions': {k: b.version for k, b in bundles.items()},
                 'processing': {method: asdict(ProcessingConfig(FusionConfig(method), choices)) for method in methods},
                 'trace': trace, 'scope': 'all fitted parameters and comparison settings fixed before test replay'})
    schedule_path = output / 'schedule.json'
    schedule = allocate(pool, (AgentSlot('rgb-01', 'rgb', 400), AgentSlot('thermal-01', 'thermal', 400)))
    if schedule_path.exists():
        if schedule != Schedule.load(schedule_path, pool):
            raise ValueError('Saved learning schedule differs')
    else:
        schedule.save(schedule_path)
    all_rows, summaries = [], {}
    for method in methods:
        processing = ProcessingConfig(FusionConfig(method), choices)
        directory = output / method / 'results'
        if (directory / 'summary.json').exists():
            saved = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
            if saved['acquisition_learning']['version'] != bundles[method].version or saved['processing'] != json.loads(json.dumps(asdict(processing))):
                raise ValueError('Existing replay uses other models or settings')
            if saved.get('evaluation_reference_sha256') != evaluation_fingerprint(pool, schedule):
                raise ValueError('Evaluation labels changed or the saved evaluation lacks a reference fingerprint; choose a new output')
            summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
        else:
            summary = run_replay(pool, schedule, directory, processing=processing, trained=trained,
                                 learned=bundles[method], trace=trace)
        summaries[method] = summary
        for choice in choices:
            result = summary['policies'][choice.key]
            all_rows.append({'fusion': method, 'policy': choice.key, 'method': choice.method, 'gain_metric': config.gain_metric,
                             'entropy_threshold': choice.threshold, 'transfer_penalty': choice.transfer_penalty,
                             'megabyte_penalty': choice.megabyte_penalty, 'random_probability': choice.probability if choice.method == 'random_acquisition' else None,
                             'seed': choice.seed if choice.method == 'random_acquisition' else None,
                             'agent_frames': result['agent_frames'], 'accuracy': result['accuracy'], 'brier': result['brier'],
                             'transfers': result['transfers'], 'bytes': result['bytes'],
                             'rgb_to_thermal_pulls': result['per_agent']['rgb-01']['transfers'],
                             'thermal_to_rgb_pulls': result['per_agent']['thermal-01']['transfers']})
        print(f'{method}: evaluated {len(choices)} fixed policies on {summary["scheduled_frames"]} frames', flush=True)
    with (output / 'comparison.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    write_json(output / 'comparison.json', {'plan': plan, 'config': asdict(config), 'rows': all_rows,
               'frozen_versions': {k: b.version for k, b in bundles.items()},
               'comparison_scope': f'same new CNNs trained on {plan["frames"]["cnn_train"]} frames; do not compare directly against the previous 191-frame CNN run',
               'test_status': plan['test_status']})
    write_report(output, plan, all_rows)
    if reference_run is not None:
        from phdsim.experiments.presence.comparison import write_objective_comparison
        write_objective_comparison(reference_run, output)
    return {'plan': plan['frames'], 'gain_metric': config.gain_metric,
            'policies_per_fusion': len(choices), 'output': str(output)}
