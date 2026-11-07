import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch
from torch import nn

from phdsim.experiments import urbaning_cobevt_rgb_train_eval as e
from phdsim.experiments import urbaning_cobevt_rgb_controlled as c
from phdsim.perception.urbaning.cobevt_rgb_training import fit_normalizers, original_heads
from phdsim.perception.urbaning.cobevt_rgb_adapter import metric_grid
from phdsim.perception.urbaning.bev_cpu import corners


class Loss(nn.Module):
    def __init__(self):super().__init__();self.loss_dict={}
    def forward(self,out,target):
        a=(out['psm']-target['psm']).square().mean();b=(out['rm']-target['rm']).square().mean()
        self.loss_dict={'conf_loss':a,'reg_loss':b};return a+b


class SourceFixture:
    """Small canonical source ZIP with real frozen state_dicts; no native results."""
    def __init__(self,root):
        self.base=root/'base';self.base.mkdir();self.source=root/'source';self.source.mkdir()
        self.output=root/'audit';torch.manual_seed(4)
        self.heads=[nn.Conv2d(256,32,1).eval().requires_grad_(False),nn.Conv2d(256,56,1).eval().requires_grad_(False)]
        self.records=[];self.features=[];self.targets=[]
        self.boxes=np.stack([corners([x,0,0],2,3,2,0) for x in (-9,-3,3,9)])
        for i in range(4):
            sequence=c.SEQUENCES[0 if i<2 else 1][1]
            self.records.append({'key':f'{sequence}:{i:06d}:100000','sequence':sequence,
                                 'gt_boxes':self.boxes.copy(),'gt_labels':np.arange(1,5)})
            rgb=torch.randn(12,4,6);rgb[-4:]=1
            f={'bev':torch.randn(1,256,4,6),'rgb':rgb,'xy':metric_grid((4,6),[-6,-4,-2,6,4,2])}
            self.features.append(f)
            with torch.no_grad():self.targets.append(original_heads(*self.heads,f['bev']+.1))
        fixture=self
        class Store:
            def __len__(self):return len(fixture.records)
            def __getitem__(self,i):return fixture.features[i]
            def target(self,i):return fixture.targets[i]
        self.store=Store();self.decode_calls=0
        def decode(outputs):
            self.decode_calls+=1
            return self.boxes.copy(),np.c_[np.full(4,.9),np.arange(1,5)]
        self.runtime=SimpleNamespace(heads=self.heads,loss=Loss(),decode=decode)
        self.bundle={'files':{'best_model.pth':'official-fixture'}}
        self.protocol=c.protocol(self.base,2);c.write_json(self.source/'protocol.json',self.protocol)
        self.normalizer={'normalizers':fit_normalizers(self.features),'train_only':True,
                         'keys':[r['key'] for r in self.records],'protocol_sha256':c.sha256(self.source/'protocol.json')}
        c.write_json(self.source/'normalizers.json',self.normalizer)
        val_keys=[f'{c.SEQUENCES[2][1]}:{i:06d}:100000' for i in range(4)]
        self.inventory={'keys':{'train':self.normalizer['keys'],'validation':val_keys},'model':self.bundle,
                        'protocol_sha256':c.sha256(self.source/'protocol.json')}
        c.write_json(self.source/'inventory.json',self.inventory)
        (self.source/'extraction').mkdir();rows_by_seq={seq:[] for _,seq in c.SEQUENCES}
        for record in self.records:
            directory=c.feature_dir(self.source,record['key']);directory.mkdir(parents=True)
            c.write_json(directory/'manifest.json',{'fixture':record['key']})
            rows_by_seq[record['sequence']].append({'key':record['key'],'manifest_sha256':c.sha256(directory/'manifest.json')})
        for seq,rows in rows_by_seq.items():c.write_json(self.source/'extraction'/(seq+'.json'),{'frames':rows})
        stats=[c.frame_statistics(self.boxes,np.c_[np.full(4,.9),np.arange(1,5)],self.boxes,np.arange(1,5)) for _ in range(4)]
        metrics=e.aggregate(stats);reports=[]
        for seed in c.SEEDS:
            directory=self.source/'seeds'/str(seed);directory.mkdir(parents=True)
            digests={};state_sha=None;parameters=None
            for mode in c.MODES:
                torch.manual_seed(seed)
                model=c.BoundedAdapter(270,256,self.normalizer['normalizers']['lidar']['std'],16)
                state_sha=c.sha(b''.join(v.numpy().tobytes() for v in model.state_dict().values()))
                parameters=sum(p.numel() for p in model.parameters())
                # Saved "final" weights must differ from zero initialization;
                # this detects accidentally evaluating a freshly initialized adapter.
                with torch.no_grad():model.adapter.delta.bias.fill_(.02+.01*c.MODES.index(mode))
                path=directory/mode/'model-final.pt';path.parent.mkdir()
                c.atomic_torch(path,{'mode':mode,'seed':seed,'configuration':self.protocol,
                    'initial_state_sha256':state_sha,'parameter_count':parameters,'model':model.state_dict(),
                    'progress':{'epoch':32,'next_frame':0,'history':[{'epoch':n,'detection':1/n} for n in range(1,33)]}})
                digests[mode]=c.sha256(path)
            frozen={'seed':seed,'protocol_sha256':c.sha256(self.source/'protocol.json'),
                    'normalizers_sha256':c.sha256(self.source/'normalizers.json'),'models':digests,
                    'initial_state_sha256':state_sha,'parameter_count':parameters,'final_epoch':32}
            report={'seed':seed,'head_weights_unchanged':True,'freeze':frozen,
                    'metrics':{name:metrics for name in ('original_lidar',*c.MODES,'lidar_rgb_shuffled_eval_diagnostic')}}
            c.write_json(directory/'freeze.json',frozen);c.write_json(directory/'report.json',report);reports.append(report)
        c.write_json(self.source/'report.json',{'protocol':self.protocol,'independent_raw_prediction_ap_replay':True,'seeds':reports})
        archive=self.source/'urbaning-cobevt-rgb-controlled.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(self.source.rglob('*')):
                if path.is_file() and path!=archive:z.write(path,str(path.relative_to(self.source)))
        c.write_json(self.source/'completed.json',{'sha256':c.sha256(archive),'bytes':archive.stat().st_size})
    def hashes(self):return {str(p.relative_to(self.source)):c.sha256(p) for p in self.source.rglob('*') if p.is_file()}


class TrainEvaluationTests(unittest.TestCase):
    def test_complete_frozen_train_evaluation_replay_export_no_source_writes_or_fitting(self):
        with tempfile.TemporaryDirectory() as t:
            f=SourceFixture(Path(t));before=f.hashes()
            def loader(base,output,tag,a,b):
                self.assertEqual((a,b),(200,0));self.assertFalse(output.is_relative_to(f.source))
                return {'train':f.records,'validation':[]},{}
            with patch.object(c,'verify_bundle',return_value=f.bundle),patch.object(c,'prepare_upstream'), \
                 patch.object(c,'load_config',return_value={}),patch.object(c,'load_frozen_heads',return_value=f.heads), \
                 patch.object(c,'native_runtime',return_value=f.runtime),patch.object(c,'load_records',side_effect=loader), \
                 patch.object(c,'FeatureStore',return_value=f.store), \
                 patch.object(c,'fit_adapter',side_effect=AssertionError('fitting prohibited')), \
                 patch.object(c,'load_model',side_effect=AssertionError('backbone prohibited')), \
                 patch.object(c,'SpatialEncoder',side_effect=AssertionError('CNN prohibited')), \
                 patch('torch.optim.AdamW',side_effect=AssertionError('optimizer prohibited')):
                for seed in c.SEEDS:e.run_seed(f.base,f.source,f.output,f.base,2,seed)
                self.assertEqual(f.decode_calls,52)  # original4 only once +4 variants x4 frames x3 seeds
                e.run_seed(f.base,f.source,f.output,f.base,2,0)
                self.assertEqual(f.decode_calls,52)
                e.collect(f.base,f.source,f.output,2)
                before_archive=(f.output/'urbaning-cobevt-rgb-train-eval.zip').read_bytes()
                e.collect(f.base,f.source,f.output,2)
                self.assertEqual(before_archive,(f.output/'urbaning-cobevt-rgb-train-eval.zip').read_bytes())
            self.assertEqual(before,f.hashes())
            result=json.loads((f.output/'report.json').read_text())
            self.assertTrue(result['independent_train_ap_replay'])
            self.assertEqual(len(result['paired_rgb_minus_lidar']),3)
            self.assertTrue(all(row['validation200_map_percent'] is None for row in result['rows'] if row['variant']==e.AS_TRAINED))
            self.assertEqual(len(result['seeds'][0]['train']['original_lidar']['per_recording']),2)
            train=result['seeds'][0]['train']
            self.assertLess(train['lidar_rgb_adapter']['frozen_model_train_loss']['detection'],
                            train['original_lidar']['frozen_model_train_loss']['detection'])
            with zipfile.ZipFile(f.output/'urbaning-cobevt-rgb-train-eval.zip') as z:
                self.assertIsNone(z.testzip());self.assertEqual(len([n for n in z.namelist() if n.endswith('.npz')]),52)

    def test_variant_resume_skips_completed_head_inference_and_rejects_changed_export(self):
        with tempfile.TemporaryDirectory() as t:
            f=SourceFixture(Path(t));normalizers=f.normalizer['normalizers'];identity={'residual_penalty':1e-4}
            original=f.runtime.decode
            def interrupted(out):
                if f.decode_calls==2:raise InterruptedError('fixture preemption')
                return original(out)
            directory=f.output/'variant'
            with patch.object(f.runtime,'decode',side_effect=interrupted):
                with self.assertRaises(InterruptedError):e.evaluate('original_lidar',f.records,f.store,f.runtime,directory,identity,normalizers)
            self.assertEqual(f.decode_calls,2)
            e.evaluate('original_lidar',f.records,f.store,f.runtime,directory,identity,normalizers)
            self.assertEqual(f.decode_calls,4)
            self.assertEqual(e.replay_variant(directory)[0]['metrics']['frames'],4)
            path=next(directory.glob('*.npz'));path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'export changed'):e.replay_variant(directory)

    def test_source_archive_model_and_feature_identity_rejections(self):
        with tempfile.TemporaryDirectory() as t:
            f=SourceFixture(Path(t))
            with patch.object(c,'verify_bundle',return_value=f.bundle):
                verified=e.verify_source(f.base,f.source,0,2)
                e.verify_train_inventory(f.source,f.records,verified)
                with self.assertRaisesRegex(ValueError,'thread'):e.verify_source(f.base,f.source,0,4)
                feature=c.feature_dir(f.source,f.records[0]['key'])/'manifest.json';feature.write_text('{}')
                with self.assertRaisesRegex(ValueError,'Feature manifest'):e.verify_train_inventory(f.source,f.records,verified)
                model=f.source/'seeds/0/lidar_adapter/model-final.pt';model.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'differs from archive'):e.verify_source(f.base,f.source,0,2)

    def test_final_model_rejects_nonfinal_checkpoint_and_wrong_recipe(self):
        with tempfile.TemporaryDirectory() as t:
            f=SourceFixture(Path(t))
            with patch.object(c,'verify_bundle',return_value=f.bundle):verified=e.verify_source(f.base,f.source,0,2)
            model,history=e.load_adapter(f.source,0,'lidar_adapter',f.store,verified)
            self.assertEqual(len(history),32);self.assertFalse(model.training)
            self.assertTrue(all(not p.requires_grad for p in model.parameters()))
            self.assertTrue(torch.equal(model.adapter.delta.bias,torch.full((256,),.02)))
            feature=f.features[0]
            with torch.no_grad():
                corrected,_=model(feature['bev'],c.mode_context('lidar_adapter',feature,feature['rgb'],f.normalizer['normalizers']))
            self.assertFalse(torch.equal(corrected,feature['bev']))
            path=f.source/'seeds/0/lidar_adapter/model-final.pt'
            saved=torch.load(path,weights_only=True);saved['progress']['epoch']=31;c.atomic_torch(path,saved)
            with self.assertRaisesRegex(ValueError,'Final model identity'):e.load_adapter(f.source,0,'lidar_adapter',f.store,verified)

    def test_configuration_lock_is_safe_for_parallel_initialization(self):
        with tempfile.TemporaryDirectory() as t:
            f=SourceFixture(Path(t))
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                values=list(pool.map(lambda _:e.bind_configuration(f.source,f.output,2),range(4)))
            self.assertTrue(all(v==values[0] for v in values))
            self.assertEqual(json.loads((f.output/'protocol.json').read_text()),values[0])
            with self.assertRaisesRegex(ValueError,'separate non-nested'):e.bind_configuration(f.source,f.source/'audit',2)

    def test_submission_waits_for_original_report_or_reuses_completed_source(self):
        repo=Path(__file__).resolve().parents[1]
        original=(repo/'scripts/slurm/submit_urbaning_cobevt_rgb_train_eval.sh').read_text()
        with tempfile.TemporaryDirectory(prefix='train eval ') as t:
            root=Path(t);work=root/'work';(work/'bin').mkdir(parents=True)
            wrapper=work/'bin/urbaning-python.sh';wrapper.write_text('#!/bin/bash\n');wrapper.chmod(0o755)
            source=work/'phdsim/runs/urbaning-cobevt-rgb-controlled-001';source.mkdir(parents=True);(source/'protocol.json').write_text('{}')
            script=root/'submit.sh';script.write_text(original.replace('WORK=/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work','WORK='+repr(str(work))))
            fake=root/'fake';fake.mkdir();log=root/'log';counter=root/'counter';counter.write_text('100')
            sbatch=fake/'sbatch';sbatch.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\nn=$(cat "$COUNTER")\nn=$((n+1))\necho "$n" > "$COUNTER"\necho "$n"\n');sbatch.chmod(0o755)
            squeue=fake/'squeue';squeue.write_text('#!/bin/bash\necho "${SOURCE_STATE:-}"\n');squeue.chmod(0o755)
            env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'CALLS':str(log),'COUNTER':str(counter),'SOURCE_STATE':'RUNNING'}
            pending=subprocess.run(['bash',str(script)],cwd=repo,env=env,capture_output=True,text=True)
            self.assertEqual(pending.returncode,0,pending.stderr)
            lines=log.read_text().splitlines();self.assertEqual(len(lines),2)
            self.assertIn('--dependency=afterok:21599633',lines[0]);self.assertIn('--array=0-2%2',lines[0])
            self.assertIn('--dependency=afterok:101',lines[1])
            log.write_text('');env['SOURCE_STATE']=''
            failed=subprocess.run(['bash',str(script)],cwd=repo,env=env,capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0);self.assertEqual(log.read_text(),'')
            (source/'completed.json').write_text('{}');(source/'report.json').write_text('{}')
            ready=subprocess.run(['bash',str(script)],cwd=repo,env=env,capture_output=True,text=True)
            self.assertEqual(ready.returncode,0,ready.stderr)
            self.assertNotIn('--dependency=',log.read_text().splitlines()[0])


if __name__=='__main__':
    torch.set_num_threads(2)
    unittest.main()
