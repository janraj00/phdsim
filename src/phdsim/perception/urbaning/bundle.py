"""Pinned official CoBEVT release; no upstream source or weights are vendored."""

import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request

UPSTREAM_COMMIT = 'd5766e75f985c6c566a09abfa23d3fbb32f03820'
RELEASE_URL = 'https://github.com/thi-ad/UrbanIng-V2X/releases/tag/v1.0.0'
ARCHIVE_URL = RELEASE_URL.replace('/tag/', '/download/') + '/CoBEVT_SIS_1_2_vs_3.7z'
ARCHIVE_BYTES = 31691270
ARCHIVE_SHA256 = '9c02b3bf069f421f266c0ca68a0448d149967235032f2a26948f1ffdb7bfd9ab'
BUNDLE_NAME = 'CoBEVT_SIS_1_2_vs_3'
FILE_HASHES = {
    'best_model.pth': '5fec613dfa8c15be306b0d9a323cd58c0d9e03ea07747f356a6ecd9c55185986',
    'config.yaml': '08d73e5019d3de3858459498866445c35d8994a5004eb802867f7558ed8cf826',
    'eval_3d_det.yaml': '9845ee27b44278d40ff84aefecdbc9ba9acaa97e6b4fc6591fc84a73f6719350',
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_bundle(directory):
    directory = Path(directory)
    for name, expected in FILE_HASHES.items():
        if sha256(directory / name) != expected:
            raise ValueError('Official model file failed SHA256 verification: ' + name)
    return {'release': RELEASE_URL, 'archive_sha256': ARCHIVE_SHA256,
            'files': dict(FILE_HASHES), 'upstream_commit': UPSTREAM_COMMIT}


def fetch_bundle(directory, archive=None):
    """Verify an existing bundle, or atomically publish a verified extraction."""
    import py7zr

    directory = Path(directory).resolve()
    if directory.exists():
        return verify_bundle(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cobevt-', dir=directory.parent) as temporary:
        temporary = Path(temporary)
        if archive is None:
            archive = temporary / 'release.7z'
            with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response, archive.open('xb') as output:
                size = 0
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(block)
                    if size > ARCHIVE_BYTES:
                        raise ValueError('Release download exceeds pinned size')
                    output.write(block)
        archive = Path(archive)
        if archive.stat().st_size != ARCHIVE_BYTES or sha256(archive) != ARCHIVE_SHA256:
            raise ValueError('Release archive failed size/SHA256 verification')
        with py7zr.SevenZipFile(archive, 'r') as handle:
            expected = {BUNDLE_NAME + '/' + name for name in FILE_HASHES}
            entries = handle.list()
            files = set()
            for entry in entries:
                if entry.is_symlink:
                    raise ValueError('Links are not allowed in model archives')
                if entry.is_file and entry.filename in expected:
                    files.add(entry.filename)
                elif not (entry.is_directory and entry.filename == BUNDLE_NAME):
                    raise ValueError('Unexpected release member: ' + entry.filename)
            if files != expected or len(entries) != len({e.filename for e in entries}):
                raise ValueError('Missing or duplicate release members')
            handle.extractall(path=temporary / 'unpacked')
        extracted = temporary / 'unpacked' / BUNDLE_NAME
        manifest = verify_bundle(extracted)
        (extracted / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if directory.exists():
            raise FileExistsError(directory)
        extracted.rename(directory)
    return manifest


def load_config(directory):
    """Read the pinned YAML without executing its serialized numpy object tag.

    Only grid_size is replaced; it is recomputed from the released geometry.
    Unknown tags elsewhere remain errors under SafeLoader.
    """
    import yaml

    verify_bundle(directory)
    root = yaml.compose((Path(directory) / 'config.yaml').read_text(), Loader=yaml.SafeLoader)
    node = root
    for key in ('model', 'args', 'point_pillar_scatter'):
        node = next(value for name, value in node.value if name.value == key)
    for index, (name, value) in enumerate(node.value):
        if name.value == 'grid_size':
            node.value[index] = (name, yaml.ScalarNode('tag:yaml.org,2002:null', 'null'))
            break
    config = yaml.safe_load(yaml.serialize(root))
    extent = config['preprocess']['cav_lidar_range']
    voxel = config['preprocess']['args']['voxel_size']
    config['model']['args']['point_pillar_scatter']['grid_size'] = [
        round((extent[i + 3] - extent[i]) / voxel[i]) for i in range(3)]
    return config
