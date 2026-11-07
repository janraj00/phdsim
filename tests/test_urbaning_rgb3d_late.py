import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.perception.urbaning.rgb3d_late import (
    camera_to_ego, upright_boxes, classwise_nms, late_fuse, CLASS_MAP,model_assets,ASSETS)
from phdsim.evaluation.urbaning_cached import _polygon, polygon_iou


E = np.array([[0,-1,0,0],[0,0,-1,0],[1,0,0,0],[0,0,0,1]],dtype=float)
R_EGO = np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=float)


def box(x=10, y=0, yaw=0):
    c=np.array([[x,y,0.]])
    rz=np.array([[np.cos(yaw),-np.sin(yaw),0],
                 [np.sin(yaw),np.cos(yaw),0],[0,0,1.]])
    camera_center=c @ E[:3,:3].T
    rotation=E[:3,:3] @ rz @ R_EGO
    return upright_boxes(camera_center,[[2.,2.,4.]],rotation[None],E)


class GeometryAndFusion(unittest.TestCase):
    def test_pinned_converter_reflection_is_not_an_invalid_rotation(self):
        # Exact basis formula from pinned upstream create_opencood_format.py,
        # not a hand-built det+1 fixture. Native optical correction cancels
        # R1*inv(R2); the remaining rightmost R1 changes handedness.
        from phdsim.experiments.urbaning_rgb_pilot import R2_R1
        r1=np.diag([1.,-1,1,1])
        r2=np.array([[0,-1,0,0],[0,0,-1,0],[1,0,0,0],[0,0,0,1.]])
        r3=np.array([[0,-1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1.]])
        c=np.eye(4);c[:3,3]=[-1,2,-3]
        l=np.eye(4);l[:3,3]=[7,-3,2]
        converted=r1@np.linalg.inv(r2)@c@l@r3@r1
        optical=R2_R1@converted
        np.testing.assert_allclose(optical,c@l@r3@r1)
        self.assertAlmostEqual(np.linalg.det(optical[:3,:3]),-1)
        points=np.array([[10.,2.,1.],[8.,-4.,-1.]])
        observed=points@optical[:3,:3].T+optical[:3,3]
        inv=camera_to_ego(optical)
        np.testing.assert_allclose(observed@inv[:3,:3].T+inv[:3,3],points)
        # Encode an upright physical cuboid in this reflected camera basis;
        # its inverse must recover the known center/dimensions/BEV overlap.
        axes=R_EGO.copy();axes[:,2]*=-1  # left-handed ego -> proper camera pose
        pose=optical[:3,:3]@axes
        self.assertAlmostEqual(np.linalg.det(pose),1)
        bb=upright_boxes(observed[:1],[[2.,2.,4.]],pose[None],optical)[0]
        np.testing.assert_allclose(bb.mean(axis=0),points[0])
        np.testing.assert_allclose(np.ptp(bb,axis=0),[4,2,2])
        self.assertAlmostEqual(polygon_iou(_polygon(bb),_polygon(box(10,2)[0])),1)
        # Keep all structural checks: a scale/shear is NOT a handedness change.
        bad=optical.copy();bad[0,:3]*=1.001
        with self.assertRaisesRegex(ValueError,'orthogonal_error'):camera_to_ego(bad)
        bad=optical.copy();bad[:3,3]=np.nan
        with self.assertRaises(ValueError):camera_to_ego(bad)

    def test_camera_axes_dimensions_and_yaw(self):
        b=box()[0]
        np.testing.assert_allclose(b.mean(axis=0),[10,0,0],atol=1e-12)
        np.testing.assert_allclose(np.ptp(b,axis=0),[4,2,2],atol=1e-12)
        b=box(15,3,np.pi/2)[0]
        np.testing.assert_allclose(b.mean(axis=0),[15,3,0],atol=1e-12)
        np.testing.assert_allclose(np.ptp(b,axis=0),[2,4,2],atol=1e-12)
        self.assertAlmostEqual(polygon_iou(_polygon(b),_polygon(b)),1)
        moved=E.copy();moved[:3,3]=[1,2,3]
        p=np.array([15.,3.,0.,1.])
        np.testing.assert_allclose(camera_to_ego(moved) @ (moved @ p),p)

    def test_nms_preserves_new_objects_and_different_classes(self):
        lb=box(); ls=np.array([[.9,1.]])
        rb=np.concatenate([box(),box(30),box()])
        rs=np.array([[.8,1.],[.7,1.],[.6,4.]])
        b,s,idx=late_fuse(lb,ls,rb,rs)
        self.assertEqual(idx.tolist(),[0,2,3])
        self.assertEqual(len(b),3)
        np.testing.assert_array_equal(s[:,0],[.9,.7,.6])
        self.assertEqual(classwise_nms(lb,ls).tolist(),[0])

    def test_empty_and_invalid(self):
        eb=np.empty((0,8,3));es=np.empty((0,2))
        b,s,k=late_fuse(eb,es,eb,es)
        self.assertEqual(b.shape,(0,8,3));self.assertEqual(s.shape,(0,2))
        self.assertEqual(k.size,0)
        self.assertEqual(upright_boxes(np.empty((0,3)),np.empty((0,3)),
                                      np.empty((0,3,3)),E).shape,(0,8,3))
        with self.assertRaises(ValueError):camera_to_ego(np.ones((4,4)))
        with self.assertRaises(ValueError):classwise_nms(box(),[[2.,1.]])
        with self.assertRaises(ValueError):upright_boxes([[0,0,10]],[[0,2,4]],np.eye(3)[None],E)
        self.assertNotIn('bicycle',CLASS_MAP)
        self.assertEqual(CLASS_MAP['cyclist'],3)


class NativePilotPlumbing(unittest.TestCase):
    def test_eight_frames_detector_inputs_no_gt_and_raw_export(self):
        import cv2
        from phdsim.experiments import urbaning_rgb3d_late as m
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); output=root/'output'
            records=[]
            for j in range(8):
                yaml=root/f'{j:06d}.yaml';yaml.write_text('unused in synthetic test')
                for i in range(6):
                    cv2.imwrite(str(root/f'{j:06d}_camera{i}.png'),np.zeros((32,32,3),np.uint8))
                records.append({'key':f'20241126_0001_crossing2_00:{j:06d}:100000',
                    'sequence':'20241126_0001_crossing2_00','yaml':str(yaml),
                    'gt_boxes':box(30),'gt_labels':np.array([1]),
                    'boxes':box(),'scores':np.array([[.9,1.]]),
                    'prediction_sha256':'synthetic','native_association':{'members':{}}})
            class FrozenRGB:
                categories=['car']
                calls=[]
                variants=[]
                def __init__(self,*args,**kwargs):self.variants.append(kwargs.get('variant','omni3d'))
                def predict(self,image,intrinsic):
                    self.calls.append((image.shape,np.array(intrinsic)))
                    return {'centers':np.array([[0.,0.,30.]]),'dimensions':np.array([[2.,2.,4.]]),
                            'rotations':(E[:3,:3]@R_EGO)[None], 'corners':np.zeros((1,8,3)),
                            'scores':np.array([.8]),'classes':np.array([0]),'boxes2d':np.array([[1,1,10,10]])}
            with patch.object(m,'CubeDetector',FrozenRGB), \
                 patch.object(m,'read_inputs',return_value=({'train':records,'validation':[]},{'train':{'frames':8}})), \
                 patch.object(m,'camera_fields',return_value=[(E@np.diag([1.,-1,1,1]),
                     np.array([[30.,0,16],[0,30,16],[0,0,1]]))]*6):
                m.run(root,root,output,1)
            self.assertEqual(len(FrozenRGB.calls),48)
            checks=json.loads((output/'calibration-check.json').read_text())
            self.assertTrue(checks['passed']);self.assertEqual(len(checks['cameras']),48)
            self.assertTrue(all(abs(c['determinant']+1)<1e-12 for c in checks['cameras']))
            report=json.loads((output/'report.json').read_text())
            rgb=report['metrics']['rgb']['global_confidence_sort']
            self.assertGreater(rgb['classes']['Vehicle']['ap']['0.5'],.99)
            with zipfile.ZipFile(output/'urbaning-rgb3d-late-train8.zip') as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len([n for n in z.namelist() if n.startswith('raw/')]),48)
                self.assertEqual(len([n for n in z.namelist() if n.startswith('qa/') and n.endswith('.jpg')]),48)
                self.assertEqual(len([n for n in z.namelist() if n.endswith('_bev.png')]),8)
            with self.assertRaises(FileExistsError):m.run(root,root,output,1)
            # Official outdoor comparison must reuse the identical observations,
            # preserve the source archive, and independently replay old metrics.
            archive=output/'urbaning-rgb3d-late-train8.zip'
            raw=archive.read_bytes()
            from phdsim.experiments.urbaning_rgb_pilot import sha
            args=(root,root,root/'outdoor',1,'outdoor',archive)
            with patch.object(m,'CubeDetector',FrozenRGB), \
                 patch.object(m,'read_inputs',return_value=({'train':records,'validation':[]},{'train':{'frames':8}})), \
                 patch.object(m,'camera_fields',return_value=[(E@np.diag([1.,-1,1,1]),
                     np.array([[30.,0,16],[0,30,16],[0,0,1]]))]*6), \
                 patch.object(m,'REFERENCE_SHA',sha(raw)):
                m.run(*args)
                new=json.loads((root/'outdoor/report.json').read_text())
                with zipfile.ZipFile(root/'outdoor/urbaning-rgb3d-outdoor-train8.zip') as zz:
                    self.assertIsNone(zz.testzip());self.assertIn('paired-reference-report.json',zz.namelist())
                self.assertEqual(new['metrics'],report['metrics'])
                self.assertTrue(new['paired_reference']['all_bindings_verified'])
                self.assertEqual(archive.read_bytes(),raw)
                self.assertEqual(FrozenRGB.variants,['omni3d','outdoor'])
                (root/'000000_camera0.png').write_bytes(b'changed payload')
                with self.assertRaisesRegex(ValueError,'camera image/calibration/time'):
                    m.run(root,root,root/'changed',1,'outdoor',archive)

    def test_official_variants_and_outdoor_reference_required(self):
        from phdsim.experiments import urbaning_rgb3d_late as m
        self.assertEqual(model_assets('omni3d'),ASSETS)
        self.assertNotEqual(model_assets('outdoor'),ASSETS)
        with self.assertRaises(ValueError):model_assets('unreviewed checkpoint')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'requires the original paired'):
                m.run(Path(d),Path(d),Path(d)/'new',1,'outdoor')

    def test_bad_calibration_is_reported_before_model_creation(self):
        from phdsim.experiments import urbaning_rgb3d_late as m
        bad=E.copy();bad[0,0]=.1
        records=[{'key':str(i),'sequence':'train','yaml':'not_read'} for i in range(8)]
        with tempfile.TemporaryDirectory() as td, \
             patch.object(m,'read_inputs',return_value=({'train':records,'validation':[]},{})), \
             patch.object(m,'camera_fields',return_value=[(bad,np.eye(3))]*6), \
             patch.object(m,'CubeDetector') as detector:
            out=Path(td)/'new'
            with self.assertRaisesRegex(ValueError,'before model inference'):m.run(out,out,out,1)
            detector.assert_not_called()
            report=json.loads((out/'calibration-check.json').read_text())
            self.assertFalse(report['passed']);self.assertIn('error',report['cameras'][0])

    def test_completed_runtime_reuse_is_read_only_and_does_not_build(self):
        import os
        from phdsim.perception.urbaning.rgb3d_late import OMNI_COMMIT,D2_COMMIT,P3D_COMMIT
        script=Path(__file__).resolve().parents[1]/'scripts/urbaning_rgb3d_late.py'
        spec=importlib.util.spec_from_file_location('rgb3d_bootstrap',script)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{'PYTHONHASHSEED':'0'}):spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'dependencies').mkdir();(root/'sources/omni3d').mkdir(parents=True)
            (root/'model').mkdir();asset={'model.pth':module.hashlib.sha256(b'fixed model').hexdigest()}
            (root/'model/model.pth').write_bytes(b'fixed model')
            (root/'ready.json').write_text(json.dumps({'omni3d':OMNI_COMMIT,'detectron2':D2_COMMIT,
                                                      'pytorch3d':P3D_COMMIT,'assets':asset}))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('phdsim.perception.urbaning.rgb3d_late.ASSETS',asset), \
                 patch.object(module.subprocess,'run',side_effect=AssertionError('No builds allowed')):
                model,env=module.reuse(root)
                self.assertEqual(model,root/'model')
                self.assertIn(str(root/'dependencies'),env['PYTHONPATH'])
                after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(before,after)
                (root/'model/model.pth').write_bytes(b'changed model')
                with self.assertRaisesRegex(ValueError,'changed official model'):module.reuse(root)


if __name__=='__main__':unittest.main()
