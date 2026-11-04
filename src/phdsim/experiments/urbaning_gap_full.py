"""Frozen spatial acquisition on the existing 1400 crossing3 frames; no tuning."""
import argparse
import io
import json
import os
from pathlib import Path
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER,available_subsets,random_subset
from phdsim.decision.urbaning_gap_acquisition import choose
from phdsim.evaluation.urbaning_cached import frame_f1
from phdsim.experiments.urbaning_ap_replay import MODES,metrics_both_orders,same_metrics,validate_statistics
from phdsim.experiments.urbaning_gap_acquisition import ReplayCache,fixed_budget_random
from phdsim.experiments.urbaning_frozen_full import SEQUENCES,EXPECTED_FRAMES,SEQUENCE_FRAMES
from phdsim.experiments.urbaning_geometry import load_sidecars
from phdsim.experiments.urbaning_subsets import _inside,ensemble_summary
from phdsim.experiments.urbaning_regional_learning import sha,write_json
from phdsim.learning.urbaning_gap_forests import PROFILES,predict
from phdsim.learning.urbaning_regions import regional_features

SEEDS=tuple(range(100))
PURE_P=(.25,.5,.75,.9)
MODE='global_confidence_sort'
SCHEMA='phdsim-urbaning-gap-full-v1'


def verified_zip(path,expected_sha):
    raw=Path(path).read_bytes()
    if sha(raw)!=expected_sha:raise ValueError('Input ZIP SHA256 differs')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist())!=len(set(z.namelist())) or z.testzip() is not None:raise ValueError('Duplicate or corrupt ZIP members')
        members={n:z.read(n) for n in z.namelist()}
    for name,h in json.loads(members['files.json']).items():
        if sha(members[name])!=h:raise ValueError('ZIP member hash differs')
    return members


def load_deployment(path,checksum):
    """Validate weights/costs/splits before opening any crossing3 inputs."""
    members=verified_zip(path,checksum);report=json.loads(members['report.json'])
    raw=members['frozen-gap-acquisition-inputs.zip']
    if report['status']!='completed' or sha(raw)!=report['deployment_sha256']:raise ValueError('Invalid frozen deployment')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None or set(z.namelist())!={'deployment.json',*[f'models/{n}.json' for n in PROFILES]}:
            raise ValueError('Unexpected deployment members')
        cfg=json.loads(z.read('deployment.json'));p=cfg['protocol']
        if (p['schema']!='phdsim-urbaning-gap-acquisition-validation-v1' or p['numpy_version']!='1.26.4'
                or p!=report['protocol'] or p['recording_groups']!={'train':['20241126_0001','20241126_0017'],'validation':['20241126_0004']}):
            raise ValueError('Invalid frozen development split/protocol')
        expected=[{k:v for k,v in row.items() if k not in ('choices','metrics')} for row in report['selected']]
        if cfg['policies']!=expected or len(cfg['policies'])!=18:raise ValueError('Frozen policy configurations differ')
        models={}
        for name in PROFILES:
            raw=z.read(f'models/{name}.json')
            if sha(raw)!=p['frozen_model_sha256'][name]:raise ValueError('Frozen model changed')
            models[name]=json.loads(raw)
            # Exercise the portable interface with no observations or labels.
            x=np.zeros((1,400,46));mask=np.array([[True,False,False,False]])
            predict(models[name],x,mask)
    configs={f'spatial_{c["profile"]}_{c["aggregation"]}_valcap{c["budget_cap"]:g}':c
             for c in cfg['policies'] if c['status']=='validation-selected'}
    return cfg,models,configs,report['deployment_sha256']


def load_full_reference(path,checksum,detector):
    members=verified_zip(path,checksum);r=json.loads(members['report.json'])
    if (r['schema']!='phdsim-urbaning-frozen-full-report-v1' or r['status']!='completed'
            or r['frames']!=EXPECTED_FRAMES or r['runtime']['numpy']!='1.26.4'
            or r['provenance']['detector']!=detector):raise ValueError('Full reference identity differs')
    origins={row['sequence']:row for row in r['provenance']['inputs']}
    if set(origins)!=set(SEQUENCES):raise ValueError('Full sequence inventory differs')
    frames=[]
    for line in members['offline-statistics.jsonl'].decode().splitlines():
        row=json.loads(line);seq=row['sequence'];ids=row['source_ids']
        if (seq not in origins or not ids or ids[0]!='100000' or not row['key'].startswith(seq+':')
                or not row['key'].endswith(':100000') or origins[seq]['predictions_sha256'].get(row['prediction_path'])!=row['prediction_sha256']):
            raise ValueError('Full frame/payload binding differs')
        stats=validate_statistics(row['statistics'],available_subsets(ids))
        frames.append(dict(row,statistics=stats,quality={a:frame_f1(s) for a,s in stats.items()}))
    keys=[f['key'] for f in frames]
    if len(keys)!=EXPECTED_FRAMES or len(set(keys))!=EXPECTED_FRAMES or keys!=sorted(keys):raise ValueError('Full frame coverage/order differs')
    if any(sum(f['sequence']==s for f in frames)!=SEQUENCE_FRAMES for s in SEQUENCES):raise ValueError('Full sequence frame count differs')
    for name,choices in r['choices'].items():
        if set(choices)!=set(keys):raise ValueError('Historical choices coverage differs')
        measured=metrics_both_orders(frames,[choices[k] for k in keys])
        for mode in MODES:same_metrics(measured[mode],r['policies'][name][mode])
    print('PARITY: all historical policies reproduced on exact 1400 portable outcomes, both AP orders',flush=True)
    return frames,r


def public_features(cache_root,frames,provenance,sequence):
    """Only Car1 boxes/scores/entropy and shared poses leave this adapter."""
    origin=next(p for p in provenance['inputs'] if p['sequence']==sequence)
    root=(Path(cache_root)/sequence/'run').resolve();trace=root/'frames.jsonl'
    poses=root.parent/'poses.json'
    for path,h in ((root/'run.json',origin['run_sha256']),(trace,origin['trace_sha256']),
                   (poses,origin['geometry_sidecar_sha256'])):
        if sha(path.read_bytes())!=h:raise ValueError('Raw cache/pose header changed: '+str(path))
    run=json.loads((root/'run.json').read_text())
    if run['status']!='completed' or run['model']!=provenance['detector'] or run['arguments']['sequence']!=sequence:
        raise ValueError('Raw run identity differs')
    sidecar=load_sidecars([poses])[origin['trace_sha256']][0]
    rows={r['frame_key']:r for r in map(json.loads,trace.read_text().splitlines())}
    if len(rows)!=len(frames) or set(rows)!=set(f['key'] for f in frames) or set(sidecar['frames'])!=set(rows):
        raise ValueError('Raw trace/pose coverage differs')
    features=[];masks=[]
    for f in frames:
        row=rows[f['key']]
        if (row['sources']['included_ids']!=f['source_ids'] or row['predictions']!=f['prediction_path']
                or row['gt_sha256']!=f['gt_sha256']):raise ValueError('Trace-to-portable binding differs')
        path=_inside(root,row['predictions'])
        if sha(path.read_bytes())!=f['prediction_sha256']:raise ValueError('Car1 source NPZ changed')
        # The container also holds offline labels/peer outputs; never load those arrays.
        with np.load(path,allow_pickle=False) as data:
            x,mask=regional_features(f['source_ids'],row['ego_entropy_bits'],data['ego_boxes'],data['ego_scores'],sidecar['frames'][f['key']])
        features.append(x[:400]);masks.append(mask)
    return np.array(features),np.array(masks)


def frozen_choices(frames,reference,cfg,models,cache_root,out,protocol_sha):
    keys=[f['key'] for f in frames];lookup={k:i for i,k in enumerate(keys)}
    choices={name:[None]*len(frames) for name in cfg}
    checkpoints=out/'spatial-checkpoints';checkpoints.mkdir(exist_ok=True)
    for seq in SEQUENCES:
        subset=[f for f in frames if f['sequence']==seq]
        x,mask=public_features(cache_root,subset,reference['provenance'],seq)
        binding=sha(protocol_sha.encode()+x.tobytes()+mask.tobytes()+json.dumps([f['key'] for f in subset]).encode())
        for profile in PROFILES:
            path=checkpoints/f'{seq}-{profile}.npz'
            if path.exists():
                with np.load(path,allow_pickle=False) as p:
                    if p['binding'].item()!=binding:raise ValueError('Spatial checkpoint inputs differ')
                    gap,gain=p['gap'],p['benefit']
                    expected=sha(gap.tobytes()+gain.tobytes())
                    if p['scores_sha256'].item()!=expected:raise ValueError('Spatial checkpoint scores changed')
                print('REUSE SPATIAL',seq,profile,flush=True)
            else:
                print('PREDICT SPATIAL',seq,profile,len(subset),'frames',flush=True)
                gap,gain=predict(models[profile],x,mask)
                tmp=path.with_suffix('.tmp')
                with tmp.open('wb') as stream:np.savez_compressed(stream,binding=binding,gap=gap,benefit=gain,
                    scores_sha256=sha(gap.tobytes()+gain.tobytes()))
                os.replace(tmp,path)
            for name,c in cfg.items():
                if c['profile']!=profile:continue
                for f,g,y in zip(subset,gap,gain):choices[name][lookup[f['key']]]=choose(f['source_ids'],g,y,c['error_cost'],c['aggregation'])
        print('DONE SPATIAL',seq,flush=True)
    if any(None in values for values in choices.values()):raise ValueError('Incomplete frozen decisions')
    return choices


def ensemble(frames,actions,cache):
    results={mode:[] for mode in MODES}
    for n,choices in enumerate(actions,1):
        m=cache.evaluate(frames,choices)
        for mode in MODES:results[mode].append(m[mode])
        if n%25==0:print('RANDOM',n,'/100 seeds',flush=True)
    return {mode:ensemble_summary(values,SEEDS) for mode,values in results.items()}


def run(validation_zip,validation_sha,reference_zip,reference_sha,cache_root,output,resume=False):
    if np.__version__!='1.26.4':raise RuntimeError('Require NumPy 1.26.4 for AP confidence-tie parity')
    cfg,models,configs,deployment_sha=load_deployment(validation_zip,validation_sha)
    out=Path(output).resolve()
    if out.exists() and not resume:raise FileExistsError('Explicit --resume required for existing output')
    out.mkdir(parents=True,exist_ok=resume)
    root=Path(__file__).parents[1]
    paths=[Path(__file__),*[root/p for p in ('decision/urbaning_gap_acquisition.py','learning/urbaning_gap_forests.py',
        'learning/urbaning_regions.py','experiments/urbaning_ap_replay.py','experiments/urbaning_gap_acquisition.py',
        'experiments/urbaning_subsets.py','decision/urbaning.py','evaluation/urbaning_cached.py','evaluation/urbaning.py')]]
    protocol={'schema':SCHEMA,'scope':'1400 previously inspected crossing3 frames; no fitting, new tuning or blind-test claim',
        'validation_zip_sha256':validation_sha,'deployment_sha256':deployment_sha,'reference_zip_sha256':reference_sha,
        'sequences':list(SEQUENCES),'frames':EXPECTED_FRAMES,'frozen_policies':configs,'numpy_version':np.__version__,
        'primary_metric':'global-confidence-sort four-class BEV mAP@.5; default AP separate',
        'validation_budget_labels':'Annotations only. Actual crossing3 request totals are reported, not forced to validation caps.',
        'primary_transfer_point':'spatial_geometry_gap_top10_valcap1.5',
        'selection':'None on crossing3. Report every saved validation configuration unchanged.',
        'pure_random_probabilities':list(PURE_P),'random_seeds':list(SEEDS),
        'secondary_control':'Offline uniform random at each unique resulting total; no model schedule/histogram',
        'implementation_sha256':{str(p.relative_to(root.parents[1])):sha(p.read_bytes()) for p in paths}}
    path=out/'protocol.json'
    if path.exists():
        if json.loads(path.read_text())!=protocol:raise ValueError('Cannot resume different code, inputs or protocol')
    else:
        if any(out.iterdir()):raise ValueError('Nonempty output has no protocol')
        write_json(path,protocol)
    protocol_sha=sha(json.dumps(protocol,sort_keys=True).encode())
    # Frozen weights/configs/protocol verified and saved before first crossing3 read.
    frames,ref=load_full_reference(reference_zip,reference_sha,cfg['protocol']['detector'])
    decisions=frozen_choices(frames,ref,configs,models,cache_root,out,protocol_sha)
    keys=[f['key'] for f in frames]
    write_json(out/'frozen-choices.json',{'protocol_sha256':protocol_sha,'choices':{n:dict(zip(keys,c)) for n,c in decisions.items()}})
    cache=ReplayCache(out/'metric-checkpoints',protocol)
    results={n:cache.evaluate(frames,c) for n,c in decisions.items()}
    for n,m in results.items():print('PRIMARY',n,'mAP',100*m[MODE]['macro_ap']['0.5'],'requests',m[MODE]['peer_requests'],flush=True)
    pure=dict(ref['pure_random'])
    for p in PURE_P:
        if str(p) in pure:
            # Reuse the prior 100-seed result only after two-seed parity in both orders.
            for seed in (0,99):
                m=cache.evaluate(frames,[random_subset(f['source_ids'],f['key'],seed,p) for f in frames])
                for mode in MODES:same_metrics(m[mode],pure[str(p)][mode]['per_seed'][str(seed)])
            print('REUSE VERIFIED PURE RANDOM',p,flush=True)
        else:
            print('PURE RANDOM',p,flush=True)
            pure[str(p)]=ensemble(frames,([random_subset(f['source_ids'],f['key'],seed,p) for f in frames] for seed in SEEDS),cache)
    controls={}
    for total in sorted({m[MODE]['peer_requests'] for m in results.values()}):
        print('SECONDARY EXACT TOTAL RANDOM',total,flush=True)
        controls[str(total)]=ensemble(frames,(fixed_budget_random(frames,total,seed) for seed in SEEDS),cache)
        if any(v['peer_requests']!=total for v in controls[str(total)][MODE]['per_seed'].values()):raise ValueError('Random count mismatch')
    all_choices={**ref['choices'],**{n:dict(zip(keys,c)) for n,c in decisions.items()}}
    per_sequence={}
    for seq in SEQUENCES:
        subset=[f for f in frames if f['sequence']==seq]
        per_sequence[seq]={n:metrics_both_orders(subset,[c[f['key']] for f in subset]) for n,c in all_choices.items()}
    report={'schema':SCHEMA,'status':'completed','protocol':protocol,'frames':len(frames),
        'policies':{**ref['policies'],**results},'pure_random':pure,'secondary_fixed_total_random':controls,
        'per_sequence':per_sequence,'choices':all_choices,'provenance':ref['provenance']}
    write_json(out/'report.json',report)
    maximum=ref['policies']['all'][MODE];qmax=maximum['peer_requests'];apmax=maximum['macro_ap']['0.5']
    lines=['# Zamrożone polityki przestrzenne — pełne 1400 klatek crossing3','',
        'Te same 7 sekwencji co wcześniejsze wyniki. Bez dostrajania kosztów i wag na crossing3. '
        'Nagrania były wcześniej oglądane; to nie jest nowy ślepy test. '
        'Budżet w nazwie oznacza historyczny limit na walidacji, a nie wymuszoną liczbę pytań tutaj.', '',
        '| Polityka | mAP@.5 (%) | Zapytania | Oszczędność vs ALWAYS (%) | Strata mAP (pp) | Random przy tylu pytaniach: mAP (%) |',
        '|---|---:|---:|---:|---:|---:|']
    for name,by_mode in report['policies'].items():
        m=by_mode[MODE];q=m['peer_requests'];ap=m['macro_ap']['0.5']
        control=controls.get(str(q));random='—' if control is None else f'{100*control[MODE]["summary"]["map_0.5"]["mean"]:.4f}'
        lines.append(f'| {name} | {100*ap:.4f} | {q} | {100*(1-q/qmax):.2f} | {100*(apmax-ap):.4f} | {random} |')
    lines+=['','| Czysty random: każdy dostępny partner niezależnie | mAP (%) | Średnio pytań |','|---|---:|---:|']
    for p in PURE_P:
        s=pure[str(p)][MODE]['summary'];lines.append(f'| p={p}, 100 ziaren | {100*s["map_0.5"]["mean"]:.4f} | {s["peer_requests"]["mean"]:.2f} |')
    lines+=['','10 wskazanych pól to wybór spośród wszystkich 400. Decyzja dotyczy całego partnera w klatce, '
        'nie przesyłania osobnych pól. GT służy wyłącznie do zapisanej oceny. Infra ma pozycję przybliżoną początkiem '
        'układu miejsca. Liczba zapytań nie mierzy bajtów ani opóźnienia. '
        'Dokładnie równy koszt randoma jest dodatkową kontrolą po fakcie; rozrzut ziaren nie jest niepewnością między nagraniami.','']
    (out/'WYNIKI_PL.md').write_text('\n'.join(lines))
    archive=out/'urbaning-gap-full.zip'
    members=[p for p in out.iterdir() if p.is_file() and p.name not in ('files.json',archive.name) and p.suffix!='.tmp']
    members+=list((out/'spatial-checkpoints').glob('*.npz'))
    write_json(out/'files.json',{str(p.relative_to(out)):sha(p.read_bytes()) for p in members})
    with zipfile.ZipFile(archive.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in members+[out/'files.json']:z.write(p,str(p.relative_to(out)))
    os.replace(archive.with_suffix('.tmp'),archive)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Final ZIP CRC failure')
    print((out/'WYNIKI_PL.md').read_text(),flush=True)
    print('SHA256',sha(archive.read_bytes()),'bytes',archive.stat().st_size,flush=True)
    print('DONE:',archive,flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('validation-zip','validation-sha','reference-zip','reference-sha','cache-root','output-dir'):parser.add_argument('--'+n,required=True)
    parser.add_argument('--resume',action='store_true')
    a=parser.parse_args(argv)
    run(a.validation_zip,a.validation_sha,a.reference_zip,a.reference_sha,a.cache_root,a.output_dir,a.resume)
