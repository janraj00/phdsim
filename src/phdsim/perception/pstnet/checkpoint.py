"""Strict loading of upstream state dictionaries on CPU or CUDA."""

from hashlib import sha256
from pathlib import Path
import torch

from .rgb import PstRgb
from phdsim.fusion.pstnet import PstFusion


def load_state(path, *, fusion=False):
    # The released inference script expects a state_dict, not a pickled module.
    value = torch.load(path, map_location='cpu', weights_only=True)
    if not isinstance(value, dict) or not value or not all(isinstance(v, torch.Tensor) for v in value.values()):
        raise ValueError('Expected authors model_best.pth tensor state_dict')
    normalized = {}
    for name, tensor in value.items():
        key = name.removeprefix('module.')
        if fusion and key.startswith('rgb_net.module.'):
            key = 'rgb_net.' + key[len('rgb_net.module.'):]
        if key in normalized:
            raise ValueError(f'Colliding checkpoint key: {key}')
        normalized[key] = tensor
    return normalized


def load_models(rgb_weights, fusion_weights, device='cpu'):
    for path in (rgb_weights, fusion_weights):
        if not Path(path).is_file():
            raise FileNotFoundError(f'Official PSTNet checkpoint required: {path}. See docs/PSTNET_REPRODUCTION.md')
    rgb = PstRgb(3, 5)
    rgb_state = load_state(rgb_weights)
    rgb.load_state_dict(rgb_state, strict=True)
    fusion_state = load_state(fusion_weights, fusion=True)
    embedded = {k[len('rgb_net.'):]: v for k, v in fusion_state.items() if k.startswith('rgb_net.')}
    if embedded.keys() != rgb_state.keys() or any(not torch.equal(v, rgb_state[k]) for k, v in embedded.items()):
        raise ValueError('Fusion embeds different RGB weights; cannot claim the same early-exit baseline')
    fusion = PstFusion(rgb)
    fusion.load_state_dict(fusion_state, strict=True)
    fusion.eval().to(device)
    for p in fusion.parameters():
        p.requires_grad_(False)
    provenance = {'rgb_sha256': sha256(Path(rgb_weights).read_bytes()).hexdigest(),
                  'fusion_sha256': sha256(Path(fusion_weights).read_bytes()).hexdigest(),
                  'architecture_commit': '47bbf0133b29e05c7a087b71fb27e8cd8c092ec8',
                  'rgb_embedded_weights_equal': True}
    return rgb, fusion, provenance
