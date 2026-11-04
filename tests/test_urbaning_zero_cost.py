import tempfile
import unittest
from pathlib import Path

from test_urbaning_subsets import make_run
from phdsim.decision.urbaning import available_subsets
from phdsim.experiments.urbaning_subsets import load_runs
from phdsim.experiments.urbaning_gap_acquisition import ReplayCache
from phdsim.experiments.urbaning_zero_cost import infra_priority_random,scopes,measure,class_summary,MODE


class ZeroCostTests(unittest.TestCase):
    def test_strong_control_has_exact_total_available_fallback_and_random_extras(self):
        frames=[{'source_ids':['100000','200000','-3']} for _ in range(6)]
        frames += [{'source_ids':['100000','200000']},{'source_ids':['100000','-3']},{'source_ids':['100000']}]
        schedules=set()
        for seed in range(100):
            actions=infra_priority_random(frames,11,seed)
            self.assertEqual(sum(len(available_subsets(f['source_ids'])[a])-1 for f,a in zip(frames,actions)),11)
            self.assertEqual(actions[6:],['vehicle_peer','infrastructure','ego'])
            self.assertEqual(set(actions[:6]),{'all','infrastructure'})
            schedules.add(tuple(actions))
        self.assertGreater(len(schedules),10)
        with self.assertRaises(ValueError):infra_priority_random(frames,7,0)
        with self.assertRaises(ValueError):infra_priority_random(frames,15,0)

    def test_sibling_sequences_form_one_recording_group(self):
        seqs=['20241127_0010_crossing3_08','20241127_0010_crossing3_09','20241127_0012_crossing3_00']
        frames=[{'sequence':s} for s in seqs]
        group=scopes(frames)
        self.assertEqual(group['recording/20241127_0010'],[0,1])
        self.assertEqual(group['recording/20241127_0012'],[2])
        self.assertEqual(sum(n.startswith('sequence/') for n in group),3)

    def test_scoped_measurement_matches_direct_ap_without_cross_scope_cache_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a=make_run(root/'a','20241127_0010_crossing3_08')
            b=make_run(root/'b','20241127_0010_crossing3_09')
            frames,_=load_runs([a,b]);groups=scopes(frames)
            cache=root/'cache';cache.mkdir()
            caches={n:ReplayCache(cache/n.replace('/','_'),{'scope':n,'keys':[frames[i]['key'] for i in ix]}) for n,ix in groups.items()}
            actions=['ego']*4+['all']*4
            result=measure(frames,actions,groups,caches)
            self.assertAlmostEqual(result['sequence/20241127_0010_crossing3_08'][MODE]['macro_ap']['0.5'],.25)
            self.assertAlmostEqual(result['sequence/20241127_0010_crossing3_09'][MODE]['macro_ap']['0.5'],1.)
            self.assertEqual(result['recording/20241127_0010'][MODE]['frames'],8)
            self.assertEqual(measure(frames,actions,groups,caches),result)
            summary=class_summary([result['full'][MODE],result['full'][MODE]])
            self.assertEqual(summary['Vehicle']['0.5']['std'],0.)


if __name__=='__main__':unittest.main()
