import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from types import ModuleType
import sys
import hashlib
import json
import zipfile

import numpy as np
import torch
from torch import nn

from phdsim.perception.urbaning.cobevt_rgb_adapter import (
    ResidualBEVAdapter, capture_fused_bev, metric_grid,
)
from phdsim.experiments.urbaning_cobevt_rgb_preflight import draw_projection
from phdsim.experiments.urbaning_cobevt_rgb_preflight import run


class ExampleDetector(nn.Module):
    def __init__(self):
        super().__init__()
        self.fusion_net = nn.Conv2d(4,4,1)
        self.cls_head = nn.Conv2d(4,8,1)
        self.reg_head = nn.Conv2d(4,14,1)

    def forward(self, x):
        feature = self.fusion_net(x)
        return {'psm':self.cls_head(feature),'rm':self.reg_head(feature)}


class AdapterTests(unittest.TestCase):
    def test_zero_start_retains_lidar_and_can_learn(self):
        torch.manual_seed(1)
        adapter = ResidualBEVAdapter(3,4,8)
        lidar, rgb = torch.randn(1,4,8,10), torch.randn(1,3,8,10)
        self.assertTrue(torch.equal(adapter(lidar,rgb),lidar))
        self.assertTrue(torch.equal(adapter(lidar,rgb*100),lidar))
        optimizer = torch.optim.SGD(adapter.parameters(),lr=.1)
        frozen = lidar.clone()
        target = lidar + 1
        before = float((adapter(lidar,rgb)-target).square().mean().detach())
        for _ in range(5):
            optimizer.zero_grad(); loss=(adapter(lidar,rgb)-target).square().mean()
            loss.backward(); optimizer.step()
        self.assertLess(float((adapter(lidar,rgb)-target).square().mean().detach()),before)
        self.assertTrue(torch.equal(lidar,frozen))

    def test_wrong_grid_and_nonfinite_fail(self):
        a = ResidualBEVAdapter(3,4,8)
        with self.assertRaises(ValueError):a(torch.zeros(1,4,8,10),torch.zeros(1,3,10,8))
        with self.assertRaises(ValueError):a(torch.zeros(1,4,8,10),torch.full((1,3,8,10),float('nan')))

    def test_original_forward_head_parity_and_hook_cleanup(self):
        m = ExampleDetector().eval().requires_grad_(False)
        original = {k:v.clone() for k,v in m.state_dict().items()}
        feature, outputs, errors = capture_fused_bev(m,torch.randn(1,4,8,10))
        self.assertEqual(feature.shape,(1,4,8,10))
        self.assertEqual(errors,{'psm':0.,'rm':0.})
        self.assertEqual(len(m.fusion_net._forward_hooks),0)
        self.assertTrue(all(torch.equal(original[k],v) for k,v in m.state_dict().items()))
        m.train()
        with self.assertRaises(ValueError):capture_fused_bev(m,torch.randn(1,4,8,10))

    def test_rectangular_metric_grid_axes(self):
        grid = metric_grid((100,256),[-102.4,-40,-5,102.4,40,5])
        self.assertEqual(grid.shape,(100,256,2))
        np.testing.assert_allclose(grid[0,0],[-102.,-39.6])
        np.testing.assert_allclose(grid[-1,-1],[102.,39.6])
        self.assertGreater(grid[0,1,0],grid[0,0,0])
        self.assertGreater(grid[1,0,1],grid[0,0,1])

    def test_native_projection_qa_uses_six_bound_images(self):
        import cv2
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); yaml=root/'000001.yaml';yaml.write_text('fixture')
            for i in range(6):cv2.imwrite(str(root/f'000001_camera{i}.png'),np.zeros((80,120,3),np.uint8))
            e=np.eye(4); k=np.array([[50,0,60],[0,50,40],[0,0,1.]])
            record={'yaml':str(yaml),'gt_boxes':np.empty((0,8,3))}
            points=np.array([[0,0,10],[100,0,10],[0,0,-10]])
            with patch('phdsim.experiments.urbaning_cobevt_rgb_preflight.camera_fields',return_value=[(e,k)]*6):
                info=draw_projection(record,points,root/'qa.jpg')
            self.assertEqual([x['sampled_points_in_image'] for x in info],[1]*6)
            self.assertEqual(cv2.imread(str(root/'qa.jpg')).shape,(1110,1280,3))

    def test_preflight_exports_train_only_features_and_qa_with_original_heads(self):
        """Complete fixture export, not a native-data correctness claim."""
        import cv2
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); records=[]; by_sequence={}
            for sequence in ['20241126_0001_crossing2_00','20241126_0017_crossing1_00']:
                by_sequence[sequence]=[]
                for i in range(4):
                    stamp=f'{i+1:06d}';folder=root/'converted'/sequence/'100000';folder.mkdir(parents=True,exist_ok=True)
                    yaml=folder/(stamp+'.yaml');yaml.write_text('fixture')
                    cloud=folder/(stamp+'.pcd')
                    cloud.write_text('VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 3\nHEIGHT 1\nPOINTS 3\nDATA ascii\n0 0 10\n100 0 10\n0 0 -10\n')
                    for c in range(6):cv2.imwrite(str(folder/(stamp+f'_camera{c}.png')),np.zeros((80,120,3),np.uint8))
                    record={'key':sequence+':'+stamp+':100000','sequence':sequence,'yaml':str(yaml),
                            'lidar_source':{'path':str(cloud),'sha256':hashlib.sha256(cloud.read_bytes()).hexdigest()},
                            'native_association':{'fixture':True},'gt_boxes':np.empty((0,8,3))}
                    records.append(record);by_sequence[sequence].append(record)
            class Dataset:
                def __init__(self,sequence):self.records=by_sequence[sequence]
                def __len__(self):return len(self.records)
                def retrieve_by_idx(self,index):
                    r=self.records[index];stamp=r['key'].split(':')[1]
                    return {'100000':{stamp:{'yaml':r['yaml'],'lidar':r['lidar_source']['path']}}},stamp
                def return_timestamp_key(self,scene,offset):return offset
                def collate_batch_test(self,items):return {'ego':items[0]}
            modules={name:ModuleType(name) for name in ['opencood','opencood.data_utils','opencood.data_utils.datasets','opencood.tools','opencood.tools.train_utils']}
            modules['opencood.data_utils.datasets'].build_dataset=lambda config,**kw:Dataset(kw['specific_scenario'])
            modules['opencood.tools.train_utils'].to_device=lambda value,device:value
            model=ExampleDetector().eval().requires_grad_(False)
            config={'model':{'args':{'lidar_range':[-10,-8,-2,10,8,2]}},'train_params':{}}
            e=np.eye(4); k=np.array([[50,0,60],[0,50,40],[0,0,1.]])
            prefix='phdsim.experiments.urbaning_cobevt_rgb_preflight.'
            with patch.dict(sys.modules,modules), patch(prefix+'prepare_upstream',return_value='pinned'), \
                 patch(prefix+'load_model',return_value=(model,config)), \
                 patch(prefix+'read_inputs',return_value=({'train':records,'validation':[]},{})), \
                 patch(prefix+'add_point_bindings'), patch(prefix+'verify_bundle',return_value={'verified':True}), \
                 patch(prefix+'capture_sources',return_value=(torch.zeros(1,4,8,10),{'included_ids':['100000']})), \
                 patch(prefix+'subset_inputs',side_effect=lambda value,indices:value), \
                 patch(prefix+'camera_fields',return_value=[(e,k)]*6):
                run(root,root,root,root/'output',2)
            report=json.loads((root/'output/report.json').read_text())
            self.assertEqual(len(report['frames']),8)
            self.assertTrue(all(r['head_max_absolute_error']=={'psm':0.,'rm':0.} for r in report['frames']))
            self.assertEqual(len(list((root/'output/features').glob('*.npz'))),8)
            with zipfile.ZipFile(root/'output/urbaning-cobevt-rgb-preflight.zip') as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len(z.namelist()),11)


if __name__=='__main__':unittest.main()
