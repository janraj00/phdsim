import tempfile
from pathlib import Path
import unittest
import hashlib
import json
import zipfile
from unittest.mock import patch
import numpy as np
import torch
from phdsim.perception.urbaning.bev_cpu import (GRID, Detector, fit_priors, corners, geometry,
    camera_grid, lift_features, point_grid, read_pcd, input_tensor, targets, loss, decode)
from phdsim.evaluation.urbaning_cached import _polygon, polygon_iou, frame_statistics
from phdsim.experiments.urbaning_bev_cpu import fit, extract, run


SMALL={**GRID,'size':32,'extent':16.}


def pcd(path):
    points=np.array([[1.,2.,3.],[2.,3.,1.]],dtype='<f4')
    header=b'VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA binary\n'
    raw=header+points.tobytes();path.write_bytes(raw)
    return points,hashlib.sha256(raw).hexdigest()


def example():
    boxes=np.stack([corners([x,y,0.],a,b,2.,yaw) for x,y,a,b,yaw in
                    [(-8,-7,3.,2.,.4),(7,-7,4.,2.5,-.7),(-7,7,1.8,.7,1.2),(7,7,.6,.6,0.)]])
    labels=np.arange(1,5)
    # All targets exist even though the old LiDAR detector proposes nothing.
    record={'gt_boxes':boxes,'gt_labels':labels,'boxes':np.empty((0,8,3)),'scores':np.empty((0,2))}
    return record,fit_priors([record])


class BEVCPUTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): torch.set_num_threads(2)

    def test_oracle_target_decode_roundtrip_four_classes_and_orientations(self):
        record,priors=example()
        t=targets(record['gt_boxes'],record['gt_labels'],priors,SMALL)
        self.assertEqual(t['statistics']['radius_gt'],4)
        self.assertEqual(int((t['heat']==1).sum()),4)
        logits=torch.full((1,4,32,32),-20.)
        reg=torch.zeros(1,4,8,32,32)
        for (c,y,x),values in zip(t['locations'],t['regression']):
            logits[0,c,y,x]=10
            reg[0,c,:,y,x]=values
        boxes,scores=decode((logits,reg),priors,SMALL)
        self.assertEqual(len(boxes),4)
        for c,box in enumerate(boxes):
            self.assertGreater(polygon_iou(_polygon(box),_polygon(record['gt_boxes'][c])),.99999)
        stats=frame_statistics(boxes,scores,record['gt_boxes'],record['gt_labels'])
        self.assertTrue(all(row[.5]['tp']==[1] for row in stats.values()))

    def test_camera_projection_and_masked_multiview_lifting(self):
        k=np.array([[20.,0,50],[0,20,50],[0,0,1.]])
        p=np.zeros((2,3,3,3),dtype=np.float32);p[:,:,:,2]=5
        grid,mask=camera_grid(p,np.eye(4),k,100,100)
        self.assertTrue(mask.all());self.assertTrue(np.allclose(grid,.01))
        maps=torch.stack([torch.full((2,4,4),2.),torch.full((2,4,4),4.)])
        out=lift_features(maps,[(np.eye(4),k)]*2,[(100,100)]*2,p)
        self.assertTrue(np.allclose(out[:4],3.));self.assertTrue(np.allclose(out[4:],1.))
        e=np.eye(4);e[2,3]=-100
        out=lift_features(maps,[(np.eye(4),k),(e,k)],[(100,100)]*2,p)
        self.assertTrue(np.allclose(out[:4],2.));self.assertTrue(np.allclose(out[4:],.5))

    def test_strict_modality_isolation(self):
        rgb=np.ones((8,32,32),dtype=np.float16); lidar=np.ones((3,32,32),dtype=np.float16)
        self.assertTrue(torch.equal(input_tensor(rgb,lidar,'rgb',SMALL),input_tensor(rgb,lidar*9,'rgb',SMALL)))
        self.assertTrue(torch.equal(input_tensor(rgb,lidar,'lidar',SMALL),input_tensor(rgb*9,lidar,'lidar',SMALL)))
        self.assertFalse(torch.equal(input_tensor(rgb,lidar,'rgb_lidar',SMALL),input_tensor(rgb,lidar*9,'rgb_lidar',SMALL)))

    def test_point_grid_handles_empty_bins_and_filters_extreme_height(self):
        p=np.array([[.2,.2,1.],[.3,.3,3.],[.2,.2,9.],[100,100,1.]])
        out=point_grid(p,SMALL,0.)
        self.assertEqual(out.shape,(3,32,32))
        self.assertAlmostEqual(float(out[1,16,16]),.75)
        self.assertAlmostEqual(float(out[2,16,16]),.5)
        self.assertEqual(np.count_nonzero(out[0]),1)
        self.assertTrue(np.isfinite(point_grid(np.empty((0,3)),SMALL,0.)).all())

    def test_pcd_binary_bytes_and_hash_binding(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'car1.pcd';points,digest=pcd(path)
            self.assertTrue(np.array_equal(read_pcd(path,digest),points))
            with self.assertRaisesRegex(ValueError,'payload changed'):read_pcd(path,'bad')

    def test_rgb_map_cache_without_gt_or_lidar_proposals(self):
        import cv2,yaml
        from phdsim.experiments.urbaning_rgb_pilot import R2_R1
        class FakeEncoder:
            identity={'test':'synthetic maps'}
            calls=0
            def __call__(self,images):
                self.calls+=1
                return torch.ones(6,16,8,8)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=root/'000001.yaml'
            k=[[100,0,100],[0,100,100],[0,0,1]]
            e=np.linalg.inv(R2_R1).tolist()
            p.write_text(yaml.safe_dump({'camera'+str(i):{'intrinsic':k,'extrinsic':e} for i in range(6)}))
            for i in range(6):cv2.imwrite(str(root/f'000001_camera{i}.png'),np.full((200,200,3),80,dtype=np.uint8))
            point=root/'000001.pcd';_,digest=pcd(point)
            record={'key':'test:000001:100000','yaml':str(p),'lidar_source':{'path':str(point),'sha256':digest}}
            encoder=FakeEncoder();cache=root/'cache'
            a=extract(record,cache,encoder,{'ground_z':0.},SMALL)
            b=extract(record,cache,encoder,{'ground_z':0.},SMALL)
            self.assertEqual(encoder.calls,1)
            self.assertEqual(a['rgb'].shape,(68,32,32));self.assertTrue(np.array_equal(a['rgb'],b['rgb']))
            self.assertGreater(np.count_nonzero(a['rgb']),0)
            cv2.imwrite(str(root/'000001_camera0.png'),np.zeros((200,200,3),dtype=np.uint8))
            with self.assertRaisesRegex(ValueError,'identity changed'):extract(record,cache,encoder,{'ground_z':0.},SMALL)

    def test_same_cell_collision_is_reported_but_not_deleted_from_gt(self):
        record,priors=example()
        t=targets(np.stack([record['gt_boxes'][0]]*2),np.ones(2),priors,SMALL)
        self.assertEqual(t['statistics']['radius_gt'],2)
        self.assertEqual(t['statistics']['same_class_cell_collisions'],1)
        self.assertEqual(len(t['locations']),1)

    def test_cpu_model_learns_new_center_targets_without_lidar_proposals(self):
        torch.manual_seed(0)
        record,priors=example();t=targets(record['gt_boxes'],record['gt_labels'],priors,SMALL)
        feature=np.zeros((8,32,32),dtype=np.float16)
        for c,y,x in t['locations']: feature[c,max(0,y-1):y+2,max(0,x-1):x+2]=3
        x=input_tensor(feature,np.zeros((3,32,32),dtype=np.float16),'rgb',SMALL)
        model=Detector(x.shape[1]);opt=torch.optim.Adam(model.parameters(),lr=.003)
        before=float(loss(model(x),t)[0].detach())
        for _ in range(40):
            opt.zero_grad();v,_=loss(model(x),t);v.backward();opt.step()
        after=float(loss(model(x),t)[0].detach())
        self.assertLess(after,before*.5)
        boxes,scores=decode(model(x),priors,SMALL)
        self.assertGreater(len(boxes),0)
        self.assertTrue(np.isfinite(boxes).all())

    def test_final_checkpoint_resume_keeps_model_and_history(self):
        record,priors=example();t=targets(record['gt_boxes'],record['gt_labels'],priors,SMALL)
        f={'rgb':np.ones((8,32,32),dtype=np.float16),'lidar':np.zeros((3,32,32),dtype=np.float16)}
        config={'seed':0,'epochs':1,'grid':SMALL}
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'rgb'
            a,history=fit('rgb',[f,f],[t,t],directory,config)
            before={k:v.clone() for k,v in a.state_dict().items()}
            b,other=fit('rgb',[f,f],[t,t],directory,config)
            self.assertEqual(history,other)
            self.assertTrue(all(torch.equal(v,b.state_dict()[k]) for k,v in before.items()))
            with self.assertRaisesRegex(ValueError,'configuration changed'):
                fit('rgb',[f],[t],directory,{**config,'epochs':2})

    def test_interrupted_epoch_resumes_at_saved_frame_exactly(self):
        record,priors=example();t=targets(record['gt_boxes'],record['gt_labels'],priors,SMALL)
        f={'rgb':np.ones((8,32,32),dtype=np.float16),'lidar':np.zeros((3,32,32),dtype=np.float16)}
        config={'seed':0,'epochs':1,'grid':SMALL}
        original=torch.optim.AdamW.step;calls=[0]
        def interrupt(optimizer,*args,**kwargs):
            calls[0]+=1
            if calls[0]==51:raise RuntimeError('synthetic interruption')
            return original(optimizer,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            expected,hist=fit('rgb',[f]*52,[t]*52,root/'clean',config)
            with patch.object(torch.optim.AdamW,'step',interrupt):
                with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                    fit('rgb',[f]*52,[t]*52,root/'interrupted',config)
            actual,other=fit('rgb',[f]*52,[t]*52,root/'interrupted',config)
            self.assertEqual(hist,other)
            self.assertTrue(all(torch.equal(v,actual.state_dict()[k]) for k,v in expected.state_dict().items()))

    def test_synthetic_end_to_end_three_modes_export_and_completed_resume(self):
        record,priors=example()
        record['baseline_statistics']=frame_statistics(record['boxes'],record['scores'],record['gt_boxes'],record['gt_labels'])
        record['yaml']='unused';record['lidar_source']={'path':'unused','sha256':'synthetic'}
        records={'train':[], 'validation':[]}
        for split,sequences in [('train',['20241126_0001_crossing2_00','20241126_0017_crossing1_00']),
                                ('validation',['20241126_0004_crossing2_00'])]:
            for s in sequences:records[split].append({**record,'key':s+':000001:100000','sequence':s})
        class FakeEncoder:
            identity={'test':'synthetic, not a result'}
            def __init__(self,*args):pass
        feature={'rgb':np.ones((8,32,32),dtype=np.float16),'lidar':np.ones((3,32,32),dtype=np.float16)}
        with tempfile.TemporaryDirectory() as temp, \
             patch('phdsim.experiments.urbaning_bev_cpu.GRID',SMALL), \
             patch('phdsim.experiments.urbaning_bev_cpu.read_inputs',return_value=(records,{'test':'synthetic'})), \
             patch('phdsim.experiments.urbaning_bev_cpu.add_point_bindings'), \
             patch('phdsim.experiments.urbaning_bev_cpu.MapEncoder',FakeEncoder), \
             patch('phdsim.experiments.urbaning_bev_cpu.shutil.disk_usage',return_value=type('Usage',(),{'free':100*1024**3})()), \
             patch('phdsim.experiments.urbaning_bev_cpu.extract',return_value=feature):
            root=Path(temp);out=root/'output'
            run(root,out,epochs=1)
            r=json.loads((out/'report.json').read_text())
            self.assertEqual(r['frames'],{'train':2,'validation':1})
            self.assertEqual(set(r['validation']),{'cobevt_lidar_reference','rgb','lidar','rgb_lidar'})
            z=zipfile.ZipFile(out/'urbaning-bev-cpu.zip')
            self.assertIsNone(z.testzip())
            self.assertEqual(sum(n.endswith('.npz') for n in z.namelist()),3)
            before=(out/'urbaning-bev-cpu.zip').read_bytes()
            run(root,out,epochs=1)
            self.assertEqual(before,(out/'urbaning-bev-cpu.zip').read_bytes())


if __name__=='__main__':unittest.main()
