import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.perception.urbaning.rgb3d_depth import fit_depth,apply_depth
from phdsim.perception.urbaning.rgb3d_late import upright_boxes
from phdsim.experiments.urbaning_rgb3d_depth import depth_targets

E=np.array([[0,-1,0,0],[0,0,-1,0],[1,0,0,0],[0,0,0,1.]],float)
R=np.array([[0,0,-1],[0,1,0],[1,0,0.]],float)
K=np.array([[30.,0,16],[0,30,16],[0,0,1]])
KEY='20241126_0001_crossing2_00:000001:100000'


class Readout(unittest.TestCase):
    def test_native_linear_delta_and_noop_have_no_gt_inputs(self):
        a={'weight':np.zeros((1,2),np.float32),'bias':np.array([5.],np.float32)}
        b={'weight':a['weight'].copy(),'bias':np.array([7.],np.float32)}
        cache={'depth_features':np.array([[1.,2.]],np.float32),'classes':np.array([0]),
               'depth_scale':np.array(2.),'centers':np.array([[2.,0,10.]],np.float32),
               'center_pixels':np.array([[22.,16.]],np.float32),'scores':np.array([.8])}
        changed=apply_depth(cache,a,b,K)
        np.testing.assert_allclose(changed['centers'],[[2.8,0,14.]])
        np.testing.assert_array_equal(apply_depth(cache,a,a,K)['centers'],cache['centers'])
        np.testing.assert_array_equal(changed['scores'],cache['scores'])
        np.testing.assert_array_equal(a['bias'],[5.])

    def test_fixed_train_only_fit_and_unsupported_class(self):
        original={'weight':np.zeros((2,3),np.float32),'bias':np.array([7.,9.],np.float32)}
        n=64
        fitted,rows=fit_depth(original,np.zeros((n,3)),np.zeros(n,int),np.full(n,5.),np.ones(n),[KEY]*n)
        self.assertAlmostEqual(float(fitted['bias'][0]),6.,places=5)
        self.assertTrue(rows[0]['adapted']);self.assertFalse(rows[1]['adapted'])
        np.testing.assert_array_equal(fitted['weight'][1],original['weight'][1])
        self.assertEqual(fitted['bias'][1],original['bias'][1])
        self.assertLess(rows[0]['train_relative_depth_mse_after'],rows[0]['train_relative_depth_mse_before'])
        np.testing.assert_array_equal(original['bias'],[7.,9.])
        with self.assertRaises(ValueError):
            fit_depth(original,np.zeros((n,3)),np.zeros(n,int),np.full(n,5.),np.ones(n),
                      ['20241126_0004_crossing2_00:000001:100000']*n)
        with self.assertRaises(ValueError):
            fit_depth(original,np.full((n,3),np.nan),np.zeros(n,int),np.full(n,5.),np.ones(n),[KEY]*n)

    def test_projected_targets_and_class_mismatch(self):
        gt=upright_boxes([[0,0,5]],[[2,2,4]],R[None],E)
        cache={'classes':np.array([0]),'scores':np.array([.8]),'boxes2d':np.array([[6.,6.,26.,26.]])}
        rows=depth_targets(cache,gt,np.array([1]),E,K,32,32,['car'])
        self.assertEqual(len(rows),1);self.assertAlmostEqual(rows[0]['depth'],5.)
        self.assertEqual(depth_targets(cache,gt,np.array([4]),E,K,32,32,['car']),[])


class Pipeline(unittest.TestCase):
    def test_full_controlled_train_freeze_validation_resume_and_cache_corruption(self):
        import cv2
        from phdsim.experiments import urbaning_rgb3d_depth as m
        from phdsim.experiments.urbaning_rgb_pilot import sha,select_frames
        from phdsim.evaluation.urbaning_cached import frame_statistics,aggregate_statistics,summarize_cached
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'output';runtime=root/'runtime';runtime.mkdir()
            (runtime/'ready.json').write_text('{}')
            model=root/'model';model.mkdir();(model/'official.bin').write_bytes(b'fixed source')
            assets={'official.bin':sha(b'fixed source')};pilot=root/'pilot.zip';pilot.write_bytes(b'source pilot')
            yaml=root/'shared.yaml';yaml.write_text('not read in synthetic test')
            for i in range(6):cv2.imwrite(str(root/f'shared_camera{i}.png'),np.zeros((32,32,3),np.uint8))
            gt=upright_boxes([[0,0,5]],[[2,2,4]],R[None],E)
            train=[];validation=[]
            for seq,count,dest in [('20241126_0001_crossing2_00',200,train),
                                    ('20241126_0017_crossing1_00',200,train),
                                    ('20241126_0004_crossing2_00',200,validation)]:
                for i in range(count):dest.append({'key':f'{seq}:{i+1:06d}:100000','sequence':seq,
                    'yaml':str(yaml),'native_association':{'members':{}},'boxes':gt.copy(),
                    'scores':np.array([[.9,1.]]),'gt_boxes':gt.copy(),'gt_labels':np.array([1])})
            original={'weight':np.zeros((1,4),np.float32),'bias':np.array([7.],np.float32)}
            class FrozenDetector:
                categories=['car'];calls=0
                def __init__(self,*args):pass
                def state(self):return {k:v.copy() for k,v in original.items()}
                def capture(self,image,intrinsic):
                    self.__class__.calls+=1
                    self.assert_shape=image.shape
                    return {'centers':np.array([[0.,0,7.]],np.float32),'center_pixels':np.array([[16.,16.]],np.float32),
                        'classes':np.array([0]),'scores':np.array([.8]),'boxes2d':np.array([[6.,6,26,26]]),
                        'dimensions':np.array([[2.,2,4]]),'rotations':R[None],
                        'depth_features':np.zeros((1,4),np.float32),'depth_scale':np.array(1.)}
            base=upright_boxes([[0,0,7]],[[2,2,4]],R[None],E)
            baseline=aggregate_statistics([frame_statistics(base,np.array([[.8,1.]]),gt,np.array([1]))]*8)
            source={'frames':[{'key':r['key'],'cameras':[{'image_sha256':sha((root/f'shared_camera{i}.png').read_bytes()),
                     'optical_from_car1':E.tolist(),'K':K.tolist(),'native_association':r['native_association']}
                     for i in range(6)]} for r in select_frames(train,4)],
                    'metrics':{'rgb':{'global_confidence_sort':summarize_cached(baseline,True),
                                      'upstream_default_frame_order':summarize_cached(baseline,False)}}}
            def inputs(base,folder,ntrain,nval):
                if nval:
                    self.assertTrue((out/'models/freeze.json').is_file())
                    self.assertEqual(json.loads((out/'models/freeze.json').read_text())['validation_loaded'],False)
                return {'train':train if ntrain else [],'validation':validation if nval else []},{'stable':'synthetic'}
            def guarded_fit(*args):
                self.assertTrue(all(k.startswith(('20241126_0001','20241126_0017')) for k in args[-1]))
                return fit_depth(*args)
            with patch.object(m,'read_inputs',side_effect=inputs),patch.object(m,'load_pilot',return_value=(source,sha(b'source pilot'))), \
                 patch.object(m,'OUTDOOR_ASSETS',assets),patch.object(m,'DepthFeatureDetector',FrozenDetector), \
                 patch.object(m,'camera_fields',return_value=[(E,K)]*6),patch.object(m,'verify_native_delta',return_value=True), \
                 patch.object(m,'fit_depth',side_effect=guarded_fit) as fitter:
                archive=m.run(root,runtime,model,pilot,out,1)
                self.assertEqual(fitter.call_count,1)
                report=json.loads((out/'report.json').read_text())
                a=report['validation_metrics']['rgb_baseline']['global_confidence_sort']['classes']['Vehicle']['ap']['0.5']
                b=report['validation_metrics']['rgb_depth_finetuned']['global_confidence_sort']['classes']['Vehicle']['ap']['0.5']
                self.assertGreater(b,a)
                self.assertEqual(FrozenDetector.calls,600*6)
                self.assertEqual((model/'official.bin').read_bytes(),b'fixed source')
                with zipfile.ZipFile(archive) as z:
                    self.assertIsNone(z.testzip());self.assertFalse(any(n.startswith('features/') for n in z.namelist()))
                    self.assertEqual(len([n for n in z.namelist() if n.startswith('frames-validation/')]),200)
                m.run(root,runtime,model,pilot,out,1)
                self.assertEqual(fitter.call_count,1);self.assertEqual(FrozenDetector.calls,600*6)
                (out/'completed.json').unlink()
                first=next((out/'features').glob('*.npz'));first.write_bytes(first.read_bytes()+b'corruption')
                with self.assertRaisesRegex(ValueError,'hash mismatch'):m.run(root,runtime,model,pilot,out,1)


if __name__=='__main__':unittest.main()
