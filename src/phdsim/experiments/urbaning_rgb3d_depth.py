"""Frozen RGB feature extraction and native depth-readout adaptation on CPU.

400 TRAIN before freeze; then200 development-validation. No crossing3, new
LiDAR inference, acquisition, learned fusion or validation-based selection.
"""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import time
import zipfile

import numpy as np

from phdsim.experiments.urbaning_rgb_pilot import read_inputs,camera_fields,sha,write_json,select_frames
from phdsim.perception.urbaning.rgb3d_late import (
    OUTDOOR_ASSETS,CLASS_MAP,camera_to_ego,upright_boxes,classwise_nms,late_fuse)
from phdsim.perception.urbaning.rgb3d_depth import (
    DepthFeatureDetector,apply_depth,fit_depth,verify_native_delta,
    FEATURE_PENALTY,BIAS_PENALTY,MIN_POSITIVES)
from phdsim.evaluation.urbaning_cached import (
    _radius_mask,frame_statistics,aggregate_statistics,summarize_cached)

SCHEMA='phdsim-rgb3d-native-depth-controlled-v1'
VARIANTS=('lidar','rgb_baseline','rgb_depth_finetuned','lidar_rgb_baseline','lidar_rgb_depth_finetuned')


def digest(value):return sha(json.dumps(value,sort_keys=True,allow_nan=False).encode())


def save_npz(path,**arrays):
    temp=path.with_suffix('.partial')
    with temp.open('wb') as f:np.savez_compressed(f,**arrays)
    os.replace(temp,path)


def iou2d(a,b):
    inter=np.maximum(np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2]),0).prod()
    aa=np.maximum(a[2:]-a[:2],0).prod();bb=np.maximum(b[2:]-b[:2],0).prod()
    return float(inter/(aa+bb-inter)) if aa+bb>inter else 0.


def depth_targets(cache,gt_boxes,gt_labels,extrinsic,intrinsic,width,height,categories):
    """Offline projected-GT association; never called by inference apply_depth."""
    optical=gt_boxes@extrinsic[:3,:3].T+extrinsic[:3,3]
    uv=optical@intrinsic.T;uv=uv[...,:2]/np.maximum(uv[...,2:3],1e-6)
    rect=np.c_[uv.min(1),uv.max(1)]
    rect[:,[0,2]]=rect[:,[0,2]].clip(0,width)
    rect[:,[1,3]]=rect[:,[1,3]].clip(0,height)
    valid=(optical[...,2]>.1).all(1)&((rect[:,2:]-rect[:,:2])>=12).all(1)&_radius_mask(gt_boxes)
    left=list(np.flatnonzero(valid));rows=[]
    for i in np.argsort(-cache['scores']):
        cls=CLASS_MAP.get(categories[int(cache['classes'][i])])
        if cls is None:continue
        choices=[g for g in left if gt_labels[g]==cls]
        if not choices:continue
        overlaps=[iou2d(cache['boxes2d'][i],rect[g]) for g in choices]
        j=int(np.argmax(overlaps))
        if overlaps[j]<.5:continue
        g=choices[j];left.remove(g)
        target=float((gt_boxes[g].mean(0)@extrinsic[:3,:3].T+extrinsic[:3,3])[2])
        rows.append({'prediction':int(i),'gt':int(g),'class':int(cache['classes'][i]),
                     'depth':target,'image_iou':overlaps[j]})
    return rows


def variants_from_arrays(data):
    lb,ls=data['lidar_boxes'],data['lidar_scores']
    b,s=data['rgb_baseline_boxes'],data['rgb_baseline_scores']
    nb,ns=data['rgb_depth_boxes'],data['rgb_depth_scores']
    fb,fs,_=late_fuse(lb,ls,b,s,.2);nf,nfs,_=late_fuse(lb,ls,nb,ns,.2)
    return {'lidar':(lb,ls),'rgb_baseline':(b,s),'rgb_depth_finetuned':(nb,ns),
            'lidar_rgb_baseline':(fb,fs),'lidar_rgb_depth_finetuned':(nf,nfs)}


def metrics_from_paths(paths):
    stats={v:[] for v in VARIANTS}
    for p in paths:
        with np.load(p,allow_pickle=False) as d:
            for v,(b,s) in variants_from_arrays(d).items():
                stats[v].append(frame_statistics(b,s,d['gt_boxes'],d['gt_labels']))
    return {v:{'global_confidence_sort':summarize_cached(aggregate_statistics(ss),True),
               'upstream_default_frame_order':summarize_cached(aggregate_statistics(ss),False)} for v,ss in stats.items()}


def load_pilot(archive,records):
    raw=archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:raise ValueError('Corrupt source outdoor pilot')
        protocol=json.loads(z.read('protocol.json'));r=json.loads(z.read('report.json'))
        if protocol.get('model_variant')!='outdoor' or protocol['model']!=OUTDOOR_ASSETS:
            raise ValueError('Source pilot is not the official outdoor model')
        known=r['metrics']['rgb']['global_confidence_sort']['macro_ap']['0.5']*100
        if not np.isclose(known,6.935736469990656,rtol=0,atol=1e-12):
            raise ValueError('Source outdoor result differs from reported21655505 pilot')
        expected={x['key'] for x in select_frames(records,4)}
        if {x['key'] for x in r['frames']}!=expected:raise ValueError('Pilot keys differ from fixed TRAIN8')
        bykey={x['key']:x for x in records}
        for row in r['frames']:
            key=row['key'];record=bykey[key]
            payload=z.read('frames/'+key.replace(':','_')+'.npz')
            if sha(payload)!=row['payload_sha256']:raise ValueError('Changed pilot frame payload')
            with np.load(io.BytesIO(payload),allow_pickle=False) as d:
                for a,b in [('boxes','original_lidar_boxes'),('scores','original_lidar_scores'),
                            ('gt_boxes','gt_boxes'),('gt_labels','gt_labels')]:
                    if not np.array_equal(record[a],d[b]):raise ValueError('Source pilot GT/LiDAR binding differs')
    return r,sha(raw)


def run(base,runtime,model_dir,pilot,output,threads):
    import cv2
    import torch
    if threads<1:raise ValueError('Positive thread count required')
    torch.set_num_threads(threads)
    if output.resolve()==pilot.parent.resolve() or output.resolve().is_relative_to(runtime.resolve()):
        raise ValueError('Use a separate output, outside source runtime/pilot')
    output.mkdir(parents=True,exist_ok=True)
    with (output/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _run(base,runtime,model_dir,pilot,output,threads)


def _run(base,runtime,model_dir,pilot,output,threads):
    import cv2
    import torch
    for name in ['features','train-loader','validation-loader','frames-train','frames-validation','models']:
        (output/name).mkdir(exist_ok=True)
    # The existing packet contains both splits; only TRAIN records are requested
    # for fitting. Validation GT is loaded as records only AFTER model freeze.
    records,provenance=read_inputs(base,output/'train-loader',200,0)
    train=records['train']
    if len(train)!=400 or records['validation']:raise ValueError('Expected exactly TRAIN400')
    source_pilot,pilot_sha=load_pilot(pilot,train)
    codefiles=[Path(__file__),Path(__file__).parents[1]/'perception/urbaning/rgb3d_depth.py',
               Path(__file__).parents[1]/'perception/urbaning/rgb3d_late.py',
               Path(__file__).with_name('urbaning_rgb_pilot.py'),
               Path(__file__).parents[1]/'evaluation/urbaning_cached.py',
               Path(__file__).parents[3]/'scripts/urbaning_rgb3d_depth.py',
               Path(__file__).parents[3]/'scripts/urbaning_rgb3d_late.py',
               Path(__file__).parents[3]/'scripts/slurm/urbaning_rgb3d_depth.sbatch']
    protocol={'schema':SCHEMA,'purpose':__doc__,'model':OUTDOOR_ASSETS,'source_pilot_sha256':pilot_sha,
              'train_provenance':provenance,'threads':threads,'native_layer':'bbox_3D_center_depth',
              'feature_penalty':FEATURE_PENALTY,'bias_penalty':BIAS_PENALTY,'min_positives':MIN_POSITIVES,
              'matching':'TRAIN projected image GT, same coarse class, greedy IoU>=.5; front/min12px; all eval GT retained',
              'selection':'fixed weighted ridge; no validation parameter/checkpoint search','peer_requests':0,
              'code':{str(p.relative_to(Path(__file__).parents[3])):sha(p.read_bytes()) for p in codefiles}}
    pfile=output/'protocol.json'
    if pfile.exists() and json.loads(pfile.read_text())!=protocol:raise ValueError('Resume protocol/source changed')
    write_json(pfile,protocol)
    protocol_sha=digest(protocol)
    for name,expected in OUTDOOR_ASSETS.items():
        if sha((model_dir/name).read_bytes())!=expected:raise ValueError('Source official model changed')
    completed=output/'completed.json'
    if completed.exists():
        done=json.loads(completed.read_text());archive=output/'urbaning-rgb3d-depth-controlled.zip'
        if (done.get('protocol_sha256')!=protocol_sha or done['sha256']!=sha(archive.read_bytes())
                or done['model_sha256']!=sha((output/'models/depth-head.pt').read_bytes())):
            raise ValueError('Completed output identity/hash differs')
        print('REUSE VERIFIED COMPLETED:',archive,flush=True)
        return archive
    runtime_before=sha((runtime/'ready.json').read_bytes())
    detector=DepthFeatureDetector(model_dir,threads);original=detector.state()
    write_json(output/'source-pilot-report.json',source_pilot)
    original_sha=sha(original['weight'].tobytes()+original['bias'].tobytes())
    started=time.monotonic();cached_count=0;pilot_rows={x['key']:x for x in source_pilot['frames']}
    print('SOURCE VERIFIED: outdoor pilot, TRAIN400; no validation loaded for fitting',flush=True)

    def camera(record,index):
        nonlocal cached_count
        e,k=camera_fields(record['yaml'])[index];camera_to_ego(e)
        image_path=Path(record['yaml']).with_name(Path(record['yaml']).stem+f'_camera{index}.png')
        raw=image_path.read_bytes();image_sha=sha(raw)
        binding={'key':record['key'],'camera':index,'image_sha256':image_sha,'E':e.tolist(),'K':k.tolist(),
                 'native_association':record['native_association'],'protocol':protocol_sha,'head':original_sha}
        name=record['key'].replace(':','_')+f'_camera{index}'
        target=output/'features'/(name+'.npz');meta=target.with_suffix('.json')
        if record['key'] in pilot_rows:
            ref=pilot_rows[record['key']]['cameras'][index]
            if (image_sha!=ref['image_sha256'] or not np.array_equal(e,ref['optical_from_car1'])
                    or not np.array_equal(k,ref['K']) or ref['native_association']!=record['native_association']):
                raise ValueError('Pilot native image/calibration/time binding differs')
        if target.exists() or meta.exists():
            if not target.exists() or not meta.exists():raise ValueError('Incomplete final feature cache')
            receipt=json.loads(meta.read_text())
            if receipt['binding']!=binding or receipt['sha256']!=sha(target.read_bytes()):
                raise ValueError('Feature cache/source hash mismatch')
            with np.load(target,allow_pickle=False) as z:data={n:z[n].copy() for n in z.files}
        else:
            image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if image is None:raise ValueError('Unreadable RGB image')
            data=detector.capture(image,k);data['image_shape']=np.array(image.shape[:2])
            save_npz(target,**data);write_json(meta,{'binding':binding,'sha256':sha(target.read_bytes())})
        if len(data['depth_features'])!=len(data['classes']):raise ValueError('Bad feature/detection association')
        cached_count+=1
        return data,e,k

    def merged(record,state,prepared=None):
        bb=[];ss=[]
        for index in range(6):
            data,e,k=camera(record,index) if prepared is None else prepared[index]
            result=data if state is original else apply_depth(data,original,state,k)
            ids=np.array([i for i,c in enumerate(data['classes']) if detector.categories[int(c)] in CLASS_MAP],int)
            b=upright_boxes(result['centers'][ids],data['dimensions'][ids],data['rotations'][ids],e)
            s=np.array([[data['scores'][i],CLASS_MAP[detector.categories[int(data['classes'][i])]]] for i in ids]).reshape(-1,2)
            bb.append(b);ss.append(s)
        b,s=np.concatenate(bb),np.concatenate(ss);keep=classwise_nms(b,s,.2)
        return b[keep],s[keep]

    # Native smoke BEFORE the full400 extraction. Hook/virtual-depth parity is
    # checked on every capture. A real perturbed original-layer forward is an
    # additional gate, restored before any persistent training/evaluation.
    smoke_ok=False;smoke_example=None
    for record in select_frames(train,4):
        for index in range(6):
            data,e,k=camera(record,index)
            if not smoke_ok and len(data['scores']):
                p=Path(record['yaml']).with_name(Path(record['yaml']).stem+f'_camera{index}.png')
                image=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                smoke_ok=verify_native_delta(detector,image,k)
                if smoke_ok:smoke_example=(p,k)
        print('NATIVE GATE',record['key'],flush=True)
    if not smoke_ok:raise ValueError('No nonempty native smoke example')
    # Independent AP guard against the completed source pilot, on the same8 GT.
    pilot_stats=[]
    for record in select_frames(train,4):
        b,s=merged(record,original)
        pilot_stats.append(frame_statistics(b,s,record['gt_boxes'],record['gt_labels']))
    for order in [True,False]:
        name='global_confidence_sort' if order else 'upstream_default_frame_order'
        if summarize_cached(aggregate_statistics(pilot_stats),order)!=source_pilot['metrics']['rgb'][name]:
            raise ValueError('Fresh native/cached source-pilot AP differs')
    print('NATIVE DEPTH GATE PASSED: original8 AP parity, features/virtual scaling, real modified-layer replay',flush=True)

    def collect_targets(rows,label):
        xx=[];cc=[];yy=[];sc=[];keys=[]
        for j,record in enumerate(rows):
            for index in range(6):
                data,e,k=camera(record,index);h,w=map(int,data['image_shape'])
                targets=depth_targets(data,record['gt_boxes'],record['gt_labels'],e,k,w,h,detector.categories)
                for t in targets:
                    xx.append(data['depth_features'][t['prediction']]);cc.append(t['class']);yy.append(t['depth'])
                    sc.append(float(data['depth_scale']));keys.append(record['key'])
            if (j+1)%10==0 or j==0:
                print(f'FEATURES {label} {j+1}/{len(rows)} positives={len(xx)} elapsed={(time.monotonic()-started)/60:.1f}min',flush=True)
        return (np.asarray(xx,np.float32).reshape(-1,original['weight'].shape[1]),np.asarray(cc,np.int64),
                np.asarray(yy,float),np.asarray(sc,float),keys)

    examples=collect_targets(train,'TRAIN')
    training_sha=sha(b''.join(x.tobytes() for x in examples[:4])+json.dumps(examples[4]).encode())
    model_path=output/'models/depth-head.pt';freeze_path=output/'models/freeze.json'
    if model_path.exists() or freeze_path.exists():
        freeze=json.loads(freeze_path.read_text())
        if (freeze['training_sha256']!=training_sha or freeze['model_sha256']!=sha(model_path.read_bytes())
                or freeze['protocol_sha256']!=digest(protocol)):raise ValueError('Frozen model resume binding differs')
        trained={k:v.numpy() for k,v in torch.load(model_path,map_location='cpu',weights_only=True).items()}
        support=freeze['support']
    else:
        print('FIT existing native depth layer; TRAIN only; fixed ridge, no validation search',flush=True)
        trained,support=fit_depth(original,*examples)
        for row in support:row['class_name']=detector.categories[row['class_id']]
        if not any(r['adapted'] for r in support):raise ValueError('No class has enough valid TRAIN targets')
        torch.save({k:torch.from_numpy(v) for k,v in trained.items()},model_path)
        freeze={'training_sha256':training_sha,'model_sha256':sha(model_path.read_bytes()),
                'protocol_sha256':digest(protocol),'support':support,'validation_loaded':False}
        write_json(freeze_path,freeze)
    torch.save({k:torch.from_numpy(v) for k,v in original.items()},output/'models/original-depth-head.pt')
    print('FROZEN native depth head:',freeze['model_sha256'],'validation not used for fitting',flush=True)
    smoke_path,smoke_k=smoke_example
    smoke_image=cv2.imdecode(np.frombuffer(smoke_path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if not verify_native_delta(detector,smoke_image,smoke_k,trained):
        raise ValueError('Trained readout has no native parity example')
    print('TRAINED NATIVE HEAD PARITY PASSED; source head restored before validation extraction',flush=True)
    del examples

    def evaluate(rows,label):
        paths=[];depth_before=[];depth_after=[];depth_by_class={}
        for j,record in enumerate(rows):
            prepared=[camera(record,index) for index in range(6)]
            b,s=merged(record,original,prepared);nb,ns=merged(record,trained,prepared)
            for data,e,k in prepared:
                h,w=map(int,data['image_shape']);changed=apply_depth(data,original,trained,k)
                targets=depth_targets(data,record['gt_boxes'],record['gt_labels'],e,k,w,h,detector.categories)
                for t in targets:
                    i=t['prediction'];name=detector.categories[t['class']]
                    before=float(abs(data['centers'][i,2]-t['depth']))
                    after=float(abs(changed['centers'][i,2]-t['depth']))
                    depth_before.append(before);depth_after.append(after)
                    row=depth_by_class.setdefault(name,{'before':[],'after':[]})
                    row['before'].append(before);row['after'].append(after)
            path=output/('frames-'+label)/(record['key'].replace(':','_')+'.npz')
            save_npz(path,lidar_boxes=record['boxes'],lidar_scores=record['scores'],rgb_baseline_boxes=b,
                     rgb_baseline_scores=s,rgb_depth_boxes=nb,rgb_depth_scores=ns,
                     gt_boxes=record['gt_boxes'],gt_labels=record['gt_labels'])
            paths.append(path)
            if (j+1)%25==0:print('REPLAY',label,j+1,'/',len(rows),flush=True)
        diagnostic={'definition':'MAE on offline image-matched camera/object observations; repeats across views/frames',
                    'count':len(depth_before),
                    'mae_before_m':float(np.mean(depth_before)) if depth_before else None,
                    'mae_after_m':float(np.mean(depth_after)) if depth_after else None,
                    'by_class':{k:{'count':len(v['before']),'mae_before_m':float(np.mean(v['before'])),
                                   'mae_after_m':float(np.mean(v['after']))} for k,v in depth_by_class.items()}}
        return metrics_from_paths(paths),diagnostic

    train_metrics,train_depth=evaluate(train,'train')
    records,val_provenance=read_inputs(base,output/'validation-loader',0,200)
    validation=records['validation']
    if len(validation)!=200 or records['train']:raise ValueError('Expected validation200 only AFTER freeze')
    if {r['sequence'].split('_crossing')[0] for r in train}&{r['sequence'].split('_crossing')[0] for r in validation}:
        raise ValueError('Overlapping original recording groups')
    print('LOAD validation200 AFTER freeze; no further fitting',flush=True)
    validation_metrics,validation_depth=evaluate(validation,'validation')
    if sha(model_path.read_bytes())!=freeze['model_sha256']:raise ValueError('Model changed during evaluation')
    if sha((runtime/'ready.json').read_bytes())!=runtime_before:raise ValueError('Source runtime marker changed')
    for name,expected in OUTDOOR_ASSETS.items():
        if sha((model_dir/name).read_bytes())!=expected:raise ValueError('Source official model was modified')
    report={'schema':SCHEMA,'protocol':protocol,'train_metrics':train_metrics,'validation_metrics':validation_metrics,
            'freeze':freeze,'native_categories':detector.categories,
            'depth_diagnostics':{'train':train_depth,'validation':validation_depth},
            'trained_parameters':sum(r['adapted'] for r in support)*(original['weight'].shape[1]+1),
            'validation_provenance':val_provenance,'seconds':time.monotonic()-started,
            'limitations':['Native depth layer only; no 2D/class/size/pose/score training',
                'No new object proposals: misses/occlusion and false positives remain',
                'TRAIN has two original recordings; validation is one previously inspected development recording',
                'No independent crossing3 result or guaranteed multimodal improvement',
                'GT projected image matches are offline supervision only; inference uses RGB features/K/classes',
                'Original raw confidence fusion unchanged and uncalibrated across detectors']}
    write_json(output/'report.json',report)
    lines=['# Native RGB depth-head adaptation\n','400 TRAIN /200 development-validation; fixed readout-only fit.\n',
           '| Variant | TRAIN BEV mAP@.5 (%) | VAL BEV mAP@.5 (%) |','|---|---:|---:|']
    for v in VARIANTS:
        a=train_metrics[v]['global_confidence_sort']['macro_ap']['0.5']
        b=validation_metrics[v]['global_confidence_sort']['macro_ap']['0.5']
        lines.append(f'| {v} | {"N/A" if a is None else f"{100*a:.4f}"} | {"N/A" if b is None else f"{100*b:.4f}"} |')
    lines+=['\nNo validation parameter selection; previously inspected development data, not an independent test.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    archive=output/'urbaning-rgb3d-depth-controlled.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ['protocol.json','report.json','summary.md','source-pilot-report.json']:z.write(output/name,name)
        for directory in ['models','frames-train','frames-validation']:
            for p in sorted((output/directory).glob('*')):
                if p.is_file():z.write(p,str(p.relative_to(output)))
        for p in sorted((output/'features').glob('*.json')):z.write(p,'feature-receipts/'+p.name)
    write_json(output/'completed.json',{'sha256':sha(archive.read_bytes()),'model_sha256':freeze['model_sha256'],
                                       'protocol_sha256':protocol_sha})
    print('\n'.join(lines),flush=True);print('DONE:',archive,flush=True)
    return archive
