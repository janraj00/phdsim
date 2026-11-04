"""Read-only two-stage diagnostics of frozen gap-pilot predictions."""
from collections import Counter
import argparse
import io
import json
from pathlib import Path
import zipfile

import numpy as np

from phdsim.experiments.urbaning_gap_pilot import K,top_indices
from phdsim.experiments.urbaning_regional_learning import load_dataset,sha,write_json


def joint_metrics(gap_scores,benefit_scores,recovered,net_gain,available,empty_only=None):
    """GT enters evaluation only. Rank by predicted gap; choose predicted subset.

    A success requires both recovering at least one Car1 miss and strictly
    reducing local FP+FN. All labels come from full-frame fusion outcomes.
    No mixed-region perception result or request saving is constructed.
    """
    n=len(gap_scores)
    if (np.shape(gap_scores)!=(n,400) or any(np.shape(v)!=(n,400,3) for v in
            (benefit_scores,recovered,net_gain)) or np.shape(available)!=(n,4)):
        raise ValueError('Unaligned two-stage arrays')
    if empty_only is not None and np.shape(empty_only)!=(n,400): raise ValueError('Bad region mask')
    hits=[];random=[];random_partner=[];hist=Counter();frames=0
    successes=0;proposals=0
    for i in range(n):
        a=available[i,1:]
        if not a.any():continue
        allowed=np.ones(400,bool) if empty_only is None else empty_only[i]
        if allowed.sum()<K:continue
        if not np.isfinite(benefit_scores[i][:,a]).all():raise ValueError('Nonfinite feasible head')
        cells=top_indices(gap_scores[i],K,allowed)
        safe=np.where(a[None],benefit_scores[i],-np.inf)
        actions=np.argmax(safe[cells],axis=1)
        truth=(recovered[i]>0)&(net_gain[i]>0)
        passed=truth[cells,actions]
        hits.append(float(passed.mean()))
        random.append(float(truth[allowed][:,a].mean()))
        random_partner.append(float(truth[cells][:,a].mean()))
        hist.update(('vehicle_peer','infrastructure','all')[j] for j in actions)
        successes+=int(passed.sum());proposals+=K;frames+=1
    return {'frames':frames,'k':K,'proposals':proposals,'successes':successes,
            'success_fraction':float(np.mean(hits)) if frames else None,
            'successes_per_10':float(K*np.mean(hits)) if frames else None,
            'pure_random_expected_fraction':float(np.mean(random)) if frames else None,
            'same_gap_regions_random_partner_expected_fraction':float(np.mean(random_partner)) if frames else None,
            'proposed_subset_histogram':dict(hist),
            'scope':'Diagnostic region/subset proposals; neither ROI transmissions nor detector mAP nor request budgets'}


def run(pilot,dataset,output):
    pilot,out=Path(pilot),Path(output)
    if out.exists():raise FileExistsError('Use a new review directory')
    report=json.loads((pilot/'report.json').read_text());protocol=report['protocol']
    if sha(Path(dataset).read_bytes())!=protocol['dataset_sha256']:raise ValueError('Different dataset')
    data,manifest,mhash=load_dataset(dataset)
    if mhash!=protocol['dataset_manifest_sha256']:raise ValueError('Different dataset manifest')
    for name,h in json.loads((pilot/'files.json').read_text()).items():
        if sha((pilot/name).read_bytes())!=h:raise ValueError('Frozen pilot changed: '+name)
    recovered=[];keys=[]
    with zipfile.ZipFile(dataset) as z:
        for item in manifest['sequences']:
            if item['split']!='validation':continue
            name='validation/'+item['sequence']+'/offline-targets.npz';raw=z.read(name)
            if sha(raw)!=item['files'][name]:raise ValueError('Label hash changed')
            with np.load(io.BytesIO(raw),allow_pickle=False) as d:
                recovered.append(d['recovered_gt'][:,:400,1:].sum(axis=-1));keys.append(d['frame_keys'])
    recovered=np.concatenate(recovered);keys=np.concatenate(keys)
    empty=data['validation']['features'][:,:400,10]>.5
    result={'schema':'phdsim-urbaning-gap-two-stage-review-v1','status':'completed',
        'source_pilot_archive_sha256':sha((pilot/'urbaning-gap-pilot.zip').read_bytes()),
        'dataset_manifest_sha256':mhash,'recording_groups':manifest['recording_groups'],
        'selection':'none; unchanged three profiles/weights; diagnostics only; no detector calls or fitting',
        'success':'selected cell has >=1 recovered Car1 missed GT AND local FP+FN strictly decreases',
        'validation':{}}
    with np.load(pilot/'offline-validation-predictions.npz',allow_pickle=False) as p:
        if not np.array_equal(p['frame_keys'],keys):raise ValueError('Validation prediction/label alignment mismatch')
        for name in report['validation']:
            args=(p[name+'_gap'],p[name+'_benefit'],recovered,p['net_gain'],p['available'])
            result['validation'][name]={'all_cells':joint_metrics(*args),'empty_cells':joint_metrics(*args,empty_only=empty)}
    result['implementation_sha256']=sha(Path(__file__).read_bytes())
    out.mkdir(parents=True);write_json(out/'two-stage-review.json',result)
    lines=['# Pilot lokalizowania braków i wyboru źródła','',
        'Ukończone uczenie: 400 klatek z dwóch nagrań. Walidacja: 200 klatek z jednego wcześniej oglądanego nagrania. '
        'Bez inferencji detektora i bez danych crossing3. Każdy wariant ma tę samą pojemność drzew; nie wybierano parametrów na walidacji.', '',
        '## Krok 1: wskazanie pól z przeoczeniami', '',
        'W każdej klatce model wskazuje 10 pól. Trafienie oznacza co najmniej jeden obiekt przeoczony przez Car1 w polu. '
        'Druga kolumna ogranicza ranking wyłącznie do pól bez detekcji Car1. Są to osobne rankingi.', '',
        '| Cechy | Trafione pola na 10: cała siatka | Trafione pola na 10: tylko pola bez detekcji |', '|---|---:|---:|']
    random=next(iter(report['validation'].values()))['gap']
    lines.append(f'| Czysty random (dokładna wartość oczekiwana) | {10*random["all_cells"]["random_precision_expected"]:.3f} | {10*random["empty_cells"]["random_precision_expected"]:.3f} |')
    labels={'geometry':'Geometria','local':'Lokalne cechy Car1','combined':'Połączenie'}
    for name,row in report['validation'].items():
        g=row['gap'];lines.append(f'| {labels[name]} | {10*g["all_cells"]["precision_at_k"]:.3f} | {10*g["empty_cells"]["precision_at_k"]:.3f} |')
    lines+=['','## Oba kroki razem: wskazane pole i wybrany wariant współpracy','',
        'Pola wybiera przewidywane ryzyko przeoczenia, a wariant współpracy — przewidywana lokalna redukcja FP+FN. '
        'Sukces oznacza odzyskanie przynajmniej jednego przeoczonego obiektu i jednocześnie poprawę lokalnego bilansu FP+FN. '
        'GT służy tylko do oceny po fakcie.', '',
        '| Cechy | Skuteczne wskazania na 10 | Czysty random na 10 | Te same wskazane pola, losowy wariant: na 10 |', '|---|---:|---:|---:|']
    for name,row in result['validation'].items():
        a=row['all_cells'];lines.append(f'| {labels[name]} | {a["successes_per_10"]:.3f} | {10*a["pure_random_expected_fraction"]:.3f} | {10*a["same_gap_regions_random_partner_expected_fraction"]:.3f} |')
    lines+=['','## Interpretacja i ograniczenia','',
        'Połączenie cech nie wygrywa każdego zadania. Lokalne cechy Car1 najlepiej wskazują przeoczenia w całej siatce; '
        'sama geometria najlepiej wskazuje je wśród pól bez detekcji. To wskazuje na różne rodzaje sytuacji, '
        'ale nie uzasadnia jeszcze uczenia kolejnego przełącznika na tym samym oglądanym zbiorze.', '',
        'Wariant „obaj partnerzy” także jest dopuszczony. Nie naliczono tu kosztu zapytań; 10 propozycji region/wariant '
        'nie oznacza 10 niezależnych zapytań. Dane opisują lokalne efekty fuzji całych klatek. '
        'Złożenie efektów różnych wariantów w jeden wynik nie jest poprawną ewaluacją ROI ani mAP.', '',
        'Wyniki dotyczą rankingu regionów i źródeł. Nie wyliczono nowego mAP detektora ani oszczędności zapytań. '
        'Pozostają do sprawdzenia przekład na wybór 0/1/2 partnerów, koszty i nowe nagrania. '
        'Siatka 400 pól 10 × 10 m jest ustawieniem analizy; puste pole detekcji nie określa widoczności.', '']
    (out/'WYNIKI_PL.md').write_text('\n'.join(lines))
    # New review bundle retains the original immutable pilot files/weights.
    archive=out/'urbaning-gap-pilot-review.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name in json.loads((pilot/'files.json').read_text()):z.write(pilot/name,'pilot/'+name)
        z.write(pilot/'files.json','pilot/files.json')
        z.write(out/'two-stage-review.json','two-stage-review.json');z.write(out/'WYNIKI_PL.md','WYNIKI_PL.md')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Review ZIP CRC failure')
        for name,h in json.loads(z.read('pilot/files.json')).items():
            if sha(z.read('pilot/'+name))!=h:raise ValueError('Review member hash mismatch')
    print((out/'WYNIKI_PL.md').read_text(),flush=True)
    print('SHA256',sha(archive.read_bytes()),'bytes',archive.stat().st_size,flush=True)
    print('DONE:',archive,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pilot','dataset','output-dir'):p.add_argument('--'+name,required=True)
    a=p.parse_args(argv);run(a.pilot,a.dataset,a.output_dir)
