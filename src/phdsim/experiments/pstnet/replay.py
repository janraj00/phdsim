"""Measured gated execution; peer images are loaded only after acquisition."""

import numpy as np
from hashlib import sha256
import json
from pathlib import Path
import torch

from phdsim.artifacts import write_json_atomic as _write
from phdsim.datasets.pst900.segmentation import load_frames, require_benchmark_split
from phdsim.perception.pstnet.checkpoint import load_models
from phdsim.perception.pstnet.features import FEATURE_NAMES

from phdsim.decision.pstnet import LearnedPstPolicy
from phdsim.evaluation.segmentation import confusion_matrix, summarize_choices
from phdsim.models.linear import LinearModel
from phdsim.perception.pstnet.input import reference_mask
from phdsim.runtime.segmentation import SegmentationReplay

def run_gated(manifest, rgb_weights, fusion_weights, bundle_path, output, *, cost=.005, device='cpu', threads=6):
    """Real selective inference, not lookup of the cached fused test output."""
    if Path(output).exists():
        raise FileExistsError('Replay report exists; choose a new output')
    torch.set_num_threads(threads)
    rgb, fusion, provenance = load_models(rgb_weights, fusion_weights, device)
    bundle = json.loads(Path(bundle_path).read_text(encoding='utf-8'))
    if bundle['schema'] != 'phdsim-pstnet-acquisition-v1' or bundle['feature_names'] != list(FEATURE_NAMES):
        raise ValueError('Incompatible acquisition bundle')
    if bundle['vision_and_data']['models'] != provenance or bundle['vision_and_data']['manifest_sha256'] != sha256(Path(manifest).read_bytes()).hexdigest():
        raise ValueError('Gate was fitted for different vision weights or dataset')
    # Online: parse metadata only. Verify each delivered image lazily, so even
    # integrity checks cannot open unrequested peer images or reference masks.
    frames = load_frames(manifest, verify=False)
    require_benchmark_split(frames)
    policy = LearnedPstPolicy(LinearModel.from_dict(bundle['model']), cost)
    engine = SegmentationReplay(rgb, fusion, policy, device=device)
    rows, choices, trace = [], [], []
    for frame in (f for f in frames if f.split == 'test'):
        prediction = engine.predict(frame)
        reference = reference_mask(frame.mask_path, frame.mask_sha256)
        rows.append({'rgb_confusion': confusion_matrix(prediction.rgb_mask, reference).tolist(),
                     'fusion_confusion': confusion_matrix(prediction.final_mask, reference).tolist(),
                     'thermal_bytes': frame.thermal_bytes})
        choices.append(prediction.acquired)
        trace.append({'frame_id': frame.frame_id, 'acquired': prediction.acquired,
                      'predicted_gain': policy.expected_gain(prediction.view),
                      'transferred_bytes': prediction.transferred_bytes, 'seconds': prediction.seconds})
        if len(rows) % 10 == 0:
            print(f'PSTNet gated replay {len(rows)}/288', flush=True)
    report = {**summarize_choices(rows, choices), 'device': device, 'threads': threads, 'cost': cost,
              'timing_scope': 'local file reads + preprocessing + RGB + features + gate + selected fusion; excludes network transport',
              'mean_seconds': {k: float(np.mean([r['seconds'][k] for r in trace])) for k in trace[0]['seconds']},
              'trace': trace}
    _write(output, report)
    return report

