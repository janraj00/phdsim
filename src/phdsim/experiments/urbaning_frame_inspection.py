"""Inspect spatial detection errors in frozen train/validation caches only.

This is a GT-guided qualitative audit, not an acquisition policy or visibility
estimator. No detector inference, fitting, upstream import or network is used.
"""

import argparse
import html
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets, choose_subset
from phdsim.evaluation.urbaning import CLASSES
from phdsim.evaluation.urbaning_cached import _polygon, _radius_mask, polygon_iou, validate_arrays
from phdsim.experiments.urbaning_geometry import load_sidecars
from phdsim.experiments.urbaning_subsets import _inside, digest, load_runs, write_json
from phdsim.learning.urbaning import recording_group

COST = .05
NAMES = {'ego': 'Car1', 'vehicle_peer': 'Car1 + Car2',
         'infrastructure': 'Car1 + Infra', 'all': 'Car1 + Car2 + Infra'}
REASONS = {
    'reference': 'Fixed middle frame among frames with both partners available',
    'car2_recovery': 'Car2 recovers GT missed by both Car1 and the Infra variant',
    'infra_recovery': 'Infra recovers GT missed by both Car1 and the Car2 variant',
    'joint_recovery': 'Both partners recover GT missed by all three other variants',
    'lost_after_adding_car2': 'Adding Car2 to Infra loses previously matched GT',
    'no_query_net_advantage': 'Car1-only has higher F1-minus-request-cost than all queried variants'}


def match_objects(boxes, scores, gt_boxes, gt_labels):
    """Trace original array indices through the existing evaluator's matching.

Same class, descending confidence, greedy BEV IoU >= .5, float32 IoU rounding,
and the same upstream 0--100m corner-radius filter. IDs are frame-local array
indices, not dataset tracking IDs. Empty-class F1 is undefined (None).
"""
    boxes, scores = np.asarray(boxes), np.asarray(scores)
    gt_boxes, gt_labels = np.asarray(gt_boxes), np.asarray(gt_labels)
    if scores.shape != (len(boxes), 2):
        raise ValueError('Expected Nx2 scores')
    validate_arrays(boxes, scores[:, 1], scores[:, 0])
    validate_arrays(gt_boxes, gt_labels)
    pred_ids = np.flatnonzero(_radius_mask(boxes))
    gt_ids = np.flatnonzero(_radius_mask(gt_boxes))
    matches, classes = [], {}
    for class_id, name in enumerate(CLASSES, 1):
        pred = pred_ids[scores[pred_ids, 1] == class_id]
        pred = pred[np.argsort(-scores[pred, 0])]
        truth = gt_ids[gt_labels[gt_ids] == class_id]
        pred_polygons = [_polygon(boxes[p]) for p in pred]
        gt_polygons = [_polygon(gt_boxes[g]) for g in truth]
        overlap = np.asarray([[polygon_iou(p, g) for g in gt_polygons]
                               for p in pred_polygons], dtype=np.float32).reshape(len(pred), len(truth))
        remaining, tp = list(range(len(truth))), 0
        for p, row in zip(pred, overlap):
            best = int(np.argmax(row[remaining])) if remaining else None
            if best is not None and row[remaining[best]] >= .5:
                slot = remaining.pop(best)
                matches.append({'prediction_index': int(p), 'gt_index': int(truth[slot]),
                                'class_id': class_id, 'iou': float(row[slot]),
                                'score': float(scores[p, 0])})
                tp += 1
        denominator = len(truth) + len(pred)
        classes[name] = {'tp': tp, 'fp': len(pred) - tp, 'fn': len(truth) - tp,
                         'gt': len(truth), 'f1': 2 * tp / denominator if denominator else None}
    matched_gt = {m['gt_index'] for m in matches}
    matched_pred = {m['prediction_index'] for m in matches}
    denominator = len(gt_ids) + len(pred_ids)
    return {'matches': matches, 'classes': classes,
            'gt_indices_considered': gt_ids.tolist(), 'prediction_indices_considered': pred_ids.tolist(),
            'matched_gt_indices': sorted(matched_gt),
            'missed_gt_indices': sorted(set(gt_ids.tolist()) - matched_gt),
            'false_positive_indices': sorted(set(pred_ids.tolist()) - matched_pred),
            'tp': len(matches), 'fp': len(pred_ids) - len(matches), 'fn': len(gt_ids) - len(matches),
            'f1': 2 * len(matches) / denominator if denominator else 1.}


def audit_frame(frame, data):
    options = available_subsets(frame['source_ids'])
    outcomes = {a: match_objects(data[a + '_boxes'], data[a + '_scores'],
                                  data['gt_boxes'], data['gt_labels']) for a in options}
    ego_matched = set(outcomes['ego']['matched_gt_indices'])
    for action, result in outcomes.items():
        if abs(result['f1'] - frame['quality'][action]) > 1e-12:
            raise ValueError('Object matching disagrees with the verified cached evaluator')
        found = set(result['matched_gt_indices'])
        result['recovered_vs_ego_gt_indices'] = sorted(found - ego_matched)
        result['lost_vs_ego_gt_indices'] = sorted(ego_matched - found)
        result['requests'] = len(options[action]) - 1
        result['utility'] = result['f1'] - COST * result['requests']
    hindsight = choose_subset(frame['source_ids'],
                              {a: v['f1'] - outcomes['ego']['f1'] for a, v in outcomes.items()}, COST)
    return {'frame_key': frame['key'], 'sequence': frame['sequence'],
            'source_ids': frame['source_ids'], 'outcomes': outcomes,
            'offline_best_action_f1_minus_cost': hindsight}


def category_evidence(frame):
    outcomes = frame['outcomes']
    if set(outcomes) != set(ACTION_ORDER):
        return {}
    found = {a: set(v['matched_gt_indices']) for a, v in outcomes.items()}
    groups = {
        'car2_recovery': found['vehicle_peer'] - found['ego'] - found['infrastructure'],
        'infra_recovery': found['infrastructure'] - found['ego'] - found['vehicle_peer'],
        'joint_recovery': found['all'] - found['ego'] - found['vehicle_peer'] - found['infrastructure'],
        'lost_after_adding_car2': found['infrastructure'] - found['all']}
    evidence = {name: {'score': len(ids), 'focus_gt_indices': sorted(ids)} for name, ids in groups.items()}
    advantage = outcomes['ego']['utility'] - max(v['utility'] for a, v in outcomes.items() if a != 'ego')
    evidence['no_query_net_advantage'] = {'score': max(0., advantage),
                                        'focus_gt_indices': outcomes['ego']['missed_gt_indices'][:1]}
    return evidence


def select_cases(frames, min_gap=10):
    if min_gap < 0:
        raise ValueError('Frame gap must be nonnegative')
    candidates = [f for f in sorted(frames, key=lambda f: f['frame_key'])
                  if set(f['outcomes']) == set(ACTION_ORDER)]
    if not candidates:
        raise ValueError('Need frames where Car2 and Infra are both available')
    middle = candidates[len(candidates) // 2]
    chosen = [(middle, 'reference', {'score': None,
                                    'focus_gt_indices': middle['outcomes']['ego']['missed_gt_indices'][:1]})]
    omitted = []
    for category in list(REASONS)[1:]:
        eligible = [(f, category_evidence(f)[category]) for f in candidates]
        eligible = [(f, e) for f, e in eligible if e['score'] > 1e-12]
        eligible.sort(key=lambda pair: (-pair[1]['score'], pair[0]['frame_key']))
        spaced = [(f, e) for f, e in eligible if all(
            f['frame_key'] != old['frame_key'] and
            (f['sequence'] != old['sequence'] or abs(f['row_position'] - old['row_position']) >= min_gap)
            for old, _, _ in chosen)]
        if spaced:
            f, evidence = spaced[0]
            chosen.append((f, category, evidence))
        else:
            omitted.append({'category': category, 'positive_candidates': len(eligible),
                            'reason': 'no positive candidate' if not eligible else 'spacing/uniqueness constraint'})
    return chosen, omitted


def plot_case(data, audit, poses, output, focus_index, zoom=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Polygon

    gt = data['gt_boxes']
    center = gt[focus_index, :4, :2].mean(axis=0) if focus_index is not None else np.zeros(2)
    if zoom:
        xlim, ylim = (center[0] - 18, center[0] + 18), (center[1] - 18, center[1] + 18)
    else:
        polygons = [gt[i, :4, :2] for i in audit['outcomes']['ego']['gt_indices_considered']]
        for a, result in audit['outcomes'].items():
            polygons.extend(data[a + '_boxes'][i, :4, :2] for i in result['prediction_indices_considered'])
        xy = np.vstack([np.zeros((1, 2))] + polygons)
        lo, hi = xy.min(axis=0) - 5, xy.max(axis=0) + 5
        width = max(20., float(np.max(hi - lo)))
        c = (hi + lo) / 2
        xlim, ylim = (c[0] - width/2, c[0] + width/2), (c[1] - width/2, c[1] + width/2)
    fig, axes = plt.subplots(2, 2, figsize=(13, 12))
    try:
        for ax, action in zip(axes.ravel(), ACTION_ORDER):
            result = audit['outcomes'][action]
            missed = set(result['missed_gt_indices'])
            for i in result['gt_indices_considered']:
                ax.add_patch(Polygon(gt[i, :4, :2], fill=False, edgecolor='#c62828' if i in missed else '#999999',
                                     linewidth=1.3 if i in missed else .65, linestyle='--'))
            false = set(result['false_positive_indices'])
            for i in result['prediction_indices_considered']:
                ax.add_patch(Polygon(data[action + '_boxes'][i, :4, :2], fill=False,
                                     edgecolor='#e68a00' if i in false else '#16844b', linewidth=.9))
                if zoom:
                    p = data[action + '_boxes'][i, :4, :2].mean(axis=0)
                    if xlim[0] <= p[0] <= xlim[1] and ylim[0] <= p[1] <= ylim[1]:
                        score, class_id = data[action + '_scores'][i]
                        ax.annotate('{} {:.2f}'.format(('V', 'H', '2W', 'P')[int(class_id)-1], score),
                                    p, xytext=(2, -7), textcoords='offset points', fontsize=6)
            if focus_index is not None:
                ax.scatter(*center, s=130, facecolors='none', edgecolors='#294ec4', linewidth=1.5)
                ax.annotate('GT {}: {}'.format(focus_index, CLASSES[int(data['gt_labels'][focus_index]) - 1]),
                            center, xytext=(5, 8), textcoords='offset points', fontsize=8, color='#294ec4')
            ax.scatter(0, 0, marker='*', s=90, color='black', zorder=5)
            for identity, pose in poses.items():
                p = np.asarray(pose)[:2, 3]
                vehicle = int(identity) > 0
                ax.scatter(*p, marker='^' if vehicle else 's', color='#2563b0' if vehicle else '#8d36a8', s=45)
            ax.set(xlim=xlim, ylim=ylim, xlabel='Car1 LiDAR frame x [m]', ylabel='Car1 LiDAR frame y [m]')
            ax.set_aspect('equal'); ax.grid(alpha=.2)
            ax.set_title('{}\nTP={}  FP={}  FN={}  F1={:.3f}'.format(
                NAMES[action], result['tp'], result['fp'], result['fn'], result['f1']), fontsize=11)
        legend = [Line2D([], [], color='#16844b', label='Correct prediction (TP)'),
                  Line2D([], [], color='#e68a00', label='False prediction (FP)'),
                  Line2D([], [], color='#c62828', linestyle='--', label='Missed GT (FN)'),
                  Line2D([], [], color='#999999', linestyle='--', label='Matched GT reference'),
                  Line2D([], [], marker='*', color='black', linestyle='', label='Car1 origin'),
                  Line2D([], [], marker='^', color='#2563b0', linestyle='', label='Car2 pose'),
                  Line2D([], [], marker='s', color='#8d36a8', linestyle='', label='Infra site origin proxy')]
        fig.legend(handles=legend, loc='lower center', ncol=3, fontsize=9)
        fig.suptitle(audit['frame_key'] + (' — 36m zoom' if zoom else ' — full scene') +
                     '\nOffline GT-guided inspection; BEV IoU 0.5; no visibility/occlusion map', fontsize=12)
        fig.tight_layout(rect=(0, .09, 1, .94))
        fig.savefig(output, dpi=140)
    finally:
        plt.close(fig)
    from PIL import Image
    with Image.open(output) as image:
        image.verify()


def write_index(out, cases):
    sections = []
    for case in cases:
        rows = ''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{:.3f}</td><td>{:.3f}</td></tr>'.format(
            NAMES[a], m['tp'], m['fp'], m['fn'], m['f1'], m['utility'])
            for a, m in case['outcomes'].items())
        directory = case['directory']
        sections.append('<section><h2>{}</h2><p>{}</p><p>{}</p><table><tr><th>Input</th><th>TP</th>'
                        '<th>FP</th><th>FN</th><th>F1</th><th>F1 − cost</th></tr>{}</table>'
                        '<p><a href="{}/local-evidence.json">Car1 evidence + pose metadata</a> | '
                        '<a href="{}/offline-outcomes.json">Offline outcomes with GT</a></p>'
                        '<img src="{}/scene.png" alt="Four full-scene comparisons">'
                        '<img src="{}/zoom.png" alt="Four zoomed comparisons"></section>'.format(
                            html.escape(case['frame_key']), html.escape(REASONS[case['category']]),
                            html.escape(str(case['evidence'])), rows, directory, directory, directory, directory))
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>UrbanIng frame inspection</title>' \
           '<style>body{font:16px system-ui;max-width:1300px;margin:30px auto;padding:20px}img{width:100%}' \
           'table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:7px}section{margin-top:55px}</style>' \
           '<h1>UrbanIng: offline spatial error inspection</h1>' \
           '<p>These are cached boxes over GT, not raw LiDAR images, visibility maps or online policy inputs. ' \
           'TP = correct prediction; FP = false prediction; FN = missed labelled object. ' \
           'Every panel uses the same GT, axes and matching protocol. ' \
           'GT-guided cases illustrate mechanisms; they do not estimate case frequencies. ' \
           'GT IDs are frame-local indices, not tracking identities. Infra marker is a site-origin proxy.</p>' + \
           ''.join(sections) + '</html>'
    (out / 'index.html').write_text(page, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Completed Car1 training/validation cache')
    parser.add_argument('--geometry', required=True, help='Existing trace-bound pose sidecar')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--min-frame-gap', type=int, default=10)
    args = parser.parse_args(argv)
    root, out = Path(args.run).resolve(), Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError('Preserve existing outputs; use a fresh inspection directory')
    if out.is_relative_to(root):
        raise ValueError('Keep inspection outputs outside the immutable cache directory')
    run = json.loads((root / 'run.json').read_text())
    sequence = run['arguments']['sequence']
    recording_group(sequence)
    if 'crossing3' in sequence or str(run['arguments']['ego_id']) != '100000':
        raise ValueError('Inspect Car1 training/validation recordings outside crossing3')
    if args.min_frame_gap < 0:
        raise ValueError('Frame gap must be nonnegative')
    import matplotlib  # preflight before expensive cache processing
    matplotlib.use('Agg')
    from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: F401
    print('VERIFY cached predictions, baseline AP, GT and pose bindings (no inference)', flush=True)
    frames, provenance = load_runs([root], [args.geometry])
    poses, pose_hash = load_sidecars([args.geometry])[digest(root / 'frames.jsonl')]
    if pose_hash != provenance['inputs'][0]['geometry_sidecar_sha256']:
        raise ValueError('Pose sidecar changed during inspection')
    rows = {r['frame_key']: r for r in map(json.loads, (root / 'frames.jsonl').read_text().splitlines())}
    if digest(root / 'frames.jsonl') != provenance['inputs'][0]['trace_sha256']:
        raise ValueError('Frame trace changed during inspection')
    audits = []
    for index, frame in enumerate(frames):
        path = _inside(root, rows[frame['key']]['predictions'])
        if digest(path) != provenance['inputs'][0]['predictions_sha256'][rows[frame['key']]['predictions']]:
            raise ValueError('Cached prediction changed during inspection')
        with np.load(path, allow_pickle=False) as data:
            audit = audit_frame(frame, data)
        audit['row_position'] = index
        audits.append(audit)
        if (index + 1) % 25 == 0:
            print('MATCH {}/{} frames'.format(index + 1, len(frames)), flush=True)
    selected, omitted = select_cases(audits, args.min_frame_gap)
    out.mkdir(parents=True)
    with (out / 'frame-summaries.jsonl').open('x') as stream:
        for audit in audits:
            stream.write(json.dumps(audit, allow_nan=False) + '\n')
    cases = []
    for number, (audit, category, evidence) in enumerate(selected, 1):
        key = audit['frame_key']
        directory = 'case-{:02d}-{}'.format(number, category)
        dest = out / directory; dest.mkdir()
        source = _inside(root, rows[key]['predictions'])
        expected = provenance['inputs'][0]['predictions_sha256'][rows[key]['predictions']]
        shutil.copyfile(source, dest / 'predictions.npz')
        if digest(dest / 'predictions.npz') != expected:
            raise ValueError('Selected payload copy changed')
        with np.load(dest / 'predictions.npz', allow_pickle=False) as data:
            frame = next(f for f in frames if f['key'] == key)
            # Strict input allowlist: labels and peer perception stay in the
            # separate offline file. Frame identifiers are for joining, not ML features.
            local = {'frame_key': key, 'source_ids': frame['source_ids'],
                     'ego_entropy': frame['ego_entropy'], 'ego_boxes': data['ego_boxes'].tolist(),
                     'ego_scores': data['ego_scores'].tolist(), 'peer_to_ego': poses['frames'][key],
                     'native_association': frame['native_association'],
                     'scope': 'Car1 detections plus assumed shared pose/availability metadata; causal timing unvalidated'}
            write_json(dest / 'local-evidence.json', local)
            offline = dict(audit, category=category, evidence=evidence,
                           gt_boxes=data['gt_boxes'].tolist(), gt_labels=data['gt_labels'].tolist(),
                           prediction_boxes={a: data[a + '_boxes'].tolist() for a in ACTION_ORDER},
                           prediction_scores={a: data[a + '_scores'].tolist() for a in ACTION_ORDER})
            write_json(dest / 'offline-outcomes.json', offline)
            focus = evidence['focus_gt_indices'][:1] or audit['outcomes']['ego']['gt_indices_considered'][:1]
            focus = focus[0] if focus else None
            plot_case(data, audit, poses['frames'][key], dest / 'scene.png', focus)
            plot_case(data, audit, poses['frames'][key], dest / 'zoom.png', focus, zoom=True)
        cases.append(dict(audit, directory=directory, category=category, evidence=evidence,
                          payload_sha256=expected, focus_gt_index=focus))
        print('EXPORT', category, key, flush=True)
    code = subprocess.run(['git', '-C', str(Path(__file__).resolve().parents[3]), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True).stdout.strip()
    manifest = {'schema': 'phdsim-urbaning-frame-inspection-v1', 'status': 'completed',
                'scope': 'GT-guided qualitative audit on train/validation only; not policy performance evidence',
                'sequence': sequence, 'frames': len(frames),
                'both_available_frames': sum(set(f['outcomes']) == set(ACTION_ORDER) for f in audits),
                'selection_rules': REASONS, 'minimum_row_gap': args.min_frame_gap, 'omitted_categories': omitted,
                'request_cost': COST, 'iou_threshold': .5, 'code_commit': code,
                'matplotlib': matplotlib.__version__, 'numpy': np.__version__, 'provenance': provenance,
                'cases': cases,
                'limitations': ['No point-cloud coverage, visibility or occlusion map is inferred from these boxes.',
                                'Pose sharing is assumed; Infra is the bundled site-origin proxy.',
                                'Native associations are retained, not certified as causal online observations.',
                                'GT-guided selection is qualitative; missing categories and spacing exclusions are reported.']}
    write_json(out / 'manifest.json', manifest)
    write_index(out, cases)
    files = sorted(p for p in out.rglob('*') if p.is_file())
    with zipfile.ZipFile(out / 'urbaning-frame-inspection.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(path.relative_to(out)))
    print('DONE:', out / 'urbaning-frame-inspection.zip', flush=True)


if __name__ == '__main__':
    main()
