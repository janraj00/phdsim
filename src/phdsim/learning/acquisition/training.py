"""Fit directional gain regressors with nested validation by recording family."""

from dataclasses import asdict
import numpy as np

from phdsim.learning.fusion.training import crossfit_fusion, fused_probabilities
from phdsim.models.linear import fit_linear
from .features import acquisition_features
from .objectives import gains


def fit_gain_models(samples, *, fusion_method, fusion_regularization, gain_regularizations, gain_metric):
    """Select regularization out of family, retaining harmful acquisition targets.

    Inner fusion models generate targets without the corresponding family.
    Outer families score acquisition predictions. Final directional regressors
    use all meta samples, with the selected regularization and out-of-fold
    fusion outcomes. No test observation participates in this procedure.
    """
    variants = {'learned_gain_confidence': False, 'learned_gain': True}
    groups = sorted({s['group'] for s in samples})
    outer_probabilities = np.zeros(len(samples))
    scores = {(variant, modality, reg): [] for variant in variants for modality in ('rgb', 'thermal')
              for reg in gain_regularizations}
    outer_forecasts = {(variant, modality, reg): np.zeros(len(samples))
                       for variant, modality, reg in scores}
    folds = []
    for group in groups:
        train = [s for s in samples if s['group'] != group]
        indices = [i for i, s in enumerate(samples) if s['group'] == group]
        held = [samples[i] for i in indices]
        # Inner teacher models exclude both the outer family and each teacher row's family.
        inner_p = crossfit_fusion(train, fusion_method, fusion_regularization)
        outer_p = fused_probabilities(train, held, fusion_method, fusion_regularization)
        outer_probabilities[indices] = outer_p
        folds.append({'held_out_family': group, 'train_families': sorted({s['group'] for s in train}),
                      'train_frames': len(train), 'held_out_frames': len(held)})
        for variant, quality in variants.items():
            for modality in ('rgb', 'thermal'):
                x = [acquisition_features(s[modality], quality) for s in train]
                y = gains(train, inner_p, modality, gain_metric)
                expected = gains(held, outer_p, modality, gain_metric)
                for reg in gain_regularizations:
                    model = fit_linear(x, y, kind='ridge', regularization=reg)
                    forecasts = [model.predict(acquisition_features(s[modality], quality)) for s in held]
                    outer_forecasts[variant, modality, reg][indices] = forecasts
                    scores[variant, modality, reg].append(float(np.mean((np.array(forecasts) - expected) ** 2)))
        print(f'{fusion_method}: meta fold {group}, {len(train)} train / {len(held)} held out', flush=True)
    models, diagnostics = {}, {}
    for variant, quality in variants.items():
        models[variant], diagnostics[variant] = [], {}
        for modality, incoming in (('rgb', 'thermal'), ('thermal', 'rgb')):
            selected = min(gain_regularizations, key=lambda reg: (np.mean(scores[variant, modality, reg]), -reg))
            target = gains(samples, outer_probabilities, modality, gain_metric)
            model = fit_linear([acquisition_features(s[modality], quality) for s in samples], target,
                               kind='ridge', regularization=selected)
            models[variant].append({'own_modality': modality, 'incoming_modality': incoming, 'model': asdict(model)})
            diagnostics[variant][modality] = {
                'selected_regularization': selected,
                'group_cv_mse': {str(reg): float(np.mean(scores[variant, modality, reg])) for reg in gain_regularizations},
                'teacher_mean_gain': float(target.mean()), 'teacher_positive_gain_fraction': float(np.mean(target > 0)),
                'teacher_negative_gain_fraction': float(np.mean(target < 0)),
                'teacher_zero_gain_fraction': float(np.mean(target == 0)),
                'out_of_fold_forecasts': [float(v) for v in outer_forecasts[variant, modality, selected]],
            }
    return models, diagnostics, folds, outer_probabilities
