#!/usr/bin/env python3
"""Read-only arithmetic, provenance and structural audit of supplied UrbanIng results.

No detector, training, data download or upstream runtime. Full-test AP values
are checked as reported; raw 1400-frame predictions are not in these bundles.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile
import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.decision.urbaning import ACTION_ORDER, available_subsets, matched_random_subsets
from phdsim.decision.urbaning_regional import choose_regional_subset
from phdsim.evaluation.urbaning_cached import frame_f1, frame_statistics, summarize_cached
from phdsim.experiments.urbaning_regional_learning import load_dataset, metrics
from phdsim.experiments.urbaning_regional_policy import evaluate, load_validation, prior_comparison
from phdsim.learning.urbaning_regional_gain import PROFILES, predict
from phdsim.learning.urbaning_regions import regional_features


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_zip(path, name):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(name))


def same(a, b, tolerance=1e-11):
    if abs(a-b) > tolerance: raise AssertionError((a, b))


def recover_complete_prefix(path):
    """Recover complete CRC-verified local ZIP entries; never guess missing bytes.

    Limited to the known seekable ZIP writer's no-descriptor, unencrypted
    stored/deflated members. Missing central directory is not declared intact.
    """
    raw, offset, recovered = Path(path).read_bytes(), 0, {}
    while offset+30 <= len(raw) and raw[offset:offset+4] == b'PK\x03\x04':
        _, _, flags, method, _, _, crc, size, plain_size, nlen, elen = struct.unpack_from('<4s5H3I2H', raw, offset)
        if flags & 9 or method not in (0, 8) or plain_size > 100_000_000: break
        start = offset+30+nlen+elen
        name = raw[offset+30:offset+30+nlen].decode('utf-8')
        if start+size > len(raw):
            return recovered, {'incomplete_member': name, 'available_compressed_bytes': len(raw)-start,
                               'declared_compressed_bytes': size}
        content = raw[start:start+size]
        try:
            content = zlib.decompress(content, -15) if method == 8 else content
        except zlib.error as exc:
            return recovered, {'incomplete_member':name,'error':str(exc),'declared_compressed_bytes':size,
                               'interpretation':'Incomplete or damaged compressed member; cause not established'}
        if len(content) != plain_size or zlib.crc32(content) != crc:
            return recovered, {'incomplete_member':name,'error':'CRC or decompressed length mismatch'}
        if name in recovered: raise ValueError('Duplicate recovered entry')
        recovered[name] = content
        offset = start+size
    return recovered, {'stopped_at': offset, 'total_bytes': len(raw)}


def box(x=0, y=0):
    a = np.array([[-1,-1],[1,-1],[1,1],[-1,1]], float) + [x,y]
    return np.r_[np.c_[a,np.zeros(4)], np.c_[a,np.ones(4)]]


def spatial_collapse(model):
    car, infra = np.eye(4), np.eye(4)
    car[0,3], infra[0,3] = -50, 50
    ids = ['100000','200000','-2']; poses = {'200000': car, '-2': infra}
    boxes = np.stack([box(-30,0),box(30,0)])
    one, mask = regional_features(ids,.7,boxes,np.array([[.2,1],[.9,1]]),poses)
    two, _ = regional_features(ids,.7,boxes,np.array([[.9,1],[.2,1]]),poses)
    np.testing.assert_allclose(one.astype(float).sum(axis=0),two.astype(float).sum(axis=0),atol=1e-12)
    pred = predict(model,np.stack([one,two]),np.stack([mask,mask]))
    total = pred.sum(axis=(1,3))
    np.testing.assert_allclose(total[0], total[1], atol=1e-11)
    assert np.max(np.abs(pred[0]-pred[1])) > .01
    decisions = {str(cost): [choose_regional_subset(ids,p,cost) for p in pred] for cost in (0,1,2,4,8,16,32,64)}
    assert all(a == b for a,b in decisions.values())
    return {'construction': 'Two same-class boxes at x=-30,+30; exchange scores .2/.9; Car2 at -50, Infra at +50.',
            'feature_sum_max_difference': float(np.max(np.abs(one.astype(float).sum(axis=0)-two.astype(float).sum(axis=0)))),
            'local_prediction_max_difference': float(np.max(np.abs(pred[0]-pred[1]))),
            'head_totals': total.tolist(), 'total_prediction_max_difference': float(np.max(np.abs(total[0]-total[1]))),
            'decisions': decisions,
            'verdict': 'Linear cell predictor followed by sum discards the association between local need and peer geometry.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts',required=True)
    p.add_argument('--benchmark',required=True)
    p.add_argument('--geometry-model',required=True)
    p.add_argument('--regional-model-dir',required=True)
    p.add_argument('--output-dir',required=True)
    args = p.parse_args()
    root, out = Path(args.artifacts), Path(args.output_dir)
    out.mkdir(parents=True,exist_ok=False)
    audit = {'scope': 'Supplied artifact integrity, reported arithmetic/provenance, regional replay and structural counterexamples; no raw full-test rerun',
             'artifacts': {}, 'findings': {}}
    for path in sorted(root.glob('*.zip')):
        entry = {'bytes': path.stat().st_size, 'sha256': digest(path)}
        try:
            with zipfile.ZipFile(path) as z:
                if len(z.namelist()) != len(set(z.namelist())): raise ValueError('Duplicate members')
                failed = z.testzip()
                if failed: raise ValueError('CRC failure: '+failed)
                entry.update(valid_zip=True,members=len(z.namelist()))
        except (zipfile.BadZipFile,ValueError,EOFError) as exc:
            entry.update(valid_zip=False,error=str(exc))
        audit['artifacts'][path.name] = entry

    full = read_zip(root/'urbaning-full-policy-report.zip','full-policy-report.json')
    benchmark = json.loads(Path(args.benchmark).read_text())
    assert digest(args.benchmark) == full['plan']['reference_sha256']
    assert digest(args.geometry_model) == full['plan']['models']['gain_geometry']['sha256']
    assert full['plan']['expected_frames'] == benchmark['frames'] == 1400
    sequence_groups = sorted({s.split('_crossing')[0] for s in full['plan']['test_sequences']})
    assert len(sequence_groups) == 5 and len(full['completed']) == 7
    release = benchmark['release_reference_ap']
    official_map = sum(c['0.5'] for c in release.values())/4
    audit['findings']['reference'] = {
        'release_map_0.5': official_map,
        'reproduced_default_order_map_0.5': benchmark['metrics_by_global_sort']['False']['macro_ap']['0.5'],
        'reproduced_global_order_map_0.5': benchmark['metrics_by_global_sort']['True']['macro_ap']['0.5'],
        'max_class_delta_at_0.5': max(abs(v['0.5']) for v in benchmark['metrics_by_global_sort']['False']['delta_vs_release'].values()),
        'frames': 1400,'sequence_count': 7,'original_recording_groups': sequence_groups,
        'interpretation': 'Close to the released checkpoint evaluation, not a new higher model score or proof of paper-table reproduction.'}
    audit['findings']['full_test'] = {}
    for model_name, modes in full['models'].items():
        global_report = modes['True']
        defaults = modes['False']
        policies = global_report['policies']
        assert global_report['seeds'] == list(range(100))
        keys = list(policies['all']['choices'])
        assert len(keys) == len(set(keys)) == 1400
        availability = {'ego': ['100000'],'vehicle_peer': ['100000','200000'],
                        'infrastructure': ['100000','-3'],'all': ['100000','200000','-3']}
        ids = [availability[policies['all']['choices'][k]] for k in keys]
        for name, row in policies.items():
            assert set(row['choices']) == set(keys)
            assert row['choices'] == defaults['policies'][name]['choices']
            requests = sum(len(available_subsets(i)[row['choices'][k]])-1 for i,k in zip(ids,keys))
            assert requests == row['peer_requests']
            same(row['mean_frame_utility'],row['mean_frame_f1']-.05*requests/1400)
            for iou in ('0.3','0.5','0.7'):
                same(row['macro_ap'][iou],sum(c['ap'][iou] for c in row['classes'].values())/4)
        for mode in ('False','True'):
            for iou in ('0.3','0.5','0.7'):
                same(modes[mode]['policies']['all']['macro_ap'][iou],benchmark['metrics_by_global_sort'][mode]['macro_ap'][iou])
        learned = policies['learned_joint_gain']
        choices = [learned['choices'][k] for k in keys]
        controls = global_report['random_controls']['learned_joint_gain']
        for mode in ('budget','schedule'):
            for seed, sample in controls[mode]['per_seed'].items():
                random = matched_random_subsets(ids,keys,choices,int(seed),mode)
                pulls = [len(available_subsets(i)[a])-1 for i,a in zip(ids,random)]
                assert sum(pulls) == sample['peer_requests'] == learned['peer_requests']
                assert Counter(random) == Counter(sample['action_histogram'])
                assert {str(n):pulls.count(n) for n in range(3)} == sample['request_histogram'] == learned['request_histogram']
        times = defaultdict(list)
        for key, association in global_report['native_associations'].items():
            times[key.split('_crossing')[0]].append(association['timestamp_ns'])
        assert all(len(v)==len(set(v)) for v in times.values())
        audit['findings']['full_test'][model_name] = {
            'map_0.5': learned['macro_ap']['0.5'],'f1': learned['mean_frame_f1'],'requests': learned['peer_requests'],
            'saved_fraction': 1-learned['peer_requests']/policies['all']['peer_requests'],
            'budget_random': controls['budget']['summary'],
            'f1_draws_beaten': sum(learned['mean_frame_f1'] > row['mean_frame_f1'] for row in controls['budget']['per_seed'].values()),
            'map_draws_beaten': sum(learned['macro_ap']['0.5'] > row['macro_ap']['0.5'] for row in controls['budget']['per_seed'].values()),
            'note': 'Reported AP/F1 checked internally; full per-detection statistics are not bundled.'}
    print('PASS full-report arithmetic, reference/model hashes, coverage and matched random choices',flush=True)

    recovered, recovery = recover_complete_prefix(root/'urbaning-regional-learning.zip')
    audit['findings']['learning_archive_recovery'] = {**recovery,'complete_crc_verified_members':list(recovered)}
    report = json.loads(recovered['regional-learning-report.json'])
    model_dir = Path(args.regional_model_dir)
    for profile in PROFILES:
        assert recovered['models/'+profile+'.json'] == (model_dir/(profile+'.json')).read_bytes()
    data, manifest, mhash = load_dataset(root/'urbaning-regional-dataset.zip')
    assert mhash == report['dataset_manifest_sha256']
    val = data['validation']
    feature_examples = []
    with zipfile.ZipFile(root/'urbaning-frame-inspection.zip') as z:
        for name in z.namelist():
            if not name.endswith('local-evidence.json'): continue
            local = json.loads(z.read(name))
            i = val['frame_keys'].tolist().index(local['frame_key'])
            features, available = regional_features(local['source_ids'], local['ego_entropy'],
                np.asarray(local['ego_boxes']), np.asarray(local['ego_scores']),local['peer_to_ego'])
            np.testing.assert_array_equal(features,val['features'][i])
            np.testing.assert_array_equal(available,val['available'][i])
            feature_examples.append(local['frame_key'])
    audit['findings']['regional_feature_recomputation'] = {
        'examples':feature_examples,'columns_checked':46,
        'inputs':'Car1 boxes/scores/entropy and shared poses only; no GT or peer detections',
        'result':'exact equality on five supplied real-data cases'}
    checked = {}
    for profile in PROFILES:
        model = json.loads(recovered['models/'+profile+'.json'])
        prediction = predict(model,val['features'],val['available'])
        score = metrics(prediction,val['gain'],val['available'],val['features'])
        same(score['macro_mse'],report['validation'][profile]['macro_mse'])
        checked[profile] = {'macro_mse':score['macro_mse'],'stratum_macro_mse':score['stratum_macro_mse']}
    audit['findings']['regional_prediction'] = {'verified_frozen_models':checked,
        'zero_mse':report['validation']['zero']['macro_mse'],'frames':manifest['frames'],
        'recording_groups':manifest['recording_groups'],
        'limitation':'23.4% is relative prediction MSE reduction, not detection or policy improvement.'}
    full_model = json.loads(recovered['models/full.json'])
    audit['findings']['spatial_collapse'] = spatial_collapse(full_model)
    r = read_zip(root/'urbaning-regional-policy.zip','regional-policy-report.json')
    frozen = read_zip(root/'urbaning-regional-policy.zip','regional-policy.json')
    assert frozen['model'] == full_model
    assert hashlib.sha256(recovered['models/full.json']).hexdigest() == r['model_sha256']
    counts, source_ids = load_validation(root/'urbaning-regional-dataset.zip',val,manifest)
    prior = prior_comparison(root/'urbaning-tree-pilot.zip',manifest,counts,source_ids,val['frame_keys'].tolist())
    geometry = json.loads(Path(args.geometry_model).read_text())
    ridge = read_zip(root/'urbaning-tree-pilot.zip','ridge-gain.json')
    for name in ('heads','mean','scale','alpha','features'):
        assert geometry[name] == ridge[name]
    audit['findings']['prior_validation'] = {'replayed_policies':prior,'ridge_equals_existing_geometry':True}
    prediction = predict(full_model,val['features'],val['available'])
    choices = [choose_regional_subset(i,p,r['protocol']['selected_error_count_penalty']) for i,p in zip(source_ids,prediction)]
    assert dict(zip(val['frame_keys'].tolist(),choices)) == r['choices']
    score = evaluate(counts,source_ids,choices)
    same(score['mean_frame_f1'],r['policies']['regional']['mean_frame_f1'])
    assert score['peer_requests'] == 329
    for mode in ('budget','schedule'):
        for seed, sample in r['random_controls'][mode]['per_seed'].items():
            random = matched_random_subsets(source_ids,val['frame_keys'].tolist(),choices,int(seed),mode)
            random_score = evaluate(counts,source_ids,random)
            same(random_score['mean_frame_f1'],sample['mean_frame_f1'])
            assert random_score['peer_requests'] == sample['peer_requests'] == 329
    audit['findings']['regional_policy'] = {k:r[k] for k in ('policies','candidates','protocol')}
    print('PASS regional hashes/counts, all frozen model MSE, chosen actions and 200 exact random replays',flush=True)

    stats_one = frame_statistics(np.stack([box(),box(10,0)]),np.array([[.9,1],[.8,1]]),np.stack([box()]),np.array([1]))
    stats_two = frame_statistics(np.stack([box(),box(10,0)]),np.array([[.8,1],[.9,1]]),np.stack([box()]),np.array([1]))
    same(frame_f1(stats_one),frame_f1(stats_two))
    ap = [summarize_cached(s)['classes']['Vehicle']['ap']['0.5'] for s in (stats_one,stats_two)]
    assert ap[0] > ap[1]
    audit['findings']['counts_do_not_determine_ap'] = {'same_f1':frame_f1(stats_one),'different_vehicle_ap':ap}
    audit['findings']['limitations'] = [
        'Original full-test boxes/GT/model runtime are on Ares, not independently rerun here.',
        'Cache hashes attest identity, not annotation correctness or causal pre-query sensor availability.',
        'Validation was repeatedly inspected and used for selection; new regional results are development-only.',
        'Benchmarking one CoBEVT checkpoint is not a comparison of every published fusion method.',
        'A passed software test suite does not establish scientific validity of the policy.']
    (out/'audit-checks.json').write_text(json.dumps(audit,indent=2,allow_nan=False)+'\n')
    repair = out/'repaired-learning'; repair.mkdir()
    (repair/'AUDIT_REPAIR.md').write_text(
        '# Archive repair, 2026-11-03\n\nThe previous shared ZIP was incomplete and lacked a usable central directory. '
        'Complete JSON models, report, README, SOURCE and map were recovered from its local headers and verified by CRC. '
        'Their bytes and numerical results are unchanged. The incomplete validation-predictions.npz member is omitted; '
        'predictions can be regenerated from the five frozen models and the verified dataset without detector inference or fitting. '
        'These results remain development-only; the separate audit identifies a spatial pooling limitation.\n')
    with zipfile.ZipFile(repair/'urbaning-regional-learning.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in recovered.items():
            if name.endswith('.npz'): continue
            z.writestr(name,content)
        z.write(repair/'AUDIT_REPAIR.md','AUDIT_REPAIR.md')
    with zipfile.ZipFile(repair/'urbaning-regional-learning.zip') as z: assert z.testzip() is None
    print('PASS repaired compact archive; original member bytes retained, incomplete predictions omitted',flush=True)
    print('DONE',out/'audit-checks.json',flush=True)


if __name__ == '__main__': main()
