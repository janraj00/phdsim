"""Agent-independent observation records and immutable payload packages."""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import shutil
from phdsim.core.identity import TargetRef
from phdsim.artifacts import digest, read_lines, write_json, write_lines

POOL_SCHEMA = 'phdsim-observation-pool-v1'


@dataclass(frozen=True)
class PoolRecord:
    observation_id: str
    sequence_id: str
    tick: int
    target: TargetRef
    split: str
    stream_id: str
    modality: str
    payload_path: str
    payload_format: str
    payload_sha256: str = ''
    capture_time_ns: int | None = None
    calibration_ref: str | None = None
    pose_ref: str | None = None

    def __post_init__(self):
        if not all((isinstance(v, str) and v for v in (self.observation_id, self.sequence_id, self.stream_id, self.modality, self.payload_path, self.payload_format))):
            raise ValueError('Observation identifiers, modality and payload description are required')
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError('tick must be a nonnegative integer')
        if self.split not in ('train', 'validation', 'test'):
            raise ValueError('Unknown data split')
        if self.capture_time_ns is not None and (type(self.capture_time_ns) is not int or self.capture_time_ns < 0):
            raise ValueError('capture_time_ns must be a nonnegative integer')
        if self.payload_sha256 and (len(self.payload_sha256) != 64 or any((c not in '0123456789abcdef' for c in self.payload_sha256))):
            raise ValueError('Invalid payload SHA256')
        if not isinstance(self.target.kind, str) or not isinstance(self.target.id, str):
            raise ValueError('Target kind and id must be strings')
        for reference in (self.calibration_ref, self.pose_ref):
            if reference is not None and (not isinstance(reference, str) or not reference):
                raise ValueError('Invalid calibration/pose reference')

    @property
    def frame(self) -> tuple[str, int]:
        return (self.sequence_id, self.tick)

    def to_dict(self) -> dict:
        return {'observation_id': self.observation_id, 'sequence_id': self.sequence_id, 'tick': self.tick, 'target': {'kind': self.target.kind, 'id': self.target.id}, 'split': self.split, 'stream_id': self.stream_id, 'modality': self.modality, 'payload': {'path': self.payload_path, 'format': self.payload_format, 'sha256': self.payload_sha256}, 'capture_time_ns': self.capture_time_ns, 'calibration_ref': self.calibration_ref, 'pose_ref': self.pose_ref}

    @classmethod
    def from_dict(cls, row: dict) -> 'PoolRecord':
        allowed = {'observation_id', 'sequence_id', 'tick', 'target', 'split', 'stream_id', 'modality', 'payload', 'capture_time_ns', 'calibration_ref', 'pose_ref'}
        if set(row) - allowed or set(row['payload']) - {'path', 'format', 'sha256'}:
            raise ValueError('Unknown pool fields; agent ownership and labels do not belong in observations')
        return cls(row['observation_id'], row['sequence_id'], row['tick'], TargetRef(**row['target']), row['split'], row['stream_id'], row['modality'], row['payload']['path'], row['payload']['format'], row['payload'].get('sha256', ''), row.get('capture_time_ns'), row.get('calibration_ref'), row.get('pose_ref'))


def validate_records(records: tuple[PoolRecord, ...]) -> None:
    if not records or len({r.observation_id for r in records}) != len(records):
        raise ValueError('Pool must contain observations with unique ids')
    frames, sequences, targets, streams, slots = ({}, {}, {}, {}, set())
    for row in records:
        for mapping, key, value in ((frames, row.frame, (row.target, row.split)), (sequences, row.sequence_id, row.split), (targets, row.target, row.split), (streams, row.stream_id, row.modality)):
            if key in mapping and mapping[key] != value:
                raise ValueError('Inconsistent frame/target, sequence split or stream modality')
            mapping[key] = value
        slot = (row.frame, row.stream_id)
        if slot in slots:
            raise ValueError('One stream may have only one observation per frame')
        slots.add(slot)


def pool_fingerprint(records: tuple[PoolRecord, ...], dataset_id: str, dataset_version: str) -> str:
    value = [POOL_SCHEMA, dataset_id, dataset_version, [r.to_dict() for r in records]]
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ObservationPool:

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.manifest = json.loads((self.root / 'pool.json').read_text(encoding='utf-8'))
        if self.manifest['schema'] != POOL_SCHEMA:
            raise ValueError('Unsupported pool schema')
        self.records = tuple((PoolRecord.from_dict(row) for row in read_lines(self.root / 'observations.jsonl')))
        validate_records(self.records)
        self.by_id = {r.observation_id: r for r in self.records}
        self.fingerprint = pool_fingerprint(self.records, self.manifest['dataset_id'], self.manifest['dataset_version'])
        if self.fingerprint != self.manifest['observations_sha256']:
            raise ValueError('Observation manifest fingerprint mismatch')
        if self.manifest['observation_count'] != len(self.records):
            raise ValueError('Observation count mismatch')
        for row in self.records:
            self.payload_path(row)
            for reference in (row.calibration_ref, row.pose_ref):
                if reference is not None:
                    self._local_path(reference)

    def _local_path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(self.root) or (not path.is_file()):
            raise ValueError('Pool payload/calibration must be an existing file inside its package')
        return path

    def payload_path(self, row: PoolRecord) -> Path:
        return self._local_path(row.payload_path)

    def read_payload(self, observation_id: str) -> bytes:
        row = self.by_id[observation_id]
        content = self.payload_path(row).read_bytes()
        if sha256(content).hexdigest() != row.payload_sha256:
            raise ValueError('Payload fingerprint mismatch')
        return content

    def read_labels(self) -> dict[TargetRef, object]:
        """Only offline training and the evaluator call this method."""
        path = self.root / 'labels.jsonl'
        if not path.exists():
            return {}
        result = {}
        targets = {r.target for r in self.records}
        for row in read_lines(path):
            if set(row) != {'target', 'label'}:
                raise ValueError('Labels require target and label')
            target = TargetRef(**row['target'])
            if target not in targets or target in result:
                raise ValueError('Duplicate or unknown label target')
            result[target] = row['label']
        return result


def prepare_pool(input_manifest: str | Path, output: str | Path, *, dataset_id: str, dataset_version: str, labels: str | Path | None=None) -> ObservationPool:
    """Normalize an adapter's JSONL manifest and copy referenced assets unchanged."""
    source = Path(input_manifest).resolve()
    records = tuple((PoolRecord.from_dict(row) for row in read_lines(source)))
    validate_records(records)
    if not dataset_id or not dataset_version:
        raise ValueError('Dataset identity and version are required')
    inputs = {}
    for row in records:
        for reference in (row.payload_path, row.calibration_ref, row.pose_ref):
            if reference is not None:
                path = (source.parent / reference).resolve()
                if not path.is_file():
                    raise ValueError(f'Missing source asset: {reference}')
                inputs[reference] = path
        if row.payload_sha256 and digest(inputs[row.payload_path]) != row.payload_sha256:
            raise ValueError('Source payload fingerprint mismatch')
    destination = Path(output).resolve()
    if destination == source.parent or destination in source.parents:
        raise ValueError('Output must not replace the source directory')
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f'Output directory is not empty: {destination}')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'assets').mkdir(exist_ok=True)
    copied = {}
    for reference, path in inputs.items():
        fingerprint = digest(path)
        relative = f'assets/{fingerprint}{path.suffix.lower()}'
        if not (destination / relative).exists():
            shutil.copyfile(path, destination / relative)
        copied[reference] = (relative, fingerprint)
    normalized = []
    for row in records:
        data = row.to_dict()
        path, fingerprint = copied[row.payload_path]
        data['payload'] = {'path': path, 'format': row.payload_format, 'sha256': fingerprint}
        data['calibration_ref'] = copied[row.calibration_ref][0] if row.calibration_ref else None
        data['pose_ref'] = copied[row.pose_ref][0] if row.pose_ref else None
        normalized.append(PoolRecord.from_dict(data))
    result = tuple(normalized)
    write_lines(destination / 'observations.jsonl', (r.to_dict() for r in result))
    write_json(destination / 'pool.json', {'schema': POOL_SCHEMA, 'dataset_id': dataset_id, 'dataset_version': dataset_version, 'observations_sha256': pool_fingerprint(result, dataset_id, dataset_version), 'observation_count': len(result), 'alignment': 'explicit frame/target mapping supplied by adapter; no pixel alignment implied'})
    if labels is not None:
        write_lines(destination / 'labels.jsonl', read_lines(Path(labels)))
    pool = ObservationPool(destination)
    pool.read_labels()
    return pool
