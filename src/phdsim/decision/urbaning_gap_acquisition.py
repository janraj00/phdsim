"""One whole-frame source decision from frozen spatial predictions only."""
import math
import numpy as np

from phdsim.decision.urbaning import ACTION_ORDER,available_subsets

AGGREGATIONS=('gap_top10','all_cells')
ERROR_COSTS=(0.,.25,.5,1.,2.,4.,8.,16.,32.,64.)


def choose(source_ids,gap_scores,local_benefit,error_cost,aggregation='gap_top10'):
    """Sum one subset's predicted local benefits, then charge per actual peer.

    In gap_top10 the same ten cells, selected by predicted gap score without
    labels, are used for all subset heads. Only ONE whole-frame subset wins.
    This never mixes predictions from different source subsets across cells.
    """
    gap,gains=np.asarray(gap_scores,float),np.asarray(local_benefit,float)
    options=available_subsets(source_ids)
    if (gap.shape!=(400,) or gains.shape!=(400,3) or not np.isfinite(gap).all()
            or aggregation not in AGGREGATIONS or not math.isfinite(error_cost) or error_cost<0):
        raise ValueError('Invalid public scores, aggregation or error-count penalty')
    cells=(np.lexsort((np.arange(400),-gap))[:10] if aggregation=='gap_top10' else np.arange(400))
    values={'ego':0.}
    for j,action in enumerate(ACTION_ORDER[1:]):
        if action in options:
            if not np.isfinite(gains[:,j]).all():raise ValueError('Nonfinite feasible subset head')
            values[action]=float(gains[cells,j].sum())
    return min(options,key=lambda a:(-(values[a]-error_cost*(len(options[a])-1)),
                                     len(options[a])-1,ACTION_ORDER.index(a)))
