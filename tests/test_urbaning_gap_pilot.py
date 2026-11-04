import copy
import unittest
from unittest.mock import patch

import numpy as np

from phdsim.experiments.urbaning_gap_pilot import benefit_metrics,gap_metrics,top_indices
from phdsim.experiments.urbaning_gap_review import joint_metrics
from phdsim.learning.urbaning_gap_forests import fit_forest,predict_forest,predict,PROFILES

try:
    import sklearn
except ImportError:
    sklearn=None


class GapRankingTests(unittest.TestCase):
    def test_two_stage_uses_gap_ranking_and_requires_real_recovery(self):
        gap=np.zeros((1,400));gap[0,:10]=1
        gain=np.zeros((1,400,3));gain[0,:,1]=1;gain[0,10:,2]=100
        available=np.ones((1,4),bool)
        recovered=np.zeros_like(gain);truth=np.zeros_like(gain)
        recovered[0,:5,1]=1;truth[0,:5,1]=1
        # False-alarm cleanup without any recovery is not a joint success.
        truth[0,5:10,1]=2
        r=joint_metrics(gap,gain,recovered,truth,available)
        self.assertEqual(r['successes'],5);self.assertEqual(r['proposals'],10)
        self.assertEqual(r['proposed_subset_histogram'],{'infrastructure':10})
        self.assertAlmostEqual(r['pure_random_expected_fraction'],5/1200)
        self.assertAlmostEqual(r['same_gap_regions_random_partner_expected_fraction'],5/30)
        truth[0,:5,1]=-1
        self.assertEqual(joint_metrics(gap,gain,recovered,truth,available)['successes'],0)

    def test_top_k_and_exact_random_expectations(self):
        score=np.tile(np.arange(400,dtype=float),(2,1));fn=np.zeros((2,400),int);fn[:,-10:]=1
        empty=np.ones((2,400),bool)
        r=gap_metrics(score/400,fn,empty)
        self.assertEqual(r['all_cells']['precision_at_k'],1.)
        self.assertEqual(r['all_cells']['mean_recall_at_k_on_positive_frames'],1.)
        self.assertEqual(r['all_cells']['random_precision_expected'],.025)
        np.testing.assert_array_equal(top_indices(np.ones(400),10),np.arange(10))
        r=gap_metrics(score/400,np.zeros_like(fn),empty)
        self.assertIsNone(r['all_cells']['mean_recall_at_k_on_positive_frames'])
        self.assertEqual(r['all_cells']['precision_at_k'],0.)

    def test_source_ranking_masks_unavailable_and_counts_harm(self):
        mask=np.array([[1,1,0,0]],bool)
        pred=np.full((1,400,3),np.nan);pred[0,:,0]=np.arange(400)
        truth=np.zeros_like(pred);truth[:,:,1:]=1e9
        truth[0,-10:,0]=1
        r=benefit_metrics(pred,truth,mask)
        self.assertEqual(r['positive_benefit_precision_at_k'],1.)
        self.assertEqual(r['pure_random_expected_precision'],.025)
        bad=pred.copy();bad[:,:,1:]=0
        with self.assertRaises(ValueError):benefit_metrics(bad,truth,mask)
        truth[0,-10:,0]=-1
        r=benefit_metrics(pred,truth,mask)
        self.assertEqual(r['positive_benefit_precision_at_k'],0.)
        self.assertEqual(r['mean_selected_local_error_reduction'],-1.)

    @unittest.skipIf(sklearn is None,'Optional isolated sklearn runtime')
    def test_portable_forest_and_deployment_boundary(self):
        rng=np.random.default_rng(42);x=rng.normal(size=(4,400,46)).astype(np.float32)
        mask=np.array([[1,1,1,1],[1,1,1,1],[1,1,0,0],[1,0,1,0]],bool)
        x[:,:,30]=mask[:,1,None];x[:,:,38]=mask[:,2,None]
        params={'n_estimators':4,'max_depth':4,'min_samples_leaf':5,'max_features':1.,'bootstrap':False,'random_state':42}
        flat=x.reshape(-1,46)
        gap=fit_forest(flat,(flat[:,5]>0).astype(int),'combined',classification=True,parameters=params,n_jobs=1)
        benefit=fit_forest(flat,flat[:,5]*flat[:,33],'combined',classification=False,parameters=params,n_jobs=1)
        model={'gap':gap,'benefit':dict.fromkeys(('vehicle_peer','infrastructure','all'),benefit)}
        before=copy.deepcopy(model)
        with patch.dict('sys.modules',{'sklearn':None,'torch':None,'opencood':None}):p,g=predict(model,x,mask)
        self.assertEqual(p.shape,(4,400));self.assertEqual(g.shape,(4,400,3))
        self.assertTrue(np.isnan(g[2,:,1:]).all());self.assertTrue(np.isnan(g[3,:,0]).all())
        self.assertEqual(model,before)
        with self.assertRaises(TypeError):predict(model,x,mask,gt_boxes=[])
        broken=copy.deepcopy(gap);broken['features'].reverse()
        with self.assertRaises(ValueError):predict_forest(broken,flat)
        broken=copy.deepcopy(gap);broken['trees'][0]['left'][0]=0
        with self.assertRaises(ValueError):predict_forest(broken,flat)
        wrong=x.copy();wrong[:,:,38]=1
        with self.assertRaises(ValueError):predict(model,wrong,mask)
        self.assertFalse(set(PROFILES['local'])&set(PROFILES['geometry']))


if __name__=='__main__':unittest.main()
