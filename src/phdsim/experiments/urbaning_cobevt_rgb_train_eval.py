"""Read-only frozen-model TRAIN evaluation after controlled adapter validation.

No fitting, image encoder or LiDAR backbone. TRAIN inference uses existing
feature caches; validation metrics come from the checksum-verified completed
source archive. Compare changes to the original detector within EACH split.
"""
import argparse
import fcntl
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import torch

from phdsim.experiments import urbaning_cobevt_rgb_controlled as c
from phdsim.perception.urbaning.cobevt_rgb_training import BoundedAdapter, original_heads

SCHEMA='phdsim-cobevt-rgb-frozen-train-eval-v1'
AS_TRAINED='lidar_rgb_shuffled_train_control_as_trained'
VARIANTS=(*c.MODES,AS_TRAINED)


def code_identity():
    root=Path(__file__).parents[3]
    paths=[Path(__file__),root/'scripts/urbaning_cobevt_rgb_train_eval.py',
           root/'scripts/slurm/urbaning_cobevt_rgb_train_eval.sbatch']
    return {str(p.relative_to(root)):c.sha256(p) for p in paths}


def configuration(source,threads):
    return {'schema':SCHEMA,'code':code_identity(),'source':str(source),'threads':threads,
            'operation':'evaluate fixed final models; no fitting or checkpoint selection',
            'source_protocol_sha256':c.sha256(source/'protocol.json'),
            'source_completed_sha256':c.sha256(source/'completed.json'),
            'source_report_sha256':c.sha256(source/'report.json'),
            'primary':'same 4-class global-sort BEV VOC mAP@.5; no F1 substitution',
            'train_variants':list(VARIANTS),'validation':'reuse verified completed source reports',
            'no_source_writes':True,'crossing3_access':False,'peer_requests':0}


def bind_configuration(source,output,threads):
    if source==output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Audit output and source must be separate non-nested directories')
    output.mkdir(parents=True,exist_ok=True);expected=configuration(source,threads)
    path=output/'protocol.json'
    # Two array workers may initialize this output simultaneously. Lock the
    # short protocol write, not the entire evaluation process.
    with (output/'protocol.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if path.exists() and json.loads(path.read_text())!=expected:
            raise ValueError('Audit configuration changed; use a new output')
        if not path.exists():c.write_json(path,expected)
    return expected


def verify_source(base,source,seed,threads):
    """Bind protocol, normalizers, models and receipts to the completed ZIP."""
    completed=json.loads((source/'completed.json').read_text())
    archive=source/'urbaning-cobevt-rgb-controlled.zip'
    if c.sha256(archive)!=completed['sha256']:raise ValueError('Completed controlled archive changed')
    selected=['protocol.json','inventory.json','normalizers.json','report.json',
              f'seeds/{seed}/freeze.json',f'seeds/{seed}/report.json']
    selected += [f'seeds/{seed}/{mode}/model-final.pt' for mode in c.MODES]
    selected += ['extraction/'+seq+'.json' for _,seq in c.SEQUENCES]
    with zipfile.ZipFile(archive) as z:
        for name in selected:
            if c.sha256(source/name)!=c.sha(z.read(name)):raise ValueError('Source differs from archive: '+name)
    protocol=json.loads((source/'protocol.json').read_text())
    inventory=json.loads((source/'inventory.json').read_text())
    normalizer=json.loads((source/'normalizers.json').read_text())
    report=json.loads((source/'seeds'/str(seed)/'report.json').read_text())
    collected=json.loads((source/'report.json').read_text())
    freeze=report['freeze'];protocol_sha=c.sha256(source/'protocol.json')
    if protocol['schema']!=c.SCHEMA or protocol['code']!=c.implementation():
        raise ValueError('Scientific source code differs from the controlled run')
    if (collected['protocol']!=protocol or not collected['independent_raw_prediction_ap_replay'] or
        next((r for r in collected['seeds'] if r['seed']==seed),None)!=report):
        raise ValueError('Validation report was not bound to the completed original replay')
    if protocol['base']!=str(base) or protocol['threads']!=threads:
        raise ValueError('Use original base path and CPU thread count')
    if (inventory['protocol_sha256']!=protocol_sha or normalizer['protocol_sha256']!=protocol_sha or
        freeze['protocol_sha256']!=protocol_sha or freeze['normalizers_sha256']!=c.sha256(source/'normalizers.json')):
        raise ValueError('Protocol/normalizer binding differs')
    if not normalizer['train_only'] or normalizer['keys']!=inventory['keys']['train']:
        raise ValueError('Expected unchanged TRAIN-only normalizers')
    if report['seed']!=seed or freeze['seed']!=seed or not report['head_weights_unchanged']:
        raise ValueError('Invalid frozen seed report')
    if freeze!=json.loads((source/'seeds'/str(seed)/'freeze.json').read_text()):
        raise ValueError('Freeze receipt differs')
    for mode,digest in freeze['models'].items():
        if c.sha256(source/'seeds'/str(seed)/mode/'model-final.pt')!=digest:
            raise ValueError('Frozen adapter changed')
    if inventory['model']!=c.verify_bundle(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3'):
        raise ValueError('Original detector bundle differs')
    return {'protocol':protocol,'inventory':inventory,'normalizer':normalizer,'seed_report':report,
            'source_archive_sha256':completed['sha256'],
            'files':{name:c.sha256(source/name) for name in selected}}


def verify_train_inventory(source,records,verified):
    expected=verified['inventory']['keys']['train']
    if [r['key'] for r in records]!=expected:raise ValueError('TRAIN inventory changed')
    validation=set(verified['inventory']['keys']['validation'])
    if any(r['key'] in validation or 'crossing3' in r['sequence'] for r in records):
        raise ValueError('Unexpected validation/test record in TRAIN evaluation')
    bindings={}
    for split,seq in c.SEQUENCES:
        if split=='train':
            rows=json.loads((source/'extraction'/(seq+'.json')).read_text())['frames']
            bindings.update({r['key']:r['manifest_sha256'] for r in rows})
    for record in records:
        path=c.feature_dir(source,record['key'])/'manifest.json'
        if c.sha256(path)!=bindings[record['key']]:raise ValueError('Feature manifest differs from extraction receipt')


def load_adapter(source,seed,mode,store,verified):
    path=source/'seeds'/str(seed)/mode/'model-final.pt'
    saved=torch.load(path,map_location='cpu',weights_only=True)
    freeze=verified['seed_report']['freeze'];protocol=verified['protocol']
    if (saved['mode']!=mode or saved['seed']!=seed or saved['configuration']!=protocol or
        saved['progress']['epoch']!=protocol['epochs'] or saved['progress']['next_frame']!=0 or
        saved['initial_state_sha256']!=freeze['initial_state_sha256'] or
        saved['parameter_count']!=freeze['parameter_count']):raise ValueError('Final model identity differs')
    if [r['epoch'] for r in saved['progress']['history']]!=list(range(1,protocol['epochs']+1)):
        raise ValueError('Final model epoch history differs')
    feature=store[0]
    model=BoundedAdapter(feature['bev'].shape[1]+feature['rgb'].shape[0]+2,
                        feature['bev'].shape[1],verified['normalizer']['normalizers']['lidar']['std'],
                        protocol['hidden_channels'])
    model.load_state_dict(saved['model'],strict=True);model.eval().requires_grad_(False)
    return model,saved['progress']['history']


def aggregate(statistics):
    total=c.aggregate_statistics(statistics)
    return {'global_confidence_sort':c.summarize_cached(total,True),
            'upstream_default_frame_order':c.summarize_cached(total,False),
            'frames':len(statistics),'peer_requests':0}


def raw_frame(path,record,digest):
    if c.sha256(path)!=digest:raise ValueError('Audit prediction changed')
    with np.load(path,allow_pickle=False) as z:
        if not np.array_equal(z['gt_boxes'],record['gt_boxes']) or not np.array_equal(z['gt_labels'],record['gt_labels']):
            raise ValueError('TRAIN evaluation GT changed')
        return z['boxes'].copy(),z['scores'].copy()


def evaluate(variant,records,store,runtime,directory,identity,normalizers,adapter=None,mode=None,shuffle=False):
    """Frozen heads/adapters only. Per-frame receipts allow an interrupted resume."""
    directory.mkdir(parents=True,exist_ok=True);binding=directory/'protocol.json'
    expected={**identity,'variant':variant,'mode':mode,'shuffle':shuffle,'keys':[r['key'] for r in records]}
    if binding.exists() and json.loads(binding.read_text())!=expected:raise ValueError('Variant identity changed')
    if not binding.exists():c.write_json(binding,expected)
    indices=c.far_shuffle(records);stats=[];groups={};losses=[];bindings=[];started=time.monotonic()
    with torch.no_grad():
        for i,record in enumerate(records):
            stem=record['key'].replace(':','_');path=directory/(stem+'.npz');receipt=directory/(stem+'.json')
            donor=records[indices[i] if shuffle else i]['key'] if adapter is not None and mode!='lidar_adapter' else None
            gt_sha=c.sha(record['gt_boxes'].tobytes()+record['gt_labels'].tobytes())
            row_identity={'key':record['key'],'gt_sha256':gt_sha,'rgb_donor':donor}
            if receipt.exists():
                row=json.loads(receipt.read_text())
                if row['identity']!=row_identity:raise ValueError('Resumed frame binding changed')
                boxes,scores=raw_frame(path,record,row['sha256'])
            else:
                feature=store[i];bev=feature['bev'];regularizer=0.
                if adapter is not None:
                    visual=store[indices[i]]['rgb'] if shuffle else feature['rgb']
                    bev,raw=adapter(bev,c.mode_context(mode,feature,visual,normalizers))
                    regularizer=float(identity['residual_penalty']*raw.square().mean())
                outputs=original_heads(*runtime.heads,bev)
                detection=runtime.loss(outputs,store.target(i))
                loss={'detection':float(detection),'classification':float(runtime.loss.loss_dict['conf_loss']),
                      'regression':float(runtime.loss.loss_dict['reg_loss']),'regularizer':regularizer}
                if not all(np.isfinite(v) for v in loss.values()):raise ValueError('Non-finite frozen-model loss')
                boxes,scores=runtime.decode(outputs)
                np.savez_compressed(path,boxes=boxes,scores=scores,gt_boxes=record['gt_boxes'],gt_labels=record['gt_labels'])
                row={'identity':row_identity,'file':path.name,'sha256':c.sha256(path),'loss':loss}
                c.write_json(receipt,row)
            if set(row['loss'])!={'detection','classification','regression','regularizer'} or not all(np.isfinite(v) for v in row['loss'].values()):
                raise ValueError('Invalid frozen-model loss receipt')
            stat=c.frame_statistics(boxes,scores,record['gt_boxes'],record['gt_labels']);stats.append(stat)
            groups.setdefault(c.recording_group(record['sequence']),[]).append(stat)
            losses.append(row['loss']);bindings.append(row)
            if i==0 or (i+1)%25==0:
                elapsed=time.monotonic()-started
                print(f'TRAIN EVAL {variant} {i+1}/{len(records)} elapsed={elapsed/60:.1f}min',flush=True)
    result={'metrics':aggregate(stats),'per_recording':{g:aggregate(rows) for g,rows in groups.items()},
            'frozen_model_train_loss':{k:float(np.mean([r[k] for r in losses])) for k in losses[0]},
            'input_condition':'far-shuffled RGB' if shuffle else 'aligned/local evidence',
            'diagnostic_only':True}
    c.write_json(directory/'manifest.json',{'identity':expected,'bindings':bindings,'result':result})
    return result


def assert_source_unchanged(source,verified):
    for name,digest in verified['files'].items():
        if c.sha256(source/name)!=digest:raise ValueError('Source changed during read-only evaluation: '+name)


def run_seed(base,source,output,upstream,threads,seed):
    audit=bind_configuration(source,output,threads)
    verified=verify_source(base,source,seed,threads)
    directory=output/'seeds'/str(seed);directory.mkdir(parents=True,exist_ok=True)
    if (directory/'report.json').exists():
        report=json.loads((directory/'report.json').read_text())
        if report['audit']!=audit:raise ValueError('Completed audit seed configuration differs')
        for variant,expected in report['train'].items():
            if replay_variant(directory/('train-'+variant))[0]!=expected:raise ValueError('Completed audit seed metrics changed')
        assert_source_unchanged(source,verified)
        print('REUSE TRAIN evaluation seed',seed,flush=True);return
    c.prepare_upstream(upstream)
    config=c.load_config(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3')
    heads=c.load_frozen_heads(base/'models/urbaning/CoBEVT_SIS_1_2_vs_3');runtime=c.native_runtime(config,heads)
    snapshot=[{k:v.clone() for k,v in h.state_dict().items()} for h in heads]
    records,_=c.load_records(base,output,'seed-'+str(seed)+'-TRAIN',200,0)
    train=records['train'];verify_train_inventory(source,train,verified)
    store=c.FeatureStore(source,train);normalizers=verified['normalizer']['normalizers']
    identity={'audit_protocol_sha256':c.sha256(output/'protocol.json'),
              'source_archive_sha256':verified['source_archive_sha256'],'seed':seed,
              'normalizers_sha256':c.sha256(source/'normalizers.json'),
              'residual_penalty':verified['protocol']['residual_penalty']}
    results={};histories={}
    # The original detector is seed-independent: evaluate it once, in worker0.
    if seed==0:
        results['original_lidar']=evaluate('original_lidar',train,store,runtime,directory/'train-original_lidar',
                                            {**identity,'model_sha256':verified['inventory']['model']['files']['best_model.pth']},normalizers)
    for mode in c.MODES:
        adapter,histories[mode]=load_adapter(source,seed,mode,store,verified)
        model_identity={**identity,'model_sha256':verified['seed_report']['freeze']['models'][mode]}
        results[mode]=evaluate(mode,train,store,runtime,directory/('train-'+mode),model_identity,normalizers,adapter,mode)
        if mode=='lidar_rgb_shuffled_train_control':
            # Its actual fitting condition used far-shuffled TRAIN RGB. Keep
            # this diagnostic distinct from the aligned TRAIN/VAL comparison.
            results[AS_TRAINED]=evaluate(AS_TRAINED,train,store,runtime,directory/('train-'+AS_TRAINED),
                                        model_identity,normalizers,adapter,mode,shuffle=True)
        if any(p.grad is not None or p.requires_grad for p in adapter.parameters()):raise ValueError('Adapter was not frozen')
    for head,old in zip(heads,snapshot):
        if any(not torch.equal(v,old[k]) for k,v in head.state_dict().items()):raise ValueError('Frozen head changed')
        if any(p.grad is not None or p.requires_grad for p in head.parameters()):raise ValueError('Head was not frozen')
    assert_source_unchanged(source,verified)
    result={'schema':SCHEMA,'seed':seed,'audit':audit,'train':results,'training_history':histories,
            'validation':verified['seed_report']['metrics'],'source':verified,
            'no_fitting':True,'source_files_unchanged':True,'crossing3_access':False}
    c.write_json(directory/'report.json',result)
    print('DONE TRAIN EVAL SEED',seed,flush=True)


def replay_variant(directory):
    manifest=json.loads((directory/'manifest.json').read_text());statistics=[];groups={};bindings=[]
    for row in manifest['bindings']:
        path=directory/row['file']
        if c.sha256(path)!=row['sha256']:raise ValueError('TRAIN raw export changed')
        with np.load(path,allow_pickle=False) as z:
            if c.sha(z['gt_boxes'].tobytes()+z['gt_labels'].tobytes())!=row['identity']['gt_sha256']:
                raise ValueError('TRAIN GT export changed')
            stat=c.frame_statistics(z['boxes'],z['scores'],z['gt_boxes'],z['gt_labels'])
        statistics.append(stat)
        group=c.recording_group(row['identity']['key'].split(':')[0]);groups.setdefault(group,[]).append(stat)
        bindings.append((row['identity']['key'],row['identity']['gt_sha256']))
    result=manifest['result']
    if aggregate(statistics)!=result['metrics']:raise ValueError('Independent TRAIN AP replay differs')
    if {g:aggregate(rows) for g,rows in groups.items()}!=result['per_recording']:
        raise ValueError('Independent TRAIN recording AP replay differs')
    recomputed_loss={k:float(np.mean([r['loss'][k] for r in manifest['bindings']]))
                     for k in ('detection','classification','regression','regularizer')}
    if recomputed_loss!=result['frozen_model_train_loss']:raise ValueError('Frozen loss aggregation differs from frame receipts')
    return result,bindings


def ap(metrics,name=None):
    selected=metrics['global_confidence_sort']
    value=selected['macro_ap']['0.5'] if name is None else selected['classes'][name]['ap']['0.5']
    return None if value is None else 100*value


def delta(a,b):return None if a is None or b is None else a-b
def display(value):return 'N/A' if value is None else f'{value:.4f}'


def collect(base,source,output,threads):
    audit=bind_configuration(source,output,threads)
    if (output/'completed.json').exists():
        archive=output/'urbaning-cobevt-rgb-train-eval.zip'
        if c.sha256(archive)!=json.loads((output/'completed.json').read_text())['sha256']:raise ValueError('Audit archive changed')
        print('REUSE completed:',archive,flush=True);return
    reports=[json.loads((output/'seeds'/str(seed)/'report.json').read_text()) for seed in c.SEEDS]
    if [r['seed'] for r in reports]!=list(c.SEEDS):raise ValueError('Audit seed inventory changed')
    verify_source(base,source,0,threads)
    original=reports[0]['train']['original_lidar'];bindings=None
    for report in reports:
        if report['audit']!=audit or not report['no_fitting']:raise ValueError('Audit report identity differs')
        assert_source_unchanged(source,report['source'])
        for variant,expected in report['train'].items():
            value,keys=replay_variant(output/'seeds'/str(report['seed'])/('train-'+variant))
            if value!=expected:raise ValueError('Seed report differs from TRAIN export')
            if bindings is not None and keys!=bindings:raise ValueError('TRAIN frame/GT differs across models')
            bindings=keys
    baseline_val=reports[0]['validation']['original_lidar'];rows=[];paired=[];classes=[]
    for report in reports:
        if report['validation']['original_lidar']!=baseline_val:raise ValueError('Validation baseline differs across seeds')
        for variant in ('original_lidar',*VARIANTS):
            train=original if variant=='original_lidar' else report['train'][variant]
            validation=report['validation'].get(variant)
            train_ap=ap(train['metrics']);val_ap=None if validation is None else ap(validation)
            rows.append({'seed':report['seed'],'variant':variant,'train400_map_percent':train_ap,
                         'validation200_map_percent':val_ap,
                         'train_delta_vs_original_pp':delta(train_ap,ap(original['metrics'])),
                         'validation_delta_vs_original_pp':delta(val_ap,ap(baseline_val)),
                         'frozen_train_detection_loss':train['frozen_model_train_loss']['detection'],
                         'train_input_condition':train['input_condition']})
            for name in train['metrics']['global_confidence_sort']['classes']:
                classes.append({'seed':report['seed'],'variant':variant,'class':name,
                    'train_ap_percent':ap(train['metrics'],name),
                    'validation_ap_percent':None if validation is None else ap(validation,name),
                    'train_delta_vs_original_pp':delta(ap(train['metrics'],name),ap(original['metrics'],name)),
                    'validation_delta_vs_original_pp':None if validation is None else delta(ap(validation,name),ap(baseline_val,name))})
        paired.append({'seed':report['seed'],
                       'train_rgb_minus_lidar_pp':delta(ap(report['train']['lidar_rgb_adapter']['metrics']),
                                                     ap(report['train']['lidar_adapter']['metrics'])),
                       'validation_rgb_minus_lidar_pp':delta(ap(report['validation']['lidar_rgb_adapter']),
                                                          ap(report['validation']['lidar_adapter']))})
    result={'schema':SCHEMA,'audit':audit,'rows':rows,'per_class':classes,'paired_rgb_minus_lidar':paired,
            'seeds':reports,'independent_train_ap_replay':True,
            'limitations':['TRAIN and validation have different recordings/difficulty; compare baseline-relative changes in each split',
                'Use per-recording TRAIN results, not only pooled TRAIN400',
                'TRAIN is in-sample diagnostic, not independent accuracy evidence',
                'The as-trained shuffled-input row has no matching original validation condition; validation is N/A',
                'Frozen detection loss and epoch-average optimization loss are different quantities; neither replaces AP',
                'Validation is the same previously inspected recording; no new blind test, fitting or checkpoint selection',
                'TRAIN-improves/validation-worsens supports a generalization gap, not a unique explanation of its cause']}
    means=[]
    fields=('train400_map_percent','train_delta_vs_original_pp','validation200_map_percent','validation_delta_vs_original_pp')
    for variant in ('original_lidar',*VARIANTS):
        selected=[row for row in rows if row['variant']==variant]
        means.append({'variant':variant,**{key:None if any(row[key] is None for row in selected)
                       else float(np.mean([row[key] for row in selected])) for key in fields}})
    result['mean_across_seeds']=means
    c.write_json(output/'report.json',result)
    lines=['# Frozen adapter TRAIN/validation diagnosis','',
           'No fitting or backbone/image-encoder inference. Same final models/normalizers; primary metric BEV mAP@.5.',
           '','| Mean over seeds | TRAIN400 mAP (%) | TRAIN change vs LiDAR (pp) | VAL200 mAP (%) | VAL change vs LiDAR (pp) |',
           '|---|---:|---:|---:|---:|']
    for row in means:lines.append('| '+row['variant']+' | '+' | '.join(display(row[k]) for k in fields)+' |')
    compact=lines.copy()
    lines += ['','## Per seed',
           '','| Seed | Variant | TRAIN400 mAP (%) | TRAIN change vs LiDAR (pp) | VAL200 mAP (%) | VAL change vs LiDAR (pp) |',
           '|---:|---|---:|---:|---:|---:|']
    for row in rows:
        values=[row[k] for k in ('train400_map_percent','train_delta_vs_original_pp','validation200_map_percent','validation_delta_vs_original_pp')]
        lines.append(f'| {row["seed"]} | {row["variant"]} | '+' | '.join(display(v) for v in values)+' |')
    lines+=['','## TRAIN by original recording','',
            '| Seed | Variant | Recording | TRAIN mAP (%) | Change vs original LiDAR (pp) |','|---:|---|---|---:|---:|']
    for report in reports:
        for variant in ('original_lidar',*VARIANTS):
            train=original if variant=='original_lidar' else report['train'][variant]
            for group,metrics in train['per_recording'].items():
                value=ap(metrics);baseline=ap(original['per_recording'][group])
                lines.append(f'| {report["seed"]} | {variant} | {group} | {display(value)} | {display(delta(value,baseline))} |')
    lines+=['','## RGB minus LiDAR adapter','',
            '| Seed | TRAIN difference (pp) | Validation difference (pp) |','|---:|---:|---:|']
    for row in paired:lines.append(f'| {row["seed"]} | {display(row["train_rgb_minus_lidar_pp"])} | {display(row["validation_rgb_minus_lidar_pp"])} |')
    lines+=['',*result['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n');print('\n'.join(compact),flush=True)
    print('Per-seed, per-class, per-recording AP and frozen losses are in report.json / summary.md.',flush=True)
    archive=output/'urbaning-cobevt-rgb-train-eval.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('protocol.json','report.json','summary.md'):z.write(output/name,name)
        for path in sorted((output/'seeds').rglob('*')):
            if path.is_file():z.write(path,str(path.relative_to(output)))
    c.write_json(output/'completed.json',{'sha256':c.sha256(archive),'bytes':archive.stat().st_size})
    print('DONE:',archive,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','source','output','upstream'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--stage',choices=('seed','collect'),required=True)
    p.add_argument('--seed',type=int,choices=c.SEEDS,default=0);p.add_argument('--cpu-threads',type=int,default=8)
    a=p.parse_args()
    if a.cpu_threads<1:p.error('Positive thread count required')
    if torch.__version__!='2.6.0+cpu' or np.__version__!='1.26.4':raise RuntimeError('Use original pinned CPU runtime')
    torch.set_num_threads(a.cpu_threads)
    base,source,output,upstream=[getattr(a,k).resolve() for k in ('base','source','output','upstream')]
    if a.stage=='seed':run_seed(base,source,output,upstream,a.cpu_threads,a.seed)
    else:collect(base,source,output,a.cpu_threads)


if __name__=='__main__':main()
