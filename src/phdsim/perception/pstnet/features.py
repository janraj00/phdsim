"""Acquisition features available from RGB alone, before any peer transfer."""

import numpy as np
import torch

FEATURE_NAMES = ('entropy_mean', 'entropy_std', 'entropy_p95', 'foreground_entropy',
                 'top2_margin_mean', 'low_confidence_fraction',
                 *(f'predicted_fraction_{i}' for i in range(5)),
                 *(f'mean_probability_{i}' for i in range(5)),
                 'rgb_brightness', 'rgb_contrast', 'rgb_dark_fraction')


def rgb_features(rgb, logits):
    if rgb.shape != (1, 3, 360, 640) or logits.shape != (1, 5, 360, 640):
        raise ValueError('PSTNet acquisition expects one 360x640 RGB frame and five logits')
    probabilities = logits.detach().softmax(1)[0]
    if not torch.isfinite(probabilities).all():
        raise ValueError('Non-finite RGB probabilities')
    p = probabilities.cpu().numpy()
    entropy = -(p * np.log(np.clip(p, 1e-30, 1))).sum(0) / np.log(5)
    prediction = p.argmax(0)
    foreground = prediction != 0
    top = np.sort(p, axis=0)[-2:]
    pixels = rgb.detach().cpu().numpy()
    values = (float(entropy.mean()), float(entropy.std()), float(np.quantile(entropy, .95)),
              float(entropy[foreground].mean()) if foreground.any() else 0.,
              float((top[1] - top[0]).mean()), float((top[1] < .5).mean()),
              *(float((prediction == i).mean()) for i in range(5)),
              *(float(p[i].mean()) for i in range(5)),
              float(pixels.mean()), float(pixels.std()), float((pixels < .1).mean()))
    return tuple(values)
