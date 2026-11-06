import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from types import ModuleType
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch
from torch import nn

from phdsim.experiments import urbaning_cobevt_rgb_controlled as c
from phdsim.perception.urbaning.cobevt_rgb_training import fit_normalizers, original_heads
from phdsim.perception.urbaning.cobevt_rgb_adapter import metric_grid
from phdsim.perception.urbaning.bev_cpu import corners


class Loss(nn.Module):
    def __init__(self):super().__init__();self.loss_dict={}
    def forward(self,out,target):
        a=(out['psm']-target['psm']).square().mean();b=(out['rm']-target['rm']).square().mean()
        self.loss_dict={'conf_loss':a,'reg_loss':b};return a+b


def fixture(n=4):
    torch.manual_seed(9)
    heads=[nn.Conv2d(256,32,1).eval().requires_grad_(False),nn.Conv2d(256,56,1).eval().requires_grad_(False)]
    values=[];targets=[];records=[]
    boxes=np.stack([corners([x,0,0],2,3,2,0) for x in (-9,-3,3,9)])
    for i in range(n):
        f={'bev':torch.randn(1,256,4,6).contiguous(memory_format=torch.channels_last),
           'rgb':torch.randn(12,4,6),'xy':metric_grid((4,6),[-6,-4,-2,6,4,2])}
        f['rgb'][-4:]=1;values.append(f)
        with torch.no_grad():targets.append(original_heads(*heads,f['bev']+.1))
        sequence='20241126_0001_crossing2_00' if i<n//2 else '20241126_0017_crossing1_00'
        records.append({'key':f'{sequence}:{i:06d}:100000','sequence':sequence,
                        'gt_boxes':boxes.copy(),'gt_labels':np.arange(1,5)})
    class Store:
        def __init__(self,values,targets):self.values=values;self.targets=targets
        def __len__(self):return len(self.values)
        def __getitem__(self,i):return self.values[i]
        def target(self,i):return self.targets[i]
    store=Store(values,targets)
    runtime=SimpleNamespace(heads=heads,loss=Loss(),decode=lambda out:(boxes.copy(),np.c_[np.full(4,.9),np.arange(1,5)]))
    return records,values,store,runtime


def configuration():
    return {'epochs':2,'learning_rate':.01,'weight_decay':1e-4,'residual_penalty':1e-4,'gradient_clip':1.}


class ControlledTests(unittest.TestCase):
    def test_native_size_extraction_reuse_new_forward_disk_roundtrip_and_resume(self):
        """Real feature/head/lifting/cache code; dataset I/O and encoder are fixtures."""
        torch.manual_seed(3)
        bev=torch.randn(1,256,100,256)
        heads=[nn.Conv2d(256,32,1).eval().requires_grad_(False),nn.Conv2d(256,56,1).eval().requires_grad_(False)]
        class Model(nn.Module):
            def __init__(self):
                super().__init__();self.fusion_net=nn.Identity();self.cls_head=heads[0];self.reg_head=heads[1]
                self.eval().requires_grad_(False)
            def forward(self,inputs):return original_heads(*heads,self.fusion_net(inputs['bev']))
        config={'model':{'args':{'lidar_range':[-102.4,-40,-5,102.4,40,3]}},'train_params':{}}
        boxes=np.stack([corners([x,0,0],2,3,2,0) for x in (-9,-3,3,9)])
        runtime=SimpleNamespace(heads=heads,decode=lambda out:(boxes,np.c_[np.full(4,.9),np.arange(1,5)]),
                                target=lambda row:{'fixture_target':torch.ones(1,2,3)})
        class Encoder:
            def __init__(self,*args):self.identity={'fixture':True}
            def __call__(self,images):return torch.ones(6,48,24,40)
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);(output/'protocol.json').write_text('{}');sequence=c.SEQUENCES[0][1]
            folder=output/'converted'/sequence/'100000';folder.mkdir(parents=True)
            records=[]
            for i in range(200):
                path=folder/f'{i+1:06d}.yaml';lidar=path.with_suffix('.pcd')
                if i<2:path.write_text('fixture');lidar.write_bytes(b'point fixture')
                records.append({'key':f'{sequence}:{i+1:06d}:100000','sequence':sequence,'yaml':str(path),
                    'native_association':{},'gt_boxes':boxes,'gt_labels':np.arange(1,5),
                    'lidar_source':{'path':str(lidar),'sha256':c.sha(b'point fixture')}})
            c.write_json(output/'inventory.json',{'ground_z_train_only':-1.,'keys':{'train':[r['key'] for r in records]}})
            weights=output/'weights';(weights/'checkpoints').mkdir(parents=True)
            payload=b'weight fixture';(weights/'checkpoints/mobilenet_v3_small-047dcff4.pth').write_bytes(payload)
            class Dataset:
                def __len__(self):return 200
                def retrieve_by_idx(self,i):
                    stamp=f'{i+1:06d}';return {'100000':{stamp:{'yaml':records[i]['yaml'],'lidar':records[i]['lidar_source']['path']}}},i
                def return_timestamp_key(self,scene,i):return f'{i+1:06d}'
                def collate_batch_test(self,items):return {'ego':{'bev':bev}}
            datasets=ModuleType('opencood.data_utils.datasets');datasets.build_dataset=lambda *a,**k:Dataset()
            train_utils=ModuleType('opencood.tools.train_utils');train_utils.to_device=lambda value,device:value
            fake_modules={'opencood.data_utils.datasets':datasets,'opencood.tools.train_utils':train_utils}
            image_hashes={str(i):'fixture'+str(i) for i in range(6)}
            with torch.no_grad():native=original_heads(*heads,bev)
            cached={'bev':bev.numpy(),'xy':metric_grid((100,256),config['model']['args']['lidar_range']),
                    **{k:v.numpy() for k,v in native.items()}}
            reuse=(cached,{'kind':'reviewed_preflight','sha256':'fixture'},
                   [{'camera':i,'image_sha256':image_hashes[str(i)]} for i in range(6)])
            def reviewed(base,record):return reuse if record['key']==records[0]['key'] else None
            with patch.dict('sys.modules',fake_modules),patch.object(c,'prepare_upstream'), \
                 patch.object(c,'load_records',return_value=({'train':records,'validation':[]},{})), \
                 patch.object(c,'add_point_bindings'),patch.object(c,'load_config',return_value=config), \
                 patch.object(c,'load_frozen_heads',return_value=heads),patch.object(c,'native_runtime',return_value=runtime), \
                 patch.object(c,'SpatialEncoder',Encoder),patch.object(c,'WEIGHTS_SHA',c.sha(payload)), \
                 patch.object(c,'image_payloads',return_value=([np.zeros((8,8,3),np.uint8)]*6,image_hashes)), \
                 patch.object(c,'reused_preflight',side_effect=reviewed), \
                 patch.object(c,'camera_fields',return_value=[(np.eye(4),np.eye(3))]*6), \
                 patch.object(c,'capture_sources',return_value=({}, {'included_ids':[100000]})), \
                 patch.object(c,'subset_inputs',side_effect=lambda batch,indices:batch), \
                 patch.object(c,'load_model',return_value=(Model(),config)) as loading:
                c.extract_sequence(output,output,output,weights,{'threads':2},0,max_frames=2)
                self.assertEqual(loading.call_count,1)
                c.extract_sequence(output,output,output,weights,{'threads':2},0,max_frames=2)
                self.assertEqual(loading.call_count,1)  # no native backbone on completed cache reuse
            store=c.FeatureStore(output,records[:2])
            self.assertTrue(torch.equal(store[0]['bev'],bev));self.assertTrue(torch.equal(store[1]['bev'],bev))
            self.assertEqual(tuple(store[0]['rgb'].shape),(196,100,256))
            self.assertEqual(tuple(store.target(1)['fixture_target'].shape),(1,2,3))
            for row in records[:2]:
                manifest=json.loads((c.feature_dir(output,row['key'])/'manifest.json').read_text())
                self.assertTrue(manifest['parity_passed'])

    def test_inventory_requires_disjoint_original_recordings_and_exact_counts(self):
        records={'train':[],'validation':[]}
        for split,seq in c.SEQUENCES:
            records[split]+=[{'key':f'{seq}:{i:06d}:100000','sequence':seq} for i in range(200)]
        c.check_inventory(records)
        records['validation'].pop()
        with self.assertRaisesRegex(ValueError,'200'):c.check_inventory(records)
        # Different clips of one original recording must not leak between splits.
        train=records['train'][0]['sequence'];val=train[:-2]+'01'
        records['validation']=[{'key':f'{val}:{i:06d}:100000','sequence':val} for i in range(200)]
        sequences=(('train',c.SEQUENCES[0][1]),('train',c.SEQUENCES[1][1]),('validation',val))
        with patch.object(c,'SEQUENCES',sequences):
            with self.assertRaisesRegex(ValueError,'overlaps'):c.check_inventory(records)

    def test_far_shuffle_is_label_free_within_recording_and_not_nearby(self):
        records=[]
        for sequence in ('20241126_0001_crossing2_00','20241126_0017_crossing1_00'):
            records += [{'key':f'{sequence}:{i:06d}:100000','sequence':sequence} for i in range(200)]
        mapping=c.far_shuffle(records)
        self.assertEqual(sorted(mapping),list(range(400)))
        for i,j in enumerate(mapping):
            self.assertEqual(records[i]['sequence'],records[j]['sequence'])
            self.assertEqual(abs(i-j),100)

    def test_streaming_normalization_matches_original_and_never_reads_validation(self):
        records,values,store,runtime=fixture()
        expected=fit_normalizers(values)
        streamed={'lidar':c.channel_normalizer(c.FieldSequence(store,'bev',lambda x:x[0])),
                  'rgb':c.channel_normalizer(c.FieldSequence(store,'rgb',lambda x:x[:-4]),
                                             c.FieldSequence(store,'rgb',c.rgb_mask))}
        self.assertEqual(expected,streamed)
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);(output/'protocol.json').write_text('{}')
            def loader(*args):
                self.assertEqual(args[-2:],(200,0))
                return {'train':records,'validation':[]},{}
            with patch.object(c,'load_records',side_effect=loader),patch.object(c,'FeatureStore',return_value=store):
                c.prepare_training(output,output,configuration())
            result=json.loads((output/'normalizers.json').read_text())
            self.assertTrue(result['train_only']);self.assertEqual(result['normalizers'],expected)

    def test_disk_store_bounds_cache_and_rejects_changed_payload(self):
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);(output/'protocol.json').write_text('{}');records=[]
            for i in range(3):
                row={'key':f'train:{i}:100000','yaml':str(output/f'{i}.yaml')};records.append(row)
                Path(row['yaml']).write_text('fixture')
                directory=c.feature_dir(output,row['key']);directory.mkdir(parents=True)
                np.save(directory/'bev.npy',np.ones((1,256,4,6),np.float32)*i)
                np.save(directory/'rgb.npy',np.ones((12,4,6),np.float16))
                c.write_json(directory/'manifest.json',{'identity':{'key':row['key'],
                    'protocol_sha256':c.sha256(output/'protocol.json'),'yaml_sha256':c.sha256(row['yaml'])},
                    'files':{name:c.sha256(directory/name) for name in ('bev.npy','rgb.npy')}})
            store=c.FeatureStore(output,records)
            for i in range(3):self.assertEqual(float(store[i]['bev'].mean()),i)
            self.assertEqual(len(store.recent),2)
            c.feature_dir(output,records[0]['key']).joinpath('bev.npy').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'Cached file changed'):c.FeatureStore(output,records)

    def test_disposable_native_gate_uses_only_train_and_discards_probe_state(self):
        records,values,store,runtime=fixture()
        with tempfile.TemporaryDirectory() as t:
            output=Path(t)
            with patch.object(c,'extract_sequence') as extraction,patch.object(c,'prepare_upstream'), \
                 patch.object(c,'load_records',return_value=({'train':records,'validation':[]},{})) as loader, \
                 patch.object(c,'FeatureStore',return_value=store),patch.object(c,'load_config',return_value={}), \
                 patch.object(c,'load_frozen_heads',return_value=runtime.heads),patch.object(c,'native_runtime',return_value=runtime):
                c.smoke(output,output,output,output,configuration())
            self.assertEqual(extraction.call_args.kwargs,{'max_frames':2})
            self.assertEqual(loader.call_args.args[-2:],(200,0))
            report=json.loads((output/'smoke.json').read_text())
            self.assertEqual(report['status'],'passed');self.assertEqual(len(report['rows']),3)
            self.assertFalse((output/'normalizers.json').exists())
            self.assertEqual(list(output.glob('*.pt')),[])

    def test_matched_initialization_no_rgb_control_and_exact_mid_epoch_resume(self):
        records,values,store,runtime=fixture(104);normalizers=fit_normalizers(values);config=configuration()
        context1=c.mode_context('lidar_adapter',values[0],values[0]['rgb'],normalizers)
        context2=c.mode_context('lidar_adapter',values[0],values[1]['rgb']*100,normalizers)
        self.assertTrue(torch.equal(context1,context2))
        before=[{k:v.clone() for k,v in h.state_dict().items()} for h in runtime.heads]
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            full,a=c.fit_adapter('lidar_rgb_adapter',0,records,store,runtime.heads,runtime,normalizers,root/'full',config)
            original=c.atomic_torch
            def interrupt(path,value):
                original(path,value)
                if path.name=='checkpoint.pt' and value['progress']['next_frame']==100:raise InterruptedError()
            with patch.object(c,'atomic_torch',side_effect=interrupt):
                with self.assertRaises(InterruptedError):
                    c.fit_adapter('lidar_rgb_adapter',0,records,store,runtime.heads,runtime,normalizers,root/'resume',config)
            resumed,b=c.fit_adapter('lidar_rgb_adapter',0,records,store,runtime.heads,runtime,normalizers,root/'resume',config)
            self.assertEqual(a['progress'],b['progress'])
            for k,v in full.state_dict().items():self.assertTrue(torch.equal(v,resumed.state_dict()[k]),k)
            _,control=c.fit_adapter('lidar_adapter',0,records,store,runtime.heads,runtime,normalizers,root/'control',config)
            self.assertEqual(a['initial_state_sha256'],control['initial_state_sha256'])
            self.assertEqual(a['parameter_count'],control['parameter_count'])
        for head,snapshot in zip(runtime.heads,before):
            self.assertTrue(all(torch.equal(v,snapshot[k]) for k,v in head.state_dict().items()))
            self.assertTrue(all(p.grad is None for p in head.parameters()))

    def test_complete_three_seed_freeze_heldout_evaluation_replay_export_and_reuse(self):
        """Artificial perfect predictions test wiring only, never native accuracy."""
        train,values,train_store,runtime=fixture()
        validation=[{**r,'sequence':'20241126_0004_crossing2_00',
                     'key':f'20241126_0004_crossing2_00:{i:06d}:100000'} for i,r in enumerate(train)]
        normalizers=fit_normalizers(values);config=configuration()
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);(output/'protocol.json').write_text('{}')
            c.write_json(output/'normalizers.json',{'normalizers':normalizers,'keys':[r['key'] for r in train],
                         'protocol_sha256':c.sha256(output/'protocol.json'),'train_only':True})
            for name in ('inventory.json','train-shuffle.json'):c.write_json(output/name,{})
            (output/'extraction').mkdir()
            active_seed=[None]
            def loader(base,out,tag,a,b):
                if b:
                    directory=output/'seeds'/str(active_seed[0])
                    self.assertTrue((directory/'freeze.json').is_file())
                    frozen=json.loads((directory/'freeze.json').read_text())
                    for mode in c.MODES:self.assertEqual(c.sha256(directory/mode/'model-final.pt'),frozen['models'][mode])
                    return {'train':[],'validation':validation},{}
                self.assertEqual(b,0)
                return {'train':train,'validation':[]},{}
            with patch.object(c,'prepare_upstream'),patch.object(c,'load_config',return_value={}), \
                 patch.object(c,'load_frozen_heads',return_value=runtime.heads),patch.object(c,'native_runtime',return_value=runtime), \
                 patch.object(c,'load_records',side_effect=loader),patch.object(c,'FeatureStore',return_value=train_store):
                for index,seed in enumerate(c.SEEDS):
                    active_seed[0]=seed;c.seed_worker(output,output,output,config,index)
                c.seed_worker(output,output,output,config,0)
            c.collect(output,config)
            report=json.loads((output/'report.json').read_text())
            self.assertTrue(report['independent_raw_prediction_ap_replay'])
            self.assertEqual(report['primary_paired_delta_pp']['per_seed'],[0,0,0])
            self.assertEqual(len(report['seeds']),3)
            archive=output/'urbaning-cobevt-rgb-controlled.zip';before=archive.read_bytes()
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip());self.assertEqual(len([p for p in z.namelist() if p.endswith('.npz')]),60)
            c.collect(output,config);self.assertEqual(before,archive.read_bytes())
            # The independent replay must reject even one edited exported file.
            prediction=next((output/'seeds/0/validation-lidar_adapter').glob('*.npz'))
            prediction.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'predictions changed'):
                c.replay_predictions(prediction.parent)

    def test_submission_dependencies_and_parallel_limits_without_slurm(self):
        repo=Path(__file__).resolve().parents[1]
        source=(repo/'scripts/slurm/submit_urbaning_cobevt_rgb_controlled.sh').read_text()
        with tempfile.TemporaryDirectory(prefix='rgb slurm ') as t:
            root=Path(t);work=root/'work';(work/'bin').mkdir(parents=True);(work/'inputs').mkdir()
            wrapper=work/'bin/urbaning-python.sh';wrapper.write_text('#!/bin/bash\n');wrapper.chmod(0o755)
            (work/'inputs/urbaning-gap-acquisition-inputs-001.zip').touch()
            pre=work/'phdsim/runs/urbaning-cobevt-rgb-preflight-21597293';pre.mkdir(parents=True)
            (pre/'urbaning-cobevt-rgb-preflight.zip').touch()
            script=root/'submit.sh';script.write_text(source.replace('WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work','WORK='+repr(str(work))))
            fake=root/'fake';fake.mkdir();log=root/'calls';counter=root/'counter';counter.write_text('100')
            sbatch=fake/'sbatch';sbatch.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\nn=$(cat "$COUNTER")\nn=$((n+1))\necho "$n" > "$COUNTER"\necho "$n"\n');sbatch.chmod(0o755)
            env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'CALLS':str(log),'COUNTER':str(counter)}
            result=subprocess.run(['bash',str(script)],cwd=repo,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            calls=log.read_text().splitlines();self.assertEqual(len(calls),6)
            for i,line in enumerate(calls[1:],1):self.assertIn(f'--dependency=afterok:{100+i}',line)
            self.assertIn('--array=0-2%2',calls[2]);self.assertIn('--array=0-2%2',calls[4])
            self.assertIn('logs/',calls[0]);self.assertIn('REPORT: 106',result.stdout)


if __name__=='__main__':
    torch.set_num_threads(2)
    unittest.main()
