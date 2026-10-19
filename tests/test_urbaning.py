"""Source integrity, timing, geometry and portable metadata for the UrbanIng spike."""

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from phdsim.datasets.urbaning.archive import checked_member
from phdsim.datasets.urbaning.catalog import build_catalog, read_sync
from phdsim.datasets.urbaning.geometry import box_corners, project_points, read_lidar, transform_points
from phdsim.datasets.urbaning.labels import read_annotations, seconds_to_ns
from phdsim.datasets.urbaning.source import DEFAULT_SEQUENCE, SUPPORT_FILES, _download, sequence_files


class Response(io.BytesIO):
    def __init__(self, body, status=200, **headers):
        super().__init__(body)
        self.status = status
        self.headers = headers


def metadata():
    names = [(DEFAULT_SEQUENCE + '.7z.001', 'dataset'),
             (DEFAULT_SEQUENCE + '.json', 'labels')]
    names += [(name, '') for name in sorted(SUPPORT_FILES)]
    names += [('digital_twin.7z.001', ''), ('20241126_0001_crossing2_00.7z.001', 'dataset')]
    files = [{'directoryLabel': directory, 'restricted': False,
              'dataFile': {'id': i, 'filename': name, 'filesize': 10,
                           'checksum': {'type': 'MD5', 'value': 'a'*32}}}
             for i, (name, directory) in enumerate(names)]
    return {'data': {'latestVersion': {'versionNumber': 1, 'versionMinorNumber': 0, 'files': files}}}


def track(timestamps):
    return {'track_id': 4, 'object_type': 'Car', 'timestamps': timestamps,
            'positions': [[0, 0, 1]] * len(timestamps), 'orientations': [0] * len(timestamps),
            'dimensions': [[4, 2, 2]], 'attributes': {'occlusion': ['visible'] * len(timestamps)}}


class UrbanIngTest(unittest.TestCase):
    def test_source_selection_excludes_other_sequences_and_digital_twin(self):
        result = sequence_files(metadata(), DEFAULT_SEQUENCE)
        self.assertEqual(len(result), 5)
        self.assertFalse(any('digital_twin' in item['name'] for item in result))
        self.assertFalse(any('0001_crossing2' in item['name'] for item in result))
        with self.assertRaises(ValueError):
            sequence_files(metadata(), '../another')
        broken = metadata()
        broken['data']['latestVersion']['files'][0]['dataFile']['filename'] = DEFAULT_SEQUENCE + '.7z.002'
        with self.assertRaises(ValueError):
            sequence_files(broken, DEFAULT_SEQUENCE)

    def test_download_resume_and_checksum_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = b'abcdef'
            item = {'name': 'sample.bin', 'relative_path': 'sample.bin', 'bytes': len(body),
                    'source_id': 1, 'md5': hashlib.md5(body).hexdigest()}
            (root / 'sample.bin.partial').write_bytes(b'abc')
            response = Response(b'def', 206, **{'Content-Range': 'bytes 3-5/6'})
            with patch('urllib.request.urlopen', return_value=response):
                result = _download(root, item)
            self.assertEqual((root / 'sample.bin').read_bytes(), body)
            self.assertEqual(result['sha256'], hashlib.sha256(body).hexdigest())

    def test_invalid_range_and_hash_never_publish_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = {'name': 'sample.bin', 'relative_path': 'sample.bin', 'bytes': 6,
                    'source_id': 1, 'md5': hashlib.md5(b'abcdef').hexdigest()}
            (root / 'sample.bin.partial').write_bytes(b'abc')
            with patch('urllib.request.urlopen', return_value=Response(b'abcdef')):
                with self.assertRaisesRegex(ValueError, 'resume range'):
                    _download(root, item)
            self.assertFalse((root / 'sample.bin').exists())
            (root / 'sample.bin.partial').write_bytes(b'wrong!')
            with self.assertRaisesRegex(ValueError, 'MD5'):
                _download(root, item)
            self.assertFalse((root / 'sample.bin').exists())

    def test_json_is_valid_source_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            body = b'{"id": 1}'
            item = {'name': 'labels.json', 'relative_path': 'labels.json', 'bytes': len(body),
                    'source_id': 1, 'md5': hashlib.md5(body).hexdigest()}
            with patch('urllib.request.urlopen', return_value=Response(body, **{'Content-Type': 'application/json'})):
                _download(Path(temporary), item)
            self.assertEqual((Path(temporary) / 'labels.json').read_bytes(), body)

    def test_archive_paths_are_bounded(self):
        for name in ('../escape', '/absolute', r'C:\absolute', r'folder\..\escape'):
            with self.assertRaises(ValueError):
                checked_member(name)
        self.assertEqual(checked_member('camera/123.jpg'), 'camera/123.jpg')

    def test_sync_preserves_missing_and_future_sensor_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'timesync_info.csv'
            path.write_text(',0,1\ntimestamp_ms,1700000000000,1700000000100\n'
                            'camera,1700000000001.jpg,\n', encoding='utf-8')
            rows = read_sync(path)
            self.assertEqual(rows[0]['timestamp_ns'], 1700000000000000000)
            self.assertEqual(rows[0]['members']['camera'], '1700000000001.jpg')
            self.assertIsNone(rows[1]['members']['camera'])
            path.write_text(',0,1\ntimestamp_ms,1700000000000,1700000000000\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_sync(path)

    def test_labels_keep_precision_and_reference_only_access(self):
        self.assertEqual(seconds_to_ns('1732636213.1'), 1732636213100000000)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'labels.json'
            path.write_text(json.dumps({'tracks': [track([1732636213.0, 1732636213.1])]}), encoding='utf-8')
            rows = read_annotations(path, DEFAULT_SEQUENCE)
            self.assertEqual(rows[1]['timestamp_ns'] - rows[0]['timestamp_ns'], 100000000)
            self.assertEqual(rows[0]['access'], 'offline_ground_truth')
            self.assertEqual(rows[0]['dimensions_lwh_m'], [4, 2, 2])
            path.write_text(json.dumps({'tracks': [track([1732636213.0, 1732636213.0])]}), encoding='utf-8')
            with self.assertRaises(ValueError):
                read_annotations(path, DEFAULT_SEQUENCE)

    def test_known_geometry_and_projection(self):
        matrix = np.eye(4)
        matrix[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        matrix[:3, 3] = [10, 20, 30]
        np.testing.assert_allclose(transform_points(np.array([[1, 0, 0]]), matrix), [[10, 21, 30]])
        camera = np.eye(4)
        pixels, valid = project_points(np.array([[1, 2, 10], [1, 2, -10]]), camera,
                                       np.array([[100, 0, 50], [0, 100, 40], [0, 0, 1]]))
        np.testing.assert_allclose(pixels[0], [60, 60])
        self.assertEqual(valid.tolist(), [True, False])
        corners = box_corners({'dimensions_lwh_m': [4, 2, 2], 'position_m': [0, 0, 1], 'yaw_rad': np.pi/2})
        np.testing.assert_allclose(corners.max(axis=0), [1, 2, 2])

    @unittest.skipUnless(importlib.util.find_spec('duckdb'), 'UrbanIng extra not installed')
    def test_catalog_preserves_native_samples_and_int64_timestamps(self):
        import duckdb
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'extracted' / DEFAULT_SEQUENCE
            directory.mkdir(parents=True)
            (directory / 'extraction.json').write_text(json.dumps({'sequence_relative_path': '.'}), encoding='utf-8')
            (root / 'source').mkdir()
            (root / 'source' / f'{DEFAULT_SEQUENCE}-download.json').write_text(
                json.dumps({'dataset_version': '1.0'}), encoding='utf-8')
            (root / 'source/dataverse-dataset.json').write_text(json.dumps(metadata()), encoding='utf-8')
            names = ['vehicle1_front_left_camera', 'crossing1_13_thermal_camera',
                     'vehicle1_middle_lidar', 'vehicle1_state']
            stamps = [1700000000000, 1700000000100]
            sync_rows = [['', '0', '1'], ['timestamp_ms', *stamps]]
            for name in names:
                (directory / name).mkdir()
                filenames = []
                for index, stamp in enumerate(stamps):
                    if name.endswith('camera'):
                        filename = f'{stamp+1}.jpg'
                        Image.new('RGB', (16, 12), (index*20, 80, 60)).save(directory / name / filename)
                    elif name.endswith('lidar'):
                        filename = f'{stamp}.npz'
                        np.savez(directory / name / filename, x=np.array([0., 1.]), y=np.zeros(2), z=np.ones(2),
                                 intensity=np.ones(2), time_offset_ms=np.array([0., 1.]))
                    else:
                        filename = f'{stamp}.json'
                        (directory / name / filename).write_text(json.dumps({'gTv': np.eye(4).tolist()}), encoding='utf-8')
                    filenames.append(filename)
                sync_rows.append([name, *filenames])
            with (directory / 'timesync_info.csv').open('w', newline='', encoding='utf-8') as handle:
                csv.writer(handle).writerows(sync_rows)
            (directory / 'calibration.json').write_text(json.dumps({name: {} for name in names if not name.endswith('state')}), encoding='utf-8')
            labels = root / 'raw/labels'
            labels.mkdir(parents=True)
            (labels / f'{DEFAULT_SEQUENCE}.json').write_text(json.dumps({'tracks': [track([1700000000., 1700000000.1, 1700000000.2])]}), encoding='utf-8')
            catalog = build_catalog(root, DEFAULT_SEQUENCE)
            manifest = json.loads((catalog / 'manifest.json').read_text())
            self.assertEqual(manifest['tables']['observations']['rows'], 8)
            self.assertEqual(manifest['tables']['annotations']['rows'], 3)
            self.assertEqual(manifest['annotated_anchor_count'], 2)
            self.assertEqual(manifest['unmatched_annotation_timestamps_ns'], [1700000000200000000])
            with duckdb.connect() as connection:
                row = connection.read_parquet(str(catalog / 'observations.parquet')).aggregate(
                    'min(timestamp_ns), max(timestamp_ns)').fetchone()
            self.assertEqual(row, (1700000000000000000, 1700000000101000000))
            associations = [json.loads(line) for line in (catalog / 'associations.jsonl').read_text().splitlines()]
            self.assertEqual(associations[0]['offset_ns'], 1000000)
            assets = [json.loads(line) for line in (catalog / 'assets.jsonl').read_text().splitlines()]
            self.assertTrue(all(not Path(item['storage_key']).is_absolute() for item in assets))
            self.assertEqual(build_catalog(root, DEFAULT_SEQUENCE), catalog)


if __name__ == '__main__':
    unittest.main()
