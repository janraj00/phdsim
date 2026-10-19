"""Whole-frame pixels, never a mask or a crop selected using reference labels."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
import torch

from .baseline import ImagePayload


def image_tensor(payload: ImagePayload, modality: str, height: int, width: int):
    content = Path(payload.path).read_bytes()
    if sha256(content).hexdigest() != payload.sha256:
        raise ValueError("CNN image fingerprint mismatch")
    with Image.open(BytesIO(content)) as source:
        if source.format != "PNG" or source.mode != ("RGB" if modality == "rgb" else "L"):
            raise ValueError("CNN requires an original RGB or thermal PNG")
        # Thermal is repeated as three grayscale channels; no RGB data is added.
        image = source.convert("RGB")
        image = ImageOps.pad(image, (width, height), method=Image.Resampling.BILINEAR,
                             color=(124, 116, 104) if modality == "rgb" else (128, 128, 128))
        pixels = np.array(image, dtype=np.float32, copy=True) / 255
    tensor = torch.from_numpy(pixels).permute(2, 0, 1).contiguous()
    mean = torch.tensor((0.485, 0.456, 0.406))[:, None, None]
    std = torch.tensor((0.229, 0.224, 0.225))[:, None, None]
    return (tensor - mean) / std


def local_quality_features(normalized):
    """Eight fixed summaries of the delivered image only, without fitted parameters."""
    mean = normalized.new_tensor((0.485, 0.456, 0.406))[:, None, None]
    std = normalized.new_tensor((0.229, 0.224, 0.225))[:, None, None]
    gray = (normalized * std + mean).mean(0).clamp(0, 1)
    values = (gray.mean(), gray.std(unbiased=False), (gray < 0.1).float().mean(),
              (gray > 0.9).float().mean(), (gray[:, 1:] - gray[:, :-1]).abs().mean(),
              (gray[1:] - gray[:-1]).abs().mean(), gray[:gray.shape[0] // 2].mean(),
              gray[gray.shape[0] // 2:].mean())
    return tuple(float(value) for value in values)
