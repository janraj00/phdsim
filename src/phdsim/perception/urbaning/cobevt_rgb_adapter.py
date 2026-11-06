"""Feature residual for a frozen CoBEVT detector; not an RGB-trained model.

The caller must supply RGB features in the same metric BEV grid. This module
does not perform camera projection, and does not claim those features exist.
"""
import torch
from torch import nn


class ResidualBEVAdapter(nn.Module):
    def __init__(self, rgb_channels, bev_channels=256, hidden=32):
        super().__init__()
        self.rgb_channels, self.bev_channels = rgb_channels, bev_channels
        self.body = nn.Sequential(nn.Conv2d(rgb_channels, hidden, 1), nn.SiLU(),
                                  nn.Conv2d(hidden, hidden, 3, padding=1), nn.SiLU())
        self.delta = nn.Conv2d(hidden, bev_channels, 1)
        nn.init.zeros_(self.delta.weight)
        nn.init.zeros_(self.delta.bias)

    def forward(self, lidar_bev, rgb_bev):
        if (lidar_bev.ndim != 4 or rgb_bev.ndim != 4
                or lidar_bev.shape[1] != self.bev_channels
                or rgb_bev.shape[1] != self.rgb_channels
                or lidar_bev.shape[0] != rgb_bev.shape[0]
                or lidar_bev.shape[2:] != rgb_bev.shape[2:]):
            raise ValueError('RGB and LiDAR need the same batch and metric BEV grid')
        if not bool(torch.isfinite(rgb_bev).all()) or not bool(torch.isfinite(lidar_bev).all()):
            raise ValueError('Non-finite BEV input')
        return lidar_bev + self.delta(self.body(rgb_bev))


def capture_fused_bev(model, inputs):
    """Capture actual final BEV from an unchanged eval-only official forward."""
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError('The original detector must be frozen and in eval mode')
    captured = []
    handle = model.fusion_net.register_forward_hook(
        lambda module, arguments, output: captured.append(output.detach().clone()))
    try:
        with torch.no_grad():
            outputs = model(inputs)
    finally:
        handle.remove()
    if len(captured) != 1 or captured[0].ndim != 4:
        raise ValueError('Expected one final fused BEV tensor')
    feature = captured[0]
    with torch.no_grad():
        replay = {'psm': model.cls_head(feature), 'rm': model.reg_head(feature)}
    if set(outputs) != set(replay):
        raise ValueError('Official detector outputs changed')
    errors = {}
    for key in replay:
        torch.testing.assert_close(replay[key], outputs[key], rtol=0, atol=1e-6)
        errors[key] = float((replay[key] - outputs[key]).abs().max())
    return feature, outputs, errors


def metric_grid(shape, bounds):
    """Cell centers of a rectangular BEV, with rows=y and columns=x."""
    import numpy as np
    h, w = map(int, shape)
    x0, y0, _, x1, y1, _ = map(float, bounds)
    if h < 1 or w < 1 or not (x1 > x0 and y1 > y0):
        raise ValueError('Invalid BEV shape or bounds')
    x = x0 + (np.arange(w) + .5) * (x1 - x0) / w
    y = y0 + (np.arange(h) + .5) * (y1 - y0) / h
    yy, xx = np.meshgrid(y, x, indexing='ij')
    return np.stack([xx, yy], axis=-1)
