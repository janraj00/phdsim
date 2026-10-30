"""Export pose-only sidecars from immutable converted inputs, without inference."""

import argparse
import json
from pathlib import Path

import yaml

from phdsim.experiments.urbaning_subsets import digest, write_json
from phdsim.learning.urbaning_geometry import SCHEMA, validate_transform


def read_pose(path):
    # Compose, never construct the document: converted YAML also contains labels
    # and can carry Python tags. Only six scalar pose fields leave this adapter.
    node = yaml.compose(Path(path).read_text())
    if not isinstance(node, yaml.MappingNode):
        raise ValueError('Expected converted YAML mapping')
    matches = [v for k, v in node.value if k.value == 'lidar_pose']
    if len(matches) != 1 or not isinstance(matches[0], yaml.SequenceNode) or len(matches[0].value) != 6:
        raise ValueError('Expected one six-component lidar_pose')
    if any(not isinstance(v, yaml.ScalarNode) for v in matches[0].value):
        raise ValueError('Expected scalar pose components')
    return [float(v.value) for v in matches[0].value]


def export(run_directory, upstream, output, converted_root=None):
    from phdsim.experiments.urbaning_stage1 import prepare_upstream
    revision = prepare_upstream(upstream)
    from opencood.utils.transformation_utils import x1_to_x2
    root = Path(run_directory).resolve()
    run = json.loads((root / 'run.json').read_text())
    if run.get('status') != 'completed' or run.get('schema') != 'phdsim-urbaning-stage1-v1':
        raise ValueError('Export requires a completed stage1 run')
    frames, hashes = {}, {}
    for row in map(json.loads, (root / 'frames.jsonl').read_text().splitlines()):
        poses = {}
        for identity in row['sources']['included_ids']:
            record = row['source_files'][identity]['yaml']
            path = Path(record['path']) if converted_root is None else (
                Path(converted_root) / run['arguments']['sequence'] / identity / (row['source_frame_id'] + '.yaml'))
            if digest(path) != record['sha256']:
                raise ValueError('Converted pose-source hash mismatch')
            poses[identity] = read_pose(path)
            hashes[str(path)] = record['sha256']
        ego = row['sources']['included_ids'][0]
        if row['frame_key'] in frames:
            raise ValueError('Duplicate frame')
        frames[row['frame_key']] = {identity: validate_transform(x1_to_x2(pose, poses[ego])).tolist()
                                     for identity, pose in poses.items() if identity != ego}
    result = {'schema': SCHEMA, 'trace_sha256': digest(root / 'frames.jsonl'),
              'upstream_commit': revision, 'source_yaml_sha256': hashes, 'frames': frames,
              'metadata_assumption': 'Current poses shared before querying perception; no measured beacon overhead',
              'infra_pose_semantics': 'bundled site-frame origin proxy, not physical sensor location',
              'scope': 'offline native associations, not validated causal pose availability'}
    write_json(output, result)


def load_sidecars(paths):
    result = {}
    for path in paths:
        value = json.loads(Path(path).read_text())
        if value.get('schema') != SCHEMA or value.get('trace_sha256') in result:
            raise ValueError('Invalid or duplicate geometry sidecar')
        result[value['trace_sha256']] = (value, digest(path))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--converted-root', help='Relocated converted root; source hashes must still match')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError('Use a new geometry output')
    export(args.run, args.upstream, args.output, args.converted_root)
    print(args.output)
