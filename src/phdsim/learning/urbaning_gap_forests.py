"""Region gap/local benefit models with a GT-free, NumPy-only prediction API."""
import numpy as np

from phdsim.learning.urbaning_regions import FEATURES

SCHEMA = 'phdsim-urbaning-gap-forest-v1'
PROFILES = {'geometry': tuple(range(4))+tuple(range(30,46)),
            'local': tuple(range(4,30)), 'combined': tuple(range(46))}
PARAMETERS = {'n_estimators':64, 'max_depth':8, 'min_samples_leaf':100,
              'max_features':1.0, 'bootstrap':False, 'random_state':42}


def evidence(features):
    x=np.asarray(features,dtype=np.float32)
    if x.ndim!=3 or x.shape[1:]!=(400,46) or not np.isfinite(x).all():
        raise ValueError('Expected finite frames x 400 spatial cells x 46 ordered public features')
    return x


def export_forest(estimator, profile, classification):
    if profile not in PROFILES: raise ValueError('Unknown feature profile')
    if classification and list(estimator.classes_)!=[0,1]: raise ValueError('Require binary gap labels')
    trees=[]
    for tree in estimator.estimators_:
        t=tree.tree_
        v=t.value[:,0]
        values=v[:,1]/v.sum(axis=1) if classification else v[:,0]
        trees.append({'left':t.children_left.tolist(),'right':t.children_right.tolist(),
                      'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),'value':values.tolist()})
    return {'schema':SCHEMA,'profile':profile,'features':list(FEATURES),'indices':list(PROFILES[profile]),
            'target':'any_car1_fn_in_cell' if classification else '-(delta_fp+delta_fn), sum over classes',
            'task':'gap' if classification else 'local_benefit','trees':trees}


def fit_forest(features, target, profile, *, classification, n_jobs=4, parameters=None):
    """Offline fit; caller supplies train-only rows. Predictor accepts no targets."""
    from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor
    x=np.asarray(features,dtype=np.float32);y=np.asarray(target)
    if profile not in PROFILES or x.ndim!=2 or x.shape[1]!=46 or y.shape!=(len(x),) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid fitting arrays')
    params=dict(PARAMETERS if parameters is None else parameters)
    cls=ExtraTreesClassifier if classification else ExtraTreesRegressor
    estimator=cls(**params,n_jobs=n_jobs).fit(x[:,PROFILES[profile]],y.astype(int) if classification else y)
    model=export_forest(estimator,profile,classification)
    # Verify serialization on a fixed train-only sample before using validation.
    selected=x[np.linspace(0,len(x)-1,min(1000,len(x)),dtype=int)]
    native=(estimator.predict_proba(selected[:,PROFILES[profile]])[:,1] if classification else
            estimator.predict(selected[:,PROFILES[profile]]))
    portable=predict_forest(model,selected)
    if not np.allclose(native,portable,rtol=0,atol=1e-12): raise ValueError('Portable forest parity failure')
    return model


def predict_forest(model, features):
    """Flat public evidence only. Finite inputs; no pickle or sklearn at runtime."""
    x=np.asarray(features,dtype=np.float32);profile=model.get('profile')
    if (model.get('schema')!=SCHEMA or profile not in PROFILES or model.get('features')!=list(FEATURES)
            or model.get('indices')!=list(PROFILES[profile]) or x.ndim!=2 or x.shape[1]!=46 or not np.isfinite(x).all()
            or model.get('task') not in ('gap','local_benefit') or not model.get('trees')):
        raise ValueError('Unsupported model, feature order or input shape')
    x=x[:,PROFILES[profile]];result=np.zeros(len(x),float)
    for tree in model['trees']:
        left,right,feature=(np.asarray(tree[n]) for n in ('left','right','feature'))
        threshold,value=(np.asarray(tree[n],float) for n in ('threshold','value'))
        n=len(left)
        if n<1 or any(a.shape!=(n,) for a in (right,feature,threshold,value)) or any(a.dtype.kind not in 'iu' for a in (left,right,feature)) or not np.isfinite(threshold).all() or not np.isfinite(value).all():
            raise ValueError('Malformed tree arrays')
        leaf=(left==-1)&(right==-1);branch=~leaf;nodes=np.arange(n)
        if (np.any(left[branch]<=nodes[branch]) or np.any(right[branch]<=nodes[branch])
                or np.any(left[branch]>=n) or np.any(right[branch]>=n)
                or np.any(feature[branch]<0) or np.any(feature[branch]>=x.shape[1])
                or not np.array_equal(np.sort(np.r_[left[branch],right[branch]]),np.arange(1,n))):
            raise ValueError('Malformed tree topology')
        where=np.zeros(len(x),dtype=np.int64)
        active=np.flatnonzero(~leaf[where])
        for _ in range(n):
            if not len(active):break
            node=where[active]
            where[active]=np.where(x[active,feature[node]]<=threshold[node],left[node],right[node])
            active=active[~leaf[where[active]]]
        else: raise ValueError('Tree traversal did not terminate')
        result+=value[where]
    result/=len(model['trees'])
    if model['task']=='gap' and ((result<0)|(result>1)).any(): raise ValueError('Invalid gap probability')
    return result


def predict(model, features, available):
    """Public model boundary: Car1 regional summaries + available peer metadata."""
    x=evidence(features);mask=np.asarray(available)
    if (mask.dtype!=bool or mask.shape!=(len(x),4) or not mask[:,0].all()
            or not np.array_equal(mask[:,3],mask[:,1]&mask[:,2])
            or not np.array_equal(x[:,:,30],np.broadcast_to(mask[:,1,None],x.shape[:2]))
            or not np.array_equal(x[:,:,38],np.broadcast_to(mask[:,2,None],x.shape[:2]))):
        raise ValueError('Availability/feature binding mismatch')
    if set(model)!= {'gap','benefit'} or set(model['benefit'])!= {'vehicle_peer','infrastructure','all'}:
        raise ValueError('Missing separately supervised heads')
    flat=x.reshape(-1,46)
    gap=predict_forest(model['gap'],flat).reshape(x.shape[:2])
    gains=np.stack([predict_forest(model['benefit'][n],flat).reshape(x.shape[:2]) for n in ('vehicle_peer','infrastructure','all')],axis=-1)
    gains=np.where(mask[:,None,1:],gains,np.nan)
    return gap,gains
