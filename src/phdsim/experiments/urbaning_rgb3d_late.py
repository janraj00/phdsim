"""Eight TRAIN frames: independent RGB 3D detections and fixed late fusion.

An engineering pilot, not a modality ranking, validation gain or new training.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from phdsim.experiments.urbaning_rgb_pilot import read_inputs, camera_fields, sha, write_json
from phdsim.perception.urbaning.rgb3d_late import (
    CubeDetector, CLASS_MAP, ASSETS, upright_boxes, classwise_nms, late_fuse)
from phdsim.evaluation.urbaning_cached import (
    frame_statistics, aggregate_statistics, summarize_cached)

SCHEMA = 'phdsim-urbaning-rgb3d-late-train8-v1'
EDGES = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
         (0,4),(1,5),(2,6),(3,7)]


def draw_camera(image, corners, scores, intrinsic, gt, extrinsic, path):
    """Offline display only; annotations never enter detector/fusion calls."""
    import cv2
    h, w = image.shape[:2]
    scale = min(960/w, 540/h)
    out = cv2.resize(image, (round(w*scale), round(h*scale)))
    def draw(box, color):
        if np.any(box[:,2] <= .1): return
        uvw = box @ intrinsic.T
        uv = uvw[:,:2]/uvw[:,2:3]*scale
        if not np.isfinite(uv).all() or np.abs(uv).max() > 1e6: return
        uv = np.rint(uv).astype(int)
        for a,b in EDGES: cv2.line(out, tuple(uv[a]), tuple(uv[b]), color, 1)
    # Native Cube R-CNN vertices have a different edge order from OpenCOOD.
    # Reorder only for display; retain the original camera-space payload.
    for box, score in zip(corners, scores):
        if score >= .25: draw(box[[0,1,5,4,3,2,6,7]], (255,220,30))
    for box in gt:
        draw(box @ extrinsic[:3,:3].T + extrinsic[:3,3], (40,210,40))
    cv2.putText(out, 'cyan: RGB predicted 3D, score>=.25; green: offline GT',
                (8,20), cv2.FONT_HERSHEY_SIMPLEX, .45, (255,255,255), 1)
    if not cv2.imwrite(str(path), out): raise OSError('Cannot save camera QA')


def draw_bev(variants, truth, key, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    fig,axes=plt.subplots(1,3,figsize=(15,6),layout='constrained')
    for ax,(name,color) in zip(axes,[('original_lidar','tab:orange'),('rgb','tab:cyan'),
                                     ('lidar_rgb_late','tab:purple')]):
        for b in truth:ax.add_patch(Polygon(b[:4,:2],fill=False,edgecolor='green',linewidth=.9))
        boxes,scores=variants[name]
        for b,s in zip(boxes,scores):
            if s[0]>=.25:ax.add_patch(Polygon(b[:4,:2],fill=False,edgecolor=color,linewidth=.8))
        ax.scatter([0],[0],marker='^',color='black',s=45)
        ax.set(xlim=(-105,105),ylim=(-45,45),aspect='equal',title=name,
               xlabel='Car1 x (m), forward',ylabel='Car1 y (m), left')
        ax.grid(alpha=.2)
    fig.suptitle(key+'\nGreen: all offline GT; colored: predictions score>=.25; black: Car1. Display window only.')
    fig.savefig(path,dpi=140);plt.close(fig)


def run(base, model_dir, output, threads):
    import cv2
    if output.exists():
        raise FileExistsError('Preserve the previous pilot; select a fresh output')
    output.mkdir(parents=True)
    (output/'raw').mkdir(); (output/'qa').mkdir(); (output/'frames').mkdir()
    records, provenance = read_inputs(base, output, 4, 0)
    train = records['train']
    if len(train) != 8 or records['validation'] or any('crossing3' in r['sequence'] for r in train):
        raise ValueError('Exactly eight TRAIN frames and no validation/crossing3 required')
    protocol = {'schema': SCHEMA, 'purpose': __doc__, 'frames': provenance,
                'model': ASSETS, 'class_map': CLASS_MAP, 'cpu_threads': threads,
                'bev_nms_iou': .2, 'raw_rgb_score_threshold': 'official ROI_HEADS config, .01',
                'training': False, 'peer_requests': 0,
                'geometry': 'native camera 3D center/dimensions; length-axis yaw upright approximation',
                'inference_inputs': ['RGB image', 'camera intrinsics'],
                'fusion_inputs': ['independent detection boxes', 'scores', 'classes'],
                'source_code': {str(p.relative_to(Path(__file__).parents[3])):sha(p.read_bytes())
                                for p in [Path(__file__), Path(__file__).parents[1]/'perception/urbaning/rgb3d_late.py']}}
    write_json(output/'protocol.json', protocol)
    detector = CubeDetector(model_dir, threads)
    names = ('original_lidar', 'lidar_nms_control', 'rgb', 'lidar_rgb_late')
    statistics = {k: [] for k in names}; rows = []; counts = Counter()
    started = time.monotonic()
    for index, record in enumerate(train):
        key = record['key']; name = key.replace(':','_')
        rgb_boxes = []; rgb_scores = []; cameras = []
        for i, (e,k) in enumerate(camera_fields(record['yaml'])):
            path = Path(record['yaml']).with_name(Path(record['yaml']).stem + f'_camera{i}.png')
            raw = path.read_bytes()
            image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None: raise ValueError('Unreadable camera image')
            tick = time.monotonic()
            # No GT, LiDAR values/proposals, scores or partner predictions here.
            result = detector.predict(image, k)
            raw_path = output/'raw'/f'{name}_camera{i}.npz'
            np.savez_compressed(raw_path, **result)
            categories = [detector.categories[int(v)] for v in result['classes']]
            counts.update(categories)
            selected = np.array([j for j,c in enumerate(categories) if c in CLASS_MAP], dtype=int)
            boxes = upright_boxes(result['centers'][selected], result['dimensions'][selected],
                                   result['rotations'][selected], e)
            scores = np.array([[result['scores'][j], CLASS_MAP[categories[j]]] for j in selected],
                              dtype=float).reshape(-1,2)
            rgb_boxes.append(boxes); rgb_scores.append(scores)
            draw_camera(image, result['corners'][selected], result['scores'][selected], k,
                        record['gt_boxes'], e, output/'qa'/f'{name}_camera{i}.jpg')
            cameras.append({'camera':i, 'path':str(path), 'image_sha256':sha(raw),
                            'optical_from_car1':e.tolist(), 'K':k.tolist(),
                            'native_association':record['native_association'],
                            'prediction_sha256':sha(raw_path.read_bytes()),
                            'detections_all_categories':len(categories), 'detections_mapped':len(selected),
                            'seconds':time.monotonic()-tick})
            print(f'RGB3D {index+1}/8 camera={i} objects={len(selected)} seconds={cameras[-1]["seconds"]:.1f}', flush=True)
        boxes, scores = np.concatenate(rgb_boxes), np.concatenate(rgb_scores)
        keep = classwise_nms(boxes, scores, .2)
        boxes, scores = boxes[keep], scores[keep]
        lb, ls = record['boxes'], record['scores']
        lk = classwise_nms(lb, ls, .2)
        fb, fs, provenance_indices = late_fuse(lb, ls, boxes, scores, .2)
        variants = {'original_lidar':(lb,ls), 'lidar_nms_control':(lb[lk],ls[lk]),
                    'rgb':(boxes,scores), 'lidar_rgb_late':(fb,fs)}
        draw_bev(variants,record['gt_boxes'],key,output/'qa'/f'{name}_bev.png')
        data = {'gt_boxes':record['gt_boxes'], 'gt_labels':record['gt_labels'],
                'fused_union_indices':provenance_indices}
        for v,(b,s) in variants.items():
            data[v+'_boxes'] = b; data[v+'_scores'] = s
            statistics[v].append(frame_statistics(b,s,record['gt_boxes'],record['gt_labels']))
        f = output/'frames'/f'{name}.npz'; np.savez_compressed(f,**data)
        rows.append({'key':key, 'cameras':cameras, 'payload_sha256':sha(f.read_bytes()),
                     'baseline_prediction_sha256':record['prediction_sha256']})
        print(f'DONE FRAME {index+1}/8 RGB={len(boxes)} LiDAR={len(lb)} fused={len(fb)}', flush=True)
    metrics = {v:{'global_confidence_sort':summarize_cached(aggregate_statistics(stats),True),
                  'upstream_default_frame_order':summarize_cached(aggregate_statistics(stats),False)}
               for v,stats in statistics.items()}
    report = {'schema':SCHEMA, 'status':'completed engineering TRAIN8 pilot',
              'frames':rows, 'metrics':metrics, 'rgb_categories_raw':dict(counts),
              'seconds':time.monotonic()-started, 'limitations':[
                  'Eight TRAIN frames, no fitting and no independent test or modality ranking',
                  'External pretrained RGB and LiDAR models have different training data',
                  'All original GT retained; EScooter/OtherVehicle lack exact RGB class counterparts',
                  'Bicycle detections are not silently equated with rider-plus-bicycle Cyclist',
                  'RGB and LiDAR confidences are uncalibrated across models',
                  'BEV uses predicted length-axis yaw; RGB roll/pitch are discarded without GT adjustment',
                  'Native camera association offsets retained offline; no motion compensation or latency claims',
                  'Review raw 3D projection and depth before interpreting any mAP change']}
    write_json(output/'report.json',report)
    archive = output/'urbaning-rgb3d-late-train8.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file() and p != archive and p.name != 'ap-export.zip':
                z.write(p,str(p.relative_to(output)))
    print('TRAIN8 ENGINEERING DIAGNOSTIC; no validation/generalization result', flush=True)
    for v in names:
        m = metrics[v]['global_confidence_sort']['macro_ap']['0.5']
        print(v, None if m is None else 100*m, flush=True)
    print('DONE:', archive,flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cpu-threads',type=int,default=8)
    a=p.parse_args()
    if a.cpu_threads < 1:p.error('Positive thread count required')
    run(a.base.resolve(),a.model_dir.resolve(),a.output.resolve(),a.cpu_threads)
