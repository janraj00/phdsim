import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from phdsim.experiments.urbaning_gap_hybrid import PAIRS,MODE,replay_pair,select,load_reference
from phdsim.experiments.urbaning_regional_learning import sha


class HybridTests(unittest.TestCase):
    def test_local_gap_changes_cells_while_geometry_benefit_stays_fixed(self):
        frame={'source_ids':['100000','200000','-1']}
        geo=np.r_[np.ones(10),np.zeros(390)][None]
        local=np.r_[np.zeros(10),np.ones(10),np.zeros(380)][None]
        benefit=np.zeros((1,400,3));benefit[0,:10,1]=1;benefit[0,10:20,0]=1
        p={'geometry_gap':geo,'local_gap':local,'geometry_benefit':benefit,'local_benefit':-benefit}
        self.assertEqual(replay_pair([frame],p,'geometry','geometry',.5),['infrastructure'])
        self.assertEqual(replay_pair([frame],p,'local','geometry',.5),['vehicle_peer'])
        self.assertEqual(replay_pair([frame],p,'local','local',.5),['ego'])
        with self.assertRaises(TypeError):replay_pair([frame],p,'local','geometry',.5,gt_boxes=[])
        with self.assertRaises(ValueError):replay_pair([],p,'local','geometry',.5)

    def test_caps_select_on_map_then_queries_not_f1_or_unavailable_budget(self):
        candidates=[]
        for gap,benefit in PAIRS:
            for cost,q,ap in ((64.,0,.2),(8.,99,.4),(4.,100,.4),(.5,250,.6)):
                candidates.append({'gap_profile':gap,'benefit_profile':benefit,'error_cost':cost,
                    'metrics':{MODE:{'peer_requests':q,'macro_ap':{'0.5':ap},'mean_frame_f1':1-ap}}})
        result=select(candidates,200)
        self.assertEqual(len(result),12)
        for i in range(0,12,3):
            self.assertEqual([r['metrics'][MODE]['peer_requests'] for r in result[i:i+3]],[99,99,250])

    def test_only_exact_development_reference_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'ref.zip'
            raw=json.dumps({'schema':'phdsim-urbaning-gap-acquisition-validation-v1','status':'completed'}).encode()
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('report.json',raw);z.writestr('files.json',json.dumps({'report.json':sha(raw)}))
            self.assertEqual(load_reference(p,sha(p.read_bytes()))['status'],'completed')
            with self.assertRaisesRegex(ValueError,'ZIP changed'):load_reference(p,'wrong')
            raw=json.dumps({'schema':'phdsim-urbaning-gap-full-v1','status':'completed'}).encode()
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('report.json',raw);z.writestr('files.json',json.dumps({'report.json':sha(raw)}))
            with self.assertRaisesRegex(ValueError,'development validation'):load_reference(p,sha(p.read_bytes()))


if __name__=='__main__':unittest.main()
