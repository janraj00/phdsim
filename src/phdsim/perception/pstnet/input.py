"""PSTNet authors' inference preprocessing; no ImageNet normalization."""

import numpy as np
from PIL import Image
import torch
from hashlib import sha256
from io import BytesIO
from pathlib import Path

SIZE = (640, 360)


def _verified_image(path, expected_sha256):
    if expected_sha256 is None:
        return Image.open(path)
    content = Path(path).read_bytes()
    if sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f'Image fingerprint mismatch at delivery: {path}')
    return Image.open(BytesIO(content))


def rgb_tensor(path, expected_sha256=None):
    with _verified_image(path, expected_sha256) as image:
        values = np.array(image.convert('RGB').resize(SIZE, Image.Resampling.BILINEAR))
    return torch.from_numpy(values.transpose(2, 0, 1).copy()).float().div(255).unsqueeze(0)


def thermal_tensor(path, expected_sha256=None):
    import cv2
    with _verified_image(path, expected_sha256) as image:
        values = np.array(image.convert('L').resize(SIZE, Image.Resampling.BILINEAR))
    values = cv2.inpaint(values, (values == 0).astype(np.uint8), 10, cv2.INPAINT_NS)
    return torch.from_numpy(values / 255.0).float().unsqueeze(0).unsqueeze(0)


def reference_mask(path, expected_sha256=None):
    with _verified_image(path, expected_sha256) as image:
        mask = np.array(image.resize(SIZE, Image.Resampling.NEAREST))
    if mask.shape != (360, 640) or not np.isin(mask, np.arange(5)).all():
        raise ValueError('Expected original PST900 class-index mask, classes 0..4')
    return mask.astype(np.uint8)
