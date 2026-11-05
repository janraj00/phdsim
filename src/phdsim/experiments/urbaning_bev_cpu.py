"""Train a proposal-independent RGB/LiDAR BEV prototype on CPU.

All three variants use the same small head and training schedule. This is an
engineering prototype, not a reproduction of pretrained BEVFusion/Simple-BEV.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile

import numpy as np
import torch

from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import frame_statistics, aggregate_statistics, summarize_cached
from phdsim.experiments.urbaning_rgb_pilot import (Encoder, camera_fields, read_inputs,
                                                  select_frames, sha, write_json)
from phdsim.perception.urbaning.bev_cpu import (GRID, MODES, Detector, fit_priors, voxel_points,
    lift_features, point_grid, read_pcd, input_tensor, targets, loss, decode)

SCHEMA = 'phdsim-urbaning-bev-cpu-v1'


def implementation():
    from phdsim.perception.urbaning import bev_cpu
    return {p.name: sha(p.read_bytes()) for p in (Path(__file__), Path(bev_cpu.__file__),
            Path(__file__).with_name('urbaning_rgb_pilot.py'))}


def add_point_bindings(records, provenance):
    bindings = {}
    for source in provenance['train']['source_runs']+provenance['validation']['source_runs']:
        path = Path(source['directory'])/'frames.jsonl'
        if sha(path.read_bytes()) != source['trace_sha256']:
            raise ValueError('Run trace changed')
        for row in map(json.loads, path.read_text().splitlines()):
            bindings[row['frame_key']] = row['source_files']['100000']['lidar']
    for values in records.values():
        for record in values:
            record['lidar_source'] = bindings[record['key']]
            source = record['lidar_source']
            if sha(Path(source['path']).read_bytes()) != source['sha256']:
                raise ValueError('Original Car1 point cloud changed')


class MapEncoder:
    def __init__(self, weights_dir, threads):
        self.base = Encoder(weights_dir, threads)
        self.identity = {**self.base.identity,
            'encoder': 'frozen MobileNetV3-small spatial maps, fixed seeded channel projection16',
            'input': 'RGB resized384x640, ImageNet mean/std',
            'projection': 'NumPy PCG64 seed0 normal576x16 /sqrt576; no label fit'}
        projection = np.random.default_rng(0).normal(size=(576, GRID['rgb_channels']))/np.sqrt(576)
        self.projection = torch.tensor(projection, dtype=torch.float32)

    def __call__(self, images):
        import cv2
        h, w = GRID['image_hw']
        batch = np.stack([cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (w,h)).transpose(2,0,1)
                          for image in images]).astype(np.float32)/255
        batch -= np.array([.485,.456,.406], dtype=np.float32)[None,:,None,None]
        batch /= np.array([.229,.224,.225], dtype=np.float32)[None,:,None,None]
        with torch.inference_mode():
            features = self.base.model.features(torch.from_numpy(batch))
            return torch.einsum('bchw,cd->bdhw', features, self.projection).contiguous()


def extract(record, directory, encoder, priors, grid):
    """Only Car1 images, calibration and Car1 points; no GT/proposals here."""
    import cv2
    p = Path(record['yaml'])
    paths = [p.with_name(p.stem+'_camera'+str(i)+'.png') for i in range(6)]
    raw = [q.read_bytes() for q in paths]
    point = record['lidar_source']
    points = read_pcd(point['path'], point['sha256'])
    identity = {'schema':SCHEMA, 'key':record['key'], 'code':implementation(), 'grid':grid,
                'ground_z_train_prior':priors['ground_z'], 'encoder':encoder.identity,
                'yaml_sha256':sha(p.read_bytes()),
                'images':{str(q):sha(b) for q,b in zip(paths,raw)}, 'car1_lidar':point}
    name = record['key'].replace(':','_')
    target, meta = directory/(name+'.npz'), directory/(name+'.json')
    if target.exists() and meta.exists():
        value = json.loads(meta.read_text())
        if value['identity'] != identity or value['sha256'] != sha(target.read_bytes()):
            raise ValueError('Feature cache identity changed; use a new output')
        with np.load(target, allow_pickle=False) as z:
            return {'rgb':z['rgb'], 'lidar':z['lidar']}
    images = [cv2.imdecode(np.frombuffer(b,dtype=np.uint8),cv2.IMREAD_COLOR) for b in raw]
    if any(image is None for image in images):
        raise ValueError('Unreadable converted RGB')
    maps = encoder(images)
    sizes = [image.shape[1::-1] for image in images]
    rgb = lift_features(maps, camera_fields(p), sizes, voxel_points(grid,priors['ground_z']))
    # The point payload is separate: RGB-only input_tensor never passes it to a model.
    lidar = point_grid(points,grid,priors['ground_z'])
    if not np.isfinite(rgb).all() or not np.isfinite(lidar).all():
        raise ValueError('Non-finite BEV features')
    directory.mkdir(parents=True,exist_ok=True)
    tmp = target.with_suffix('.tmp.npz'); np.savez_compressed(tmp,rgb=rgb,lidar=lidar); os.replace(tmp,target)
    write_json(meta,{'identity':identity,'sha256':sha(target.read_bytes())})
    return {'rgb':rgb,'lidar':lidar}


def atomic_torch(path,value):
    temp = path.with_suffix('.tmp'); torch.save(value,temp); os.replace(temp,path)


def fit(mode, features, annotations, directory, config):
    directory.mkdir(exist_ok=True)
    torch.manual_seed(config['seed'])
    channels = features[0]['rgb'].shape[0]+features[0]['lidar'].shape[0]+2
    model = Detector(channels)
    optimizer = torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    checkpoint = directory/'checkpoint.pt'
    state = {'epoch':0,'next_frame':0,'loss_sum':0.,'steps':0,'history':[]}
    if checkpoint.exists():
        value = torch.load(checkpoint,map_location='cpu',weights_only=True)
        if value['configuration'] != config or value['mode'] != mode:
            raise ValueError('Checkpoint configuration changed')
        model.load_state_dict(value['model']); optimizer.load_state_dict(value['optimizer'])
        state = value['progress']
        print('RESUME',mode,'epoch',state['epoch'],'frame',state['next_frame'],flush=True)
    def save():
        atomic_torch(checkpoint,{'schema':SCHEMA,'configuration':config,'mode':mode,
            'model':model.state_dict(),'optimizer':optimizer.state_dict(),'progress':state})
    started = time.monotonic(); new_steps = 0
    model.train()
    for epoch in range(state['epoch'],config['epochs']):
        order = np.random.default_rng(config['seed']+epoch).permutation(len(features))
        for index in range(state['next_frame'],len(order)):
            i = int(order[index]); f = features[i]
            optimizer.zero_grad(set_to_none=True)
            total, pieces = loss(model(input_tensor(f['rgb'],f['lidar'],mode,config['grid'])),annotations[i])
            if not torch.isfinite(total):
                raise ValueError('Non-finite loss in '+mode)
            total.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),10.); optimizer.step()
            state['loss_sum'] += float(total.detach()); state['steps'] += 1
            state['epoch'] = epoch; state['next_frame'] = index+1; new_steps += 1
            if new_steps == 1 or new_steps % 25 == 0:
                elapsed = time.monotonic()-started
                remaining = (config['epochs']-epoch-1)*len(order)+len(order)-index-1
                print(f'TRAIN {mode} epoch={epoch+1}/{config["epochs"]} frame={index+1}/{len(order)} '
                      f'loss={float(total.detach()):.4f} mean_step={elapsed/new_steps:.3f}s '
                      f'model_remaining~{elapsed/new_steps*remaining/60:.1f}min',flush=True)
            if new_steps % 50 == 0: save()
        state['history'].append({'epoch':epoch+1,'mean_training_loss':state['loss_sum']/state['steps']})
        print('EPOCH',mode,state['history'][-1],flush=True)
        state.update(epoch=epoch+1,next_frame=0,loss_sum=0.,steps=0); save()
        write_json(directory/'training-history.json',state['history'])
    atomic_torch(directory/'model-final.pt',{'schema':SCHEMA,'mode':mode,'configuration':config,
        'model':model.state_dict(),'history':state['history']})
    model.eval()
    return model,state['history']


def measure(model,mode,records,features,priors,output=None):
    stats = []; predictions = []
    with torch.inference_mode():
        for i,(record,feature) in enumerate(zip(records,features)):
            boxes,scores = decode(model(input_tensor(feature['rgb'],feature['lidar'],mode,GRID)),priors,GRID)
            stats.append(frame_statistics(boxes,scores,record['gt_boxes'],record['gt_labels']))
            predictions.append((boxes,scores))
            if output is not None:
                output.mkdir(exist_ok=True)
                path = output/(record['key'].replace(':','_')+'.npz')
                np.savez_compressed(path,boxes=boxes,scores=scores,gt_boxes=record['gt_boxes'],gt_labels=record['gt_labels'])
            if (i+1)%25 == 0:
                print('EVALUATE',mode,i+1,'/',len(records),flush=True)
    combined = aggregate_statistics(stats)
    return {'global_confidence_sort':summarize_cached(combined,True),
            'upstream_default_frame_order':summarize_cached(combined,False)},predictions


def draw_examples(records,predictions,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output.mkdir(exist_ok=True)
    def boxes(ax,values,color):
        for b in values:
            p = np.r_[b[:4,:2],b[:1,:2]]
            ax.plot(p[:,0],p[:,1],color=color,lw=.8)
    indices = np.linspace(0,len(records)-1,min(3,len(records)),dtype=int)
    for index in indices:
        record = records[index]
        fig,axes = plt.subplots(1,4,figsize=(18,5),layout='constrained')
        items = [('CoBEVT LiDAR reference',record['boxes'])]+[(m,predictions[m][index][0]) for m in MODES]
        for ax,(name,pred) in zip(axes,items):
            boxes(ax,record['gt_boxes'],'#999999'); boxes(ax,pred,'#1261a0')
            ax.scatter([0],[0],marker='^',c='black',s=25)
            ax.set(xlim=(-100,100),ylim=(-100,100),xlabel='Car1 converted x (m)',ylabel='y (m)',title=name)
            ax.set_aspect('equal'); ax.grid(alpha=.2)
        fig.suptitle(record['key']+' — gray: GT; blue: predictions')
        fig.savefig(output/(record['key'].replace(':','_')+'.png'),dpi=130); plt.close(fig)


def run(base,output,epochs=8,weights_dir=None):
    if np.__version__ != '1.26.4' or torch.__version__ != '2.6.0+cpu':
        raise RuntimeError('Expected pinned NumPy1.26.4 and torch2.6.0+cpu')
    threads = int(os.environ.get('SLURM_CPUS_PER_TASK','8')); torch.set_num_threads(threads)
    output.mkdir(parents=True,exist_ok=True)
    config = {'schema':SCHEMA,'code':implementation(),'epochs':epochs,'seed':0,'grid':GRID,
              'train_per_recording':200,'validation_per_recording':200,'modes':list(MODES),
              'learning_rate':.001,'weight_decay':.0001,'score_threshold':.05,'topk_per_class':40,
              'nms_bev_iou':.2,'base':str(base)}
    path = output/'configuration.json'
    if path.exists() and json.loads(path.read_text()) != config:
        raise ValueError('Output belongs to another configuration; preserve it and choose a new output')
    write_json(path,config)
    if (output/'completed.json').exists():
        receipt=json.loads((output/'completed.json').read_text())
        if sha((output/'urbaning-bev-cpu.zip').read_bytes()) != receipt['sha256']:
            raise ValueError('Completed archive changed')
        print('REUSE completed:',output/'urbaning-bev-cpu.zip',flush=True); return
    print('PREFLIGHT full existing400 train/200 validation; no crossing3; no pretrained CoBEVT inference',flush=True)
    records,provenance = read_inputs(base,output,200,200)
    add_point_bindings(records,provenance)
    priors=fit_priors(records['train']); write_json(output/'train-only-priors.json',priors)
    print('ALL TRAIN GT targets, not LiDAR-TP proposals:',priors['training_gt_instances'],flush=True)
    if shutil.disk_usage(output).free < 8*1024**3:
        raise OSError('Need at least8GiB filesystem free space for this new cache (quota must also permit it)')
    encoder=MapEncoder(weights_dir or output/'weights',threads)
    write_json(output/'encoder.json',encoder.identity); write_json(output/'inputs.json',provenance)
    features={}; count=0; started=time.monotonic(); total=sum(map(len,records.values()))
    for split in ('train','validation'):
        features[split]=[]
        for record in records[split]:
            # Deliberately omit GT, scores, boxes, source peers from extractor arguments.
            inputs={k:record[k] for k in ('key','yaml','lidar_source')}
            features[split].append(extract(inputs,output/'features',encoder,priors,GRID)); count+=1
            if count==1 or count%5==0:
                seconds=time.monotonic()-started
                print(f'BEV FEATURES {count}/{total} mean={seconds/count:.2f}s/frame '
                      f'remaining~{seconds/count*(total-count)/60:.1f}min',flush=True)
    # Drop CNN and temporary image tensors before optimization of the small heads.
    del encoder
    annotation=[targets(r['gt_boxes'],r['gt_labels'],priors,GRID) for r in records['train']]
    target_stats={key:int(sum(a['statistics'][key] for a in annotation)) for key in annotation[0]['statistics']}
    write_json(output/'target-statistics.json',target_stats)
    baseline=aggregate_statistics([r['baseline_statistics'] for r in records['validation']])
    metrics={'cobevt_lidar_reference':{'global_confidence_sort':summarize_cached(baseline,True),
                                    'upstream_default_frame_order':summarize_cached(baseline,False)}}
    histories={}; train_diagnostic={}; predictions={}
    # Predeclared train diagnostic:20 uniform frames per train recording, not selection.
    diagnostic_keys={r['key'] for r in select_frames(records['train'],20)}
    diagnostic_indices=[i for i,r in enumerate(records['train']) if r['key'] in diagnostic_keys]
    for mode in MODES:
        print('START MODEL',mode,'new box centers, sizes and orientations; no proposal conditioning',flush=True)
        model,histories[mode]=fit(mode,features['train'],annotation,output/mode,config)
        train_diagnostic[mode],_=measure(model,mode,[records['train'][i] for i in diagnostic_indices],
            [features['train'][i] for i in diagnostic_indices],priors)
        metrics[mode],predictions[mode]=measure(model,mode,records['validation'],features['validation'],priors,
                                                output/(mode+'-predictions'))
        del model
    draw_examples(records['validation'],predictions,output/'bev-examples')
    report={'schema':SCHEMA,'status':'completed','frames':{s:len(v) for s,v in records.items()},
        'primary_metric':'four-class BEV polygon mAP@IoU0.5, global confidence sort, existing0–100m corner-radius filter',
        'validation':metrics,'training_diagnostic40':train_diagnostic,'training_histories':histories,
        'training_gt_support':priors['training_gt_instances'],'target_statistics':target_stats,
        'configuration':config,'elapsed_features_training_evaluation_seconds':time.monotonic()-started,
        'limitations':['New small CPU prototype, not a reproduction of BEVFusion or Simple-BEV.',
            'Frozen ImageNet RGB encoder; fixed random channel compression and four sampled height planes; approx1.1m cells.',
            'RGB-only receives no LiDAR values, detections, scores or proposals. LiDAR-only receives no RGB values.',
            'Classical point-grid LiDAR encoder and small shared head family; results do not rank modalities universally.',
            f'All three heads use the same train/validation, initialization and fixed{epochs}-epoch schedule.',
            'CoBEVT is only an external reference with different pretraining/training data; its checkpoint may have seen these development recordings.',
            'GT used only to learn train priors/targets and offline evaluation; all GT retained in evaluation, including target-grid collisions.',
            'Only two train recordings and one previously inspected validation recording; no crossing3 or independent test.',
            'Sparse bilinear lifting has depth/occlusion ambiguity and no metric depth supervision. Native camera offsets remain offline.']}
    write_json(output/'report.json',report)
    lines=['# Car1 standalone BEV detection on CPU','',f'Train{len(records["train"])} / validation{len(records["validation"])}; epochs{epochs}; zero partner requests.',
           '','| Variant | BEV mAP@0.5 (%) |','|---|---:|']
    for mode,value in metrics.items():
        ap=value['global_confidence_sort']['macro_ap']['0.5']
        lines.append('| '+mode+' | '+('undefined' if ap is None else f'{100*ap:.4f}')+' |')
    lines+=['','## Per-class AP@0.5 (%)','','| Variant | '+' | '.join(CLASSES)+' |','|---|'+'---:|'*4]
    for mode,value in metrics.items():
        values=[value['global_confidence_sort']['classes'][c]['ap']['0.5'] for c in CLASSES]
        lines.append('| '+mode+' | '+' | '.join('undefined' if a is None else f'{100*a:.4f}' for a in values)+' |')
    lines+=['','CoBEVT is a separately trained reference, not a controlled modality ablation.',
            'RGB-only / LiDAR-only / RGB+LiDAR within this prototype are the controlled comparison.',
            '',*report['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n'); print('\n'.join(lines),flush=True)
    bundle=output/'urbaning-bev-cpu.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('report.json','summary.md','inputs.json','configuration.json','encoder.json','train-only-priors.json','target-statistics.json'):
            z.write(output/name,name)
        for mode in MODES:
            for p in (output/(mode+'-predictions')).glob('*.npz'): z.write(p,p.relative_to(output))
            for name in ('model-final.pt','training-history.json'): z.write(output/mode/name,Path(mode)/name)
        for p in (output/'bev-examples').glob('*.png'): z.write(p,p.relative_to(output))
    receipt={'sha256':sha(bundle.read_bytes()),'bytes':bundle.stat().st_size}
    write_json(output/'completed.json',receipt)
    print('SHA256',receipt['sha256'],'bytes',receipt['bytes'],flush=True); print('DONE:',bundle,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=8); p.add_argument('--weights-dir',type=Path)
    args=p.parse_args(argv)
    if args.epochs<1: p.error('Epochs must be positive')
    run(args.base.resolve(),args.output_dir.resolve(),args.epochs,args.weights_dir)


if __name__=='__main__': main()
