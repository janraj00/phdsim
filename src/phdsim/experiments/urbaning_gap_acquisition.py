"""Validation mAP/request replay of frozen spatial models; no detector/fitting."""
import argparse
import json
from pathlib import Path
import os
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER,available_subsets,random_subset
from phdsim.decision.urbaning_gap_acquisition import AGGREGATIONS,ERROR_COSTS,choose
from phdsim.experiments.urbaning_ap_replay import MODES,baseline_choices,load_archive,metrics_both_orders
from phdsim.experiments.urbaning_regional_learning import load_dataset,sha,write_json
from phdsim.experiments.urbaning_subsets import ensemble_summary
from phdsim.learning.urbaning_gap_forests import PROFILES

BUDGETS=(.5,1.,1.5)
SEEDS=tuple(range(100))
PURE_P=(.25,.5,.75,.9)
MODE='global_confidence_sort'


def bind_validation(dataset_manifest,ap_manifest,frames,prediction_keys):
    if dataset_manifest['detector']!=ap_manifest['detector']:raise ValueError('Detector mismatch')
    if dataset_manifest['recording_groups']!=ap_manifest['recording_groups']:raise ValueError('Recording groups mismatch')
    actual=ap_manifest['splits']['validation']['provenance']['inputs']
    expected=[i for row in dataset_manifest['sequences'] if row['split']=='validation' for i in row['provenance']['inputs']]
    fields=('sequence','run_sha256','trace_sha256','predictions_sha256')
    core=lambda rows:sorted([{k:i[k] for k in fields} for i in rows],key=lambda i:i['sequence'])
    if core(actual)!=core(expected):raise ValueError('Different validation payload bindings')
    keys=[f['key'] for f in frames]
    if len(set(prediction_keys))!=len(prediction_keys) or set(keys)!=set(prediction_keys):raise ValueError('Prediction frame coverage mismatch')
    lookup={k:i for i,k in enumerate(prediction_keys)}
    return [lookup[k] for k in keys]


def fixed_budget_random(frames,requests,seed):
    """Offline uniform sampling without replacement over feasible frame/peer asks.

    Only the scalar total cost is supplied, not model actions, timing, histogram,
    labels or confidence. Both/one/zero naturally arise from the sampled asks.
    """
    candidates=[(i,role) for i,f in enumerate(frames) for role in (1,2)
                if ACTION_ORDER[role] in available_subsets(f['source_ids'])]
    if type(requests)is not int or not 0<=requests<=len(candidates):raise ValueError('Invalid random request total')
    from phdsim.decision.urbaning import _rng
    selected=_rng(seed,'fixed-total-queries',requests).sample(candidates,requests)
    masks=np.zeros(len(frames),int)
    for i,role in selected:masks[i]|=role
    names=('ego','vehicle_peer','infrastructure','all')
    return [names[n] for n in masks]


class ReplayCache:
    """Atomic per-outcome checkpoints bound to protocol and exact action list."""
    def __init__(self, directory, protocol):
        self.directory=Path(directory)
        self.directory.mkdir(exist_ok=True)
        self.protocol_sha=sha(json.dumps(protocol,sort_keys=True,allow_nan=False).encode())

    def evaluate(self,frames,actions):
        actions=list(actions)
        binding=sha(json.dumps({'protocol':self.protocol_sha,'choices':actions},sort_keys=True).encode())
        path=self.directory/(binding+'.json')
        if path.exists():
            saved=json.loads(path.read_text())
            if saved['binding']!=binding:raise ValueError('Checkpoint binding mismatch')
            metrics=saved['metrics']
            if saved['metrics_sha256']!=sha(json.dumps(metrics,sort_keys=True).encode()):
                raise ValueError('Checkpoint metrics changed')
            return metrics
        metrics=metrics_both_orders(frames,actions)
        saved={'binding':binding,'metrics':metrics,
               'metrics_sha256':sha(json.dumps(metrics,sort_keys=True).encode())}
        tmp=path.with_suffix('.tmp')
        write_json(tmp,saved)
        os.replace(tmp,path)
        return metrics


def random_ensemble(frames,choices,cache):
    results={mode:[] for mode in MODES}
    for seed,actions in zip(SEEDS,choices):
        measured=cache.evaluate(frames,actions)
        for mode in MODES:results[mode].append(measured[mode])
        if (seed+1)%25==0:print('RANDOM',seed+1,'/100 seeds',flush=True)
    return {mode:ensemble_summary(rows,SEEDS) for mode,rows in results.items()}


def run(pilot,dataset,ap_export,output,resume=False):
    if np.__version__!='1.26.4':raise RuntimeError('Use frozen NumPy 1.26.4 AP runtime')
    pilot,out=Path(pilot).resolve(),Path(output).resolve()
    if out.exists() and not resume:raise FileExistsError('Use a new output directory or explicit --resume')
    print('VERIFY frozen pilot, regional data and original AP baselines; no inference or fitting',flush=True)
    old=json.loads((pilot/'report.json').read_text());frozen=old['protocol']
    if sha(Path(dataset).read_bytes())!=frozen['dataset_sha256']:raise ValueError('Different regional dataset')
    _,manifest,mhash=load_dataset(dataset)
    if mhash!=frozen['dataset_manifest_sha256']:raise ValueError('Different regional manifest')
    for name,h in json.loads((pilot/'files.json').read_text()).items():
        if sha((pilot/name).read_bytes())!=h:raise ValueError('Frozen pilot changed')
    samples,ap_manifest=load_archive(ap_export)  # crossing3 guard and original AP parity
    frames=samples['validation'];keys=[f['key'] for f in frames]
    out.mkdir(parents=True,exist_ok=resume)
    root=Path(__file__).parents[1]
    implementation={str(p.relative_to(Path(__file__).parents[3])):sha(p.read_bytes()) for p in (
        Path(__file__),root/'decision/urbaning_gap_acquisition.py',root/'decision/urbaning.py',
        root/'experiments/urbaning_ap_replay.py',root/'experiments/urbaning_subsets.py',
        root/'evaluation/urbaning_cached.py')}
    # Save exact grid/budget/selection before computing any candidate AP.
    protocol={'schema':'phdsim-urbaning-gap-acquisition-validation-v1','status':'frozen-before-replay',
        'scope':'200 development validation frames; costs selected here, not independent test results',
        'metric':'four-class global-confidence-sort BEV mAP@.5; default ordering separate',
        'profiles':list(PROFILES),'aggregations':list(AGGREGATIONS),'error_count_cost_grid':list(ERROR_COSTS),
        'request_budget_caps_per_frame':list(BUDGETS),
        'selection':'Within each profile/aggregation/budget: maximum validation mAP@.5, then fewer requests, then original cost-grid order',
        'runtime_rule':'sum frozen local FP+FN benefit over same gap-selected ten cells or all400, minus cost per requested peer; one whole-frame action',
        'pure_random_probabilities':list(PURE_P),'seeds':list(SEEDS),
        'secondary_random':'offline uniform fixed-total requests across all feasible frame/peer edges; no model schedule or histogram',
        'dataset_manifest_sha256':mhash,'pilot_report_sha256':sha((pilot/'report.json').read_bytes()),
        'ap_export_sha256':sha(Path(ap_export).read_bytes()),'implementation_sha256':implementation,
        'numpy_version':np.__version__,'detector':ap_manifest['detector'],
        'recording_groups':manifest['recording_groups'],'frozen_model_sha256':old['models_sha256']}
    if (out/'protocol.json').exists():
        if json.loads((out/'protocol.json').read_text())!=protocol:raise ValueError('Cannot resume a different protocol, implementation or input')
    else:
        if resume and any(out.iterdir()):raise ValueError('Nonempty resume directory has no protocol')
        write_json(out/'protocol.json',protocol)
    cache=ReplayCache(out/'checkpoints',protocol)
    baseline={a:cache.evaluate(frames,baseline_choices(frames,a)) for a in ACTION_ORDER}
    for preferred in ('infrastructure','vehicle_peer'):
        fallback='vehicle_peer' if preferred=='infrastructure' else 'infrastructure'
        choices=[next(a for a in (preferred,fallback,'ego') if a in available_subsets(f['source_ids'])) for f in frames]
        baseline[preferred+'_otherwise_other']=cache.evaluate(frames,choices)
    candidates=[]
    with np.load(pilot/'offline-validation-predictions.npz',allow_pickle=False) as p:
        order=bind_validation(manifest,ap_manifest,frames,p['frame_keys'].tolist())
        expected_mask=np.array([[a in available_subsets(f['source_ids']) for a in ACTION_ORDER] for f in frames])
        if not np.array_equal(p['available'][order],expected_mask):raise ValueError('Availability differs')
        for profile in PROFILES:
            gap,gain=p[profile+'_gap'][order],p[profile+'_benefit'][order]
            for aggregation in AGGREGATIONS:
                for cost in ERROR_COSTS:
                    actions=[choose(f['source_ids'],g,y,cost,aggregation) for f,g,y in zip(frames,gap,gain)]
                    metrics=cache.evaluate(frames,actions)
                    candidate={'profile':profile,'aggregation':aggregation,'error_cost':cost,'metrics':metrics,
                               'choices':dict(zip(keys,actions))}
                    candidates.append(candidate)
                print('REPLAYED',profile,aggregation,len(ERROR_COSTS),'costs',flush=True)
    selected=[]
    for profile in PROFILES:
        for aggregation in AGGREGATIONS:
            family=[c for c in candidates if c['profile']==profile and c['aggregation']==aggregation]
            for budget in BUDGETS:
                feasible=[c for c in family if c['metrics'][MODE]['peer_requests']<=budget*len(frames)]
                if not feasible:
                    selected.append({'profile':profile,'aggregation':aggregation,'budget_cap':budget,'status':'no grid point within budget'})
                    continue
                best=min(feasible,key=lambda c:(-c['metrics'][MODE]['macro_ap']['0.5'],c['metrics'][MODE]['peer_requests'],ERROR_COSTS.index(c['error_cost'])))
                selected.append(dict(best,budget_cap=budget,status='validation-selected'))
    write_json(out/'selected-frozen-policies.json',{'protocol':protocol,'policies':selected})
    # Freeze decision configuration and model bytes before any future test read.
    bundle=out/'frozen-gap-acquisition-inputs.zip'
    with zipfile.ZipFile(bundle.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        deployment={'protocol':protocol,'policies':[{k:v for k,v in c.items() if k not in ('choices','metrics')} for c in selected]}
        z.writestr('deployment.json',json.dumps(deployment,allow_nan=False))
        for name,h in old['models_sha256'].items():
            raw=(pilot/'models'/f'{name}.json').read_bytes()
            if sha(raw)!=h:raise ValueError('Frozen weights changed')
            z.writestr('models/'+name+'.json',raw)
    os.replace(bundle.with_suffix('.tmp'),bundle)
    print('FROZEN DEPLOYMENT',sha(bundle.read_bytes()),flush=True)
    pure={}
    for p in PURE_P:
        print('PURE RANDOM',p,flush=True)
        pure[str(p)]=random_ensemble(frames,([random_subset(f['source_ids'],f['key'],seed,p) for f in frames] for seed in SEEDS),cache)
    totals=sorted({c['metrics'][MODE]['peer_requests'] for c in selected if c['status']=='validation-selected'})
    matched={}
    for total in totals:
        print('SECONDARY EXACT TOTAL RANDOM',total,flush=True)
        matched[str(total)]=random_ensemble(frames,(fixed_budget_random(frames,total,seed) for seed in SEEDS),cache)
        if any(v['peer_requests']!=total for v in matched[str(total)][MODE]['per_seed'].values()):raise ValueError('Random cost mismatch')
    report={'schema':protocol['schema'],'status':'completed','protocol':protocol,'frames':len(frames),
        'baseline':baseline,'candidates':candidates,'selected':selected,'pure_random':pure,
        'secondary_fixed_total_random':matched,'provenance':ap_manifest['splits']['validation']['provenance'],
        'deployment_sha256':sha(bundle.read_bytes()),
        'implementation_sha256':implementation}
    write_json(out/'report.json',report)
    maximum=baseline['all'][MODE]['peer_requests'];maximum_ap=baseline['all'][MODE]['macro_ap']['0.5']
    labels={'geometry':'Geometria','local':'Lokalne cechy Car1','combined':'Połączenie'}
    lines=['# Decyzje o partnerach z modeli przestrzennych — walidacja','',
        '200 klatek crossing2, wcześniej oglądana walidacja. Modele pozostały zamrożone. '
        'Koszt/wybór punktu na krzywej dobierano na tej walidacji, więc wynik nie jest niezależnym testem.', '',
        'Główna miara: BEV mAP@0.5, cztery klasy, globalne sortowanie confidence. '
        'W każdej klatce wybieramy jeden rzeczywisty wariant całej klatki: Car1 / Car1+Car2 / Car1+Infra / wszyscy. '
        'Nie składamy detekcji z różnych wariantów w osobnych polach.', '',
        '| Wariant | Budżet maks. pytań/klatkę | Koszt | mAP (%) | Pytania | Oszczędność vs ALWAYS (%) | Strata mAP vs ALWAYS (pp) | Losowy ten sam koszt: mAP (%) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for c in selected:
        if c['status']!='validation-selected':continue
        m=c['metrics'][MODE];q=m['peer_requests'];name=labels[c['profile']]+' / '+('10 wskazanych pól' if c['aggregation']=='gap_top10' else 'wszystkie 400 pól')
        lines.append(f'| {name} | {c["budget_cap"]:g} | {c["error_cost"]:g} | {100*m["macro_ap"]["0.5"]:.4f} | {q} | {100*(1-q/maximum):.2f} | {100*(maximum_ap-m["macro_ap"]["0.5"]):.4f} | {100*matched[str(q)][MODE]["summary"]["map_0.5"]["mean"]:.4f} |')
    lines+=['','## Punkty odniesienia','', '| Wariant | mAP (%) | Pytania |','|---|---:|---:|']
    for name,m in baseline.items():lines.append(f'| {name} | {100*m[MODE]["macro_ap"]["0.5"]:.4f} | {m[MODE]["peer_requests"]} |')
    for p,m in pure.items():
        s=m[MODE]['summary'];lines.append(f'| Czysty random p={p}, 100 ziaren | {100*s["map_0.5"]["mean"]:.4f} | {s["peer_requests"]["mean"]:.2f} |')
    lines+=['','Budżety są ograniczeniami, nie wymuszoną liczbą pytań. Koszt jest w jednostkach przewidywanej redukcji FP+FN, '
        'nie w jednostkach mAP ani historycznej użyteczności F1. Opłata dotyczy partnera raz na klatkę. '
        'Czysty random pyta każdego dostępnego partnera niezależnie. Kontrola dokładnej liczby pytań jest dodatkową '
        'retrospektywną kontrolą, losującą spośród możliwych pytań bez harmonogramu modelu.', '',
        'Parametry i wagi są gotowe do dalszego zamrożonego replayu. Wynik walidacji nie uzasadnia twierdzenia o generalizacji '
        'na nowe nagrania. Crossing3 nie było odczytywane przez ten eksperyment.', '']
    (out/'WYNIKI_PL.md').write_text('\n'.join(lines))
    artifact=out/'urbaning-gap-acquisition-validation.zip'
    files=[p for p in out.iterdir() if p.is_file() and p.name not in ('files.json',artifact.name) and p.suffix!='.tmp']
    write_json(out/'files.json',{p.name:sha(p.read_bytes()) for p in files})
    with zipfile.ZipFile(artifact.with_suffix('.tmp'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.iterdir()):
            if p.is_file() and p!=artifact and p.suffix!='.tmp':z.write(p,p.name)
    os.replace(artifact.with_suffix('.tmp'),artifact)
    with zipfile.ZipFile(artifact) as z:
        if z.testzip() is not None:raise ValueError('Output CRC failure')
    print((out/'WYNIKI_PL.md').read_text(),flush=True)
    print('SHA256',sha(artifact.read_bytes()),'bytes',artifact.stat().st_size,flush=True)
    print('DONE:',artifact,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('pilot','dataset','ap-export','output-dir'):p.add_argument('--'+n,required=True)
    p.add_argument('--resume',action='store_true',help='Reuse matching atomic checkpoints; refuse changed inputs/code/protocol')
    a=p.parse_args(argv);run(a.pilot,a.dataset,a.ap_export,a.output_dir,a.resume)
