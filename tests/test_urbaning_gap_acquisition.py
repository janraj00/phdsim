import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import zipfile
import json
import numpy as np
from phdsim.decision.urbaning import available_subsets
from phdsim.decision.urbaning_gap_acquisition import choose
from phdsim.experiments.urbaning_gap_acquisition import fixed_budget_random,ReplayCache
from phdsim.experiments.urbaning_gap_acquisition_job import pack,stage,safe_extract
from phdsim.experiments.urbaning_regional_learning import sha


class GapAcquisitionTests(unittest.TestCase):
    def test_same_gap_cells_one_whole_frame_decision_and_direct_joint_head(self):
        ids=['100000','200000','-1'];gap=np.zeros(400);gap[:10]=1
        gains=np.zeros((400,3));gains[:10,0]=1;gains[:10,2]=1.01
        # Same ten cells and the direct joint score; not sum of singleton gains.
        self.assertEqual(choose(ids,gap,gains,.2),'vehicle_peer')
        gains[:10,2]=2
        self.assertEqual(choose(ids,gap,gains,.2),'all')
        gains[100,1]=1000
        self.assertEqual(choose(ids,gap,gains,.2),'all')
        self.assertEqual(choose(ids,gap,gains,.2,'all_cells'),'infrastructure')
        self.assertEqual(choose(ids,gap,gains,2000),'ego')
        with self.assertRaises(TypeError):choose(ids,gap,gains,.2,gt_boxes=[])

    def test_unavailable_heads_never_enter_decision(self):
        gains=np.full((400,3),np.nan);gains[:,0]=1
        self.assertEqual(choose(['100000','200000'],np.zeros(400),gains,1),'vehicle_peer')
        self.assertEqual(choose(['100000'],np.zeros(400),gains,0),'ego')
        with self.assertRaises(ValueError):choose(['100000','200000'],np.zeros(400),gains,-1)

    def test_fixed_total_random_has_full_support_without_policy_schedule(self):
        frames=[{'key':f'seq:{i}:100000','source_ids':['100000','200000','-1']} for i in range(4)]
        frames+=[{'key':'seq:4:100000','source_ids':['100000','-1']},{'key':'seq:5:100000','source_ids':['100000']}]
        support=set()
        for seed in range(100):
            choices=fixed_budget_random(frames,4,seed)
            self.assertEqual(sum(len(available_subsets(f['source_ids'])[a])-1 for f,a in zip(frames,choices)),4)
            self.assertEqual(choices[-1],'ego');support.update(choices[:4])
        self.assertEqual(support,{'ego','vehicle_peer','infrastructure','all'})
        self.assertEqual(fixed_budget_random(frames,0,1),['ego']*6)
        with self.assertRaises(ValueError):fixed_budget_random(frames,10,1)

    def test_checkpoints_reuse_only_identical_protocol_and_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            metric={'global_confidence_sort':{'ap':.3}}
            cache=ReplayCache(temp,{'inputs':'a','code':'b'})
            with patch('phdsim.experiments.urbaning_gap_acquisition.metrics_both_orders',return_value=metric) as evaluator:
                self.assertEqual(cache.evaluate([],['ego']),metric)
                self.assertEqual(cache.evaluate([],['ego']),metric)
                self.assertEqual(evaluator.call_count,1)
                cache.evaluate([],['all'])
                ReplayCache(temp,{'inputs':'changed','code':'b'}).evaluate([],['ego'])
                self.assertEqual(evaluator.call_count,3)
            for path in Path(temp).glob('*.json'):
                data=json.loads(path.read_text());data['metrics']={'tampered':True};path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'metrics changed'):cache.evaluate([],['ego'])

    def test_portable_package_verified_staging_and_resumption(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            sources=[]
            for i in range(3):
                path=temp/f'{i}.zip'
                with zipfile.ZipFile(path,'w') as z:z.writestr('example.json','{}')
                sources.append(path)
            bundle=temp/'inputs.zip';pack(*sources,bundle)
            checksum=sha(bundle.read_bytes());out=temp/'staged'
            self.assertEqual(stage(bundle,checksum,out),out)
            self.assertTrue((out/'pilot/example.json').is_file())
            self.assertEqual(stage(bundle,checksum,out),out)
            with self.assertRaisesRegex(ValueError,'SHA256 differs'):stage(bundle,'wrong',out)
            (out/'ap-export.zip').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'archive changed'):stage(bundle,checksum,out)
            unsafe=temp/'unsafe.zip'
            with zipfile.ZipFile(unsafe,'w') as z:z.writestr('../outside','x')
            with self.assertRaisesRegex(ValueError,'Unsafe ZIP'):safe_extract(unsafe,temp/'extract')


if __name__=='__main__':unittest.main()
