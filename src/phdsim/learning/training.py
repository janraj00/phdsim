"""Orchestrate independent fusion/acquisition fitting and persist a frozen bundle."""

from dataclasses import asdict
from pathlib import Path

from phdsim.artifacts import write_lines
from .acquisition.features import CONFIDENCE_NAMES, QUALITY_NAMES
from .acquisition.objectives import GAIN_METRICS, gains, teacher_description
from .acquisition.training import fit_gain_models
from .bundle import meta_fingerprint, save_bundle
from .fusion.features import FUSION_NAMES
from .fusion.training import fit_fusion
from .samples import validate_meta_samples


def fit_gain_bundle(pool, trained, plan, samples, output, *, fusion_method,
                    fusion_regularization=10., gain_regularizations=(1., 10., 100.), gain_metric='brier'):
    """Nested leave-family-out selection; targets retain harmful (negative) transfers."""
    output = Path(output)
    if gain_metric not in GAIN_METRICS:
        raise ValueError(f'Unknown acquisition gain metric: {gain_metric}')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Learning output is not empty: {output}')
    validate_meta_samples(pool, plan, samples)
    models, diagnostics, folds, outer_probabilities = fit_gain_models(
        samples, fusion_method=fusion_method, fusion_regularization=fusion_regularization,
        gain_regularizations=gain_regularizations, gain_metric=gain_metric)
    fusion = fit_fusion(samples, fusion_regularization) if fusion_method == 'learned_probability' else None
    row = {
        'schema': 'phdsim-acquisition-models-v1', 'pool_fingerprint': pool.fingerprint,
        'perception_version': trained.perception.version, 'meta_sha256': meta_fingerprint(pool, plan['sequences']['meta_train']),
        'plan': plan, 'fusion_method': fusion_method, 'fusion_model': asdict(fusion) if fusion else None,
        'fusion_regularization': fusion_regularization, 'gain_models': models,
        'feature_names': {'fusion': FUSION_NAMES, 'learned_gain_confidence': CONFIDENCE_NAMES,
                          'learned_gain': CONFIDENCE_NAMES + QUALITY_NAMES},
        'gain_metric': gain_metric, 'classification_threshold': 0.5,
        'teacher': teacher_description(gain_metric),
        'crossfit': 'outer leave-recording-family-out; inner leave-family-out teacher generation; group-mean MSE selects gain ridge penalty',
        'fusion_selection': 'regularization fixed in advance; final fit on meta recordings only',
        'runtime_inputs': 'own probability, own entropy and optionally eight own-image summaries; candidate modality and estimated transfer cost',
        'forbidden_runtime_inputs': 'neighbor image/prediction before transfer, label, mask, target ID as learned feature',
        'folds': folds, 'diagnostics': diagnostics,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_lines(output / 'meta_samples.jsonl', ({'target': asdict(s['target']), 'recording_family': s['group'],
                'reference_label': s['label'], 'rgb': asdict(s['rgb']), 'thermal': asdict(s['thermal']),
                'crossfit_fused_probability': float(p),
                'gain_metric': gain_metric,
                'rgb_gain': float(gains([s], [p], 'rgb', gain_metric)[0]),
                'thermal_gain': float(gains([s], [p], 'thermal', gain_metric)[0])}
                for s, p in zip(samples, outer_probabilities)))
    bundle = save_bundle(output / 'learning.json', row)
    bundle.validate(pool, trained, fusion_method)
    return bundle
