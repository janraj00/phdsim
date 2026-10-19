"""Offline full-information teacher outcomes; separate from online replay."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import torch

from phdsim.artifacts import write_json_atomic as _write
from phdsim.datasets.pst900.segmentation import load_frames, require_benchmark_split
from phdsim.perception.pstnet.checkpoint import load_models
from phdsim.perception.pstnet.features import FEATURE_NAMES

from phdsim.datasets.pst900.review import recording_family
from phdsim.decision.pstnet import FixedPstPolicy
from phdsim.evaluation.segmentation import confusion_matrix
from phdsim.perception.pstnet.input import reference_mask
from phdsim.runtime.segmentation import SegmentationReplay

def collect_cache(manifest, rgb_weights, fusion_weights, output, *, device='cpu', threads=6):
    """Offline ONLY: both outcomes are needed to supervise acquisition."""
    torch.set_num_threads(threads)
    rgb, fusion, provenance = load_models(rgb_weights, fusion_weights, device)
    frames = load_frames(manifest)
    require_benchmark_split(frames)
    metadata = {'schema': 'phdsim-pstnet-counterfactuals-v1', 'models': provenance,
                'manifest_sha256': sha256(Path(manifest).read_bytes()).hexdigest(),
                'feature_names': list(FEATURE_NAMES), 'preprocessing': 'pstnet-authors-360x640-inpaint-ns10-v1',
                'scope': 'offline full-information teacher cache; never exposed to deployed gate'}
    fingerprint = sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    output = Path(output)
    if output.exists():
        cached = json.loads(output.read_text(encoding='utf-8'))
        if cached['metadata'] != metadata:
            raise ValueError('Existing cache uses other models or data')
        return cached
    engine = SegmentationReplay(rgb, fusion, FixedPstPolicy(True), device=device)
    rows = []
    for i, frame in enumerate(frames, 1):
        # Resumable intermediates are bound to exact data + checkpoints + feature schema.
        path = output.parent / 'frames' / fingerprint / (sha256(frame.frame_id.encode()).hexdigest() + '.json')
        if path.exists():
            row = json.loads(path.read_text(encoding='utf-8'))
            if row['frame_id'] != frame.frame_id:
                raise ValueError('Counterfactual cache identity mismatch')
        else:
            prediction = engine.predict(frame)
            # Reference class indices are decoded for scoring after outputs exist.
            reference = reference_mask(frame.mask_path, frame.mask_sha256)
            row = {'frame_id': frame.frame_id, 'split': frame.split, 'group': recording_family(frame.sequence_id),
                   'features': list(prediction.view.features), 'thermal_bytes': frame.thermal_bytes,
                   'rgb_confusion': confusion_matrix(prediction.rgb_mask, reference).tolist(),
                   'fusion_confusion': confusion_matrix(prediction.final_mask, reference).tolist(),
                   'seconds': prediction.seconds}
            _write(path, row)
        rows.append(row)
        if i % 10 == 0 or i == len(frames):
            print(f'PSTNet counterfactuals {i}/{len(frames)}', flush=True)
    value = {'metadata': metadata, 'rows': rows}
    _write(output, value)
    return value


def load_cache(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if value['metadata']['schema'] != 'phdsim-pstnet-counterfactuals-v1' or value['metadata']['feature_names'] != list(FEATURE_NAMES):
        raise ValueError('Incompatible counterfactual cache')
    rows = value['rows']
    if Counter(r['split'] for r in rows) != {'train': 597, 'test': 288} or len({r['frame_id'] for r in rows}) != 885:
        raise ValueError('Incomplete or duplicate official benchmark cache')
    return value

