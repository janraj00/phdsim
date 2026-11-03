"""Portable detection statistics and one evaluator for frozen acquisition choices.

Exports existing train/validation caches only; no detector, fitting or downloads.
GT and counterfactual statistics are offline evaluation data, never policy inputs.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, action_subsets, available_subsets, matched_random_subsets
from phdsim.evaluation.urbaning import CLASSES, IOU_THRESHOLDS
from phdsim.evaluation.urbaning_cached import frame_f1
from phdsim.experiments.urbaning_regional_dataset import validate_split_headers
from phdsim.experiments.urbaning_subsets import evaluate, load_runs, ensemble_summary
from phdsim.learning.urbaning import recording_group

SCHEMA = 'phdsim-urbaning-ap-export-v1'
CHOICES_SCHEMA = 'phdsim-urbaning-frozen-choices-v1'
MODES = {'global_confidence_sort': True, 'upstream_default_frame_order': False}
COST = .05  # historical F1 utility diagnostic only; never a selection metric here


def sha(raw): return hashlib.sha256(raw).hexdigest()


def dumps(value): return json.dumps(value, allow_nan=False, separators=(',', ':'))


def baseline_choices(frames, action):
    return [next(a for a, subset in available_subsets(f['source_ids']).items()
                 if subset == action_subsets(f['source_ids'])[action]) for f in frames]


def metrics_both_orders(frames, choices):
    # The same evaluator used by the existing frozen-policy replay. No new AP
    # formula, sequence-AP average, per-cell F1 or policy optimization is added.
    return {name: evaluate(frames, choices, COST, global_sort=mode) for name, mode in MODES.items()}


def same_metrics(actual, expected, tolerance=1e-7):
    for key in ('frames', 'peer_requests', 'request_histogram', 'action_histogram'):
        if actual[key] != expected[key]: raise ValueError('Replay mismatch: '+key)
    for key in ('mean_frame_f1', 'mean_frame_utility'):
        if abs(actual[key]-expected[key]) > 1e-12: raise ValueError('Replay mismatch: '+key)
    for name in CLASSES:
        if actual['classes'][name]['ground_truth_count'] != expected['classes'][name]['ground_truth_count']:
            raise ValueError('GT support changed')
        for iou in map(str, IOU_THRESHOLDS):
            a, b = actual['classes'][name]['ap'][iou], expected['classes'][name]['ap'][iou]
            if (a is None) != (b is None) or (a is not None and abs(a-b)>tolerance):
                raise ValueError('AP parity failure: '+name+' @ '+iou)


def export(train_runs, validation_runs, output):
    groups = validate_split_headers(train_runs, validation_runs)  # before any prediction load
    out = Path(output).resolve()
    if out.exists(): raise FileExistsError('Use a new export directory; previous artifacts are preserved')
    out.mkdir(parents=True)
    manifest = {'schema': SCHEMA, 'status': 'completed', 'scope': 'offline train/validation detection-statistics export',
                'recording_groups': groups, 'classes': list(CLASSES), 'iou_thresholds': list(IOU_THRESHOLDS),
                'action_order': list(ACTION_ORDER), 'splits': {}, 'files': {},
                'protocol': {'primary_metric': 'four-class BEV mAP@0.5; global confidence sort',
                             'secondary_ap_order': 'upstream default; lexical frame order without global sorting',
                             'f1': 'secondary diagnostic: mean frame micro F1 at BEV IoU .5',
                             'request_cost': 'one requested peer per frame; counts only, not bytes or latency',
                             'f1_utility_cost_diagnostic': COST,
                             'selection': 'none; no fitting, tuning or budget selection',
                             'matching': 'existing frozen class-wise score-ordered greedy BEV matcher, 0–100m corner-radius filter',
                             'frame_order': 'lexical native frame key; stored order retained in default-order AP'},
                'runtime': {'python': platform.python_version(), 'numpy': np.__version__}}
    detector = None
    for split, runs in (('train', train_runs), ('validation', validation_runs)):
        def progress(seq, n, total):
            if n % 25 == 0 or n == total: print('VERIFY', split, seq, '{}/{}'.format(n,total), flush=True)
        frames, provenance = load_runs(runs, progress=progress)
        if detector is not None and detector != provenance['detector']: raise ValueError('Mixed frozen detectors')
        detector = provenance['detector']
        traces = {}
        for item in provenance['inputs']:
            trace = Path(item['directory'])/'frames.jsonl'
            if sha(trace.read_bytes()) != item['trace_sha256']: raise ValueError('Source trace changed during export')
            traces.update({r['frame_key']:(r,item) for r in map(json.loads,trace.read_text().splitlines())})
        name = 'offline-statistics-'+split+'.jsonl'
        bindings = {}
        with (out/name).open('x') as stream:
            for frame in frames:
                row, origin = traces[frame['key']]
                payload_sha = origin['predictions_sha256'][row['predictions']]
                if sha((Path(origin['directory'])/row['predictions']).read_bytes()) != payload_sha:
                    raise ValueError('Source prediction changed during export')
                bindings[frame['key']] = {'sequence':frame['sequence'],'source_ids':frame['source_ids'],
                    'prediction_path':row['predictions'],'prediction_sha256':payload_sha,'gt_sha256':row['gt_sha256']}
                stream.write(dumps({'key':frame['key'], 'sequence':frame['sequence'],
                    'source_ids':frame['source_ids'], 'native_association':frame['native_association'],
                    'prediction_sha256':payload_sha,
                    'gt_sha256':row['gt_sha256'], 'statistics':frame['statistics']})+'\n')
        manifest['files'][name] = sha((out/name).read_bytes())
        manifest['splits'][split] = {'frames':len(frames),'provenance':provenance,'frame_bindings':bindings,
            'baselines':{action:metrics_both_orders(frames,baseline_choices(frames,action)) for action in ACTION_ORDER}}
        print('EXPORTED', split, len(frames), 'frames; four baselines reproduced against original cache metrics', flush=True)
    manifest['detector'] = detector
    files = [Path(__file__),Path(__file__).with_name('urbaning_subsets.py'),
             Path(__file__).parents[1]/'evaluation/urbaning_cached.py',Path(__file__).parents[1]/'decision/urbaning.py']
    manifest['implementation_sha256'] = {str(p.relative_to(Path(__file__).parents[3])):sha(p.read_bytes()) for p in files}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    (out/'README.md').write_text('# Offline UrbanIng AP statistics\n\n'
        'Existing frozen predictions only; no inference or fitting. Per-frame/class/action confidences and TP/FP flags '
        'at BEV IoU .3/.5/.7, GT counts, source identities and provenance. These are offline labels/outcomes, '
        'not deployable model inputs. Train/validation original-recording groups are disjoint; crossing3 is excluded. '
        'Primary AP uses global confidence sorting; upstream frame order is separately reported. '
        'Do not infer independent generalization from these already-inspected development recordings.\n')
    bundle = out/'urbaning-ap-export.zip'
    with zipfile.ZipFile(bundle,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name in (*manifest['files'],'manifest.json','README.md'): z.write(out/name,name)
    # Verify the final portable bytes and baseline parity before announcing success.
    load_archive(bundle)
    with zipfile.ZipFile(bundle) as z:
        if z.testzip() is not None: raise ValueError('Export ZIP CRC failure')
    receipt={'status':'completed','archive':bundle.name,'sha256':sha(bundle.read_bytes()),
             'bytes':bundle.stat().st_size,'frames':{s:r['frames'] for s,r in manifest['splits'].items()}}
    (out/'export-completed.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('SHA256',receipt['sha256'],'bytes',receipt['bytes'],flush=True)
    print('DONE:',bundle,flush=True)
    return bundle


def validate_statistics(statistics, options):
    if set(statistics) != set(options): raise ValueError('Unavailable or missing canonical action')
    converted, common_gt = {}, None
    for action, classes in statistics.items():
        if set(classes) != set(CLASSES): raise ValueError('Class contract mismatch')
        converted[action], support = {}, []
        for name in CLASSES:
            if set(classes[name]) != set(map(str,IOU_THRESHOLDS)): raise ValueError('IoU contract mismatch')
            converted[action][name] = {}
            class_gt, class_scores = None, None
            for iou, row in classes[name].items():
                if set(row) != {'gt','tp','fp','score'}: raise ValueError('Statistics field allowlist mismatch')
                tp, fp, score = (np.asarray(row[n]) for n in ('tp','fp','score'))
                gt = row['gt']
                if (type(gt) is not int or gt<0 or tp.ndim!=1 or fp.shape!=tp.shape or score.shape!=tp.shape
                        or not np.isin(tp,[0,1]).all() or not np.isin(fp,[0,1]).all()
                        or not np.array_equal(tp+fp,np.ones(len(tp))) or tp.sum()>gt
                        or not np.isfinite(score).all() or ((score<0)|(score>1)).any()
                        or (np.diff(score)>0).any()):
                    raise ValueError('Invalid per-detection statistics')
                if class_gt is not None and (class_gt!=gt or class_scores!=row['score']):
                    raise ValueError('IoU thresholds changed GT/confidence support')
                class_gt, class_scores = gt, row['score']
                converted[action][name][float(iou)] = row
            support.append(class_gt)
        if common_gt is not None and support!=common_gt: raise ValueError('GT support differs between actions')
        common_gt = support
    return converted


def load_archive(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names)!=len(set(names)) or any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in names):
            raise ValueError('Unsafe or duplicate ZIP member')
        manifest = json.loads(z.read('manifest.json'))
        if (manifest.get('schema')!=SCHEMA or manifest.get('status')!='completed'
                or manifest.get('classes')!=list(CLASSES) or manifest.get('iou_thresholds')!=list(IOU_THRESHOLDS)
                or manifest.get('action_order')!=list(ACTION_ORDER)
                or set(manifest.get('splits',{}))!={'train','validation'}):
            raise ValueError('Unknown AP export contract')
        if set(manifest['files'])!={'offline-statistics-train.jsonl','offline-statistics-validation.jsonl'}:
            raise ValueError('Unexpected statistics file contract')
        groups = manifest['recording_groups']
        if not all(groups.values()) or set(groups['train'])&set(groups['validation']): raise ValueError('Recording split overlap')
        # Header check first: never load a crossing3 file through development export.
        for split, record in manifest['splits'].items():
            sequences = [r['sequence'] for r in record['provenance']['inputs']]
            if (any('crossing3' in s for s in sequences) or len(sequences)!=len(set(sequences))
                    or sorted({recording_group(s) for s in sequences})!=groups[split]
                    or record['provenance']['detector']!=manifest['detector']):
                raise ValueError('Invalid detector or development recording headers')
        result, seen = {}, set()
        for split in manifest['splits']:
            name = 'offline-statistics-'+split+'.jsonl'; raw=z.read(name)
            if sha(raw)!=manifest['files'][name]: raise ValueError('Statistics SHA256 mismatch')
            origins = {r['sequence']:r for r in manifest['splits'][split]['provenance']['inputs']}
            bindings = manifest['splits'][split]['frame_bindings']
            frames = []
            for line in raw.decode().splitlines():
                row=json.loads(line); key=row['key']; seq=row['sequence']; ids=row['source_ids']
                if (seq not in origins or key in seen or not key.startswith(seq+':') or not key.endswith(':100000')
                        or not ids or str(ids[0])!='100000'
                        or key not in bindings):
                    raise ValueError('Frame identity or payload binding mismatch')
                binding = bindings[key]
                if (any(binding[k]!=row[k] for k in ('sequence','source_ids','prediction_sha256','gt_sha256'))
                        or origins[seq]['predictions_sha256'].get(binding['prediction_path'])!=row['prediction_sha256']):
                    raise ValueError('Frame-to-prediction/GT binding changed')
                seen.add(key)
                statistics=validate_statistics(row['statistics'],available_subsets(ids))
                frames.append({'key':key,'sequence':seq,'source_ids':ids,'statistics':statistics,
                    'native_association':row['native_association'],'quality':{a:frame_f1(s) for a,s in statistics.items()}})
            if (len(frames)!=manifest['splits'][split]['frames'] or not frames
                    or set(f['key'] for f in frames)!=set(bindings)
                    or [f['key'] for f in frames]!=sorted(f['key'] for f in frames)):
                raise ValueError('Incomplete or unordered frame coverage')
            for action in ACTION_ORDER:
                measured=metrics_both_orders(frames,baseline_choices(frames,action))
                for mode in MODES: same_metrics(measured[mode],manifest['splits'][split]['baselines'][action][mode])
            result[split]=frames
    return result, manifest


def load_choices(path, manifest, frames, split):
    path=Path(path)
    if path.suffix=='.zip':
        with zipfile.ZipFile(path) as z: raw=z.read('regional-policy-report.json')
    else: raw=path.read_bytes()
    name,choices=normalize_choices(json.loads(raw),manifest,frames,split)
    return name,choices,sha(raw)


def normalize_choices(row, manifest, frames, split):
    schema=row.get('schema')
    if schema=='phdsim-urbaning-regional-policy-v1':
        if split!='validation' or row.get('status')!='completed': raise ValueError('Regional report is validation-only')
        name='regional_linear_sum_audited_prototype'
        expected={'detector':row['detector'],'inputs':[i for p in row['validation_provenance'] for i in p['inputs']]}
        frozen=row['policies']['regional']
    elif schema==CHOICES_SCHEMA:
        if row.get('split')!=split: raise ValueError('Frozen choices split mismatch')
        name=row['name'];expected=row['provenance'];frozen=row.get('expected_metrics')
    else: raise ValueError('Unknown frozen choices schema')
    actual=manifest['splits'][split]['provenance']
    fields=('sequence','run_sha256','trace_sha256','predictions_sha256')
    def core(p): return sorted([{k:i[k] for k in fields} for i in p['inputs']],key=lambda i:i['sequence'])
    if expected['detector']!=actual['detector'] or core(expected)!=core(actual): raise ValueError('Choices use different frozen caches')
    if not isinstance(name,str) or not name or name in ACTION_ORDER:
        raise ValueError('Policy name must not replace a fixed baseline')
    keys=[f['key'] for f in frames]
    if set(row['choices'])!=set(keys): raise ValueError('Choices require exact frame coverage')
    choices=[row['choices'][k] for k in keys]
    for f,a in zip(frames,choices):
        if a not in available_subsets(f['source_ids']): raise ValueError('Unavailable frozen choice')
    if frozen:
        measured=evaluate(frames,choices,COST)
        if measured['peer_requests']!=frozen['peer_requests'] or abs(measured['mean_frame_f1']-frozen['mean_frame_f1'])>1e-12:
            raise ValueError('AP replay changed frozen requests/F1')
    return name,choices


def prior_choices(path, manifest, frames, split):
    if split!='validation':raise ValueError('The prior pilot is validation-only')
    with zipfile.ZipFile(path) as z: raw=z.read('validation-report.json')
    prior=json.loads(raw)
    if prior.get('schema')!='phdsim-urbaning-tree-pilot-v1' or prior.get('status')!='completed':
        raise ValueError('Unknown prior-pilot schema')
    result={}
    for name in ('ridge','tree'):
        original=prior['validation_policies'][name]
        label='previous_'+name
        row={'schema':CHOICES_SCHEMA,'split':split,'name':label,'provenance':prior['provenance']['validation'],
             'choices':original['choices'],'expected_metrics':original['global_confidence_sort']}
        _,choices=normalize_choices(row,manifest,frames,split)
        result[label]=(choices,original)
    return result,sha(raw)


def replay(archive, choices_file, output, split='validation', prior_pilot=None):
    out=Path(output).resolve()
    if out.exists(): raise FileExistsError('Use a new evaluation directory')
    data,manifest=load_archive(archive);frames=data[split]
    name,choices,choice_hash=load_choices(choices_file,manifest,frames,split)
    policies={a:metrics_both_orders(frames,baseline_choices(frames,a)) for a in ACTION_ORDER}
    policies[name]=metrics_both_orders(frames,choices)
    schedules={name:choices};prior_hash=None
    if prior_pilot:
        originals,prior_hash=prior_choices(prior_pilot,manifest,frames,split)
        for label,(selected,original) in originals.items():
            measured=metrics_both_orders(frames,selected)
            same_metrics(measured['global_confidence_sort'],original['global_confidence_sort'])
            same_metrics(measured['upstream_default_frame_order'],original['upstream_default_order'])
            policies[label]=measured;schedules[label]=selected
    ids,keys=[f['source_ids'] for f in frames],[f['key'] for f in frames]
    controls={}
    for label,reference_choices in schedules.items():
        controls[label]={}
        for control in ('budget','schedule'):
            samples={m:[] for m in MODES}
            for seed in range(100):
                selected=matched_random_subsets(ids,keys,reference_choices,seed,control)
                metrics=metrics_both_orders(frames,selected)
                for mode,m in metrics.items():
                    ref=policies[label][mode]
                    if m['peer_requests']!=ref['peer_requests'] or m['request_histogram']!=ref['request_histogram']:
                        raise ValueError('Matched random budget changed')
                    samples[mode].append(m)
            controls[label][control]={mode:ensemble_summary(v,list(range(100))) for mode,v in samples.items()}
            print('REPLAY',label,control,'100 seeds; AP orders reported separately',flush=True)
    always=policies['all']['global_confidence_sort']['peer_requests']
    for rows in policies.values():
        for row in rows.values():
            row['saved_requests_vs_always']=always-row['peer_requests']
            row['saved_fraction_vs_always']=(always-row['peer_requests'])/always if always else 0.
    report={'schema':'phdsim-urbaning-common-ap-replay-v1','status':'completed','split':split,
            'scope':'Existing frozen choices only; development replay, no fitting/tuning or new method claim',
            'protocol':manifest['protocol'],'archive_sha256':sha(Path(archive).read_bytes()),
            'choices_payload_sha256':choice_hash,'provenance':manifest['splits'][split]['provenance'],
            'prior_pilot_payload_sha256':prior_hash,
            'policies':policies,'random_controls':controls,
            'limitations':['Previously inspected development recordings; no independent test.',
                          'Historical linear-sum regional policy has an audited spatial limitation; AP completion does not repair it.',
                          'AP aggregates detections before integration; F1 is a secondary mean-frame diagnostic.',
                          'Peer requests are simulated counts, not measured bytes, latency or energy.']}
    out.mkdir(parents=True)
    (out/'common-ap-report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines=['# Frozen acquisition replay — development only','','Primary: BEV mAP@.5, global confidence sort. Upstream default order is separate.','',
           '| Policy | Global mAP@.5 | Upstream-order mAP@.5 | Secondary F1 | Requests | Saved |','|---|---:|---:|---:|---:|---:|']
    fmt=lambda v:'undefined (missing class)' if v is None else '{:.4f}%'.format(100*v)
    for label,rows in policies.items():
        m=rows['global_confidence_sort'];u=rows['upstream_default_frame_order']
        lines.append('| {} | {} | {} | {} | {} | {:.2f}% |'.format(label,fmt(m['macro_ap']['0.5']),fmt(u['macro_ap']['0.5']),fmt(m['mean_frame_f1']),m['peer_requests'],100*m['saved_fraction_vs_always']))
    lines+=['','No model, threshold or budget was selected by this evaluator. Per-class AP and both random controls are in the JSON.']
    (out/'README.md').write_text('\n'.join(lines)+'\n')
    with zipfile.ZipFile(out/'urbaning-common-ap-report.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for filename in ('common-ap-report.json','README.md'):z.write(out/filename,filename)
    with zipfile.ZipFile(out/'urbaning-common-ap-report.zip') as z:
        if z.testzip() is not None:raise ValueError('Report ZIP CRC failure')
    print('DONE:',out/'urbaning-common-ap-report.zip',flush=True)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
    e=subs.add_parser('export');e.add_argument('--train-runs',nargs='+',required=True);e.add_argument('--validation-runs',nargs='+',required=True)
    e.add_argument('--output-dir',required=True)
    r=subs.add_parser('evaluate');r.add_argument('--archive',required=True);r.add_argument('--choices',required=True)
    r.add_argument('--prior-pilot',help='Optional prior ridge/tree ZIP; requests/F1 and both AP orders must reproduce')
    r.add_argument('--split',choices=('train','validation'),default='validation');r.add_argument('--output-dir',required=True)
    a=p.parse_args(argv)
    if a.command=='export':export(a.train_runs,a.validation_runs,a.output_dir)
    else:replay(a.archive,a.choices,a.output_dir,a.split,a.prior_pilot)


if __name__=='__main__':main()
