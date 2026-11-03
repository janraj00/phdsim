"""Whole-frame partner choice from signed regional predictions, without GT."""
import math

import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER, available_subsets

ERROR_COSTS = (0., 1., 2., 4., 8., 16., 32., 64.)


def choose_regional_subset(source_ids, regional_gains, error_cost):
    """Sum all cells/classes; charge each requested peer once per frame.

    error_cost is in predicted FP+FN counts, NOT the F1 utility cost .05.
    Both is its directly predicted head, never the sum of two single heads.
    A tie prefers fewer peers, then canonical action order. No ROI mixing.
    """
    gains = np.asarray(regional_gains, float)
    if gains.shape != (401, 3, 4) or not np.isfinite(gains).all():
        raise ValueError('Expected finite 401-cell x 3-action x 4-class predictions')
    if not math.isfinite(error_cost) or error_cost < 0:
        raise ValueError('Nonnegative finite error-count penalty required')
    totals = np.r_[0., gains.sum(axis=(0, 2))]
    options = available_subsets(source_ids)
    return min(options, key=lambda a: (-(totals[ACTION_ORDER.index(a)] - error_cost*(len(options[a])-1)),
                                       len(options[a])-1, ACTION_ORDER.index(a)))
