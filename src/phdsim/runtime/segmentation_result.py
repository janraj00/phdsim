"""Output of selective segmentation execution, including its decision and measured stages."""

from dataclasses import dataclass
import numpy as np
from phdsim.decision.pstnet.view import RgbAcquisitionView


@dataclass(frozen=True)
class SegmentationPrediction:
    rgb_mask: np.ndarray
    final_mask: np.ndarray
    view: RgbAcquisitionView
    acquired: bool
    transferred_bytes: int
    seconds: dict
