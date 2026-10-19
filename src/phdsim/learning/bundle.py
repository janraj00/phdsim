"""Frozen, schema-checked models bound to their CNN and development data."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from phdsim.fusion.learned_probability import LearnedProbabilityFusion
from phdsim.fusion.mean_probability import MeanProbabilityFusion
from phdsim.models.linear import LinearModel
from phdsim.learning.acquisition.features import CONFIDENCE_NAMES, QUALITY_NAMES
from phdsim.learning.fusion.features import FUSION_NAMES
from phdsim.learning.acquisition.objectives import GAIN_METRICS
from phdsim.datasets import write_json


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def meta_fingerprint(pool, sequences):
    labels = pool.read_labels()
    rows = sorted((r for r in pool.records if r.sequence_id in sequences), key=lambda r: r.observation_id)
    return fingerprint([(r.observation_id, r.payload_sha256, labels[r.target]) for r in rows])


@dataclass(frozen=True)
class LearningBundle:
    manifest: dict
    fusion: object
    gain_models: dict

    @property
    def version(self):
        return self.manifest['version']

    @property
    def fusion_method(self):
        return self.manifest['fusion_method']

    @property
    def gain_metric(self):
        return self.manifest.get('gain_metric', 'brier')

    def validate(self, pool, trained, fusion_method, gain_metric=None):
        row = self.manifest
        if row['pool_fingerprint'] != pool.fingerprint or row['perception_version'] != trained.perception.version:
            raise ValueError('Learning bundle belongs to another pool or perception model')
        if fusion_method != self.fusion_method:
            raise ValueError('Gain model was trained for another fusion method')
        if gain_metric is not None and gain_metric != self.gain_metric:
            raise ValueError('Gain model was trained for another acquisition objective')
        plan = row['plan']
        meta = set(plan['sequences']['meta_train'])
        fitting = trained.model_snapshot.get('training_sequences')
        actual = set(fitting) if fitting is not None else {r.sequence_id for r in pool.records if r.split == 'train'}
        if actual != set(plan['sequences']['cnn_train']) or meta & actual:
            raise ValueError('Meta recordings overlap CNN fitting, or fitting scope differs')
        if any(r.split != 'train' for r in pool.records if r.sequence_id in meta):
            raise ValueError('Only original train recordings may train meta models')
        if meta_fingerprint(pool, meta) != row['meta_sha256']:
            raise ValueError('Meta labels or observations changed')

    @classmethod
    def load(cls, path):
        row = json.loads(Path(path).read_text(encoding='utf-8'))
        if row['schema'] != 'phdsim-acquisition-models-v1':
            raise ValueError('Unknown learning model schema')
        if row['version'] != fingerprint({k: v for k, v in row.items() if k != 'version'}):
            raise ValueError('Learning model fingerprint mismatch')
        if row.get('gain_metric', 'brier') not in GAIN_METRICS or row.get('classification_threshold', 0.5) != 0.5:
            raise ValueError('Unknown acquisition objective or classification threshold')
        expected_features = {'fusion': list(FUSION_NAMES), 'learned_gain_confidence': list(CONFIDENCE_NAMES),
                             'learned_gain': list(CONFIDENCE_NAMES + QUALITY_NAMES)}
        if row['feature_names'] != expected_features:
            raise ValueError('Learning feature schema differs from runtime')
        method = row['fusion_method']
        if method == 'learned_probability':
            model = LinearModel.from_dict(row['fusion_model'])
            if model.kind != 'logistic' or len(model.center) != len(FUSION_NAMES):
                raise ValueError('Unexpected learned fusion model')
            fusion = LearnedProbabilityFusion(model, row['version'])
        elif method == 'mean_probability':
            fusion = MeanProbabilityFusion()
        else:
            raise ValueError('Unknown learned bundle fusion')
        gains = {name: {(item['own_modality'], item['incoming_modality']): LinearModel.from_dict(item['model'])
                        for item in models} for name, models in row['gain_models'].items()}
        if set(gains) != {'learned_gain', 'learned_gain_confidence'} or any(
                set(models) != {('rgb', 'thermal'), ('thermal', 'rgb')} for models in gains.values()):
            raise ValueError('Incomplete directional gain models')
        if any(model.kind != 'ridge' or len(model.center) != len(expected_features[name])
               for name, models in gains.items() for model in models.values()):
            raise ValueError('Unexpected acquisition model feature dimension')
        return cls(row, fusion, gains)


def save_bundle(path, row):
    row = {**row, 'version': fingerprint(row)}
    write_json(Path(path), row)
    return LearningBundle.load(path)
