import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.perception.urbaning.rgb3d_late import (
    camera_to_ego, upright_boxes, classwise_nms, late_fuse, CLASS_MAP)
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
                def __init__(self,*args):pass
                def predict(self,image,intrinsic):
                    self.calls.append((image.shape,np.array(intrinsic)))
                    return {'centers':np.array([[0.,0.,30.]]),'dimensions':np.array([[2.,2.,4.]]),
                            'rotations':(E[:3,:3]@R_EGO)[None], 'corners':np.zeros((1,8,3)),
                            'scores':np.array([.8]),'classes':np.array([0]),'boxes2d':np.array([[1,1,10,10]])}
            with patch.object(m,'CubeDetector',FrozenRGB), \
                 patch.object(m,'read_inputs',return_value=({'train':records,'validation':[]},{'train':{'frames':8}})), \
                 patch.object(m,'camera_fields',return_value=[(E,np.array([[30.,0,16],[0,30,16],[0,0,1]]))]*6):
                m.run(root,root,output,1)
            self.assertEqual(len(FrozenRGB.calls),48)
            report=json.loads((output/'report.json').read_text())
            rgb=report['metrics']['rgb']['global_confidence_sort']
            self.assertGreater(rgb['classes']['Vehicle']['ap']['0.5'],.99)
            with zipfile.ZipFile(output/'urbaning-rgb3d-late-train8.zip') as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len([n for n in z.namelist() if n.startswith('raw/')]),48)
                self.assertEqual(len([n for n in z.namelist() if n.startswith('qa/') and n.endswith('.jpg')]),48)
                self.assertEqual(len([n for n in z.namelist() if n.endswith('_bev.png')]),8)
            with self.assertRaises(FileExistsError):m.run(root,root,output,1)


if __name__=='__main__':unittest.main()
