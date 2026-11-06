"""Eight-TRAIN-frame adapter memorization diagnostic, not validation accuracy.

Reuse verified native Car1 BEV caches; freeze original CoBEVT heads. Fit two
same-capacity residual adapters with the original anchor detection loss.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import zipfile

import numpy as np
import torch
from torch import nn

from phdsim.evaluation.urbaning_cached import (_radius_mask, _polygon, polygon_iou,
    frame_statistics, aggregate_statistics, summarize_cached)
from phdsim.experiments.urbaning_rgb_pilot import read_inputs, camera_fields, sha, write_json, WEIGHTS_SHA
from phdsim.experiments.urbaning_bev_cpu import atomic_torch
from phdsim.experiments.urbaning_stage1 import prepare_upstream
from phdsim.perception.urbaning.bundle import load_config, verify_bundle
from phdsim.perception.urbaning.cobevt_rgb_adapter import metric_grid
from phdsim.perception.urbaning.cobevt_rgb_training import (SpatialEncoder, lift_rectangular,
    fit_normalizers, context, BoundedAdapter, original_heads, shuffled_indices)

SCHEMA='phdsim-cobevt-rgb-adapter-train8-v1'
PREFLIGHT_SHA='8608d07b6862e3288718b0e4469ccb1e983439973c5a96e845cb2263048b9429'
MODES=('lidar_adapter','lidar_rgb_adapter')


def code_identity():
    from phdsim.perception.urbaning import cobevt_rgb_training, cobevt_rgb_adapter, bev_cpu
    paths=[Path(__file__),Path(cobevt_rgb_training.__file__),Path(cobevt_rgb_adapter.__file__),
           Path(bev_cpu.__file__),Path(__file__).with_name('urbaning_rgb_pilot.py')]
    return {p.name:sha(p.read_bytes()) for p in paths}


def verified_inputs(base,preflight,output,config):
    archive=preflight/'urbaning-cobevt-rgb-preflight.zip'
    if sha(archive.read_bytes())!=PREFLIGHT_SHA:raise ValueError('Expected reviewed Ares21597293 archive')
    with zipfile.ZipFile(archive) as z:
        report=json.loads(z.read('report.json'));protocol=json.loads(z.read('protocol.json'))
        if z.testzip() is not None:raise ValueError('Preflight CRC failure')
    if report['status']!='completed' or protocol['training'] or protocol['validation_frames']!=0:
        raise ValueError('Preflight protocol differs')
    if protocol['model']!=verify_bundle(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3'):
        raise ValueError('Official model identity differs')
    records,provenance=read_inputs(base,output,4,0)
    rows=records['train']; previous={r['key']:r for r in report['frames']}
    if len(rows)!=8 or set(previous)!={r['key'] for r in rows} or records['validation']:
        raise ValueError('Training inventory differs from reviewed eight frames')
    features=[]
    for r in rows:
        old=previous[r['key']]
        if r['native_association']!=old['native_association']:raise ValueError('Native image association changed')
        path=preflight/'features'/(r['key'].replace(':','_')+'.npz')
        if sha(path.read_bytes())!=old['cache_sha256']:raise ValueError('Native BEV cache changed')
        with np.load(path,allow_pickle=False) as z:
            value={k:z[k].copy() for k in ('bev','xy','psm','rm')}
        if value['bev'].shape!=(1,256,100,256) or not all(np.isfinite(a).all() for a in value.values()):
            raise ValueError('Invalid original BEV cache')
        np.testing.assert_allclose(value['xy'],metric_grid((100,256),config['model']['args']['lidar_range']),rtol=0,atol=1e-8)
        r['expected_image_hashes']={c['camera']:c['image_sha256'] for c in old['cameras']}
        features.append({'bev':torch.from_numpy(value['bev']).float(), 'xy':value['xy'],
                         'psm':torch.from_numpy(value['psm']), 'rm':torch.from_numpy(value['rm']),
                         'cache_sha256':old['cache_sha256']})
    return rows,features,provenance


def load_frozen_heads(model_dir):
    verify_bundle(model_dir)
    state=torch.load(model_dir/'best_model.pth',map_location='cpu',weights_only=True)
    heads=[]
    for name,outputs in [('cls_head',32),('reg_head',56)]:
        layer=nn.Conv2d(256,outputs,1)
        layer.load_state_dict({key:state[name+'.'+key] for key in ('weight','bias')},strict=True)
        heads.append(layer.eval().requires_grad_(False))
    return heads


def native_runtime(config,heads):
    from opencood.data_utils.post_processor import build_postprocessor
    from opencood.loss.point_pillar_loss import PointPillarLoss
    from opencood.utils import box_utils
    class_names=[a['class_name'] for a in config['postprocess']['anchor_args']['anchor_generator_config']]
    post=build_postprocessor(config['postprocess'],class_names,train=True)
    anchors,counts=post.generate_anchor_box()
    xy=metric_grid(anchors[0].shape[:2],config['model']['args']['lidar_range'])
    for anchor in anchors:
        np.testing.assert_allclose(anchor[:,:,0,:2],xy,rtol=0,atol=1e-5)
    batch={'ego':{'all_anchors':torch.from_numpy(np.stack(anchors)).float(),
                  'num_anchors_per_location':counts,'transformation_matrix':torch.eye(4)}}
    loss=PointPillarLoss(config['loss']['args'])
    def target(record):
        keep=_radius_mask(record['gt_boxes']);boxes=record['gt_boxes'][keep];labels=record['gt_labels'][keep]
        centers=box_utils.corner_to_center(boxes,order='hwl')
        reconstructed=box_utils.boxes_to_corners_3d(centers,order='hwl')
        for original,decoded in zip(boxes,reconstructed):
            if polygon_iou(_polygon(original),_polygon(decoded))<.999:
                raise ValueError('GT corner/anchor-center conversion does not preserve BEV boxes')
        gt=np.c_[centers,labels]
        values=post.generate_label(gt_box_center=gt,anchors=anchors,
                                   num_anchors_per_location=counts,mask=np.ones(len(gt)))
        values=post.collate_batch([values])
        return {k:v.float() for k,v in values.items()}
    def decode(outputs):
        with torch.no_grad():
            boxes,scores=post.post_process(batch,{'ego':outputs},
                gt_range=config['preprocess']['cav_lidar_range_validation'])
        if boxes is None:return np.empty((0,8,3)),np.empty((0,2))
        return boxes.detach().numpy(),scores.detach().numpy()
    return SimpleNamespace(target=target,decode=decode,loss=loss,heads=heads)


def ground_prior(records):
    bottoms=[]
    for r in records:
        for b in r['gt_boxes']:
            if np.linalg.norm(b.mean(0)[:2])<30:bottoms.append(float(b[:,2].min()))
    if not bottoms:raise ValueError('No near-ground TRAIN boxes')
    return float(np.median(bottoms))


def extract_rgb(record,feature,encoder,ground,directory):
    import cv2
    raw=[];hashes={}
    for c in range(6):
        p=Path(record['yaml']).with_name(Path(record['yaml']).stem+'_camera'+str(c)+'.png')
        b=p.read_bytes();digest=sha(b)
        if digest!=record['expected_image_hashes'][c]:raise ValueError('Reviewed RGB payload changed')
        raw.append(b);hashes[str(c)]=digest
    identity={'schema':SCHEMA,'code':code_identity(),'key':record['key'],'images':hashes,
              'yaml_sha256':sha(Path(record['yaml']).read_bytes()),'ground_z_train_only':ground,
              'native_bev_sha256':feature['cache_sha256'],'encoder':encoder.identity}
    name=record['key'].replace(':','_');path=directory/(name+'.npz');meta=directory/(name+'.json')
    if path.exists() and meta.exists():
        old=json.loads(meta.read_text())
        if old['identity']!=identity or old['sha256']!=sha(path.read_bytes()):raise ValueError('RGB cache identity changed')
        with np.load(path,allow_pickle=False) as z:return torch.from_numpy(z['rgb'].astype(np.float32))
    images=[cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR) for b in raw]
    if any(x is None for x in images):raise ValueError('Unreadable bound RGB image')
    maps=encoder(images)
    rgb=lift_rectangular(maps,camera_fields(record['yaml']),[im.shape[1::-1] for im in images],feature['xy'],ground)
    tmp=path.with_suffix('.tmp.npz');np.savez_compressed(tmp,rgb=rgb.numpy().astype(np.float16));os.replace(tmp,path)
    write_json(meta,{'identity':identity,'sha256':sha(path.read_bytes())})
    # Fresh and resumed runs optimize the same quantized feature representation.
    return torch.from_numpy(rgb.numpy().astype(np.float16).astype(np.float32))


def optimize(mode,features,targets,runtime,normalizers,directory,configuration):
    directory.mkdir(exist_ok=True);torch.manual_seed(configuration['seed'])
    channels=features[0]['bev'].shape[1]+features[0]['rgb'].shape[0]+2
    adapter=BoundedAdapter(channels,features[0]['bev'].shape[1],normalizers['lidar']['std'],16)
    optimizer=torch.optim.AdamW(adapter.parameters(),lr=configuration['learning_rate'],weight_decay=1e-4)
    inputs=[context(f['bev'],f['rgb'],mode,normalizers,f['xy']) for f in features]
    history=[];first=0;checkpoint=directory/'checkpoint.pt'
    if checkpoint.exists():
        saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
        if saved['configuration']!=configuration or saved['mode']!=mode:raise ValueError('Checkpoint identity changed')
        adapter.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer'])
        history=saved['history'];first=saved['epoch']
        print('RESUME',mode,'epoch',first,flush=True)
    def mean_loss():
        values=[]
        with torch.no_grad():
            for f,x,target in zip(features,inputs,targets):
                bev,_=adapter(f['bev'],x);value=runtime.loss(original_heads(*runtime.heads,bev),target)
                values.append(float(value))
        return float(np.mean(values))
    initial=mean_loss() if first==0 else saved['initial_loss']
    started=time.monotonic();steps=0
    for epoch in range(first,configuration['epochs']):
        rows=[]
        for i in np.random.default_rng(configuration['seed']+epoch).permutation(len(features)):
            optimizer.zero_grad(set_to_none=True)
            bev,raw=adapter(features[i]['bev'],inputs[i])
            detection=runtime.loss(original_heads(*runtime.heads,bev),targets[i])
            penalty=configuration['residual_penalty']*raw.square().mean()
            objective=detection+penalty
            if not bool(torch.isfinite(objective)):raise ValueError('Non-finite adapter loss')
            objective.backward();norm=torch.nn.utils.clip_grad_norm_(adapter.parameters(),1.)
            if not bool(torch.isfinite(norm)):raise ValueError('Non-finite adapter gradient')
            optimizer.step();steps+=1
            rows.append({'detection':float(detection.detach()),'regularization':float(penalty.detach()),
                         'classification':float(runtime.loss.loss_dict['conf_loss'].detach()),
                         'regression':float(runtime.loss.loss_dict['reg_loss'].detach())})
        row={'epoch':epoch+1,**{k:float(np.mean([r[k] for r in rows])) for k in rows[0]}}
        history.append(row)
        atomic_torch(checkpoint,{'configuration':configuration,'mode':mode,'epoch':epoch+1,
            'model':adapter.state_dict(),'optimizer':optimizer.state_dict(),'history':history,'initial_loss':initial})
        if epoch==first or (epoch+1)%8==0:
            elapsed=time.monotonic()-started;remaining=(configuration['epochs']-epoch-1)*len(features)
            print(f'TRAIN {mode} epoch={epoch+1}/{configuration["epochs"]} loss={row["detection"]:.6f} '
                  f'mean_step={elapsed/max(steps,1):.3f}s remaining~{elapsed/max(steps,1)*remaining/60:.1f}min',flush=True)
    final=mean_loss()
    atomic_torch(directory/'model-final.pt',{'configuration':configuration,'mode':mode,'model':adapter.state_dict(),
        'history':history,'initial_detection_loss':initial,'final_detection_loss':final})
    write_json(directory/'training-history.json',history)
    return adapter,{'initial_detection_loss':initial,'final_detection_loss':final,
                    'loss_decreased':final<initial,'history':history}


def evaluate(label,records,features,runtime,output,adapter=None,mode=None,normalizers=None,shuffle=None):
    stats=[];predictions=[];output.mkdir(exist_ok=True)
    with torch.no_grad():
        for i,(r,f) in enumerate(zip(records,features)):
            bev=f['bev']
            if adapter is not None:
                visual=features[shuffle[i] if shuffle is not None else i]['rgb']
                x=context(bev,visual,mode,normalizers,f['xy']);bev,_=adapter(bev,x)
            outputs=original_heads(*runtime.heads,bev)
            boxes,scores=runtime.decode(outputs)
            statistics=frame_statistics(boxes,scores,r['gt_boxes'],r['gt_labels']);stats.append(statistics)
            predictions.append((boxes,scores))
            np.savez_compressed(output/(r['key'].replace(':','_')+'.npz'),boxes=boxes,scores=scores,
                                gt_boxes=r['gt_boxes'],gt_labels=r['gt_labels'])
    total=aggregate_statistics(stats)
    result={'global_confidence_sort':summarize_cached(total,True),
            'upstream_default_frame_order':summarize_cached(total,False),'frames':len(records),'peer_requests':0}
    ap=result['global_confidence_sort']['macro_ap']['0.5']
    print('EVALUATE',label,'TRAIN mAP@.5=',100*ap if ap is not None else 'N/A: absent GT class',flush=True)
    return result,predictions


def draw(records,predictions,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output.mkdir(exist_ok=True)
    for i in (0,3,4,7):
        fig,axes=plt.subplots(1,3,figsize=(16,5),layout='constrained')
        for ax,label in zip(axes,('original_lidar',*MODES)):
            for boxes,color in [(records[i]['gt_boxes'],'#888888'),(predictions[label][i][0],'#087e8b')]:
                for b in boxes:
                    polygon=np.r_[b[:4,:2],b[:1,:2]];ax.plot(polygon[:,0],polygon[:,1],color=color,lw=.8)
            ax.set(xlim=(-105,105),ylim=(-45,45),xlabel='Car1 x [m]',ylabel='y [m]',title=label)
            ax.set_aspect('equal');ax.grid(alpha=.2)
        fig.suptitle(records[i]['key']+' | TRAIN memorization only | gray=GT, teal=prediction')
        fig.savefig(output/(records[i]['key'].replace(':','_')+'.png'),dpi=140);plt.close(fig)


def run(base,preflight,upstream,model_dir,output,weights,threads,epochs=64):
    if np.__version__!='1.26.4' or torch.__version__!='2.6.0+cpu':raise RuntimeError('Use pinned CPU torch2.6/NumPy1.26.4')
    torch.set_num_threads(threads);torch.manual_seed(0);np.random.seed(0)
    output.mkdir(parents=True,exist_ok=True)
    configuration={'schema':SCHEMA,'code':code_identity(),'base':str(base),'preflight':str(preflight),
        'preflight_zip_sha256':PREFLIGHT_SHA,'epochs':epochs,'seed':0,'learning_rate':.001,
        'weight_decay':1e-4,'residual_penalty':1e-4,'max_delta':'one TRAIN channel standard deviation via tanh',
        'hidden_channels':16,'threads':threads,'scope':'TRAIN8 memorization; no validation/test',
        'train_modes':list(MODES),'evaluation':'fixed original decode;4-class global-sort BEV mAP@.5'}
    config_path=output/'configuration.json'
    if config_path.exists() and json.loads(config_path.read_text())!=configuration:raise ValueError('Output configuration differs')
    write_json(config_path,configuration)
    if (output/'completed.json').exists():
        receipt=json.loads((output/'completed.json').read_text())
        if sha((output/'urbaning-cobevt-rgb-adapter-train8.zip').read_bytes())!=receipt['sha256']:raise ValueError('Completed archive changed')
        print('REUSE completed:',output/'urbaning-cobevt-rgb-adapter-train8.zip',flush=True);return
    prepare_upstream(upstream)
    config=load_config(model_dir)
    if model_dir.resolve()!=(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3').resolve():raise ValueError('Use original model bundle in BASE')
    print('VERIFY reviewed native BEV caches; no LiDAR backbone/fusion inference',flush=True)
    records,features,provenance=verified_inputs(base,preflight,output,config)
    heads=load_frozen_heads(model_dir);snapshot=[{k:v.clone() for k,v in h.state_dict().items()} for h in heads]
    runtime=native_runtime(config,heads)
    for f in features:
        native=original_heads(*heads,f['bev'])
        for k in ('psm','rm'):torch.testing.assert_close(native[k],f[k],rtol=0,atol=1e-6)
        del f['psm'],f['rm']
    print('PARITY original heads vs all8 reviewed native logits passed',flush=True)
    ground=ground_prior(records)
    weight_file=weights/'checkpoints/mobilenet_v3_small-047dcff4.pth'
    if not weight_file.is_file() or sha(weight_file.read_bytes())!=WEIGHTS_SHA:raise ValueError('Existing official ImageNet weights required')
    encoder=SpatialEncoder(weights,threads);encoder_id=encoder.identity
    rgb_dir=output/'rgb-features';rgb_dir.mkdir(exist_ok=True)
    for i,(r,f) in enumerate(zip(records,features)):
        f['rgb']=extract_rgb(r,f,encoder,ground,rgb_dir)
        print(f'RGB BEV {i+1}/8 shape={tuple(f["rgb"].shape)}',flush=True)
    del encoder
    normalizers=fit_normalizers(features)
    write_json(output/'normalizers.json',normalizers)
    write_json(output/'inputs.json',{'source':provenance,'keys':[r['key'] for r in records],
        'model':verify_bundle(model_dir),'ground_z_train_only':ground,'rgb_encoder':encoder_id,
        'native_bev_hashes':{r['key']:f['cache_sha256'] for r,f in zip(records,features)}})
    targets=[runtime.target(r) for r in records]
    target_summary=[]
    for r,t in zip(records,targets):
        target_summary.append({'key':r['key'],'evaluation_gt_count':len(r['gt_labels']),
            'radius_gt_count':int(_radius_mask(r['gt_boxes']).sum()),
            'positive_anchors_by_class':{str(c):int((t['pos_equal_one']==c).sum()) for c in range(1,5)}})
    write_json(output/'target-statistics.json',target_summary)
    # Identity check using exactly the same path subsequently optimized.
    probe=BoundedAdapter(256+features[0]['rgb'].shape[0]+2,256,normalizers['lidar']['std'],16)
    for mode in MODES:
        for f in features:
            bev,_=probe(f['bev'],context(f['bev'],f['rgb'],mode,normalizers,f['xy']))
            if not torch.equal(bev,f['bev']):raise ValueError('Zero adapter changed original features')
    metrics={};predictions={};histories={}
    metrics['original_lidar'],predictions['original_lidar']=evaluate('original_lidar',records,features,runtime,output/'original_lidar-predictions')
    for mode in MODES:
        adapter,histories[mode]=optimize(mode,features,targets,runtime,normalizers,output/mode,configuration)
        metrics[mode],predictions[mode]=evaluate(mode,records,features,runtime,output/(mode+'-predictions'),adapter,mode,normalizers)
        if mode=='lidar_rgb_adapter':
            metrics['lidar_rgb_shuffled_diagnostic'],_=evaluate('lidar_rgb_shuffled_diagnostic',records,features,runtime,
                output/'lidar_rgb_shuffled_diagnostic-predictions',adapter,mode,normalizers,shuffled_indices(records))
    for head,original in zip(heads,snapshot):
        if any(not torch.equal(original[k],v) for k,v in head.state_dict().items()):raise ValueError('Original head mutated')
    report={'schema':SCHEMA,'status':'completed','scope':'eight TRAIN frames, same frames for fitting and evaluation',
        'validation_frames':0,'test_frames':0,'metrics':metrics,'training':histories,'target_statistics':target_summary,
        'protocol':configuration,'head_weights_unchanged':True,'zero_start_exact':True,
        'limitations':['Memorization diagnostic only; no generalization/fusion benefit claim',
            'Both learned variants retain Car1 LiDAR; no RGB-only detector',
            'Frozen ImageNet stride16 RGB encoder; four fixed height planes; no depth/occlusion supervision',
            'Native image offsets preserved offline; original checkpoint may have seen these training clips',
            'Training objective is upstream anchor detection loss; primary evaluation remains BEV mAP@.5',
            'Adapter correction bounded by one train standard deviation per channel; this limits expressiveness']}
    write_json(output/'report.json',report)
    draw(records,predictions,output/'examples')
    lines=['# Car1 adapter: TRAIN8 memorization diagnostic','',
           'Same8 TRAIN frames for optimization/evaluation;0 validation/test; frozen original heads;0 peer requests.','',
           '| Variant | TRAIN BEV mAP@.5 (%) |','|---|---:|']
    for key,value in metrics.items():
        ap=value['global_confidence_sort']['macro_ap']['0.5']
        displayed=f'{ap*100:.4f}' if ap is not None else 'N/A: absent GT class'
        lines.append(f'| {key} | {displayed} |')
    lines += ['','These are training diagnostics, not evidence of generalization or an RGB gain.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines),flush=True)
    archive=output/'urbaning-cobevt-rgb-adapter-train8.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('configuration.json','inputs.json','normalizers.json','target-statistics.json','report.json','summary.md'):
            z.write(output/name,name)
        for mode in MODES:
            for name in ('model-final.pt','training-history.json'):z.write(output/mode/name,mode+'/'+name)
        for folder in output.iterdir():
            if folder.name.endswith('-predictions') or folder.name=='examples':
                for p in sorted(folder.iterdir()):z.write(p,str(p.relative_to(output)))
    write_json(output/'completed.json',{'sha256':sha(archive.read_bytes())})
    print('DONE:',archive,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','preflight','upstream','model-dir','output','weights-dir'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--cpu-threads',type=int,default=8);p.add_argument('--epochs',type=int,default=64)
    a=p.parse_args()
    if a.cpu_threads<1 or a.epochs<1:p.error('Threads/epochs must be positive')
    run(a.base.resolve(),a.preflight.resolve(),a.upstream.resolve(),a.model_dir.resolve(),a.output.resolve(),
        a.weights_dir.resolve(),a.cpu_threads,a.epochs)


if __name__=='__main__':main()
