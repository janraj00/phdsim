"""Portable AP parity, fixed choices, leakage boundaries and malformed input guards."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER
from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import aggregate_statistics, frame_statistics, summarize_cached
from phdsim.experiments.urbaning_ap_replay import (
    CHOICES_SCHEMA, export, load_archive, load_choices, metrics_both_orders, replay, validate_statistics)
from phdsim.experiments.urbaning_subsets import load_runs
from test_urbaning_subsets import IDS, box, make_run


class APReplayTest(unittest.TestCase):
    def prepare(self, root):
        train=make_run(root/'train','20241126_0017_crossing1_00',2)
        val=make_run(root/'val','20241126_0004_crossing2_00',2)
        # AP depends on confidence ordering; counts/F1 alone cannot recover it.
        for i in range(2):
            path=val/'predictions/{:06d}.npz'.format(i)
            with np.load(path,allow_pickle=False) as d: arrays={k:d[k] for k in d.files}
            arrays['ego_boxes']=np.stack([box(x=0 if i==0 else 50)])
            arrays['ego_scores']=np.array([[.8 if i==0 else .9,1]])
            np.savez_compressed(path,**arrays)
        all_stats={a:[] for a in ACTION_ORDER}
        for i in range(2):
            with np.load(val/'predictions/{:06d}.npz'.format(i),allow_pickle=False) as d:
                for a in ACTION_ORDER:
                    all_stats[a].append(frame_statistics(d[a+'_boxes'],d[a+'_scores'],d['gt_boxes'],d['gt_labels']))
        (val/'metrics.json').write_text(json.dumps({a:summarize_cached(aggregate_statistics(s)) for a,s in all_stats.items()}))
        return train,val

    def test_export_and_common_replay_preserve_both_ap_orders_and_fixed_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);train,val=self.prepare(root)
            bundle=export([train],[val],root/'export')
            data,manifest=load_archive(bundle); frames=data['validation']
            original,_=load_runs([val]);before=copy.deepcopy(frames)
            for action in ACTION_ORDER:
                actual=metrics_both_orders(frames,[action]*2)
                expected=metrics_both_orders(original,[action]*2)
                self.assertEqual(actual,expected)
            self.assertEqual(before,frames)
            ego=manifest['splits']['validation']['baselines']['ego']
            self.assertAlmostEqual(ego['global_confidence_sort']['classes']['Vehicle']['ap']['0.5'],.25)
            self.assertAlmostEqual(ego['upstream_default_frame_order']['classes']['Vehicle']['ap']['0.5'],.5)
            choices={frames[0]['key']:'vehicle_peer',frames[1]['key']:'all'}
            path=root/'frozen.json'
            path.write_text(json.dumps({'schema':CHOICES_SCHEMA,'name':'fixed_example','split':'validation',
                                       'provenance':manifest['splits']['validation']['provenance'],'choices':choices}))
            report=replay(bundle,path,root/'report')
            self.assertEqual(report['policies']['fixed_example']['global_confidence_sort']['peer_requests'],3)
            self.assertEqual(report['policies']['fixed_example']['global_confidence_sort']['request_histogram'],{'0':0,'1':1,'2':1})
            for mode in ('schedule','budget'):
                for order in report['random_controls']['fixed_example'][mode].values():
                    self.assertEqual(len(order['per_seed']),100)
                    self.assertTrue(all(s['peer_requests']==3 for s in order['per_seed'].values()))
            with self.assertRaises(FileExistsError): export([train],[val],root/'export')
            with zipfile.ZipFile(root/'report/urbaning-common-ap-report.zip') as z:self.assertIsNone(z.testzip())
            regional={'schema':'phdsim-urbaning-regional-policy-v1','status':'completed',
                      'detector':manifest['detector'],'validation_provenance':[manifest['splits']['validation']['provenance']],
                      'choices':choices,'policies':{'regional':report['policies']['fixed_example']['global_confidence_sort']}}
            with zipfile.ZipFile(root/'regional.zip','w') as z:z.writestr('regional-policy-report.json',json.dumps(regional))
            label,decoded,_=load_choices(root/'regional.zip',manifest,frames,'validation')
            self.assertEqual(label,'regional_linear_sum_audited_prototype')
            self.assertEqual(decoded,list(choices.values()))
            prior_row={'global_confidence_sort':report['policies']['fixed_example']['global_confidence_sort'],
                       'upstream_default_order':report['policies']['fixed_example']['upstream_default_frame_order'],
                       'choices':choices}
            prior={'schema':'phdsim-urbaning-tree-pilot-v1','status':'completed',
                   'provenance':{'validation':manifest['splits']['validation']['provenance']},
                   'validation_policies':{'ridge':prior_row,'tree':prior_row}}
            with zipfile.ZipFile(root/'prior.zip','w') as z:z.writestr('validation-report.json',json.dumps(prior))
            combined=replay(bundle,root/'regional.zip',root/'combined',prior_pilot=root/'prior.zip')
            self.assertIn('previous_ridge',combined['policies'])
            self.assertEqual(set(combined['random_controls']),{'regional_linear_sum_audited_prototype','previous_ridge','previous_tree'})

    def test_statistics_reject_impossible_counts_mismatched_gt_and_unavailable_actions(self):
        stats=frame_statistics(np.stack([box()]),np.array([[.8,1]]),np.stack([box()]),np.array([1]))
        raw=json.loads(json.dumps({'ego':stats,'vehicle_peer':stats}))
        validate_statistics(raw,{'ego':(0,),'vehicle_peer':(0,1)})
        bad=copy.deepcopy(raw);bad['vehicle_peer']['Vehicle']['0.5']['fp']=[1]
        with self.assertRaises(ValueError):validate_statistics(bad,{'ego':(0,),'vehicle_peer':(0,1)})
        bad=copy.deepcopy(raw)
        for row in bad['vehicle_peer']['Vehicle'].values():row['gt']=2
        with self.assertRaises(ValueError):validate_statistics(bad,{'ego':(0,),'vehicle_peer':(0,1)})
        with self.assertRaises(ValueError):validate_statistics(raw,{'ego':(0,)})

    def test_recording_overlap_or_crossing3_rejected_before_cache_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            train=make_run(root/'train','20241126_0017_crossing1_00',2)
            for n,seq in enumerate(('20241126_0017_crossing1_01','20241127_0009_crossing3_00')):
                val=make_run(root/('val'+str(n)),seq,2)
                with patch('phdsim.experiments.urbaning_ap_replay.load_runs') as loader:
                    with self.assertRaises(ValueError):export([train],[val],root/('out'+str(n)))
                    loader.assert_not_called()

    def test_choices_and_statistics_hashes_are_bound_to_exact_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);train,val=self.prepare(root)
            bundle=export([train],[val],root/'export')
            data,manifest=load_archive(bundle);frames=data['validation']
            row={'schema':CHOICES_SCHEMA,'name':'frozen','split':'validation',
                 'provenance':copy.deepcopy(manifest['splits']['validation']['provenance']),
                 'choices':{f['key']:'all' for f in frames}}
            path=root/'choices.json'
            row['provenance']['inputs'][0]['trace_sha256']='changed'
            path.write_text(json.dumps(row))
            with self.assertRaises(ValueError):load_choices(path,manifest,frames,'validation')
            with zipfile.ZipFile(bundle) as z: members={n:z.read(n) for n in z.namelist()}
            members['offline-statistics-validation.jsonl']+=b'\n'
            altered=root/'altered.zip'
            with zipfile.ZipFile(altered,'w') as z:
                for n,raw in members.items():z.writestr(n,raw)
            with self.assertRaises(ValueError):load_archive(altered)

    def test_absent_class_map_remains_undefined(self):
        stats=frame_statistics(np.stack([box()]),np.array([[.8,1]]),np.stack([box()]),np.array([1]))
        frame={'source_ids':['100000'],'statistics':{'ego':stats},'quality':{'ego':1.}}
        for row in metrics_both_orders([frame],['ego']).values():
            self.assertIsNone(row['macro_ap']['0.5'])
            self.assertAlmostEqual(row['classes']['Vehicle']['ap']['0.5'],1.)


if __name__=='__main__':unittest.main()
