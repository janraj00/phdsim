import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from phdsim.learning.urbaning import fit_joint_gain, predict_gains, assert_unseen_recordings
from phdsim.learning.urbaning_geometry import FEATURES, SCHEMA, geometry_features
from phdsim.experiments.urbaning_geometry import read_pose
from phdsim.experiments.urbaning_subsets import load_runs, fit, comparison, digest
from test_urbaning_subsets import box, make_run, IDS


def transform(x, y=0, yaw=0):
    c, s = np.cos(yaw), np.sin(yaw)
    m = np.eye(4)
    m[:2, :2] = [[c, -s], [s, c]]
    m[:2, 3] = [x, y]
    return m


class GeometryTests(unittest.TestCase):
    def test_distance_uses_uncertain_ego_boxes_and_peer_coordinates(self):
        boxes = np.array([box(20), box(-40)])
        scores = np.array([[.3, 1], [.95, 1]])
        poses = {'200000': transform(18), '-1': transform(-30)}
        values = geometry_features(IDS, .6, scores, boxes, poses)
        named = dict(zip(FEATURES, values))
        self.assertAlmostEqual(named['vehicle_uncertain_min_distance_over_100'], .02)
        self.assertAlmostEqual(named['infra_uncertain_min_distance_over_100'], .5)
        np.testing.assert_allclose(values, geometry_features(IDS, .6, scores[::-1], boxes[::-1], poses))
        # Rotating every ego-coordinate quantity together preserves distances.
        rotation = transform(0, yaw=np.pi / 2)
        rotated = boxes @ rotation[:3, :3].T
        rotated_poses = {k: rotation @ v for k, v in poses.items()}
        other = dict(zip(FEATURES, geometry_features(IDS, .6, scores, rotated, rotated_poses)))
        for name in FEATURES:
            if 'distance' in name or 'view_cosine' in name:
                self.assertAlmostEqual(named[name], other[name])

    def test_missing_empty_and_invalid_evidence(self):
        x = geometry_features(['100000'], .2, np.empty((0, 2)), np.empty((0, 8, 3)), {})
        self.assertEqual(len(x), 32)
        self.assertTrue(np.isfinite(x).all())
        np.testing.assert_array_equal(x[16:], 0)
        with self.assertRaises(ValueError):
            geometry_features(IDS, .2, np.empty((0, 2)), np.empty((0, 8, 3)), {})
        bad = transform(2); bad[0, 0] = 2
        with self.assertRaises(ValueError):
            geometry_features(['100000', '200000'], .2, np.empty((0, 2)),
                              np.empty((0, 8, 3)), {'200000': bad})
        # High-confidence detections do not create low-score proximity evidence.
        high = geometry_features(['100000', '200000'], .2, np.array([[.9, 1]]),
                                 np.array([box(20)]), {'200000': transform(18)})
        np.testing.assert_array_equal(high[20:24], 0)

    def test_ridge_learns_partner_distance_signal(self):
        xs, ys = [], []
        for distance in np.linspace(1, 30, 30):
            xs.append(geometry_features(IDS, .6, np.array([[.3, 1]]), np.array([box(40)]),
                                        {'200000': transform(40-distance), '-1': transform(-10)}))
            ys.append([.4-distance/100, .1, .5-distance/100])
        model = fit_joint_gain(xs, ys, np.ones((30, 3), bool), .1,
                               ['20241126_0017_crossing1_00'], schema=SCHEMA)
        near, far = predict_gains(model, xs[0]), predict_gains(model, xs[-1])
        self.assertGreater(near['vehicle_peer'], far['vehicle_peer'] + .2)
        broken = dict(model, features=list(reversed(FEATURES)))
        with self.assertRaises(ValueError):
            predict_gains(broken, xs[0])

    def test_trace_bound_sidecars_fit_and_heldout_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames, provenances = [], []
            for n, sequence in enumerate(['20241126_0017_crossing1_00',
                                          '20241126_0004_crossing2_00',
                                          '20241127_0009_crossing3_00']):
                run = make_run(root / str(n), sequence)
                rows = list(map(json.loads, (run / 'frames.jsonl').read_text().splitlines()))
                sidecar = {'schema': SCHEMA, 'trace_sha256': digest(run / 'frames.jsonl'),
                           'metadata_assumption': 'fixture pose beacons',
                           'frames': {row['frame_key']: {'200000': transform(15).tolist(),
                                                         '-1': transform(-20).tolist()} for row in rows}}
                path = root / ('poses%s.json' % n)
                path.write_text(json.dumps(sidecar))
                f, p = load_runs([run], [path]); frames.append(f); provenances.append(p)
                if n == 0:
                    sidecar['trace_sha256'] = 'stale'
                    path.write_text(json.dumps(sidecar))
                    with self.assertRaises(ValueError):
                        load_runs([run], [path])
            model = fit(frames[0], frames[1], [.1, 1], .05)
            model['detector'] = provenances[0]['detector']
            report = comparison(frames[2], provenances[2], [0, 1, 2], model)
            self.assertIn('learned_joint_gain', report['policies'])
            with self.assertRaises(ValueError):
                comparison(frames[0], provenances[0], [0], model)
            wrong = [dict(f, feature_schema='wrong') for f in frames[2]]
            with self.assertRaises(ValueError):
                comparison(wrong, provenances[2], [0], model)

    def test_pose_reader_does_not_construct_other_yaml_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.yaml'
            path.write_text('lidar_pose: [1, 2, 3, 4, 5, 6]\nlabels: !!python/object:untrusted {}\n')
            self.assertEqual(read_pose(path), [1, 2, 3, 4, 5, 6])
            path.write_text('lidar_pose: [1, 2]\n')
            with self.assertRaises(ValueError):
                read_pose(path)


if __name__ == '__main__':
    unittest.main()
