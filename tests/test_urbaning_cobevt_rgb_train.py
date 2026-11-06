import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import hashlib
import json
import zipfile
import io

import numpy as np
import torch
from torch import nn

from phdsim.perception.urbaning.cobevt_rgb_training import (
    BoundedAdapter, lift_rectangular, fit_normalizers, context, shuffled_indices, original_heads,
)
from phdsim.experiments.urbaning_cobevt_rgb_train import (
    optimize, evaluate, ground_prior, run, logit_parity, verify_native_parity,
)
from phdsim.perception.urbaning.cobevt_rgb_adapter import metric_grid
from phdsim.perception.urbaning.bev_cpu import corners


def features(n=4):
    torch.manual_seed(5)
    result=[]
    for i in range(n):
        rgb=torch.randn(12,4,6);rgb[-4:]=1
        result.append({'bev':torch.randn(1,4,4,6),'rgb':rgb,
                       'xy':metric_grid((4,6),[-6,-4,-2,6,4,2])})
    return result


class FixtureLoss(nn.Module):
    def __init__(self):super().__init__();self.loss_dict={}
    def forward(self,outputs,target):
        a=(outputs['psm']-target['psm']).square().mean()
        b=(outputs['rm']-target['rm']).square().mean()
        self.loss_dict={'conf_loss':a,'reg_loss':b}
        return a+b


def runtime():
    torch.manual_seed(9)
    heads=[nn.Conv2d(4,8,1).eval().requires_grad_(False),nn.Conv2d(4,14,1).eval().requires_grad_(False)]
    return SimpleNamespace(heads=heads,loss=FixtureLoss())


class RGBTrainingTests(unittest.TestCase):
    def test_native_size_npz_layout_roundoff_is_not_weight_drift(self):
        torch.manual_seed(0)
        x=torch.randn(1,256,100,256)*4
        channels_last=x.contiguous(memory_format=torch.channels_last)
        stream=io.BytesIO();np.savez_compressed(stream,bev=channels_last.numpy());stream.seek(0)
        with np.load(stream,allow_pickle=False) as z:reloaded=torch.from_numpy(z['bev'].copy())
        self.assertTrue(torch.equal(channels_last,reloaded))
        self.assertNotEqual(channels_last.stride(),reloaded.stride())
        for count in (32,56):
            head=nn.Conv2d(256,count,1).eval().requires_grad_(False)
            cached=head(channels_last);replayed=head(reloaded)
            measured=logit_parity(replayed,cached)
            self.assertEqual(measured['outside_tolerance'],0)
            # Do not require a particular CPU to select different arithmetic kernels.
            bad=replayed.clone();bad[0,0,0,0]+=.01
            self.assertGreater(logit_parity(bad,cached)['outside_tolerance'],0)

    def test_logit_roundoff_gate_rejects_nonfinite_shape_and_dtype_changes(self):
        x=torch.ones(1,32,4,6)
        self.assertEqual(logit_parity(x+7e-6,x)['outside_tolerance'],0)
        self.assertGreater(logit_parity(x+.001,x)['outside_tolerance'],0)
        for bad in (x.double(),x[:,:,:,:-1],x*float('nan'),x*float('inf')):
            with self.assertRaises(ValueError):logit_parity(bad,x)

    def parity_fixture(self):
        fs=features(2);r=runtime()
        boxes=np.stack([corners([x,0,0],2,3,2,0) for x in (-9,-3,3,9)])
        labels=np.arange(1,5);scores=np.c_[np.full(4,.9),labels]
        rows=[]
        for i,f in enumerate(fs):
            with torch.no_grad():f.update({k:v+7e-6 for k,v in original_heads(*r.heads,f['bev']).items()})
            f['cache_sha256']='fixture'
            rows.append({'key':f'train:{i}:100000','gt_boxes':boxes,'gt_labels':labels})
        r.decode=lambda out:(boxes.copy(),scores.copy())
        return rows,fs,r,boxes,scores

    def test_parity_records_roundoff_but_requires_identical_decode_and_ap(self):
        rows,fs,r,boxes,scores=self.parity_fixture()
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'parity.json';report=verify_native_parity(rows,fs,r,path)
            self.assertEqual(json.loads(path.read_text()),report)
            self.assertEqual(report['status'],'passed')
            self.assertTrue(report['matching_and_ap_identical'])
            self.assertGreater(report['frames'][0]['logits']['rm']['old_atol_1e6_mismatches'],0)
            self.assertEqual(len(report['metrics']),2)
            self.assertTrue(all('psm' not in f for f in fs))

    def test_parity_stops_on_changed_counts_classes_boxes_scores_and_matching(self):
        for kind in ('count','class','box','score','matching','logit'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as t:
                rows,fs,r,boxes,scores=self.parity_fixture()
                changed_boxes=boxes.copy();changed_scores=scores.copy()
                if kind=='count':changed_boxes=boxes[:-1];changed_scores=scores[:-1]
                elif kind=='class':changed_scores[0,1]=2
                elif kind=='box':changed_boxes[0,:,0]+=.01
                elif kind=='score':changed_scores[0,0]-=.001
                elif kind=='matching':
                    # 0.2mm coordinate drift is within box tolerance, but crosses IoU .5.
                    changed_boxes[0,:,0]+=2e-4
                    rows[0]['gt_boxes']=boxes.copy();rows[0]['gt_boxes'][0,:,0]+=2/3+1e-4
                elif kind=='logit':fs[0]['rm']+=.01
                calls=[(boxes,scores),(changed_boxes,changed_scores)]
                r.decode=lambda out:calls.pop(0)
                path=Path(t)/'parity.json'
                with self.assertRaises((ValueError,AssertionError)):
                    verify_native_parity(rows,fs,r,path)
                report=json.loads(path.read_text())
                self.assertEqual(report['status'],'failed');self.assertIn('error',report)
                self.assertTrue(all('psm' in f for f in fs))

    def test_parity_rejects_changed_global_score_ranking_even_if_frame_matches_same(self):
        rows,fs,r,boxes,scores=self.parity_fixture()
        # One TP in frame0, one FP in frame1: tiny cross-frame score inversion changes AP.
        rows[0]['gt_boxes']=boxes[:1];rows[0]['gt_labels']=np.array([1])
        rows[1]['gt_boxes']=boxes[:1];rows[1]['gt_labels']=np.array([1])
        false_box=boxes[:1].copy();false_box[:,:,1]+=10
        results=[(boxes[:1],np.array([[.5,1]])),(boxes[:1],np.array([[.5-1e-6,1]])),
                 (false_box,np.array([[.5-1e-6,1]])),(false_box,np.array([[.5,1]]))]
        r.decode=lambda out:results.pop(0)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'parity.json'
            with self.assertRaisesRegex(ValueError,'Native AP changed'):
                verify_native_parity(rows,fs,r,path)
            self.assertEqual(json.loads(path.read_text())['status'],'failed')

    def test_rectangular_lift_and_mask_not_square_resize(self):
        xy=metric_grid((4,6),[-3,-2,-1,3,2,2]);maps=torch.ones(1,2,8,8)
        e=np.eye(4);k=np.array([[1.,0,4],[0,1,4],[0,0,1.]])
        rgb=lift_rectangular(maps,[(e,k)],[(8,8)],xy,3.)
        self.assertEqual(tuple(rgb.shape),(12,4,6))
        torch.testing.assert_close(rgb,torch.ones_like(rgb),rtol=0,atol=1e-6)
        invalid=lift_rectangular(maps,[(e,k)],[(8,8)],xy,-20.)
        self.assertTrue(torch.equal(invalid,torch.zeros_like(invalid)))

    def test_modality_control_invariant_and_missing_views_stay_zero(self):
        f=features();stats=fit_normalizers(f)
        original=context(f[0]['bev'],f[0]['rgb'],'lidar_adapter',stats,f[0]['xy'])
        changed=context(f[0]['bev'],f[0]['rgb']*1000,'lidar_adapter',stats,f[0]['xy'])
        self.assertTrue(torch.equal(original,changed))
        full=context(f[0]['bev'],f[0]['rgb'],'lidar_rgb_adapter',stats,f[0]['xy'])
        self.assertFalse(torch.equal(original,full))
        absent=f[0]['rgb'].clone();absent[-4:]=0;absent[:-4]=0
        empty=context(f[0]['bev'],absent,'lidar_rgb_adapter',stats,f[0]['xy'])
        self.assertTrue(torch.equal(original,empty))

    def test_zero_start_bound_and_head_gradient_without_head_mutation(self):
        f=features();stats=fit_normalizers(f);x=context(f[0]['bev'],f[0]['rgb'],'lidar_rgb_adapter',stats,f[0]['xy'])
        model=BoundedAdapter(x.shape[1],4,stats['lidar']['std']);r=runtime()
        before=[{k:v.clone() for k,v in h.state_dict().items()} for h in r.heads]
        bev,raw=model(f[0]['bev'],x)
        self.assertTrue(torch.equal(bev,f[0]['bev']))
        outputs=original_heads(*r.heads,bev);sum(v.square().mean() for v in outputs.values()).backward()
        self.assertTrue(any(p.grad is not None and bool(p.grad.abs().sum()>0) for p in model.parameters()))
        self.assertTrue(all(p.grad is None for h in r.heads for p in h.parameters()))
        for head,old in zip(r.heads,before):self.assertTrue(all(torch.equal(old[k],v) for k,v in head.state_dict().items()))
        with torch.no_grad():model.adapter.delta.bias.fill_(100)
        bev,_=model(f[0]['bev'],x)
        self.assertTrue(bool(((bev-f[0]['bev']).abs()<=model.scale+1e-6).all()))

    def test_train_loss_falls_and_epoch_resume_is_identical(self):
        f=features();stats=fit_normalizers(f);r=runtime()
        targets=[]
        for row in f:
            with torch.no_grad():out=original_heads(*r.heads,row['bev']+.15)
            targets.append(out)
        config={'seed':0,'epochs':12,'learning_rate':.01,'residual_penalty':1e-4}
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            complete,history=optimize('lidar_rgb_adapter',f,targets,r,stats,root/'full',config)
            self.assertTrue(history['loss_decreased'])
            # Simulate a preemption after a complete epoch without changing config.
            original_atomic=__import__('phdsim.experiments.urbaning_cobevt_rgb_train',fromlist=['atomic_torch']).atomic_torch
            def interrupt(path,value):
                original_atomic(path,value)
                if path.name=='checkpoint.pt' and value['epoch']==5:raise InterruptedError('fixture preemption')
            with patch('phdsim.experiments.urbaning_cobevt_rgb_train.atomic_torch',side_effect=interrupt):
                with self.assertRaises(InterruptedError):optimize('lidar_rgb_adapter',f,targets,r,stats,root/'resume',config)
            resumed,resumed_history=optimize('lidar_rgb_adapter',f,targets,r,stats,root/'resume',config)
            self.assertEqual(history,resumed_history)
            for key,value in complete.state_dict().items():self.assertTrue(torch.equal(value,resumed.state_dict()[key]),key)

    def test_shuffling_stays_in_recording_and_never_same_frame(self):
        records=[{'sequence':s} for s in ('a','a','a','a','b','b','b','b')]
        ids=shuffled_indices(records)
        self.assertEqual(sorted(ids),list(range(8)))
        for i,j in enumerate(ids):
            self.assertNotEqual(i,j);self.assertEqual(records[i]['sequence'],records[j]['sequence'])

    def test_raw_export_reproduces_evaluation_and_no_peer_queries(self):
        f=features(2);r=runtime();box=corners([0,0,0],2,4,2,0)[None]
        records=[{'key':f'train:00000{i}:100000','gt_boxes':box,'gt_labels':np.array([1])} for i in range(2)]
        r.decode=lambda outputs:(box,np.array([[.9,1]]))
        with tempfile.TemporaryDirectory() as t:
            result,preds=evaluate('fixture',records,f,r,Path(t))
            self.assertEqual(result['peer_requests'],0)
            self.assertAlmostEqual(result['global_confidence_sort']['classes']['Vehicle']['ap']['0.5'],1.)
            self.assertIsNone(result['global_confidence_sort']['macro_ap']['0.5'])
            for path in Path(t).glob('*.npz'):
                with np.load(path) as z:np.testing.assert_array_equal(z['gt_boxes'],box)

    def test_ground_prior_only_uses_passed_train_boxes(self):
        near=corners([0,0,0],2,4,2,0);far=corners([100,100,-1000],2,4,2,0)
        self.assertEqual(ground_prior([{'gt_boxes':np.stack([near,far])}]),-1.)

    def test_complete_train_export_and_completed_resume_fixture(self):
        """Full eight-frame trainer/export; upstream I/O/CNN/decode are fixtures."""
        torch.manual_seed(0)
        heads=[nn.Conv2d(256,32,1).eval().requires_grad_(False),nn.Conv2d(256,56,1).eval().requires_grad_(False)]
        rows=[];fs=[]
        boxes=np.stack([corners([x,y,0],2,3,2,0) for x,y in [(-6,0),(0,0),(6,0),(0,5)]])
        labels=np.arange(1,5)
        for i in range(8):
            sequence='train_a' if i<4 else 'train_b'
            f={'bev':torch.randn(1,256,4,6),'xy':metric_grid((4,6),[-6,-4,-2,6,4,2]),
               'cache_sha256':'fixture','fixture_rgb':torch.randn(12,4,6)}
            f['fixture_rgb'][-4:]=1
            with torch.no_grad():f.update(original_heads(*heads,f['bev']));goal=original_heads(*heads,f['bev']+.05)
            goal={**goal,'pos_equal_one':torch.zeros(1,4,6,8)}
            rows.append({'key':f'{sequence}:{i:06d}:100000','sequence':sequence,'gt_boxes':boxes,
                         'gt_labels':labels,'fixture_target':goal})
            fs.append(f)
        r=SimpleNamespace(heads=heads,loss=FixtureLoss(),target=lambda row:row['fixture_target'],
                          decode=lambda outputs:(boxes,np.c_[np.full(4,.9),labels]))
        class FakeEncoder:
            def __init__(self,*args):self.identity={'fixture':True}
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);model=root/'models/urbaning/CoBEVT_SIS_1_2_vs_3';model.mkdir(parents=True)
            weights=root/'weights';(weights/'checkpoints').mkdir(parents=True)
            payload=b'fixture-weight';(weights/'checkpoints/mobilenet_v3_small-047dcff4.pth').write_bytes(payload)
            prefix='phdsim.experiments.urbaning_cobevt_rgb_train.'
            with patch(prefix+'prepare_upstream'),patch(prefix+'load_config',return_value={}), \
                 patch(prefix+'verified_inputs',return_value=(rows,fs,{'train':{'keys':[r['key'] for r in rows]}})), \
                 patch(prefix+'load_frozen_heads',return_value=heads),patch(prefix+'native_runtime',return_value=r), \
                 patch(prefix+'SpatialEncoder',FakeEncoder),patch(prefix+'WEIGHTS_SHA',hashlib.sha256(payload).hexdigest()), \
                 patch(prefix+'verify_bundle',return_value={'fixture':True}), \
                 patch(prefix+'extract_rgb',side_effect=lambda record,feature,*args:feature['fixture_rgb']):
                run(root,root,root,model,root/'out',weights,2,3)
                before=(root/'out/urbaning-cobevt-rgb-adapter-train8.zip').read_bytes()
                run(root,root,root,model,root/'out',weights,2,3)
                self.assertEqual(before,(root/'out/urbaning-cobevt-rgb-adapter-train8.zip').read_bytes())
            report=json.loads((root/'out/report.json').read_text())
            self.assertTrue(report['head_weights_unchanged'] and report['zero_start_exact'])
            self.assertEqual(report['validation_frames'],0);self.assertEqual(report['test_frames'],0)
            self.assertEqual(len(report['metrics']),4)
            self.assertTrue(all(x['loss_decreased'] for x in report['training'].values()))
            with zipfile.ZipFile(root/'out/urbaning-cobevt-rgb-adapter-train8.zip') as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.npz')]),32)


if __name__=='__main__':
    torch.set_num_threads(2)
    unittest.main()
