"""Development-only factorial replay: separate gap localization and partner benefit."""
import argparse
import json
import os
from pathlib import Path
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER,available_subsets
from phdsim.decision.urbaning_gap_acquisition import ERROR_COSTS,choose
from phdsim.experiments.urbaning_ap_replay import MODES,load_archive,same_metrics
from phdsim.experiments.urbaning_gap_acquisition import (
    BUDGETS,MODE,SEEDS,ReplayCache,bind_validation,fixed_budget_random,random_ensemble)
from phdsim.experiments.urbaning_gap_acquisition_job import stage
from phdsim.experiments.urbaning_regional_learning import load_dataset,sha,write_json

PAIRS=(('geometry','geometry'),('local','local'),('local','geometry'),('geometry','local'))


def replay_pair(frames,predictions,gap_profile,benefit_profile,cost):
    """Only frozen public scores enter the single-whole-frame action rule."""
    if (gap_profile,benefit_profile) not in PAIRS:raise ValueError('Pair outside fixed protocol')
    gap=predictions[gap_profile+'_gap'];gain=predictions[benefit_profile+'_benefit']
    if len(frames)!=len(gap) or len(gap)!=len(gain):raise ValueError('Unaligned public predictions')
    return [choose(f['source_ids'],g,y,cost,'gap_top10') for f,g,y in zip(frames,gap,gain)]


def select(candidates,frames):
    selected=[]
    for gap,benefit in PAIRS:
        family=[c for c in candidates if (c['gap_profile'],c['benefit_profile'])==(gap,benefit)]
        for budget in BUDGETS:
            allowed=[c for c in family if c['metrics'][MODE]['peer_requests']<=budget*frames]
            if not allowed:raise ValueError('No fixed cost-grid point within validation budget')
            best=min(allowed,key=lambda c:(-c['metrics'][MODE]['macro_ap']['0.5'],
                c['metrics'][MODE]['peer_requests'],ERROR_COSTS.index(c['error_cost'])))
            selected.append(dict(best,validation_budget_cap=budget))
    return selected


def load_reference(path,checksum):
    if sha(Path(path).read_bytes())!=checksum:raise ValueError('Previous validation ZIP changed')
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise ValueError('Previous validation CRC failure')
        for n,h in json.loads(z.read('files.json')).items():
            if sha(z.read(n))!=h:raise ValueError('Previous validation member changed')
        ref=json.loads(z.read('report.json'))
    if ref['schema']!='phdsim-urbaning-gap-acquisition-validation-v1' or ref['status']!='completed':
        raise ValueError('Expected previous development validation result')
    return ref


def run(inputs,input_sha,reference,reference_sha,output,resume=False):
    if np.__version__!='1.26.4':raise RuntimeError('Require NumPy 1.26.4 AP runtime')
    out=Path(output).resolve()
    if out.exists() and not resume:raise FileExistsError('Explicit --resume required')
    staged=stage(inputs,input_sha,out.with_name(out.name+'-inputs'))
    pilot=staged/'pilot';ref=load_reference(reference,reference_sha)
    old=json.loads((pilot/'report.json').read_text())
    for n,h in json.loads((pilot/'files.json').read_text()).items():
        if sha((pilot/n).read_bytes())!=h:raise ValueError('Frozen pilot member changed')
    for profile,h in old['models_sha256'].items():
        if sha((pilot/'models'/f'{profile}.json').read_bytes())!=h:raise ValueError('Frozen weights changed')
    print('VERIFY development splits, frame/payload binding and original baseline AP; no crossing3 reads',flush=True)
    _,manifest,mhash=load_dataset(staged/'regional-dataset.zip')
    samples,ap=load_archive(staged/'ap-export.zip');frames=samples['validation'];keys=[f['key'] for f in frames]
    if (len(frames)!=ref['frames'] or mhash!=ref['protocol']['dataset_manifest_sha256']
            or old['models_sha256']!=ref['protocol']['frozen_model_sha256']
            or sha((staged/'ap-export.zip').read_bytes())!=ref['protocol']['ap_export_sha256']
            or ref['provenance']!=ap['splits']['validation']['provenance']
            or sha((pilot/'report.json').read_bytes())!=ref['protocol']['pilot_report_sha256']):
        raise ValueError('Different development source bindings')
    with np.load(pilot/'offline-validation-predictions.npz',allow_pickle=False) as p:
        order=bind_validation(manifest,ap,frames,p['frame_keys'].tolist())
        mask=np.array([[a in available_subsets(f['source_ids']) for a in ACTION_ORDER] for f in frames])
        if not np.array_equal(mask,p['available'][order]):raise ValueError('Availability differs')
        predictions={f'{profile}_{head}':p[f'{profile}_{head}'][order] for profile in ('geometry','local') for head in ('gap','benefit')}
    root=Path(__file__).parents[1]
    paths=[Path(__file__),root/'decision/urbaning_gap_acquisition.py',root/'experiments/urbaning_gap_acquisition.py',
           root/'experiments/urbaning_ap_replay.py',root/'experiments/urbaning_subsets.py',
           root/'decision/urbaning.py',root/'evaluation/urbaning_cached.py']
    protocol={'schema':'phdsim-urbaning-gap-hybrid-validation-v1','scope':'200 previously inspected crossing2 development frames; no crossing3 access',
        'input_sha256':input_sha,'previous_validation_sha256':reference_sha,'pairs':[list(p) for p in PAIRS],
        'primary_hypothesis':'local gap localization + geometry benefit; compare with geometry/geometry at unchanged cost .5',
        'primary_fixed_cost':.5,'error_count_cost_grid':list(ERROR_COSTS),'validation_budget_caps':list(BUDGETS),
        'selection':'Within every fixed pair and cap: maximum global-sort mAP@.5, then fewer requests, then grid order; no cross-pair winner selected',
        'rule':'same top10 fields among all400 selected by gap head; independent subset benefit head; one whole-frame action and per-peer cost',
        'recording_groups':manifest['recording_groups'],'model_sha256':old['models_sha256'],
        'dataset_manifest_sha256':mhash,'seeds':list(SEEDS),
        'random':'predeclared pure independent random reused; secondary uniform fixed-total query events, no model timing/histogram',
        'implementation_sha256':{str(p.relative_to(root.parents[1])):sha(p.read_bytes()) for p in paths}}
    out.mkdir(parents=True,exist_ok=resume);path=out/'protocol.json'
    if path.exists():
        if json.loads(path.read_text())!=protocol:raise ValueError('Cannot resume different protocol or source')
    else:
        if any(out.iterdir()):raise ValueError('Nonempty output has no protocol')
        write_json(path,protocol)
    cache=ReplayCache(out/'checkpoints',protocol);candidates=[]
    for gap,benefit in PAIRS:
        for cost in ERROR_COSTS:
            actions=replay_pair(frames,predictions,gap,benefit,cost);metrics=cache.evaluate(frames,actions)
            if gap==benefit:
                prior=next(c for c in ref['candidates'] if c['profile']==gap and c['aggregation']=='gap_top10' and c['error_cost']==cost)
                if prior['choices']!=dict(zip(keys,actions)):raise ValueError('Homogeneous control choices changed')
                for mode in MODES:same_metrics(metrics[mode],prior['metrics'][mode])
            candidates.append({'gap_profile':gap,'benefit_profile':benefit,'error_cost':cost,
                'metrics':metrics,'choices':dict(zip(keys,actions))})
        print('REPLAYED gap='+gap,'benefit='+benefit,len(ERROR_COSTS),'fixed costs',flush=True)
    selected=select(candidates,len(frames))
    fixed=[c for c in candidates if c['error_cost']==.5]
    deployment={'protocol':protocol,'fixed_cost_comparison':[{k:v for k,v in c.items() if k not in ('metrics','choices')} for c in fixed],
        'validation_selected':[{k:v for k,v in c.items() if k not in ('metrics','choices')} for c in selected]}
    write_json(out/'frozen-configurations.json',deployment)
    frozen=out/'frozen-hybrid-inputs.zip'
    with zipfile.ZipFile(frozen.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        members={'deployment.json':json.dumps(deployment,allow_nan=False).encode()}
        members.update({f'models/{p}.json':(pilot/'models'/f'{p}.json').read_bytes() for p in ('geometry','local')})
        for name,raw in members.items():
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,raw)
    os.replace(frozen.with_suffix('.tmp'),frozen)
    print('FROZEN mixed configuration packet before random controls',sha(frozen.read_bytes()),flush=True)
    controls={}
    for total in sorted({c['metrics'][MODE]['peer_requests'] for c in selected+fixed}):
        prior=ref['secondary_fixed_total_random'].get(str(total))
        if prior is not None:
            for seed in (0,99):
                actual=cache.evaluate(frames,fixed_budget_random(frames,total,seed))
                for mode in MODES:same_metrics(actual[mode],prior[mode]['per_seed'][str(seed)])
            controls[str(total)]=prior;print('REUSE VERIFIED EXACT TOTAL RANDOM',total,flush=True)
        else:
            print('SECONDARY EXACT TOTAL RANDOM',total,flush=True)
            controls[str(total)]=random_ensemble(frames,(fixed_budget_random(frames,total,seed) for seed in SEEDS),cache)
        if any(m['peer_requests']!=total for m in controls[str(total)][MODE]['per_seed'].values()):raise ValueError('Random query total differs')
    report={'schema':protocol['schema'],'status':'completed','protocol':protocol,'frames':len(frames),
        'baseline':ref['baseline'],'pure_random':ref['pure_random'],'fixed_cost_comparison':fixed,
        'validation_selected':selected,'candidates':candidates,'secondary_fixed_total_random':controls,
        'provenance':ref['provenance'],'deployment_sha256':sha(frozen.read_bytes())}
    write_json(out/'report.json',report)
    maximum=ref['baseline']['all'][MODE];qmax=maximum['peer_requests'];apmax=maximum['macro_ap']['0.5']
    labels={'geometry':'Geometria','local':'Bieżące detekcje Car1'}
    lines=['# Rozdzielenie wskazywania pól i wyboru partnera — walidacja','',
        '200 klatek crossing2, nie pełne1400 crossing3. Te same zamrożone modele; bez treningu/detektora. '
        'Wybór10 pól spośród wszystkich400; decyzja dotyczy całej klatki. GT tylko do oceny.', '',
        'Porównanie przy wspólnym koszcie .5 nie wymusza jednakowej liczby zapytań. '
        'Dodatkowo zapisujemy wyniki wyboru kosztu na tej samej walidacji; nie są niezależnym testem.','']
    for title,rows in [('Stały koszt .5 — bez ponownego doboru',fixed),('Koszty wybrane w ramach wcześniejszych limitów walidacyjnych',selected)]:
        lines += ['## '+title,'','| Wskazywanie pól | Ocena partnerów | Limit walidacyjny | Koszt | mAP (%) | Zapytania | Oszczędność (%) | Strata mAP (pp) | Random tyle samo pytań: mAP (%) |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for c in rows:
            m=c['metrics'][MODE];q=m['peer_requests'];ap=m['macro_ap']['0.5'];budget=c.get('validation_budget_cap')
            lines.append(f'| {labels[c["gap_profile"]]} | {labels[c["benefit_profile"]]} | {"—" if budget is None else budget} | {c["error_cost"]:g} | {100*ap:.4f} | {q} | {100*(1-q/qmax):.2f} | {100*(apmax-ap):.4f} | {100*controls[str(q)][MODE]["summary"]["map_0.5"]["mean"]:.4f} |')
    lines+=['','## Czysty random i punkty odniesienia','','| Polityka | mAP (%) | Zapytania |','|---|---:|---:|']
    for name,by_mode in ref['baseline'].items():
        m=by_mode[MODE];lines.append(f'| {name} | {100*m["macro_ap"]["0.5"]:.4f} | {m["peer_requests"]} |')
    for p,by_mode in ref['pure_random'].items():
        s=by_mode[MODE]['summary'];lines.append(f'| Każdy partner niezależnie p={p},100 ziaren | {100*s["map_0.5"]["mean"]:.4f} | {s["peer_requests"]["mean"]:.2f} |')
    lines+=['','Zmiany mAP przy różnych zapytaniach nie są automatycznie poprawą selekcji. '
        'Losowanie dokładnej liczby pytań jest kontrolą po fakcie. Rozrzut ziaren nie mierzy niepewności między nagraniami. '
        'Pola bez detekcji nie są potwierdzonymi obszarami niewidocznymi; Infra ma pozycję przybliżoną początkiem układu miejsca. '
        'Nie wybieramy parametrów na crossing3 i nie deklarujemy poprawy przed wynikami.','']
    (out/'WYNIKI_PL.md').write_text('\n'.join(lines))
    artifact=out/'urbaning-gap-hybrid-validation.zip'
    files=[p for p in out.iterdir() if p.is_file() and p.name not in ('files.json',artifact.name) and p.suffix!='.tmp']
    write_json(out/'files.json',{p.name:sha(p.read_bytes()) for p in files})
    with zipfile.ZipFile(artifact.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[out/'files.json']:z.write(p,p.name)
    os.replace(artifact.with_suffix('.tmp'),artifact)
    with zipfile.ZipFile(artifact) as z:
        if z.testzip() is not None:raise ValueError('Output CRC failure')
    print((out/'WYNIKI_PL.md').read_text(),flush=True)
    print('SHA256',sha(artifact.read_bytes()),'bytes',artifact.stat().st_size,flush=True)
    print('DONE:',artifact,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('inputs','inputs-sha256','reference-validation-zip','reference-validation-sha256','output-dir'):p.add_argument('--'+n,required=True)
    p.add_argument('--resume',action='store_true');a=p.parse_args(argv)
    run(a.inputs,a.inputs_sha256,a.reference_validation_zip,a.reference_validation_sha256,a.output_dir,a.resume)
