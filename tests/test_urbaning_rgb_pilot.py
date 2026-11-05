import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.evaluation.urbaning_cached import frame_statistics
from phdsim.experiments.urbaning_rgb_pilot import (R2_R1, camera_fields, project_crop,
    select_frames, training_labels, fit_head, predict_head, pca_fit, pca_apply,
    shuffled_visual, evaluate, extract_frame, read_inputs, run, sha, CAMERAS, UPSTREAM)


def box(x=0., y=0., z=10.):
    return np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                     [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], dtype=np.float64)+[x,y,z]


class RGBPilotTests(unittest.TestCase):
    def test_converter_optical_axes_and_projection(self):
        r1 = np.diag([1.,-1,1,1])
        r2 = np.array([[0,-1,0,0],[0,0,-1,0],[1,0,0,0],[0,0,0,1.]])
        r3 = np.array([[0,-1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1.]])
        gtl = np.eye(4); gtl[:3,3] = [7,-3,2]
        ctg = np.eye(4); ctg[:3,3] = [-1,2,-3]
        e = r1@np.linalg.inv(r2)@ctg@gtl@r3@r1
        self.assertTrue(np.allclose(R2_R1@e, ctg@gtl@r3@r1))
        k = np.array([[100.,0,100],[0,100,100],[0,0,1]])
        crop = project_crop(box(), np.eye(4), k, 200, 200)
        self.assertIsNotNone(crop)
        self.assertEqual(crop[0], (86,86,114,114))
        self.assertIsNone(project_crop(box(z=0), np.eye(4), k, 200, 200))
        self.assertIsNone(project_crop(box(x=100), np.eye(4), k, 200, 200))

    def test_sampling_is_score_and_gt_independent_disjoint_recordings(self):
        frames = [{'key':s+':'+str(i).zfill(6), 'sequence':s} for s in
                  ('20241126_0001_crossing2_00','20241126_0017_crossing1_00') for i in range(200)]
        chosen = select_frames(frames, 60)
        self.assertEqual(len(chosen),120)
        self.assertEqual(chosen, select_frames(list(reversed(frames)), 60))
        self.assertEqual(len({r['key'] for r in chosen}),120)

    def test_targets_map_raw_order_and_replay_rematches(self):
        # Same GT, two overlapping predictions: original lower score is duplicate.
        boxes = np.stack([box(), box(x=.1), box(x=20)])
        scores = np.array([[.2,1],[.9,1],[.8,1]])
        gt = np.stack([box()]); labels = np.array([1])
        stats = frame_statistics(boxes,scores,gt,labels)
        self.assertEqual(training_labels(boxes,scores,stats).tolist(), [0.,1.,0.])
        record = {'boxes':boxes,'scores':scores,'gt_boxes':gt,'gt_labels':labels}
        changed = np.array([.99,.1,.8])
        actual = evaluate([record],[changed])['global_confidence_sort']['classes']['Vehicle']['ap']['0.5']
        self.assertGreater(actual,.99)
        # Reusing original labels here would incorrectly mark score.99 as FP.

    def test_training_only_normalization_and_fallback(self):
        rng = np.random.default_rng(4)
        x = rng.normal(size=(80,3)); y = (x[:,0]>0).astype(float)
        model = fit_head(x,y,np.ones(80),np.full(80,.5))
        pred = predict_head(model,x,np.ones(80),np.full(80,.5))
        self.assertGreater(float(pred[y==1].mean()),float(pred[y==0].mean()))
        self.assertTrue(np.allclose(model['mean'],x.mean(axis=0)))
        self.assertEqual(predict_head(model,x[:2],np.full(2,2),np.array([.2,.7])).tolist(),[.2,.7])
        # Applying validation cannot change stored normalizers/PCA.
        original=json.dumps(model,sort_keys=True)
        predict_head(model,x+100,np.ones(80),np.full(80,.5))
        self.assertEqual(original,json.dumps(model,sort_keys=True))
        visual=rng.normal(size=(80,20)); mask=np.ones(80,dtype=bool); mask[-3:]=False
        pca=pca_fit(visual,mask)
        projected=pca_apply(pca,visual,mask)
        self.assertTrue(np.array_equal(projected[-3:],np.zeros((3,16))))
        shuffled=shuffled_visual(projected,mask,np.r_[np.ones(40),np.full(40,2)])
        self.assertTrue(np.array_equal(shuffled[-3:],projected[-3:]))
        self.assertTrue(np.allclose(np.sort(shuffled[:40],axis=0),np.sort(projected[:40],axis=0)))

    def test_camera_reader_never_constructs_yaml_label_objects(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.yaml'
            e=np.linalg.inv(R2_R1).tolist(); k=[[100,0,100],[0,100,100],[0,0,1]]
            import yaml
            p.write_text(yaml.safe_dump({'camera'+str(i):{'extrinsic':e,'intrinsic':k} for i in range(6)})+
                         '\nCar: !!python/object/apply:os.system ["false"]\n')
            values=camera_fields(p)
            self.assertEqual(len(values),6)
            self.assertTrue(np.allclose(values[0][0],np.eye(4)))

    def test_rgb_crop_cache_integrity_and_gt_free_extraction(self):
        import cv2
        import yaml
        class FakeEncoder:
            identity={'test':'synthetic RGB'}
            def __init__(self): self.calls=0
            def __call__(self,crops):
                self.calls+=1
                return np.ones((len(crops),576),dtype=np.float32)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=root/'000001.yaml'; out=root/'out'; out.mkdir()
            e=np.linalg.inv(R2_R1).tolist(); k=[[100,0,100],[0,100,100],[0,0,1]]
            p.write_text(yaml.safe_dump({'camera'+str(i):{'extrinsic':e,'intrinsic':k} for i in range(6)}))
            for i in range(6): cv2.imwrite(str(root/f'000001_camera{i}.png'),np.full((200,200,3),80,dtype=np.uint8))
            from phdsim.experiments.urbaning_rgb_pilot import CAMERAS
            record={'key':'test:1:100000','yaml':str(p),'prediction_sha256':'test',
                    'boxes':np.stack([box()]),'scores':np.array([[.8,1]]),
                    'native_association':{'timestamp_ns':1000000000,'members':{c:'1005.jpg' for c in CAMERAS}}}
            encoder=FakeEncoder()
            a=extract_frame(record,out,encoder,qa=True)
            b=extract_frame(record,out,encoder)
            self.assertEqual(encoder.calls,1)
            self.assertTrue(a['visible'].all()); self.assertTrue(np.array_equal(a['visual'],b['visual']))
            self.assertEqual(a['time_offsets_ms'].tolist(),[5.]*6)
            cv2.imwrite(str(root/'000001_camera0.png'),np.full((200,200,3),90,dtype=np.uint8))
            with self.assertRaisesRegex(ValueError,'provenance changed'): extract_frame(record,out,encoder)

    def test_source_manifest_loader_and_end_to_end_report_resume(self):
        import cv2
        import yaml
        class FakeEncoder:
            identity={'test':'synthetic encoder; no research result'}
            def __call__(self,crops):
                return np.stack([np.linspace(0,1,576)+c.mean()/255 for c in crops]).astype(np.float32)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); base=root/'phdsim'; base.mkdir(); inputs=root/'inputs'; inputs.mkdir()
            out=root/'out'; out.mkdir()
            splits={}; manifest={'splits':{}}
            for split,sequence in [('train','20241126_0001_crossing2_00'),('validation','20241126_0004_crossing2_00')]:
                directory=base/'runs'/sequence; directory.mkdir(parents=True)
                converted=base/'converted'/sequence/sequence/'100000'; converted.mkdir(parents=True)
                runpath=directory/'run.json'; runpath.write_text('{}')
                native={'timestamp_ns':1000000000,'members':{c:'1005.jpg' for c in CAMERAS}}
                p=converted/'000001.yaml'
                e=np.linalg.inv(R2_R1).tolist(); k=[[100,0,100],[0,100,100],[0,0,1]]
                p.write_text(yaml.safe_dump({'camera'+str(i):{'extrinsic':e,'intrinsic':k} for i in range(6)}))
                for i in range(6): cv2.imwrite(str(converted/f'000001_camera{i}.png'),np.full((200,200,3),80,dtype=np.uint8))
                (p.parents[2]/'phdsim-conversion.json').write_text(json.dumps({'converter_commit':UPSTREAM,
                    'sequence':sequence,'sync_by_frame':{'000001':native}}))
                boxes=np.stack([box(x=i*4) for i in range(4)])
                scores=np.c_[np.full(4,.8),np.arange(1,5)]
                pred=directory/'prediction.npz'
                np.savez_compressed(pred,ego_boxes=boxes,ego_scores=scores,gt_boxes=boxes,gt_labels=np.arange(1,5))
                key=sequence+':000001:100000'
                trace={'frame_key':key,'native_association':native,'predictions':pred.name,'source_frame_id':'000001',
                       'source_files':{'100000':{'yaml':{'path':str(p),'sha256':sha(p.read_bytes())}}}}
                tracepath=directory/'frames.jsonl'; tracepath.write_text(json.dumps(trace)+'\n')
                source={'directory':str(directory),'sequence':sequence,'run_sha256':sha(runpath.read_bytes()),
                        'trace_sha256':sha(tracepath.read_bytes())}
                binding={'prediction_path':pred.name,'prediction_sha256':sha(pred.read_bytes()),
                         'gt_sha256':sha(boxes.tobytes()+np.arange(1,5).tobytes())}
                manifest['splits'][split]={'provenance':{'inputs':[source]},'frame_bindings':{key:binding}}
                # Deliberately match load_archive's actual return contract: hashes
                # are in manifest bindings, not frame dictionaries.
                splits[split]=[{'key':key,'sequence':sequence,'native_association':native,
                                'statistics':{'ego':frame_statistics(boxes,scores,boxes,np.arange(1,5))}}]
            packet=inputs/'urbaning-gap-acquisition-inputs-001.zip'; ap=b'synthetic archive'
            with zipfile.ZipFile(packet,'w') as z: z.writestr('ap-export.zip',ap)
            with patch('phdsim.experiments.urbaning_rgb_pilot.PACKET_SHA',sha(packet.read_bytes())), \
                 patch('phdsim.experiments.urbaning_rgb_pilot.AP_SHA',sha(ap)), \
                 patch('phdsim.experiments.urbaning_rgb_pilot.load_archive',return_value=(splits,manifest)):
                records,provenance=read_inputs(base,out,60,60)
                self.assertEqual(len(records['validation']),1)
                run(base,out,encoder=FakeEncoder())
                result=json.loads((out/'report.json').read_text())
                self.assertEqual(result['frames'],{'train':1,'validation':1})
                self.assertEqual(set(result['metrics']),{'original_lidar','lidar_recalibrated','lidar_rgb','lidar_rgb_shuffled_diagnostic'})
                before=(out/'urbaning-rgb-pilot.zip').read_bytes()
                run(base,out,encoder=FakeEncoder())
                self.assertEqual(before,(out/'urbaning-rgb-pilot.zip').read_bytes())


if __name__=='__main__': unittest.main()
