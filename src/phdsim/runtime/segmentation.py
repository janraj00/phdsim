"""RGB early exit, decision, lazy original thermal delivery, authors' fusion."""

from time import perf_counter
import numpy as np
import torch

from phdsim.decision.pstnet import RgbAcquisitionView
from .segmentation_result import SegmentationPrediction
from phdsim.perception.pstnet.features import rgb_features
from phdsim.perception.pstnet.input import rgb_tensor, thermal_tensor




class SegmentationReplay:
    def __init__(self, rgb_model, fusion_model, policy, *, device='cpu'):
        if getattr(fusion_model, 'rgb_net', rgb_model) is not rgb_model:
            raise ValueError('Early exit and fusion must share the exact RGB model')
        self.rgb_model, self.fusion_model, self.policy = rgb_model, fusion_model, policy
        self.device = device

    @torch.inference_mode()
    def predict(self, frame):
        self.rgb_model.eval()
        self.fusion_model.eval()
        synchronize = lambda: torch.cuda.synchronize(self.device) if str(self.device).startswith('cuda') else None
        synchronize()
        start = perf_counter()
        rgb = rgb_tensor(frame.rgb_path, frame.rgb_sha256).to(self.device)
        logits = self.rgb_model(rgb)
        rgb_mask = logits.argmax(1)[0].cpu().numpy().astype(np.uint8)
        view = RgbAcquisitionView(rgb_features(rgb, logits), frame.thermal_bytes)
        synchronize()
        rgb_end = perf_counter()
        acquired = bool(self.policy.acquire(view))
        decision_end = perf_counter()
        final_mask = rgb_mask
        if acquired:
            # The thermal file is opened only after the acquisition decision.
            thermal = thermal_tensor(frame.thermal_path, frame.thermal_sha256).to(self.device)
            fused = self.fusion_model(rgb, thermal, rgb_logits=logits)
            final_mask = fused.argmax(1)[0].cpu().numpy().astype(np.uint8)
        synchronize()
        end = perf_counter()
        return SegmentationPrediction(rgb_mask, final_mask, view, acquired,
                                      frame.thermal_bytes if acquired else 0,
                                      {'rgb_and_features': rgb_end - start,
                                       'decision': decision_end - rgb_end,
                                       'thermal_and_fusion': end - decision_end,
                                       'total': end - start})
