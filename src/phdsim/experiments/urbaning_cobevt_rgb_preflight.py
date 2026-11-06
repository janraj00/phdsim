"""Native TRAIN-only CoBEVT feature/head parity and RGB projection inspection.

No adapter/detector training, RGB accuracy result, validation tuning or crossing3.
"""
import argparse
import json
import os
from pathlib import Path
import time
import zipfile

import numpy as np
import torch

from phdsim.experiments.urbaning_rgb_pilot import read_inputs, camera_fields, sha, write_json
from phdsim.experiments.urbaning_bev_cpu import add_point_bindings
from phdsim.experiments.urbaning_stage1 import prepare_upstream, load_model, capture_sources
from phdsim.perception.urbaning.bundle import verify_bundle
from phdsim.perception.urbaning.cobevt import subset_inputs
from phdsim.perception.urbaning.bev_cpu import read_pcd
from phdsim.perception.urbaning.cobevt_rgb_adapter import capture_fused_bev, metric_grid


def draw_projection(record, points, output):
    """GT boxes and point projections are offline visual QA only."""
    import cv2
    panels = []; info = []
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    cameras = camera_fields(record['yaml'])
    p = points[::max(1, len(points)//12000)]
    for i, (extrinsic, intrinsic) in enumerate(cameras):
        path = Path(record['yaml']).with_name(Path(record['yaml']).stem + '_camera' + str(i) + '.png')
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None: raise ValueError('Unreadable camera payload')
        h, w = image.shape[:2]; scale = min(640/w, 340/h)
        picture = cv2.resize(image, (round(w*scale), round(h*scale)))
        def project(xyz):
            optical = xyz @ extrinsic[:3,:3].T + extrinsic[:3,3]
            uvw = optical @ intrinsic.T
            return uvw[:,:2] / np.maximum(optical[:,2:3], .01), optical[:,2] > .1
        uv, front = project(p)
        keep = front & (uv[:,0]>=0) & (uv[:,0]<w) & (uv[:,1]>=0) & (uv[:,1]<h)
        for x, y in (uv[keep]*scale).astype(int): cv2.circle(picture, (int(x),int(y)), 1, (0,170,255), -1)
        for box in record['gt_boxes']:
            xy, valid = project(box)
            if valid.all() and np.abs(xy).max() < 100000:
                xy = np.rint(xy*scale).astype(int)
                for a,b in edges: cv2.line(picture, tuple(xy[a]), tuple(xy[b]), (60,230,60), 1)
        panel = np.zeros((370,640,3), dtype=np.uint8)
        panel[28:28+picture.shape[0], :picture.shape[1]] = picture
        cv2.putText(panel, f'camera{i}: orange=LiDAR; green=GT (offline)', (8,18), cv2.FONT_HERSHEY_SIMPLEX, .43, (255,255,255), 1)
        panels.append(panel)
        info.append({'camera':i,'image_sha256':sha(raw),'sampled_points':len(p),
                     'sampled_points_in_image':int(keep.sum())})
    mosaic = np.concatenate([np.concatenate(panels[j:j+2], axis=1) for j in (0,2,4)], axis=0)
    if not cv2.imwrite(str(output), mosaic): raise OSError('Cannot write projection QA')
    return info


def run(base, upstream, model_dir, output, threads):
    if output.exists(): raise FileExistsError('Preserve existing preflight; use a fresh output directory')
    output.mkdir(parents=True)
    torch.set_num_threads(threads); np.random.seed(0); torch.manual_seed(0)
    revision = prepare_upstream(upstream)
    model, config = load_model(model_dir, torch.device('cpu'))
    records, provenance = read_inputs(base, output, 4, 0)
    if len(records['train']) != 8 or records['validation']:
        raise ValueError('Expected exactly eight fixed TRAIN frames')
    add_point_bindings(records, provenance)
    if any('crossing3' in r['sequence'] for r in records['train']):
        raise ValueError('No crossing3 access in this preflight')
    write_json(output/'protocol.json', {'purpose':__doc__, 'upstream':revision,
        'model':verify_bundle(model_dir),'selection':'four uniformly selected TRAIN frames per original recording',
        'training':False,'validation_frames':0,'provenance':provenance})
    from opencood.data_utils.datasets import build_dataset
    from opencood.tools.train_utils import to_device
    groups = {}
    for r in records['train']: groups.setdefault(r['sequence'], []).append(r)
    rows = []; started = time.monotonic()
    (output/'features').mkdir(); (output/'qa').mkdir()
    for sequence, chosen in sorted(groups.items()):
        # Use the same converted root and upstream test collator as original inference.
        data_root = Path(chosen[0]['yaml']).parents[2]
        effective = dict(config); effective['validate_dir'] = str(data_root)
        effective['train_params'] = {**config['train_params'], 'specific_ego_id':100000}
        dataset = build_dataset(effective, visualize=False, train=False, specific_scenario=sequence)
        indices = {}
        for index in range(len(dataset)):
            scene, offset = dataset.retrieve_by_idx(index)
            timestamp = dataset.return_timestamp_key(scene, offset)
            indices[sequence+':'+timestamp+':100000'] = index
        for record in chosen:
            key = record['key']; name = key.replace(':','_')
            tick = time.monotonic()
            scene, offset = dataset.retrieve_by_idx(indices[key])
            timestamp = dataset.return_timestamp_key(scene, offset)
            files = scene[next(k for k in scene if str(k) == '100000')][timestamp]
            if (Path(files['yaml']).resolve() != Path(record['yaml']).resolve()
                    or Path(files['lidar']).resolve() != Path(record['lidar_source']['path']).resolve()):
                raise ValueError('Dataset retrieval differs from verified original payload binding')
            item, sources = capture_sources(dataset, indices[key])
            if str(sources['included_ids'][0]) != '100000': raise ValueError('Car1 must be first')
            batch = to_device(dataset.collate_batch_test([item]), torch.device('cpu'))
            inputs = subset_inputs(batch['ego'], (0,))
            feature, outputs, errors = capture_fused_bev(model, inputs)
            h,w = feature.shape[-2:]
            coordinates = metric_grid((h,w), config['model']['args']['lidar_range'])
            target = output/'features'/(name+'.npz')
            np.savez_compressed(target, bev=feature.numpy(), xy=coordinates,
                                psm=outputs['psm'].numpy(), rm=outputs['rm'].numpy())
            point = record['lidar_source']; points = read_pcd(point['path'], point['sha256'])
            cameras = draw_projection(record, points, output/'qa'/(name+'.jpg'))
            rows.append({'key':key,'bev_shape':list(feature.shape),'head_max_absolute_error':errors,
                         'cache_sha256':sha(target.read_bytes()),'cameras':cameras,
                         'native_association':record['native_association'],
                         'seconds':time.monotonic()-tick})
            print(f'PREFLIGHT {len(rows)}/8 {key} BEV={tuple(feature.shape)} head_error={errors}', flush=True)
    report = {'status':'completed', 'stage':'engineering preflight, NOT RGB training or accuracy evaluation',
              'frames':rows,'seconds':time.monotonic()-started,
              'feature_boundary':'final Car1-only CoBEVT fused BEV, before original cls/reg heads',
              'limitations':['Native calibration needs visual review of QA images',
                             'RGB BEV encoder and adapter training are not implemented by this job',
                             'No accuracy gain, RGB-only result, multi-agent result or timing guarantee',
                             'Uniform sampling/voxel shuffle differs from historical full-run order'],
              'next':'review projections, then build aligned RGB encoder and fixed detector-loss training protocol'}
    write_json(output/'report.json', report)
    write_json(output/'NEXT.json', {'retain_original_lidar':True,'initial_rgb_residual':0,
                                   'train_only_adapter_first':True,'rgb_only_requires_separate_training':True})
    archive = output/'urbaning-cobevt-rgb-preflight.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('protocol.json','report.json','NEXT.json'): z.write(output/name,name)
        for p in sorted((output/'qa').glob('*.jpg')): z.write(p,'qa/'+p.name)
    print('DONE:', archive, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True); p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cpu-threads',type=int,default=8)
    a = p.parse_args()
    if a.cpu_threads < 1: p.error('Positive CPU thread count required')
    run(a.base.resolve(),a.upstream.resolve(),a.model_dir.resolve(),a.output.resolve(),a.cpu_threads)


if __name__ == '__main__': main()
