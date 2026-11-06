"""Controlled CPU adapter development experiment:400 TRAIN,200 held-out frames.

Cache native features once; fit TRAIN-only normalization/targets; run three
paired seeds and fixed final-epoch models. No acquisition, crossing3 or RGB-only
detector. All model selection on this validation recording is prohibited.
"""
import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import random
import time
import zipfile
from functools import lru_cache

import numpy as np
import torch

from phdsim.evaluation.urbaning_cached import frame_statistics, aggregate_statistics, summarize_cached
from phdsim.experiments.urbaning_rgb_pilot import read_inputs, camera_fields, sha, write_json, WEIGHTS_SHA
from phdsim.experiments.urbaning_bev_cpu import add_point_bindings, atomic_torch
from phdsim.experiments.urbaning_stage1 import prepare_upstream, load_model, capture_sources
from phdsim.experiments.urbaning_cobevt_rgb_train import (
    PREFLIGHT_SHA, PARITY_LIMITS, ground_prior, load_frozen_heads, native_runtime,
    verify_native_parity,
)
from phdsim.learning.urbaning import recording_group
from phdsim.perception.urbaning.bundle import verify_bundle, load_config, sha256
from phdsim.perception.urbaning.cobevt import subset_inputs
from phdsim.perception.urbaning.cobevt_rgb_adapter import capture_fused_bev, metric_grid
from phdsim.perception.urbaning.cobevt_rgb_training import (
    SpatialEncoder, lift_rectangular, channel_normalizer, rgb_mask, context,
    BoundedAdapter, original_heads, fit_normalizers,
)

SCHEMA='phdsim-cobevt-rgb-controlled-v1'
SEQUENCES=(('train','20241126_0001_crossing2_00'),
           ('train','20241126_0017_crossing1_00'),
           ('validation','20241126_0004_crossing2_00'))
MODES=('lidar_adapter','lidar_rgb_adapter','lidar_rgb_shuffled_train_control')
SEEDS=(0,1,2)
EPOCHS=32


def implementation():
    from phdsim.perception.urbaning import cobevt_rgb_training, cobevt_rgb_adapter, cobevt
    from phdsim.experiments import urbaning_cobevt_rgb_train, urbaning_rgb_pilot
    paths=[Path(__file__),Path(cobevt_rgb_training.__file__),Path(cobevt_rgb_adapter.__file__),
           Path(cobevt.__file__),Path(urbaning_cobevt_rgb_train.__file__),Path(urbaning_rgb_pilot.__file__),
           Path(__file__).with_name('urbaning_stage1.py'),
           Path(__file__).with_name('urbaning_bev_cpu.py'),
           Path(__file__).parents[1]/'evaluation/urbaning_cached.py',
           Path(__file__).parents[1]/'evaluation/urbaning.py',
           Path(__file__).parents[1]/'perception/urbaning/bev_cpu.py',
           Path(__file__).parents[1]/'perception/urbaning/bundle.py',
           Path(__file__).parents[1]/'learning/urbaning.py',
           Path(__file__).parents[3]/'scripts/urbaning_rgb_env.py']
    return {str(p.relative_to(Path(__file__).parents[3])):sha256(p) for p in paths}


def protocol(base,threads):
    return {'schema':SCHEMA,'code':implementation(),'base':str(base),'threads':threads,
            'seeds':list(SEEDS),'epochs':EPOCHS,'learning_rate':.001,'weight_decay':1e-4,
            'residual_penalty':1e-4,'gradient_clip':1.,'hidden_channels':16,
            'train_modes':list(MODES),'selection':'final epoch only; no validation search',
            'normalization':'TRAIN only; RGB observed cells only',
            'feature_dtype':'LiDAR float32, RGB float16->float32',
            'bev_memory_format':'channels_last after lossless load',
            'feature_preprocess_seed':'new forwards:sha256(key) first8 hex digits, NumPy/Python/torch; reviewed8 caches retain original preprocessing',
            'shuffle':'GT-free half-recording cyclic rotation, separately within each split',
            'shuffled_training_control_evaluation':'aligned validation RGB; same inputs as aligned-trained model',
            'parity_limits':PARITY_LIMITS,
            'primary':'4-class BEV VOC mAP@IoU.5, global confidence sort,0-100m corner radius',
            'primary_comparison':'paired lidar_rgb_adapter minus lidar_adapter',
            'validation_scope':'previously inspected development recording, not a blind test',
            'crossing3_access':False,'peer_requests':0}


def bind_protocol(base,output,threads):
    output.mkdir(parents=True,exist_ok=True)
    path=output/'protocol.json';expected=protocol(base,threads)
    if path.exists():
        if json.loads(path.read_text())!=expected:raise ValueError('Protocol/source changed; use a new output')
    else:write_json(path,expected)
    return expected


def check_inventory(records):
    keys=set();groups={}
    for split in ('train','validation'):
        expected={seq for part,seq in SEQUENCES if part==split}
        found={r['sequence'] for r in records[split]}
        if expected!=found:raise ValueError('Unexpected recording inventory')
        for seq in expected:
            if sum(r['sequence']==seq for r in records[split])!=200:raise ValueError('Expected200 frames per sequence')
        groups[split]={recording_group(r['sequence']) for r in records[split]}
        for row in records[split]:
            if row['key'] in keys or 'crossing3' in row['sequence']:raise ValueError('Duplicate key or crossing3')
            keys.add(row['key'])
    if groups['train']&groups['validation']:raise ValueError('Original recording overlaps across splits')


def load_records(base,output,tag,train=200,validation=200):
    path=output/'loaders'/tag;path.mkdir(parents=True,exist_ok=True)
    return read_inputs(base,path,train,validation)


def inventory(base,output,configuration):
    records,provenance=load_records(base,output,'inventory')
    check_inventory(records)
    manifest={'schema':SCHEMA,'protocol_sha256':sha256(output/'protocol.json'),
              'source':provenance,'ground_z_train_only':ground_prior(records['train']),
              'keys':{s:[r['key'] for r in values] for s,values in records.items()},
              'counts':{s:len(values) for s,values in records.items()},
              'model':verify_bundle(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3')}
    path=output/'inventory.json'
    if path.exists() and json.loads(path.read_text())!=manifest:raise ValueError('Inventory changed')
    write_json(path,manifest)
    print('INVENTORY TRAIN400 / validation200; disjoint original recordings; ground prior TRAIN only',flush=True)


def far_shuffle(records):
    """No labels/scores: rotate sorted keys by half each original recording."""
    groups={};result=list(range(len(records)))
    for i,r in enumerate(records):groups.setdefault(recording_group(r['sequence']),[]).append(i)
    for ids in groups.values():
        ids.sort(key=lambda i:records[i]['key'])
        if len(ids)<2:raise ValueError('Need two frames per recording for shuffle')
        shift=len(ids)//2
        for a,b in zip(ids,ids[shift:]+ids[:shift]):result[a]=b
    return result


def feature_dir(output,key):return output/'features'/key.replace(':','_')


def verify_files(directory,receipt):
    for name,expected in receipt['files'].items():
        if sha256(directory/name)!=expected:raise ValueError('Cached file changed: '+str(directory/name))


def image_payloads(record):
    import cv2
    p=Path(record['yaml']);raw=[p.with_name(p.stem+'_camera'+str(i)+'.png').read_bytes() for i in range(6)]
    images=[cv2.imdecode(np.frombuffer(value,np.uint8),cv2.IMREAD_COLOR) for value in raw]
    if any(im is None for im in images):raise ValueError('Unreadable bound camera payload')
    return images,{str(i):sha(b) for i,b in enumerate(raw)}


@lru_cache(maxsize=1)
def preflight_rows(base):
    preflight=base/'runs/urbaning-cobevt-rgb-preflight-21597293'
    archive=preflight/'urbaning-cobevt-rgb-preflight.zip'
    if sha256(archive)!=PREFLIGHT_SHA:raise ValueError('Reviewed preflight identity differs')
    with zipfile.ZipFile(archive) as z:report=json.loads(z.read('report.json'))
    return preflight,{row['key']:row for row in report['frames']}


def reused_preflight(base,record):
    preflight,previous=preflight_rows(base)
    if record['key'] not in previous:return None
    row=previous[record['key']]
    if record['native_association']!=row['native_association']:raise ValueError('Reviewed native binding differs')
    path=preflight/'features'/(record['key'].replace(':','_')+'.npz')
    if sha256(path)!=row['cache_sha256']:raise ValueError('Reviewed feature changed')
    with np.load(path,allow_pickle=False) as z:values={k:z[k].copy() for k in ('bev','xy','psm','rm')}
    return values,{'kind':'reviewed_preflight','sha256':row['cache_sha256']},row['cameras']


def extract_sequence(base,upstream,output,weights,configuration,index,max_frames=None):
    split,sequence=SEQUENCES[index]
    records,provenance=load_records(base,output,'extract-'+str(index),200 if split=='train' else 0,
                                    200 if split=='validation' else 0)
    chosen=[r for r in records[split] if r['sequence']==sequence]
    if len(chosen)!=200:raise ValueError('Sequence frame count changed')
    if max_frames is not None:chosen=chosen[:max_frames]
    # Read only selected point payloads, keeping the original trace/hash binding.
    add_point_bindings({'selected':chosen},provenance)
    inv=json.loads((output/'inventory.json').read_text())
    expected=[k for k in inv['keys'][split] if k.startswith(sequence+':')]
    if [r['key'] for r in chosen]!=expected[:max_frames]:
        raise ValueError('Selected inventory changed')
    prepare_upstream(upstream)
    config=load_config(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3')
    heads=load_frozen_heads(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3');runtime=native_runtime(config,heads)
    weight_file=weights/'checkpoints/mobilenet_v3_small-047dcff4.pth'
    if sha256(weight_file)!=WEIGHTS_SHA:raise ValueError('Official RGB weights changed')
    encoder=SpatialEncoder(weights,configuration['threads'])
    model=None;dataset=None;indices={};receipts=[];started=time.monotonic()
    from opencood.data_utils.datasets import build_dataset
    from opencood.tools.train_utils import to_device
    for number,record in enumerate(chosen,1):
        directory=feature_dir(output,record['key']);directory.mkdir(parents=True,exist_ok=True)
        images,image_hashes=image_payloads(record)
        identity={'key':record['key'],'protocol_sha256':sha256(output/'protocol.json'),
                  'yaml_sha256':sha256(record['yaml']),'lidar':record['lidar_source'],
                  'images':image_hashes,'native_association':record['native_association'],
                  'ground_z_train_only':inv['ground_z_train_only'],'encoder':encoder.identity}
        meta=directory/'manifest.json'
        if meta.exists():
            receipt=json.loads(meta.read_text())
            if receipt['identity']!=identity:raise ValueError('Feature identity differs')
            verify_files(directory,receipt);receipts.append({'key':record['key'],'manifest_sha256':sha256(meta)})
            if number%10==0:print('REUSE FEATURES',sequence,number,'/200',flush=True)
            continue
        reuse=reused_preflight(base,record) if split=='train' else None
        if reuse is not None:
            value,origin,cameras=reuse
            if {str(c['camera']):c['image_sha256'] for c in cameras}!=image_hashes:
                raise ValueError('Reviewed RGB payload changed')
        else:
            if model is None:
                model,_=load_model(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3',torch.device('cpu'))
                effective=dict(config);effective['validate_dir']=str(Path(record['yaml']).parents[2])
                effective['train_params']={**config['train_params'],'specific_ego_id':100000}
                dataset=build_dataset(effective,visualize=False,train=False,specific_scenario=sequence)
                for i in range(len(dataset)):
                    scene,offset=dataset.retrieve_by_idx(i)
                    indices[sequence+':'+dataset.return_timestamp_key(scene,offset)+':100000']=i
            seed=int(hashlib.sha256(record['key'].encode()).hexdigest()[:8],16)
            random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
            position=indices[record['key']];scene,offset=dataset.retrieve_by_idx(position)
            timestamp=dataset.return_timestamp_key(scene,offset)
            files=scene[next(k for k in scene if str(k)=='100000')][timestamp]
            if (Path(files['yaml']).resolve()!=Path(record['yaml']).resolve() or
                Path(files['lidar']).resolve()!=Path(record['lidar_source']['path']).resolve()):
                raise ValueError('Native dataset source differs from verified source')
            item,sources=capture_sources(dataset,position)
            if str(sources['included_ids'][0])!='100000':raise ValueError('Car1 must be first')
            batch=to_device(dataset.collate_batch_test([item]),torch.device('cpu'))
            bev,logits,_=capture_fused_bev(model,subset_inputs(batch['ego'],(0,)))
            value={'bev':bev.numpy(),'xy':metric_grid(bev.shape[-2:],config['model']['args']['lidar_range']),
                   **{k:v.numpy() for k,v in logits.items()}}
            origin={'kind':'new_native_forward','per_frame_seed':seed}
        bev=torch.from_numpy(np.array(value['bev'],copy=True)).float().contiguous(memory_format=torch.channels_last)
        if tuple(bev.shape)!=(1,256,100,256):raise ValueError('Native feature shape differs')
        np.testing.assert_array_equal(value['xy'],metric_grid((100,256),config['model']['args']['lidar_range']))
        origin['native_values_sha256']=sha(value['bev'].tobytes()+value['psm'].tobytes()+value['rm'].tobytes())
        feature={'bev':bev,'cache_sha256':origin['native_values_sha256'],
                 **{k:torch.from_numpy(np.array(value[k],copy=True)) for k in ('psm','rm')}}
        parity=verify_native_parity([record],[feature],runtime,directory/'native-parity.json')
        rgb=lift_rectangular(encoder(images),camera_fields(record['yaml']),
                             [im.shape[1::-1] for im in images],value['xy'],inv['ground_z_train_only'])
        target=runtime.target(record) if split=='train' else None
        np.save(directory/'bev.npy',bev.numpy(),allow_pickle=False)
        quantized=rgb.numpy().astype(np.float16)
        if not np.isfinite(quantized).all():raise ValueError('RGB quantization is not finite')
        np.save(directory/'rgb.npy',quantized,allow_pickle=False)
        np.savez_compressed(directory/'native-logits.npz',**{k:value[k] for k in ('psm','rm')})
        names=['bev.npy','rgb.npy','native-logits.npz','native-parity.json']
        if target is not None:
            np.savez_compressed(directory/'targets.npz',**{k:v.numpy() for k,v in target.items()});names+=['targets.npz']
        receipt={'identity':identity,'origin':origin,'files':{name:sha256(directory/name) for name in names},
                 'parity_passed':parity['matching_and_ap_identical'],
                 'native_metrics':parity['metrics'],'gt_count':len(record['gt_labels'])}
        write_json(meta,receipt);receipts.append({'key':record['key'],'manifest_sha256':sha256(meta)})
        elapsed=time.monotonic()-started
        print(f'FEATURES {sequence} {number}/{len(chosen)} elapsed={elapsed/60:.1f}min origin={origin["kind"]}',flush=True)
    summary=output/('extraction-smoke' if max_frames is not None else 'extraction');summary.mkdir(exist_ok=True)
    write_json(summary/(sequence+'.json'),{'sequence':sequence,'split':split,'frames':receipts})
    print('DONE FEATURES',sequence,flush=True)


def smoke(base,upstream,output,weights,configuration):
    """Disposable native startup/update gate BEFORE the expensive feature array."""
    extract_sequence(base,upstream,output,weights,configuration,0,max_frames=2)
    records,_=load_records(base,output,'smoke',200,0)
    chosen=[r for r in records['train'] if r['sequence']==SEQUENCES[0][1]][:2]
    store=FeatureStore(output,chosen);features=[store[i] for i in range(2)]
    normalizers=fit_normalizers(features)  # probe only; never save as real TRAIN normalization
    prepare_upstream(upstream);heads=load_frozen_heads(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3')
    runtime=native_runtime(load_config(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3'),heads)
    snapshot=[{k:v.clone() for k,v in h.state_dict().items()} for h in heads];rows=[]
    for mode in MODES:
        torch.manual_seed(0)
        model=BoundedAdapter(256+features[1]['rgb'].shape[0]+2,256,normalizers['lidar']['std'],16)
        optimizer=torch.optim.AdamW(model.parameters(),lr=configuration['learning_rate'],weight_decay=configuration['weight_decay'])
        f=features[1];visual=features[0]['rgb'] if mode==MODES[2] else f['rgb']
        x=mode_context(mode,f,visual,normalizers);bev,raw=model(f['bev'],x)
        if not torch.equal(bev,f['bev']):raise ValueError('Native zero-start adapter changed features')
        loss=runtime.loss(original_heads(*heads,bev),store.target(1))+configuration['residual_penalty']*raw.square().mean()
        if not bool(loss.isfinite()):raise ValueError('Native probe loss is not finite')
        loss.backward();norm=torch.nn.utils.clip_grad_norm_(model.parameters(),configuration['gradient_clip'])
        if not bool(norm.isfinite()) or float(norm)==0:raise ValueError('Native probe gradient is invalid/zero')
        optimizer.step()
        with torch.no_grad():
            updated,_=model(f['bev'],x);boxes,_=runtime.decode(original_heads(*heads,updated))
        rows.append({'mode':mode,'initial_loss':float(loss.detach()),'gradient_norm':float(norm),'decoded_after_one_update':len(boxes)})
    for head,old in zip(heads,snapshot):
        if any(not torch.equal(v,old[k]) for k,v in head.state_dict().items()):raise ValueError('Probe changed frozen heads')
        if any(p.grad is not None for p in head.parameters()):raise ValueError('Probe populated frozen head gradients')
    write_json(output/'smoke.json',{'status':'passed','keys':[r['key'] for r in chosen],'rows':rows,
                                  'scope':'2 TRAIN frames, disposable numerical check; probe weights/normalizers discarded'})
    print('SMOKE PASSED native reuse/new-forward, RGB, targets,3 one-update probes and decoder; probe weights discarded',flush=True)


class FeatureStore:
    """Disk-backed cache, bounded to two decoded frames; never load400 contexts."""
    def __init__(self,output,records):
        self.output=output;self.records=records;self.recent=OrderedDict()
        self.xy=metric_grid((100,256),[-102.4,-40,-5,102.4,40,3])
        protocol_sha=sha256(output/'protocol.json')
        for record in records:
            directory=feature_dir(output,record['key']);meta=json.loads((directory/'manifest.json').read_text())
            if meta['identity']['key']!=record['key'] or meta['identity']['protocol_sha256']!=protocol_sha:
                raise ValueError('Cache protocol/key differs')
            if meta['identity']['yaml_sha256']!=sha256(record['yaml']):raise ValueError('Bound YAML changed')
            verify_files(directory,meta)
    def __len__(self):return len(self.records)
    def __getitem__(self,index):
        if index not in self.recent:
            directory=feature_dir(self.output,self.records[index]['key'])
            bev=np.load(directory/'bev.npy',allow_pickle=False,mmap_mode='r').copy()
            rgb=np.load(directory/'rgb.npy',allow_pickle=False,mmap_mode='r').astype(np.float32)
            self.recent[index]={'bev':torch.from_numpy(bev).float().contiguous(memory_format=torch.channels_last),
                                'rgb':torch.from_numpy(rgb),'xy':self.xy}
        self.recent.move_to_end(index)
        while len(self.recent)>2:self.recent.popitem(last=False)
        return self.recent[index]
    def target(self,index):
        path=feature_dir(self.output,self.records[index]['key'])/'targets.npz'
        with np.load(path,allow_pickle=False) as z:return {k:torch.from_numpy(z[k].copy()).float() for k in z.files}


class FieldSequence:
    def __init__(self,store,field,transform=lambda x:x):self.store=store;self.field=field;self.transform=transform
    def __getitem__(self,index):
        if index>=len(self.store):raise IndexError(index)
        return self.transform(self.store[index][self.field])
    def __len__(self):return len(self.store)


def prepare_training(base,output,configuration):
    records,_=load_records(base,output,'normalizers',200,0)
    store=FeatureStore(output,records['train'])
    lidar=FieldSequence(store,'bev',lambda x:x[0]);rgb=FieldSequence(store,'rgb',lambda x:x[:-4])
    masks=FieldSequence(store,'rgb',rgb_mask)
    normalizers={'lidar':channel_normalizer(lidar),'rgb':channel_normalizer(rgb,masks)}
    result={'normalizers':normalizers,'keys':[r['key'] for r in records['train']],
            'protocol_sha256':sha256(output/'protocol.json'),'train_only':True}
    path=output/'normalizers.json'
    if path.exists() and json.loads(path.read_text())!=result:raise ValueError('TRAIN normalizers changed')
    write_json(path,result)
    mapping=far_shuffle(records['train'])
    write_json(output/'train-shuffle.json',{'mapping':{r['key']:records['train'][mapping[i]]['key'] for i,r in enumerate(records['train'])}})
    print('PREPARED TRAIN-only normalization and far-frame shuffle; validation not loaded',flush=True)


def mode_context(mode,feature,visual,normalizers):
    return context(feature['bev'],visual,'lidar_adapter' if mode=='lidar_adapter' else 'lidar_rgb_adapter',
                   normalizers,feature['xy'])


def fit_adapter(mode,seed,records,store,heads,runtime,normalizers,directory,configuration):
    directory.mkdir(parents=True,exist_ok=True);torch.manual_seed(seed)
    sample=store[0];model=BoundedAdapter(256+sample['rgb'].shape[0]+2,256,normalizers['lidar']['std'],16)
    optimizer=torch.optim.AdamW(model.parameters(),lr=configuration['learning_rate'],weight_decay=configuration['weight_decay'])
    start={k:v.detach().clone() for k,v in model.state_dict().items()}
    initial_sha=sha(b''.join(v.numpy().tobytes() for v in start.values()))
    mapping=far_shuffle(records);checkpoint=directory/'checkpoint.pt'
    with torch.no_grad():
        probe,_=model(sample['bev'],mode_context(mode,sample,sample['rgb'],normalizers))
        if not torch.equal(probe,sample['bev']):raise ValueError('Zero-start adapter changed native features')
    state={'epoch':0,'next_frame':0,'sum':{},'history':[]};new_steps=0;started=time.monotonic()
    if checkpoint.exists():
        saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
        if saved['configuration']!=configuration or saved['mode']!=mode or saved['seed']!=seed:
            raise ValueError('Checkpoint identity differs')
        model.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer']);state=saved['progress']
    def save():
        atomic_torch(checkpoint,{'configuration':configuration,'mode':mode,'seed':seed,
                                'model':model.state_dict(),'optimizer':optimizer.state_dict(),'progress':state})
    for epoch in range(state['epoch'],configuration['epochs']):
        order=np.random.default_rng(seed+epoch).permutation(len(store))
        for position in range(state['next_frame'],len(order)):
            i=int(order[position]);feature=store[i]
            visual=store[mapping[i]]['rgb'] if mode=='lidar_rgb_shuffled_train_control' else feature['rgb']
            x=mode_context(mode,feature,visual,normalizers)
            optimizer.zero_grad(set_to_none=True)
            corrected,raw=model(feature['bev'],x)
            detection=runtime.loss(original_heads(*heads,corrected),store.target(i))
            regularizer=configuration['residual_penalty']*raw.square().mean();objective=detection+regularizer
            if not bool(objective.isfinite()):raise ValueError('Non-finite loss')
            objective.backward();norm=torch.nn.utils.clip_grad_norm_(model.parameters(),configuration['gradient_clip'])
            if not bool(norm.isfinite()):raise ValueError('Non-finite gradient')
            optimizer.step()
            values={'detection':float(detection.detach()),'classification':float(runtime.loss.loss_dict['conf_loss'].detach()),
                    'regression':float(runtime.loss.loss_dict['reg_loss'].detach()),'regularizer':float(regularizer.detach())}
            for k,value in values.items():state['sum'][k]=state['sum'].get(k,0.)+value
            state['epoch']=epoch;state['next_frame']=position+1;new_steps+=1
            if new_steps==1 or new_steps%100==0:
                elapsed=time.monotonic()-started;remaining=(configuration['epochs']-epoch)*len(store)-position-1
                print(f'TRAIN seed={seed} {mode} epoch={epoch+1}/{configuration["epochs"]} '
                      f'frame={position+1}/{len(store)} loss={values["detection"]:.5f} '
                      f'mean_step={elapsed/new_steps:.3f}s model_remaining~{remaining*elapsed/new_steps/60:.1f}min',flush=True)
            if new_steps%100==0:save()
        state['history'].append({'epoch':epoch+1,**{k:v/len(store) for k,v in state['sum'].items()}})
        print('EPOCH',seed,mode,state['history'][-1],flush=True)
        state.update(epoch=epoch+1,next_frame=0,sum={});save()
    result={'configuration':configuration,'mode':mode,'seed':seed,'initial_state_sha256':initial_sha,
            'model':model.state_dict(),'progress':state,'parameter_count':sum(p.numel() for p in model.parameters())}
    atomic_torch(directory/'model-final.pt',result);write_json(directory/'history.json',state['history'])
    return model,result


def evaluate_model(records,store,runtime,directory,adapter=None,mode=None,normalizers=None,shuffle=False):
    directory.mkdir(parents=True,exist_ok=True);statistics=[];bindings=[];mapping=far_shuffle(records)
    with torch.no_grad():
        for i,record in enumerate(records):
            feature=store[i];bev=feature['bev']
            if adapter is not None:
                donor=mapping[i] if shuffle else i
                visual=store[donor]['rgb']
                bev,_=adapter(bev,mode_context(mode,feature,visual,normalizers))
            boxes,scores=runtime.decode(original_heads(*runtime.heads,bev))
            statistics.append(frame_statistics(boxes,scores,record['gt_boxes'],record['gt_labels']))
            name=record['key'].replace(':','_')+'.npz';path=directory/name
            np.savez_compressed(path,boxes=boxes,scores=scores,gt_boxes=record['gt_boxes'],gt_labels=record['gt_labels'])
            bindings.append({'key':record['key'],'file':name,'sha256':sha256(path),
                             'gt_sha256':sha(record['gt_boxes'].tobytes()+record['gt_labels'].tobytes()),
                             'rgb_donor':records[mapping[i] if shuffle else i]['key'] if adapter is not None and mode!='lidar_adapter' else None})
            if (i+1)%25==0:print('EVALUATE',directory.name,i+1,'/',len(records),flush=True)
    total=aggregate_statistics(statistics)
    result={'global_confidence_sort':summarize_cached(total,True),
            'upstream_default_frame_order':summarize_cached(total,False),'frames':len(records),'peer_requests':0}
    write_json(directory/'manifest.json',{'bindings':bindings,'metrics':result})
    return result


def seed_worker(base,upstream,output,configuration,index):
    seed=SEEDS[index];directory=output/'seeds'/str(seed);directory.mkdir(parents=True,exist_ok=True)
    if (directory/'report.json').exists():
        report=json.loads((directory/'report.json').read_text());frozen=report['freeze']
        if (frozen['protocol_sha256']!=sha256(output/'protocol.json') or
            frozen['normalizers_sha256']!=sha256(output/'normalizers.json')):raise ValueError('Completed seed identity changed')
        for mode,digest in frozen['models'].items():
            if sha256(directory/mode/'model-final.pt')!=digest:raise ValueError('Completed seed model changed')
        for mode,expected in report['metrics'].items():
            if replay_predictions(directory/('validation-'+mode))[0]!=expected:raise ValueError('Completed seed predictions differ')
        print('REUSE completed seed',seed,flush=True);return
    prepare_upstream(upstream);config=load_config(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3')
    heads=load_frozen_heads(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3');runtime=native_runtime(config,heads)
    snapshot=[{k:v.clone() for k,v in h.state_dict().items()} for h in heads]
    records,_=load_records(base,output,'seed-'+str(seed)+'-train',200,0)
    normalizer=json.loads((output/'normalizers.json').read_text());train=records['train']
    if (normalizer['keys']!=[r['key'] for r in train] or not normalizer['train_only'] or
        normalizer['protocol_sha256']!=sha256(output/'protocol.json')):
        raise ValueError('TRAIN normalizer inventory differs')
    normalizers=normalizer['normalizers'];store=FeatureStore(output,train)
    trained={};initial=[];parameters=[]
    for mode in MODES:
        trained[mode],result=fit_adapter(mode,seed,train,store,heads,runtime,normalizers,directory/mode,configuration)
        initial.append(result['initial_state_sha256']);parameters.append(result['parameter_count'])
    if len(set(initial))!=1 or len(set(parameters))!=1:raise ValueError('Unmatched model initialization/capacity')
    frozen={'protocol_sha256':sha256(output/'protocol.json'),'normalizers_sha256':sha256(output/'normalizers.json'),
            'seed':seed,'models':{m:sha256(directory/m/'model-final.pt') for m in MODES},
            'initial_state_sha256':initial[0],'parameter_count':parameters[0],'final_epoch':configuration['epochs'],
            'validation_access':'No validation feature/label loaded by this worker before this freeze'}
    write_json(directory/'freeze.json',frozen)
    print('FROZEN all3 final models before validation access; seed=',seed,flush=True)
    del store
    # First validation records/features used by this fitting worker only AFTER all3 models are frozen.
    records,_=load_records(base,output,'seed-'+str(seed)+'-validation',0,200)
    validation=records['validation'];store=FeatureStore(output,validation)
    metrics={'original_lidar':evaluate_model(validation,store,runtime,directory/'validation-original_lidar')}
    for mode in MODES:
        # All training variants receive ALIGNED validation inputs. Separately test
        # sensitivity to shuffled validation inputs using the aligned-trained model.
        metrics[mode]=evaluate_model(validation,store,runtime,directory/('validation-'+mode),trained[mode],mode,
                                    normalizers,shuffle=False)
    metrics['lidar_rgb_shuffled_eval_diagnostic']=evaluate_model(validation,store,runtime,
        directory/'validation-lidar_rgb_shuffled_eval_diagnostic',trained['lidar_rgb_adapter'],
        'lidar_rgb_adapter',normalizers,shuffle=True)
    for head,old in zip(heads,snapshot):
        if any(not torch.equal(old[k],v) for k,v in head.state_dict().items()):raise ValueError('Frozen heads mutated')
    if any(sha256(directory/m/'model-final.pt')!=digest for m,digest in frozen['models'].items()):
        raise ValueError('Model changed after freeze')
    result={'seed':seed,'scope':'development validation200; fixed final epoch; no test/crossing3',
            'metrics':metrics,'freeze':frozen,'head_weights_unchanged':True,'train_frames':len(train),
            'validation_frames':len(validation),'validation_recordings':1}
    write_json(directory/'report.json',result)
    print('DONE SEED',seed,flush=True)


def replay_predictions(directory):
    manifest=json.loads((directory/'manifest.json').read_text());statistics=[]
    for binding in manifest['bindings']:
        path=directory/binding['file']
        if sha256(path)!=binding['sha256']:raise ValueError('Exported predictions changed')
        with np.load(path,allow_pickle=False) as z:
            if sha(z['gt_boxes'].tobytes()+z['gt_labels'].tobytes())!=binding['gt_sha256']:
                raise ValueError('Exported GT changed')
            statistics.append(frame_statistics(z['boxes'],z['scores'],z['gt_boxes'],z['gt_labels']))
    total=aggregate_statistics(statistics)
    metrics={'global_confidence_sort':summarize_cached(total,True),
             'upstream_default_frame_order':summarize_cached(total,False),
             'frames':len(statistics),'peer_requests':0}
    if metrics!=manifest['metrics']:raise ValueError('Independent raw-prediction AP replay differs')
    return metrics,[(b['key'],b['gt_sha256']) for b in manifest['bindings']]


def collect(output,configuration):
    if (output/'completed.json').exists():
        archive=output/'urbaning-cobevt-rgb-controlled.zip'
        if sha256(archive)!=json.loads((output/'completed.json').read_text())['sha256']:
            raise ValueError('Completed archive changed')
        print('REUSE completed:',archive,flush=True);return
    reports=[json.loads((output/'seeds'/str(seed)/'report.json').read_text()) for seed in SEEDS]
    if [r['seed'] for r in reports]!=list(SEEDS):raise ValueError('Unexpected seed inventory')
    rows={};primary=[];baseline=None;gt_bindings=None;classes={}
    for report in reports:
        seed_dir=output/'seeds'/str(report['seed'])
        if report['freeze']['protocol_sha256']!=sha256(output/'protocol.json'):raise ValueError('Frozen protocol changed')
        if report['freeze']['normalizers_sha256']!=sha256(output/'normalizers.json'):raise ValueError('Frozen normalizers changed')
        for mode,digest in report['freeze']['models'].items():
            if sha256(seed_dir/mode/'model-final.pt')!=digest:raise ValueError('Frozen model changed')
        current=report['metrics']['original_lidar']
        if baseline is not None and current!=baseline:raise ValueError('Baseline differs across seeds')
        baseline=current
        for mode,value in report['metrics'].items():
            replayed,bindings=replay_predictions(seed_dir/('validation-'+mode))
            if replayed!=value:raise ValueError('Seed report differs from raw predictions')
            if gt_bindings is not None and gt_bindings!=bindings:raise ValueError('Frame/GT differs across variants or seeds')
            gt_bindings=bindings
            ap=value['global_confidence_sort']['macro_ap']['0.5']
            if ap is None:raise ValueError('Four-class mAP undefined; do not silently average fewer classes')
            rows.setdefault(mode,[]).append(100*ap)
            for name,class_row in value['global_confidence_sort']['classes'].items():
                class_ap=class_row['ap']['0.5']
                classes.setdefault(mode,{}).setdefault(name,[]).append(None if class_ap is None else 100*class_ap)
        primary.append(rows['lidar_rgb_adapter'][-1]-rows['lidar_adapter'][-1])
    summary={mode:{'per_seed':values,'mean':float(np.mean(values)),
                   'seed_sd':float(np.std(values,ddof=1)),'min':min(values),'max':max(values)} for mode,values in rows.items()}
    result={'schema':SCHEMA,'protocol':configuration,'scope':'400 TRAIN,200 development validation;3 paired seeds',
            'primary_paired_delta_pp':{'per_seed':primary,'mean':float(np.mean(primary)),
                                     'seed_sd':float(np.std(primary,ddof=1))},
            'summary_map_percent':summary,'per_class_ap_percent':classes,'seeds':reports,
            'independent_raw_prediction_ap_replay':True,
            'limitations':['One previously inspected validation recording, not a blind test or recording-level CI',
                'Seed spread measures optimization variability, not independent recording uncertainty',
                'Official frozen checkpoint may have seen these development recordings',
                'Both adapters retain LiDAR; no RGB-only or multi-agent detector',
                'Native re-voxelization may differ from historical runs; use the shared NEW cached baseline',
                'Fixed height lifting has depth/occlusion ambiguity; all native image timing offsets retained offline',
                'Shuffled evaluation is an offline diagnostic, not a deployable method']}
    write_json(output/'report.json',result)
    lines=['# Controlled Car1 adapter development result','',
           f'400 TRAIN /200 separate development-validation frames;3 paired seeds;{configuration["epochs"]} fixed epochs;0 peer requests.',
           '','| Variant | Validation BEV mAP@.5 mean (%) | Seed SD (pp) | Seeds0/1/2 (%) |',
           '|---|---:|---:|---|']
    for mode,row in summary.items():
        lines.append(f'| {mode} | {row["mean"]:.4f} | {row["seed_sd"]:.4f} | '+', '.join(f'{v:.4f}' for v in row['per_seed'])+' |')
    lines+=['',f'Primary paired RGB-minus-trained-LiDAR delta: {np.mean(primary):+.4f} pp; seeds: '+', '.join(f'{v:+.4f}' for v in primary),
            '','| Variant | Vehicle AP (%) | Heavy_Vehicle AP (%) | 2Wheeler AP (%) | Pedestrian AP (%) |',
            '|---|---:|---:|---:|---:|']
    for mode,values in classes.items():
        display=['N/A' if None in v else f'{np.mean(v):.4f}' for v in values.values()]
        lines.append('| '+mode+' | '+' | '.join(display)+' |')
    lines+=['',*result['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines),flush=True)
    archive=output/'urbaning-cobevt-rgb-controlled.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('protocol.json','inventory.json','normalizers.json','train-shuffle.json','report.json','summary.md'):
            z.write(output/name,name)
        if (output/'smoke.json').exists():z.write(output/'smoke.json','smoke.json')
        for path in sorted((output/'seeds').rglob('*')):
            if path.is_file() and path.name!='checkpoint.pt':z.write(path,str(path.relative_to(output)))
        for path in sorted((output/'extraction').glob('*.json')):z.write(path,str(path.relative_to(output)))
    write_json(output/'completed.json',{'sha256':sha256(archive),'bytes':archive.stat().st_size})
    print('DONE:',archive,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','upstream','output','weights-dir'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--stage',choices=('inventory','smoke','extract','prepare','seed','collect'),required=True)
    p.add_argument('--index',type=int,default=0);p.add_argument('--cpu-threads',type=int,default=8)
    a=p.parse_args()
    if a.cpu_threads<1:p.error('Positive thread count required')
    if a.index not in range(3):p.error('Index must be0,1,2')
    if torch.__version__!='2.6.0+cpu' or np.__version__!='1.26.4':raise RuntimeError('Use pinned CPU runtime')
    torch.set_num_threads(a.cpu_threads)
    base=a.base.resolve();output=a.output.resolve()
    configuration=bind_protocol(base,output,a.cpu_threads)
    if a.stage=='inventory':inventory(base,output,configuration)
    elif a.stage=='smoke':smoke(base,a.upstream.resolve(),output,a.weights_dir.resolve(),configuration)
    elif a.stage=='extract':extract_sequence(base,a.upstream.resolve(),output,a.weights_dir.resolve(),configuration,a.index)
    elif a.stage=='prepare':prepare_training(base,output,configuration)
    elif a.stage=='seed':seed_worker(base,a.upstream.resolve(),output,configuration,a.index)
    else:collect(output,configuration)


if __name__=='__main__':main()
