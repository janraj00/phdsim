import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch

from phdsim.perception.urbaning.rgb3d_finetune import (
    collapse_rows, projected_targets, train_key, FineTuneDetector, install_empty_sampler)
from phdsim.perception.urbaning.rgb3d_late import upright_boxes
from phdsim.evaluation.urbaning_cached import frame_statistics, aggregate_statistics, summarize_cached
from phdsim.experiments import urbaning_rgb3d_finetune as runner

CATEGORIES = ['pedestrian', 'car', 'cyclist', 'van', 'truck', 'traffic cone',
              'barrier', 'motorcycle', 'bicycle', 'bus', 'trailer']
E = np.array([[0., -1, 0, 0], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]])
K = np.array([[100., 0, 160], [0, 100, 100], [0, 0, 1]])
R = np.array([[0., 0, -1], [0, 1, 0], [1, 0, 0]])


def truth():
    return upright_boxes([[0, 0, 10]], [[2, 2, 4]], R[None], E)


class Geometry(unittest.TestCase):
    def test_class_initialization_and_background_are_exact(self):
        values = np.arange(12*4*2, dtype=np.float32).reshape(48, 2)
        before = values.copy()
        out = collapse_rows(values, CATEGORIES, 4, True).reshape(5, 4, 2)
        self.assertEqual(out.shape, (5, 4, 2))
        source = values.reshape(12, 4, 2)
        np.testing.assert_array_equal(out[0], source[[1, 3]].mean(0))
        np.testing.assert_array_equal(out[1], source[[4, 9, 10]].mean(0))
        np.testing.assert_array_equal(out[2], source[[2, 7]].mean(0))
        np.testing.assert_array_equal(out[3], source[0])
        np.testing.assert_array_equal(out[-1], source[-1])
        np.testing.assert_array_equal(values, before)
        with self.assertRaises(ValueError):
            collapse_rows(values[:-1], CATEGORIES, 4, True)

    def test_projected_cuboids_roundtrip_in_both_handednesses(self):
        gt = truth()
        for extrinsic in (E, np.diag([-1., 1, 1, 1]) @ E):
            row = projected_targets(gt, [1], extrinsic, K, 320, 200)[0]
            self.assertEqual(row['class'], 0)
            self.assertAlmostEqual(np.linalg.det(row['pose']), 1.)
            np.testing.assert_allclose(row['dimensions'], [2, 2, 4])
            np.testing.assert_allclose(row['pixel'], [160, 100])
            # Compare corner SETS because a handedness change flips local width.
            unit = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)])
            recovered = (unit*row['dimensions'][[2, 1, 0]]) @ row['pose'].T + row['center']
            expected = gt[0] @ extrinsic[:3, :3].T + extrinsic[:3, 3]
            distances = np.linalg.norm(recovered[:, None]-expected[None], axis=2)
            np.testing.assert_allclose(distances.min(1), 0, atol=1e-10)
            back = upright_boxes(row['center'][None], row['dimensions'][None], row['pose'][None], extrinsic)
            np.testing.assert_allclose(back, gt, atol=1e-10)

    def test_small_boxes_ignore_and_near_plane_skips_camera(self):
        gt = truth()
        small_k = K.copy(); small_k[:2, :2] *= .1
        self.assertEqual(projected_targets(gt, [4], E, small_k, 320, 200)[0]['class'], -1)
        crossing = gt.copy(); crossing[:, :, 0] -= 10
        self.assertIsNone(projected_targets(crossing, [1], E, K, 320, 200))
        self.assertEqual(projected_targets(np.empty((0, 8, 3)), [], E, K, 320, 200), [])

    def test_fit_recording_boundary(self):
        train_key('20241126_0001_crossing2_00:000001:100000')
        train_key('20241126_0017_crossing1_00:000001:100000')
        for key in ('20241126_0004_crossing2_00:000001:100000',
                    '20241127_0010_crossing3_08:000001:100000',
                    '20241126_0001_crossing2_00:000001:200000'):
            with self.assertRaises(ValueError):
                train_key(key)


class Boxes:
    def __init__(self, tensor):
        self.tensor = torch.as_tensor(tensor)


class Instances:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __len__(self):
        return len(next(iter(self.__dict__.values())).tensor)

    def __getitem__(self, index):
        return Instances(**{k: Boxes(v.tensor[index]) for k, v in self.__dict__.items()})


class EmptySampler(unittest.TestCase):
    def test_background_updates_keep_ignore_regions_out(self):
        roi = types.SimpleNamespace(num_classes=4, batch_size_per_image=128, ignore_thresh=.5,
                                    label_and_sample_proposals=lambda p, t: 'positive-native')
        modules = {'detectron2.structures': types.SimpleNamespace(Boxes=Boxes)}
        with patch.dict(sys.modules, modules):
            install_empty_sampler(roi)
            proposals = Instances(proposal_boxes=Boxes([[0., 0, 10, 10], [20, 20, 30, 30]]))
            target = types.SimpleNamespace(gt_classes=torch.tensor([-1]), gt_boxes=Boxes([[0., 0, 10, 10]]))
            result = roi.label_and_sample_proposals([proposals], [target])[0]
            self.assertEqual(result.gt_classes.tolist(), [4])
            np.testing.assert_array_equal(result.proposal_boxes.tensor.numpy(), [[20, 20, 30, 30]])
            self.assertEqual(tuple(result.gt_boxes3D.shape), (1, 9))
            target.gt_classes = torch.tensor([0])
            self.assertEqual(roi.label_and_sample_proposals([proposals], [target]), 'positive-native')


class NativeHeadShapes(unittest.TestCase):
    def test_all_native_category_tensors_are_collapsed_and_only_heads_train(self):
        import phdsim.perception.urbaning.rgb3d_late as source
        model = torch.nn.Module()
        model.backbone = torch.nn.Linear(2, 2)
        model.proposal_generator = torch.nn.Linear(2, 2)
        roi = model.roi_heads = torch.nn.Module()
        roi.box_head = torch.nn.Linear(2, 2)
        predictor = roi.box_predictor = torch.nn.Module()
        predictor.cls_score = torch.nn.Linear(2, 12)
        predictor.bbox_pred = torch.nn.Linear(2, 44)
        head = roi.cube_head = torch.nn.Module()
        head.pose_type = '6d'; roi.cluster_bins = 1; roi.z_type = 'direct'
        for name, block in (('bbox_3D_dims', 3), ('bbox_3D_center_deltas', 2),
                            ('bbox_3D_pose', 6), ('bbox_3D_center_depth', 1), ('bbox_3D_uncertainty', 1)):
            setattr(head, name, torch.nn.Linear(2, 11*block))
        roi.priors_dims_per_cat = torch.nn.Parameter(torch.ones(1, 11, 2, 3))
        roi.priors_z_scales = torch.nn.Parameter(torch.ones(11, 1))
        roi.label_and_sample_proposals = lambda p, t: 'native'
        old_weights = predictor.cls_score.weight.detach().numpy().copy()
        factory = lambda *a, **k: types.SimpleNamespace(model=model, categories=CATEGORIES)
        modules = {'detectron2.structures': types.SimpleNamespace(Boxes=Boxes)}
        with patch.object(source, 'CubeDetector', side_effect=factory), patch.dict(sys.modules, modules):
            detector = FineTuneDetector(Path('/unused'), 1)
        self.assertEqual(predictor.cls_score.out_features, 5)
        self.assertEqual(predictor.bbox_pred.out_features, 16)
        self.assertEqual(head.bbox_3D_pose.out_features, 24)
        self.assertEqual(tuple(roi.priors_dims_per_cat.shape), (1, 4, 2, 3))
        self.assertEqual(tuple(roi.priors_z_scales.shape), (4, 1))
        np.testing.assert_allclose(predictor.cls_score.weight.detach().numpy(), collapse_rows(old_weights, CATEGORIES, background=True))
        self.assertTrue(all(p.requires_grad == k.startswith(('roi_heads.box_head.', 'roi_heads.box_predictor.', 'roi_heads.cube_head.'))
                            for k, p in model.named_parameters()))
        state = detector.trainable_state()
        detector.load_trainable(state)
        with self.assertRaises(ValueError):
            detector.load_trainable({})


class EventStorage:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def step(self): pass


class ToyDetector(FineTuneDetector):
    def __init__(self, *args):
        torch.manual_seed(0)
        self.model = torch.nn.Module()
        self.model.roi_heads = torch.nn.Module()
        self.model.roi_heads.cube_head = torch.nn.Linear(1, 1)
        self.model.register_buffer('frozen_source', torch.tensor([3.]))

    def training_input(self, image, k, rows):
        return {'positive': any(r['class'] >= 0 for r in rows)}

    def losses(self, inputs):
        value = self.model.roi_heads.cube_head(torch.ones(1))
        losses = {'loss_cls': (value-(.2 if inputs['positive'] else -.2)).square().sum()}
        if inputs['positive']:
            losses['cube/loss_z'] = (value-.3).square().sum()
        return losses

    def predict(self, image, k):
        return {'centers': np.array([[0., 0, 10]]), 'dimensions': np.array([[2., 2, 4]]),
                'rotations': R[None], 'classes': np.array([0]), 'scores': np.array([.8])}


class Pipeline(unittest.TestCase):
    def test_synthetic_400_200_freeze_controls_and_saved_ap_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); model = root/'model'; model.mkdir()
            (model/'official.bin').write_bytes(b'original')
            runtime = root/'runtime'; runtime.mkdir(); (runtime/'ready.json').write_text('{}')
            out = root/'output'; source_dir = root/'source'; source_dir.mkdir(); source = source_dir/'source.zip'
            gt = truth(); scores = np.array([[.8, 1.]])
            records = {}
            for split, sequences in (('train', ['20241126_0001_crossing2_00', '20241126_0017_crossing1_00']),
                                     ('validation', ['20241126_0004_crossing2_00'])):
                records[split] = [{'key': f'{sequence}:{i+1:06}:100000', 'sequence': sequence,
                    'boxes': gt, 'scores': scores, 'gt_boxes': gt, 'gt_labels': np.array([1])}
                    for sequence in sequences for i in range(200)]
            stats = frame_statistics(gt, scores, gt, np.array([1]))
            report = {'schema': 'phdsim-rgb3d-native-depth-controlled-v1'}
            for split in records:
                total = aggregate_statistics([stats]*len(records[split]))
                both = {name: summarize_cached(total, order) for name, order in
                        (('global_confidence_sort', True), ('upstream_default_frame_order', False))}
                report[split+'_metrics'] = {v: both for v in ('lidar', 'rgb_baseline', 'rgb_depth_finetuned')}
            with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('report.json', json.dumps(report))
                for split, rows in records.items():
                    for row in rows:
                        buffer = io.BytesIO()
                        np.savez(buffer, lidar_boxes=gt, lidar_scores=scores,
                                 rgb_baseline_boxes=gt, rgb_baseline_scores=scores,
                                 rgb_depth_boxes=gt, rgb_depth_scores=scores,
                                 gt_boxes=gt, gt_labels=np.array([1]))
                        z.writestr('frames-'+split+'/'+row['key'].replace(':', '_')+'.npz', buffer.getvalue())
            original_bytes = source.read_bytes()
            (source_dir/'completed.json').write_text(json.dumps({'sha256': runner.sha(original_bytes)}))
            source_sha = runner.sha(original_bytes)
            def inputs(base, folder, ntrain, nval):
                if nval:
                    self.assertTrue((out/'models/freeze.json').is_file())
                    self.assertFalse(json.loads((out/'models/freeze.json').read_text())['validation_loaded'])
                return {'train': records['train'] if ntrain else [],
                        'validation': records['validation'] if nval else []}, {'synthetic': True}
            def camera(record, index):
                return np.zeros((200, 320, 3), np.uint8), E, K, {'key': record['key'], 'camera': index}
            def targets(*args):
                rows = projected_targets(*args)
                # All classes receive synthetic support; camera0 keeps real geometry.
                return [dict(rows[0], **{'class': c}) for c in range(4)]
            modules = {'detectron2.utils.events': types.SimpleNamespace(EventStorage=EventStorage)}
            with patch.dict(sys.modules, modules), patch.object(runner, 'read_inputs', side_effect=inputs), \
                 patch.object(runner, 'camera', side_effect=camera), patch.object(runner, 'projected_targets', side_effect=targets), \
                 patch.object(runner, 'FineTuneDetector', ToyDetector), patch.object(runner, 'EPOCHS', 1), \
                 patch.object(runner, 'OUTDOOR_ASSETS', {'official.bin': runner.sha(b'original')}), contextlib.redirect_stdout(io.StringIO()):
                archive = runner.run(root, runtime, model, source, out, 1)
                with self.assertRaisesRegex(ValueError, 'fresh'):
                    runner.run(root, runtime, model, source, out, 1)
            final_report = json.loads((out/'report.json').read_text())
            self.assertEqual(final_report['freeze']['updates'], 2400)
            self.assertEqual(final_report['freeze']['class_support'], [2400]*4)
            for split in records:
                self.assertTrue(final_report['splits'][split]['source_ap_reproduced'])
                self.assertTrue(final_report['splits'][split]['saved_prediction_ap_reproduced'])
                self.assertEqual(set(final_report['splits'][split]['metrics']), set(runner.VARIANTS))
            self.assertEqual(runner.sha(source.read_bytes()), source_sha)
            self.assertEqual((model/'official.bin').read_bytes(), b'original')
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.npz')]), 600)
                self.assertIn('models/final-heads.pt', z.namelist())
            source.write_bytes(original_bytes+b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                runner.source_archive(source)


if __name__ == '__main__':
    unittest.main()
