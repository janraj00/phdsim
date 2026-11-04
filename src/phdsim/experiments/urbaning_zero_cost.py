"""Post-hoc zero-cost diagnostic: exact-total controls, classes and recordings."""
import argparse
import io
import json
import os
from pathlib import Path
import zipfile

import numpy as np

from phdsim.decision.urbaning import available_subsets,_rng
from phdsim.decision.urbaning_gap_acquisition import choose
from phdsim.experiments.urbaning_ap_replay import MODES,same_metrics
from phdsim.experiments.urbaning_gap_acquisition import ReplayCache,fixed_budget_random
from phdsim.experiments.urbaning_gap_full import verified_zip,load_full_reference,SEQUENCES
from phdsim.experiments.urbaning_regional_learning import sha,write_json
from phdsim.experiments.urbaning_subsets import ensemble_summary
from phdsim.learning.urbaning import recording_group

MODE='global_confidence_sort'
SEEDS=tuple(range(100))


def infra_priority_random(frames,total,seed):
    """Retrospective strong reference: one peer whenever possible + random extras.

    Prefer Infra, otherwise Car2. Randomly add Car2 in both-available frames.
    Only the scalar total is borrowed; no policy schedule, GT or predictions.
    """
    options=[available_subsets(f['source_ids']) for f in frames]
    actions=[next(a for a in ('infrastructure','vehicle_peer','ego') if a in p) for p in options]
    minimum=sum(len(p[a])-1 for p,a in zip(options,actions))
    both=[i for i,p in enumerate(options) if 'all' in p]
    if type(total)is not int or not minimum<=total<=minimum+len(both):raise ValueError('Total outside Infra-priority feasible range')
    for i in _rng(seed,'infra-priority-extra-car2',total).sample(both,total-minimum):actions[i]='all'
    return actions


def scopes(frames):
    return {'full':list(range(len(frames))),
        **{'sequence/'+s:[i for i,f in enumerate(frames) if f['sequence']==s] for s in sorted({f['sequence'] for f in frames})},
        **{'recording/'+g:[i for i,f in enumerate(frames) if recording_group(f['sequence'])==g]
           for g in sorted({recording_group(f['sequence']) for f in frames})}}


def measure(frames,actions,groups,caches):
    return {name:caches[name].evaluate([frames[i] for i in indices],[actions[i] for i in indices])
            for name,indices in groups.items()}


def class_summary(rows):
    """Variation across randomized choices only; not independent recordings."""
    result={}
    for name in rows[0]['classes']:
        result[name]={}
        for iou in ('0.3','0.5','0.7'):
            values=[r['classes'][name]['ap'][iou] for r in rows]
            result[name][iou]=None if any(v is None for v in values) else {
                'mean':float(np.mean(values)),'std':float(np.std(values)),
                'min':float(min(values)),'max':float(max(values))}
    return result


def ensemble(frames,groups,caches,generator,total):
    samples={name:{mode:[] for mode in MODES} for name in groups}
    choices={}
    for seed in SEEDS:
        actions=generator(frames,total,seed);choices[str(seed)]=dict(zip([f['key'] for f in frames],actions))
        m=measure(frames,actions,groups,caches)
        for name,by_mode in m.items():
            for mode,value in by_mode.items():samples[name][mode].append(value)
        if m['full'][MODE]['peer_requests']!=total:raise ValueError('Random query total changed')
        if (seed+1)%25==0:print('RANDOM',seed+1,'/100 seeds',flush=True)
    return {'metrics':{name:{mode:dict(ensemble_summary(rows,SEEDS),class_ap_randomization=class_summary(rows))
             for mode,rows in by_mode.items()} for name,by_mode in samples.items()},'choices':choices}


def zero_choices(members,source,frames):
    primary=source['protocol']['primary_transfer_point'];actions={}
    if primary!='spatial_geometry_gap_top10_valcap1.5':raise ValueError('Different original primary policy')
    for seq in SEQUENCES:
        subset=[f for f in frames if f['sequence']==seq]
        with np.load(io.BytesIO(members[f'spatial-checkpoints/{seq}-geometry.npz']),allow_pickle=False) as p:
            gap,gain=p['gap'],p['benefit']
            if gap.shape!=(len(subset),400) or gain.shape!=(len(subset),400,3):raise ValueError('Score checkpoint coverage differs')
            if sha(gap.tobytes()+gain.tobytes())!=p['scores_sha256'].item():raise ValueError('Score checkpoint changed')
            for f,g,y in zip(subset,gap,gain):
                if choose(f['source_ids'],g,y,.5,'gap_top10')!=source['choices'][primary][f['key']]:
                    raise ValueError('Original .5 choices no longer reproduced')
                actions[f['key']]=choose(f['source_ids'],g,y,0.,'gap_top10')
    if set(actions)!=set(f['key'] for f in frames):raise ValueError('Zero-cost choice coverage differs')
    return [actions[f['key']] for f in frames]


def run(spatial_zip,spatial_sha,reference_zip,reference_sha,output,resume=False):
    if np.__version__!='1.26.4':raise RuntimeError('Require NumPy 1.26.4 AP runtime')
    out=Path(output).resolve()
    if out.exists() and not resume:raise FileExistsError('Explicit --resume required')
    out.mkdir(parents=True,exist_ok=resume)
    root=Path(__file__).parents[1]
    paths=[Path(__file__),*[root/p for p in ('decision/urbaning_gap_acquisition.py','decision/urbaning.py',
        'experiments/urbaning_gap_acquisition.py','experiments/urbaning_gap_full.py',
        'experiments/urbaning_ap_replay.py','experiments/urbaning_subsets.py','evaluation/urbaning_cached.py')]]
    protocol={'schema':'phdsim-urbaning-zero-cost-v1','scope':'Post-hoc user-requested cost0 diagnostic on previously inspected1400 crossing3 frames',
        'spatial_zip_sha256':spatial_sha,'reference_zip_sha256':reference_sha,
        'fixed_policy':'unchanged frozen geometry gap/benefit scores, top10/all400; cost0 only',
        'expected_queries':1813,'no_new_selection':True,'seeds':list(SEEDS),
        'primary_control':'Uniform exact1813 feasible query events; scalar cost only, no schedule/histogram',
        'strong_secondary_control':'Infra when available, otherwise Car2, plus random Car2 extras on both-available frames at same total',
        'subgroup_budgets':'Exact total matching is global only; subgroup request totals vary and are reported',
        'reporting':'Global-sort four-class BEV mAP@.5 plus requests/loss; default AP separate; class AP, seven sequences and five original recording groups',
        'interpretation':'Randomization spread is not recording-level uncertainty or statistical equivalence',
        'numpy':np.__version__,'implementation_sha256':{str(p.relative_to(root.parents[1])):sha(p.read_bytes()) for p in paths}}
    p=out/'protocol.json'
    if p.exists():
        if json.loads(p.read_text())!=protocol:raise ValueError('Cannot resume changed protocol or inputs')
    else:
        if any(out.iterdir()):raise ValueError('Nonempty output has no protocol')
        write_json(p,protocol)
    members=verified_zip(spatial_zip,spatial_sha);source=json.loads(members['report.json'])
    if (source['schema']!='phdsim-urbaning-gap-full-v1' or source['status']!='completed'
            or source['protocol']['reference_zip_sha256']!=reference_sha):raise ValueError('Different full spatial source')
    frames,ref=load_full_reference(reference_zip,reference_sha,source['provenance']['detector'])
    if source['provenance']!=ref['provenance']:raise ValueError('Spatial/portable provenance mismatch')
    primary=source['protocol']['primary_transfer_point'];actions=zero_choices(members,source,frames)
    groups=scopes(frames);cache_root=out/'checkpoints';cache_root.mkdir(exist_ok=True)
    # Include frame keys per scope: identical action lists on different recordings
    # must never collide in ReplayCache's action-list cache.
    caches={name:ReplayCache(cache_root/name.replace('/','_'),dict(protocol,scope_name=name,
                scope_frame_keys=[frames[i]['key'] for i in indices])) for name,indices in groups.items()}
    keys=[f['key'] for f in frames]
    policies={**{n:[c[k] for k in keys] for n,c in source['choices'].items()
        if n in ('ego','vehicle_peer','infrastructure','all','gain_ego','gain_geometry','regional','tree',primary)},
        'geometry_top10_cost0':actions}
    metrics={name:measure(frames,choice,groups,caches) for name,choice in policies.items()}
    for name in policies:
        if name=='geometry_top10_cost0':continue
        for mode in MODES:same_metrics(metrics[name]['full'][mode],source['policies'][name][mode])
    total=metrics['geometry_top10_cost0']['full'][MODE]['peer_requests']
    if total!=protocol['expected_queries']:raise ValueError('Previously reported zero-cost query total differs')
    write_json(out/'frozen-choices.json',{n:dict(zip(keys,a)) for n,a in policies.items()})
    print('ZERO COST REPRODUCED',100*metrics['geometry_top10_cost0']['full'][MODE]['macro_ap']['0.5'],'mAP',total,'queries',flush=True)
    print('UNIFORM EXACT TOTAL RANDOM',total,flush=True)
    uniform=ensemble(frames,groups,caches,fixed_budget_random,total)
    print('STRONG SECONDARY INFRA PRIORITY + RANDOM CAR2 EXTRAS',total,flush=True)
    priority=ensemble(frames,groups,caches,infra_priority_random,total)
    report={'schema':protocol['schema'],'status':'completed','protocol':protocol,'frames':len(frames),
        'policies':metrics,'controls':{'uniform_exact_total':uniform,'infra_priority_random_extras':priority},
        'pure_random_from_previous_report':source['pure_random'],'provenance':ref['provenance']}
    write_json(out/'report.json',report)
    all_=metrics['all']['full'][MODE];zero=metrics['geometry_top10_cost0']['full'][MODE]
    lines=['# Koszt0 — kontrola liczby zapytań, klasy i nagrania','',
        'Te same1400 wcześniej oglądanych klatek crossing3. Dodatkowa analiza po obejrzeniu wyników, '
        'bez treningu/detektora/doboru kosztu. Główna miara: globalnie sortowane BEV mAP@.5.', '',
        '| Polityka | mAP (%) | Zapytania | Oszczędność vs ALWAYS (%) | Strata mAP vs ALWAYS (pp) |',
        '|---|---:|---:|---:|---:|']
    for n in ('all',primary,'geometry_top10_cost0'):
        m=metrics[n]['full'][MODE];q=m['peer_requests'];ap=m['macro_ap']['0.5']
        lines.append(f'| {n} | {100*ap:.4f} | {q} | {100*(1-q/all_["peer_requests"]):.2f} | {100*(all_["macro_ap"]["0.5"]-ap):.4f} |')
    lines+=['','| Czysty random: każdy dostępny partner niezależnie,100 ziaren | Średnie mAP (%) | Średnio pytań |','|---|---:|---:|']
    for prob,by_mode in source['pure_random'].items():
        s=by_mode[MODE]['summary']
        lines.append(f'| p={prob} | {100*s["map_0.5"]["mean"]:.4f} | {s["peer_requests"]["mean"]:.2f} |')
    lines+=['','| Kontrola przy1813 pytaniach,100 ziaren | Średnie mAP (%) | Zakres mAP (%) |','|---|---:|---:|']
    for name,c in report['controls'].items():
        s=c['metrics']['full'][MODE]['summary']['map_0.5']
        lines.append(f'| {name} | {100*s["mean"]:.4f} | {100*s["min"]:.4f}–{100*s["max"]:.4f} |')
    lines+=['','| Klasa | ALWAYS AP (%) | Koszt0 AP (%) | Zmiana AP (pp) |','|---|---:|---:|---:|']
    for name,c in zero['classes'].items():
        a=all_['classes'][name]['ap']['0.5'];b=c['ap']['0.5'];lines.append(f'| {name} | {100*a:.4f} | {100*b:.4f} | {100*(b-a):+.4f} |')
    lines+=['','| Oryginalne nagranie | Klatki | ALWAYS mAP (%) | Koszt0 mAP (%) | Zmiana (pp) | Pytania koszt0 / ALWAYS |','|---|---:|---:|---:|---:|---:|']
    for group in groups:
        if not group.startswith('recording/'):continue
        a=metrics['all'][group][MODE];b=metrics['geometry_top10_cost0'][group][MODE]
        lines.append(f'| {group} | {b["frames"]} | {100*a["macro_ap"]["0.5"]:.4f} | {100*b["macro_ap"]["0.5"]:.4f} | {100*(b["macro_ap"]["0.5"]-a["macro_ap"]["0.5"]):+.4f} | {b["peer_requests"]} / {a["peer_requests"]} |')
    lines+=['','Klasy i podgrupy losowań, wszystkie7 sekwencji,5 grup nagrań, oba tryby AP i historyczne '
        'polityki są w report.json. Równa liczba zapytań dotyczy całych1400 klatek; w poszczególnych '
        'nagraniach może się różnić. Rozrzut ziaren nie jest przedziałem ufności między nagraniami. '
        'Mała różnica średniego mAP nie dowodzi równoważności ani braku strat dla klas. '
        'Kontrole dokładnej liczby pytań korzystają z kosztu po fakcie. Zapytania nie mierzą bajtów/opóźnienia.','']
    (out/'WYNIKI_PL.md').write_text('\n'.join(lines))
    artifact=out/'urbaning-zero-cost.zip'
    files=[p for p in out.iterdir() if p.is_file() and p.name not in ('files.json',artifact.name) and p.suffix!='.tmp']
    write_json(out/'files.json',{p.name:sha(p.read_bytes()) for p in files})
    with zipfile.ZipFile(artifact.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[out/'files.json']:z.write(p,p.name)
    os.replace(artifact.with_suffix('.tmp'),artifact)
    with zipfile.ZipFile(artifact) as z:
        if z.testzip() is not None:raise ValueError('Final ZIP CRC failure')
    print((out/'WYNIKI_PL.md').read_text(),flush=True)
    print('SHA256',sha(artifact.read_bytes()),'bytes',artifact.stat().st_size,flush=True)
    print('DONE:',artifact,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('spatial-zip','spatial-sha','reference-zip','reference-sha','output-dir'):p.add_argument('--'+n,required=True)
    p.add_argument('--resume',action='store_true');a=p.parse_args(argv)
    run(a.spatial_zip,a.spatial_sha,a.reference_zip,a.reference_sha,a.output_dir,a.resume)
