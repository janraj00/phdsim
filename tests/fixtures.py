'Synthetic scalars used only in tests; the user-facing experiment uses real images.'
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from random import Random
from phdsim.core.identity import TargetRef
from phdsim.perception import FitConfig, train_scalar_perception
from phdsim.fusion import IndependentEvidenceFusion
from phdsim.serialization import jsonable
from pathlib import Path
from phdsim.datasets import ObservationPool, PoolRecord, prepare_pool, write_json, write_lines


def train_scalar_pool(pool, modalities, config=FitConfig()):
    trained = train_scalar_perception(pool, modalities, config)
    return trained.perception, IndependentEvidenceFusion(trained.class_prior)


@dataclass(frozen=True)
class GeneratorConfig:
    train_samples: int = 1500
    validation_samples: int = 500
    test_samples: int = 1000
    signal: float = 1.0
    coarse_noise: float = 1.6
    detail_noise: float = 0.8

    def __post_init__(self) -> None:
        for count in (self.train_samples, self.validation_samples, self.test_samples):
            if not isinstance(count, int) or isinstance(count, bool) or count < 2:
                raise ValueError('Each data split needs at least two samples')
        if any((not isfinite(value) or value <= 0 for value in (self.signal, self.coarse_noise, self.detail_noise))):
            raise ValueError('Signal and noise scales must be positive and finite')

@dataclass(frozen=True)
class MeasurementRow:
    target: TargetRef
    label: int
    coarse: float
    detail: float

@dataclass(frozen=True)
class MeasurementSplit:
    name: str
    rows: tuple[MeasurementRow, ...]

@dataclass(frozen=True)
class MeasurementDataset:
    seed: int
    config: GeneratorConfig
    train: MeasurementSplit
    validation: MeasurementSplit
    test: MeasurementSplit
    version: str
    content_sha256: str

def generate_measurements(seed: int, config: GeneratorConfig=GeneratorConfig()) -> MeasurementDataset:
    splits = []
    digest = sha256()
    digest.update(json.dumps(jsonable(config), sort_keys=True).encode())
    for name, count in (('train', config.train_samples), ('validation', config.validation_samples), ('test', config.test_samples)):
        stream_seed = int.from_bytes(sha256(f'measurements-v1:{seed}:{name}'.encode()).digest()[:8], 'big')
        rng = Random(stream_seed)
        rows = []
        for index in range(count):
            label = rng.randrange(2)
            center = config.signal if label else -config.signal
            row = MeasurementRow(TargetRef('sample', f'{name}-{index:06d}'), label, center + rng.gauss(0, config.coarse_noise), center + rng.gauss(0, config.detail_noise))
            rows.append(row)
            digest.update(json.dumps(jsonable(row), sort_keys=True).encode())
        splits.append(MeasurementSplit(name, tuple(rows)))
    fingerprint = digest.hexdigest()
    return MeasurementDataset(seed, config, *splits, f'gaussian-two-source-v1:{fingerprint[:16]}', fingerprint)

def make_proxy_pool(output: str | Path, seed: int=42, config: GeneratorConfig=GeneratorConfig(300, 50, 400)) -> ObservationPool:
    """Generate raw scalar measurements, then exercise the real Stage A importer."""
    root = Path(output).resolve()
    raw = root / 'adapter_input'
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f'Output directory is not empty: {root}')
    (raw / 'values').mkdir(parents=True)
    dataset = generate_measurements(seed, config)
    records, labels = ([], [])
    for split in (dataset.train, dataset.validation, dataset.test):
        for tick, row in enumerate(split.rows):
            labels.append({'target': {'kind': row.target.kind, 'id': row.target.id}, 'label': row.label})
            for modality, value in (('rgb', row.coarse), ('thermal', row.detail)):
                observation_id = f'{row.target.id}-{modality}'
                path = f'values/{observation_id}.json'
                write_json(raw / path, value)
                records.append(PoolRecord(observation_id, f'{split.name}-sequence', tick, row.target, split.name, f'proxy-{modality}-sensor', modality, path, 'scalar-json-v1').to_dict())
    write_lines(raw / 'observations.jsonl', records)
    write_lines(raw / 'labels.jsonl', labels)
    write_json(raw / 'provenance.json', {'data_kind': 'synthetic scalar proxies; no RGB/thermal images were processed', 'seed': seed, 'generator_version': dataset.version, 'assumption': 'independent measurement noise conditional on class; ticks are independent samples'})
    return prepare_pool(raw / 'observations.jsonl', root / 'pool', dataset_id='synthetic-rgb-thermal-scalar-proxy', dataset_version=dataset.version, labels=raw / 'labels.jsonl')
