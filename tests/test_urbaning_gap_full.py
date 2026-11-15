import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from test_urbaning_subsets import make_run
from phdsim.experiments import urbaning_gap_full as full
from phdsim.experiments.urbaning_ap_replay import metrics_both_orders,baseline_choices
from phdsim.experiments.urbaning_subsets import load_runs
from phdsim.learning.urbaning_geometry import SCHEMA as POSE_SCHEMA
from phdsim.learning.urbaning_gap_forests import PROFILES,SCHEMA as FOREST_SCHEMA
from phdsim.learning.urbaning_regions import FEATURES

SEQ='20241127_0009_crossing3_00'


def archive(path,members):
    with zipfile.ZipFile(path,'w') as z:
        for name,raw in members.items():z.writestr(name,raw)
        z.writestr('files.json',json.dumps({n:full.sha(b) for n,b in members.items()}))
    return full.sha(Path(path).read_bytes())


def fixture(root):
    parent=root/'cache'/SEQ;parent.mkdir(parents=True)
    run=make_run(parent/'run',SEQ)
    rows=list(map(json.loads,(run/'frames.jsonl').read_text().splitlines()))
    poses=parent/'poses.json'
    poses.write_text(json.dumps({'schema':POSE_SCHEMA,'metadata_assumption':'fixture',
        'trace_sha256':full.sha((run/'frames.jsonl').read_bytes()),
        'frames':{r['frame_key']:{'200000':np.eye(4).tolist(),'-1':np.eye(4).tolist()} for r in rows}}))
    frames,provenance=load_runs([run],[poses])
    choices={a:dict(zip([f['key'] for f in frames],baseline_choices(frames,a))) for a in full.ACTION_ORDER}
    policies={a:metrics_both_orders(frames,list(c.values())) for a,c in choices.items()}
    reference={'schema':'phdsim-urbaning-frozen-full-report-v1','status':'completed','frames':4,
        'runtime':{'numpy':'1.26.4'},'provenance':provenance,'choices':choices,'policies':policies,'pure_random':{}}
    portable=[]
    for f,r in zip(frames,rows):
        f.update(prediction_path=r['predictions'],prediction_sha256=full.sha((run/r['predictions']).read_bytes()),gt_sha256=r['gt_sha256'])
        portable.append(json.dumps({'key':f['key'],'sequence':SEQ,'source_ids':f['source_ids'],
            'gt_sha256':r['gt_sha256'],'prediction_path':r['predictions'],
            'prediction_sha256':full.sha((run/r['predictions']).read_bytes()),'statistics':f['statistics']}))
    reference_path=root/'reference.zip'
    reference_sha=archive(reference_path,{'report.json':json.dumps(reference).encode(),
        'offline-statistics.jsonl':('\n'.join(portable)+'\n').encode()})
    models={}
    def tree(profile,task,value):
        return {'schema':FOREST_SCHEMA,'profile':profile,'features':list(FEATURES),'indices':list(PROFILES[profile]),
            'task':task,'trees':[{'left':[-1],'right':[-1],'feature':[-2],'threshold':[-2.],'value':[value]}]}
    for name in PROFILES:models[name]={'gap':tree(name,'gap',.7),
        'benefit':{a:tree(name,'local_benefit',v) for a,v in zip(full.ACTION_ORDER[1:],(.2,.5,.8))}}
    raw={name:json.dumps(m).encode() for name,m in models.items()}
    protocol={'schema':'phdsim-urbaning-gap-acquisition-validation-v1','numpy_version':'1.26.4',
        'recording_groups':{'train':['20241126_0001','20241126_0017'],'validation':['20241126_0004']},
        'detector':provenance['detector'],'frozen_model_sha256':{n:full.sha(b) for n,b in raw.items()}}
    configs=[{'profile':p,'aggregation':a,'error_cost':cost,'budget_cap':cap,'status':'validation-selected'}
        for p in PROFILES for a in ('gap_top10','all_cells') for cap,cost in ((.5,10.),(1.,5.),(1.5,.5))]
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('deployment.json',json.dumps({'protocol':protocol,'policies':configs}))
        for n,b in raw.items():z.writestr(f'models/{n}.json',b)
    deploy=buf.getvalue()
    val={'status':'completed','protocol':protocol,'selected':configs,'deployment_sha256':full.sha(deploy)}
    valpath=root/'validation.zip';valsha=archive(valpath,{'report.json':json.dumps(val).encode(),
        'frozen-gap-acquisition-inputs.zip':deploy})
    return valpath,valsha,reference_path,reference_sha,frames,reference


class GapFullTests(unittest.TestCase):
    def setUp(self):
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        for name,value in [('SEQUENCES',(SEQ,)),('EXPECTED_FRAMES',4),('SEQUENCE_FRAMES',4),
                           ('SEEDS',(0,99)),('PURE_P',(.5,))]:stack.enter_context(patch.object(full,name,value))

    def test_complete_frozen_replay_resumes_without_models_or_detector_runtime(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);v,vs,r,rs,_,_=fixture(root);out=root/'out'
            with patch.dict('sys.modules',{'torch':None,'sklearn':None,'opencood':None}):
                full.run(v,vs,r,rs,root/'cache',out)
                first=json.loads((out/'report.json').read_text())
                with patch.object(full,'predict',wraps=full.predict) as predictor:
                    full.run(v,vs,r,rs,root/'cache',out,resume=True)
                    # Three empty-input deployment preflights; no sequence prediction again.
                    self.assertEqual(predictor.call_count,3)
            self.assertEqual(first,json.loads((out/'report.json').read_text()))
            self.assertEqual(len(first['protocol']['frozen_policies']),18)
            self.assertEqual(first['frames'],4)
            with zipfile.ZipFile(out/'urbaning-gap-full.zip') as z:
                self.assertIsNone(z.testzip())
                for n,h in json.loads(z.read('files.json')).items():self.assertEqual(full.sha(z.read(n)),h)
            changed=json.loads((out/'protocol.json').read_text());changed['validation_zip_sha256']='different'
            (out/'protocol.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'different code, inputs or protocol'):
                full.run(v,vs,r,rs,root/'cache',out,resume=True)

    def test_public_adapter_never_loads_gt_or_peer_arrays_and_rejects_changed_pose(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);_,_,_,_,frames,ref=fixture(root)
            real=np.load;access=[]
            class PublicOnly:
                def __init__(self,path,**kwargs):self.npz=real(path,**kwargs)
                def __enter__(self):return self
                def __exit__(self,*args):self.npz.close()
                def __getitem__(self,key):
                    access.append(key)
                    if key not in ('ego_boxes','ego_scores'):raise AssertionError('Offline array exposed')
                    return self.npz[key]
            with patch.object(full.np,'load',side_effect=PublicOnly):
                x,mask=full.public_features(root/'cache',frames,ref['provenance'],SEQ)
            self.assertEqual(x.shape,(4,400,46));self.assertEqual(mask.shape,(4,4))
            self.assertEqual(set(access),{'ego_boxes','ego_scores'})
            (root/'cache'/SEQ/'poses.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'header changed'):
                full.public_features(root/'cache',frames,ref['provenance'],SEQ)

    def test_bad_development_hash_fails_before_any_full_reference_read(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);v,_,r,rs,_,_=fixture(root)
            with patch.object(full,'load_full_reference') as held:
                with self.assertRaisesRegex(ValueError,'SHA256 differs'):
                    full.run(v,'wrong',r,rs,root/'cache',root/'out')
                held.assert_not_called()

    def test_full_reference_guards_inventory_payload_order_and_previous_ap(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);v,vs,r,rs,_,ref=fixture(root)
            cfg,_,_,_=full.load_deployment(v,vs)
            full.load_full_reference(r,rs,cfg['protocol']['detector'])
            with zipfile.ZipFile(r) as z:members={n:z.read(n) for n in z.namelist() if n!='files.json'}
            broken=copy.deepcopy(ref);broken['policies']['all']['global_confidence_sort']['classes']['Vehicle']['ap']['0.5']=.01
            members['report.json']=json.dumps(broken).encode()
            rs=archive(r,members)
            with self.assertRaisesRegex(ValueError,'AP parity failure'):
                full.load_full_reference(r,rs,cfg['protocol']['detector'])


if __name__=='__main__':unittest.main()
