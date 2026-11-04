"""Train-only gap/partner diagnostics; validation replay, no detector or test."""
import argparse
import io
import json
from pathlib import Path
import platform
import time
import zipfile

import numpy as np

from phdsim.experiments.urbaning_regional_learning import load_dataset,sha,write_json
from phdsim.learning.urbaning_gap_forests import PARAMETERS,PROFILES,fit_forest,predict

K=10


def load(path):
    data,manifest,mhash=load_dataset(path)  # strict crossing3 guard before NPZ reads
    extra={s:{'fn':[],'gain':[],'keys':[]} for s in ('train','validation')}
    with zipfile.ZipFile(path) as z:
        for row in manifest['sequences']:
            name=row['split']+'/'+row['sequence']+'/offline-targets.npz'
            raw=z.read(name)
            if sha(raw)!=row['files'][name]: raise ValueError('Labels changed after dataset verification')
            with np.load(io.BytesIO(raw),allow_pickle=False) as a:
                extra[row['split']]['fn'].append(a['counts'][:,:400,0,:,2].sum(axis=-1))
                d=a['delta_vs_ego'][:,:400,1:]
                extra[row['split']]['gain'].append(-(d[:,:,:,:,1]+d[:,:,:,:,2]).sum(axis=-1).astype(float))
                extra[row['split']]['keys'].append(a['frame_keys'])
    for split,d in data.items():
        for name in extra[split]:extra[split][name]=np.concatenate(extra[split][name])
        if not np.array_equal(extra[split]['keys'],d['frame_keys']): raise ValueError('Target alignment mismatch')
        d.update(fn=extra[split]['fn'],net_gain=extra[split]['gain'])
    return data,manifest,mhash


def top_indices(scores,k,allowed=None):
    scores=np.asarray(scores,float)
    if scores.ndim!=1: raise ValueError('Expected one frame of scores')
    ids=np.arange(len(scores)) if allowed is None else np.flatnonzero(allowed)
    if len(ids)<k or not np.isfinite(scores[ids]).all(): raise ValueError('Not enough finite candidates')
    # Deterministic cell-index tie handling, no GT-dependent tie breaking.
    return ids[np.lexsort((ids,-scores[ids]))[:k]]


def gap_metrics(scores,fn,empty):
    scores=np.asarray(scores);truth=np.asarray(fn)>0
    if scores.shape!=truth.shape or empty.shape!=truth.shape or scores.shape[1]!=400: raise ValueError('Unaligned gap arrays')
    result={}
    for name,allowed in [('all_cells',np.ones_like(empty)),('empty_cells',empty)]:
        hit=[];random=[];recall=[];n=0
        for p,y,a in zip(scores,truth,allowed):
            if a.sum()<K:continue
            ix=top_indices(p,K,a);hit.append(float(y[ix].mean()));random.append(float(y[a].mean()))
            if y[a].sum():recall.append(float(y[ix].sum()/y[a].sum()))
            n+=1
        result[name]={'frames':n,'k':K,'precision_at_k':float(np.mean(hit)) if n else None,
            'random_precision_expected':float(np.mean(random)) if n else None,
            'mean_recall_at_k_on_positive_frames':float(np.mean(recall)) if recall else None,
            'positive_frame_support':len(recall)}
    result['brier_all_cells']=float(np.mean((scores-truth)**2))
    return result


def benefit_metrics(predicted,truth,available):
    if predicted.shape!=truth.shape or predicted.shape[1:]!=(400,3): raise ValueError('Unaligned benefit arrays')
    precision=[];random=[];random_partner=[];values=[];frames=0
    for p,t,a in zip(predicted,truth,available[:,1:]):
        if not a.any():continue
        if not np.isfinite(p[:,a]).all() or not np.isnan(p[:,~a]).all(): raise ValueError('Availability not masked')
        safe=np.where(a[None],p,-np.inf)
        actions=np.argmax(safe,axis=1);scores=safe[np.arange(400),actions]
        cells=top_indices(scores,K);selected=t[cells,actions[cells]]
        precision.append(float(np.mean(selected>0)));values.append(float(selected.mean()))
        # Exact expectation of uniform K distinct cells + uniform feasible action.
        random.append(float(np.mean(t[:,a]>0)))
        random_partner.append(float(np.mean(t[cells][:,a]>0)))
        frames+=1
    if not frames: return {'available_frames':0}
    return {'available_frames':frames,'k_distinct_regions':K,
        'positive_benefit_precision_at_k':float(np.mean(precision)),
        'pure_random_expected_precision':float(np.mean(random)),
        'same_selected_regions_random_partner_expected_precision':float(np.mean(random_partner)),
        'mean_selected_local_error_reduction':float(np.mean(values)),
        'scope':'Local labels from full-frame fusion outcomes; not ROI transmission or a valid mixed-frame detector result'}


def run(dataset,output,n_jobs=4):
    import sklearn
    if np.__version__!='1.26.4' or sklearn.__version__!='1.8.0': raise RuntimeError('Use existing isolated NumPy 1.26.4 / sklearn 1.8.0 runtime')
    out=Path(output).resolve()
    if out.exists(): raise FileExistsError('Preserve previous results; use a new output directory')
    data,manifest,mhash=load(dataset)
    out.mkdir(parents=True);(out/'models').mkdir()
    protocol={'schema':'phdsim-urbaning-gap-pilot-v1','dataset_manifest_sha256':mhash,
        'dataset_sha256':sha(Path(dataset).read_bytes()),'recording_groups':manifest['recording_groups'],
        'frames':manifest['frames'],'spatial_cells_per_frame':400,'overflow_excluded_from_spatial_ranking':True,
        'profiles':{p:list(v) for p,v in PROFILES.items()},'input_features':manifest['features'],
        'parameters':PARAMETERS,'top_k':K,'selection':'none; all three predefined variants retained; no validation tuning',
        'gap_target':'at least one Car1 false negative in cell, globally matched at BEV IoU .5',
        'benefit_target':'-(delta FP+delta FN) summed over four classes; independently for each feasible subset',
        'random':'exact expected top10 precision of uniform distinct cells and uniform feasible action; no GT-dependent schedule',
        'limits':['already inspected development recordings','400 training frames in 2 recordings; 200 validation in 1',
                  'no detector mAP, query savings or physical visibility claims','GT/peer outcomes supply offline targets only'],
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'sklearn':sklearn.__version__}}
    write_json(out/'protocol.json',protocol)
    train,val=data['train'],data['validation'];x=train['features'][:,:400];labels=train['fn']>0
    report={'protocol':protocol,'status':'completed','validation':{},'models_sha256':{},'training_seconds':{}}
    predictions={}
    for profile in PROFILES:
        start=time.monotonic();print('FIT',profile,'gap + three feasible subset heads',flush=True)
        model={'gap':fit_forest(x.reshape(-1,46),labels.ravel(),profile,classification=True,n_jobs=n_jobs),'benefit':{}}
        for j,action in enumerate(('vehicle_peer','infrastructure','all')):
            mask=train['available'][:,j+1]
            model['benefit'][action]=fit_forest(x[mask].reshape(-1,46),train['net_gain'][mask,:,j].ravel(),profile,
                                               classification=False,n_jobs=n_jobs)
        # Persist frozen weights before reading validation outcomes for scoring.
        raw=json.dumps(model,separators=(',',':'),allow_nan=False).encode()
        (out/'models'/f'{profile}.json').write_bytes(raw)
        report['models_sha256'][profile]=sha(raw)
        gap,gain=predict(model,val['features'][:,:400],val['available'])
        empty=val['features'][:,:400,10]>.5
        scores={'gap':gap_metrics(gap,val['fn'],empty),
                'benefit':benefit_metrics(gain,val['net_gain'],val['available'])}
        report['validation'][profile]=scores
        report['training_seconds'][profile]=time.monotonic()-start
        predictions[profile+'_gap']=gap;predictions[profile+'_benefit']=gain
        write_json(out/'progress.json',report)
        print('RESULT',profile,json.dumps(scores),flush=True)
    np.savez_compressed(out/'offline-validation-predictions.npz',**predictions,
        frame_keys=val['frame_keys'],available=val['available'],fn=val['fn'],net_gain=val['net_gain'])
    report['source_sha256']={str(p.relative_to(Path(__file__).parents[3])):sha(p.read_bytes()) for p in
        (Path(__file__),Path(__file__).parents[1]/'learning/urbaning_gap_forests.py',Path(__file__).with_name('urbaning_regional_learning.py'))}
    write_json(out/'report.json',report)
    lines=['# Gap and source pilot — development validation only','',
        '400 train frames / two original recordings; 200 validation / one original recording. No crossing3 reads or detector calls. '
        'Same ExtraTrees capacity for all feature profiles; no parameter or variant selection on validation.',
        '', '| Features | Gap: positive top10 cells (%) | Gap random (%) | Empty cells: positive top10 (%) | Empty random (%) | Helpful region+subset top10 (%) | Pure random (%) |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name,r in report['validation'].items():
        g=r['gap'];b=r['benefit'];v=[g['all_cells']['precision_at_k'],g['all_cells']['random_precision_expected'],
            g['empty_cells']['precision_at_k'],g['empty_cells']['random_precision_expected'],
            b['positive_benefit_precision_at_k'],b['pure_random_expected_precision']]
        lines.append('| '+name+' | '+' | '.join(f'{100*x:.3f}' for x in v)+' |')
    lines+=['','Gap precision means at least one missed GT in a selected cell. Helpful means local FP+FN reduction >0 after whole-frame fusion. '
        'These are spatial diagnostic ranking metrics, not detection mAP or query savings. '
        'Top10 proposals do not imply ten independent partner requests or a working ROI transmission scheme.',
        '', 'Empty means no Car1 detection centroid in a 10m cell, not physical free/unknown space. '
        'Metadata are assumed available before querying; Infra pose remains a site-origin proxy. '
        'Cells/adjacent frames are correlated. Models are frozen prototypes, not new blind-test evidence.','']
    (out/'RESULTS.md').write_text('\n'.join(lines))
    members=[p for p in out.rglob('*') if p.is_file()]
    write_json(out/'files.json',{str(p.relative_to(out)):sha(p.read_bytes()) for p in members})
    archive=out/'urbaning-gap-pilot.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file() and p!=archive:z.write(p,str(p.relative_to(out)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Output CRC failure')
    print((out/'RESULTS.md').read_text(),flush=True)
    print('SHA256',sha(archive.read_bytes()),'bytes',archive.stat().st_size,flush=True)
    print('DONE:',archive,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--cpu-threads',type=int,default=4)
    a=p.parse_args(argv);run(a.dataset,a.output_dir,a.cpu_threads)
