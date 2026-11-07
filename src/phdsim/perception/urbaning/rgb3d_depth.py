"""Fine-tune the existing linear depth readout; no new learned layer or GT input.

Frozen official RGB features/2D boxes/classes/scores/dimensions/pose remain
unchanged. Ridge around pretrained weights is solved on TRAIN positives only,
then folded into the original bbox_3D_center_depth weight and bias tensors.
"""
import numpy as np

from phdsim.perception.urbaning.rgb3d_late import CubeDetector

FEATURE_PENALTY = 10.
BIAS_PENALTY = 1.
MIN_POSITIVES = 32


class DepthFeatureDetector(CubeDetector):
    def __init__(self, model_dir, threads=8):
        super().__init__(model_dir,threads,variant='outdoor')
        roi=self.model.roi_heads
        if roi.z_type!='direct' or roi.cluster_bins!=1:
            raise ValueError('This readout protocol requires official direct-depth / single-bin decoding')
        self.layer=roi.cube_head.bbox_3D_center_depth
        if self.layer.out_features!=len(self.categories) or self.layer.in_features!=1024:
            raise ValueError('Unexpected native depth layer shape')

    def state(self):
        return {k:v.detach().cpu().numpy().copy() for k,v in self.layer.state_dict().items()}

    def capture(self,image,intrinsic):
        captured=[]
        def hook(module,args,result):
            captured.append((args[0].detach().cpu().clone().numpy(),result.detach().cpu().clone().numpy()))
        handle=self.layer.register_forward_hook(hook)
        try:out=self.predict(image,intrinsic)
        finally:handle.remove()
        n=len(out['scores'])
        if n==0:
            if captured and len(captured[0][0]):raise ValueError('Nonempty native head but empty postprocess')
            features=np.empty((0,self.layer.in_features),np.float32)
        else:
            if len(captured)!=1 or len(captured[0][0])!=n:
                raise ValueError('Depth features do not bind one-to-one to final detections')
            features,logits=captured[0]
        roi=self.model.roi_heads
        transform=self.resize.get_transform(image)
        resized_height=transform.new_h
        scale=(float(intrinsic[1,1])*resized_height/(roi.virtual_focal*image.shape[0])
               if roi.virtual_depth else 1.)
        if not np.isfinite(scale) or scale<=0:raise ValueError('Invalid virtual-depth scaling')
        if n:
            decoded=logits[np.arange(n),out['classes']]*scale
            np.testing.assert_allclose(decoded,out['centers'][:,2],rtol=2e-6,atol=2e-5)
            rays=np.c_[out['center_pixels'],np.ones(n)]@np.linalg.inv(intrinsic).T
            np.testing.assert_allclose(rays*out['centers'][:,2,None],out['centers'],rtol=2e-6,atol=1e-4)
        return {**out,'depth_features':features,'depth_scale':np.array(scale)}


def apply_depth(cache,original,trained,intrinsic):
    """Only RGB features/classes/K enter this inference-time operation."""
    import torch
    result={k:np.asarray(v).copy() for k,v in cache.items()}
    n=len(cache['classes'])
    if n==0:return result
    dw=np.asarray(trained['weight']-original['weight'],np.float32)
    db=np.asarray(trained['bias']-original['bias'],np.float32)
    with torch.inference_mode():
        delta=torch.nn.functional.linear(torch.from_numpy(np.asarray(cache['depth_features'],np.float32)),
                                         torch.from_numpy(dw),torch.from_numpy(db)).numpy()
    dz=delta[np.arange(n),cache['classes']]*float(cache['depth_scale'])
    rays=np.c_[cache['center_pixels'],np.ones(n)]@np.linalg.inv(intrinsic).T
    result['centers']=cache['centers']+rays*dz[:,None]
    # Retain the raw original optical corners as source evidence; regenerate
    # diagnostic corrected cuboids explicitly elsewhere, never relabel them.
    if not np.isfinite(result['centers']).all():raise ValueError('Nonfinite adapted centers')
    return result


def fit_depth(original,features,classes,targets,scales,train_keys):
    """Deterministic weighted ridge, fixed penalties; no validation arguments.

    Matching and labels are supplied by offline TRAIN supervision. Target is
    metric optical depth; only the existing category rows with >=32 positives
    change. Optimize relative depth error, with mean-normalized weights, and a
    penalty on deviation from the pretrained readout in TRAIN-standardized RGB
    feature coordinates. The resulting tensors load into the original layer.
    """
    x=np.asarray(features,np.float64);c=np.asarray(classes,np.int64)
    y=np.asarray(targets,np.float64);scale=np.asarray(scales,np.float64)
    w0=np.asarray(original['weight'],np.float32);b0=np.asarray(original['bias'],np.float32)
    if (x.ndim!=2 or x.shape[1]!=w0.shape[1] or c.shape!=(len(x),)
            or y.shape!=c.shape or scale.shape!=c.shape or len(train_keys)!=len(x)
            or not all(np.isfinite(a).all() for a in (x,y,scale))
            or np.any(y<=0) or np.any(scale<=0) or np.any(c<0) or np.any(c>=len(w0))
            or any(not k.startswith(('20241126_0001_crossing2_00:',
                                     '20241126_0017_crossing1_00:')) for k in train_keys)):
        raise ValueError('Invalid TRAIN-only depth examples')
    trained={'weight':w0.copy(),'bias':b0.copy()};support=[]
    for cls in range(len(w0)):
        keep=c==cls;count=int(keep.sum())
        row={'class_id':cls,'positives':count,'adapted':count>=MIN_POSITIVES}
        if count<MIN_POSITIVES:support.append(row);continue
        a=x[keep];target=y[keep]/scale[keep]
        mean=a.mean(0);std=np.maximum(a.std(0),1e-4)
        design=np.c_[np.ones(count),(a-mean)/std]
        # Clipped inverse-square target-depth weights, mean-normalized within
        # category. No validation selection occurs.
        weight=1/np.maximum(target,1.)**2;weight/=weight.mean()
        residual=target-(a@w0[cls]+b0[cls])
        gram=(design.T*weight)@design/count
        penalty=np.r_[BIAS_PENALTY,np.full(a.shape[1],FEATURE_PENALTY)]
        gram.flat[::len(gram)+1]+=penalty
        delta=np.linalg.solve(gram,design.T@(weight*residual)/count)
        dw=delta[1:]/std;db=delta[0]-mean@dw
        trained['weight'][cls]=(w0[cls]+dw).astype(np.float32)
        trained['bias'][cls]=np.float32(b0[cls]+db)
        after=a@trained['weight'][cls]+trained['bias'][cls]
        row.update({'train_relative_depth_mse_before':float(np.mean(((a@w0[cls]+b0[cls]-target)/target)**2)),
                    'train_relative_depth_mse_after':float(np.mean(((after-target)/target)**2))})
        support.append(row)
    if not all(np.isfinite(v).all() for v in trained.values()):raise ValueError('Nonfinite trained readout')
    return trained,support


def verify_native_delta(detector,image,intrinsic,trained=None):
    """Prove cached replay equals an actual modified ORIGINAL native layer.

    With no supplied state, temporarily add .01 to the existing depth bias.
    Otherwise load the frozen fitted state. Run the original detector, compare
    decoded outputs, then restore all source head values. No GT enters this gate.
    """
    import torch
    original=detector.state();cache=detector.capture(image,intrinsic)
    if len(cache['scores'])==0:return False
    changed={k:v.copy() for k,v in (original if trained is None else trained).items()}
    if trained is None:changed['bias']+=np.float32(.01)
    replay=apply_depth(cache,original,changed,intrinsic)
    try:
        detector.layer.load_state_dict({k:torch.from_numpy(v) for k,v in changed.items()},strict=True)
        native=detector.predict(image,intrinsic)
    finally:
        detector.layer.load_state_dict({k:torch.from_numpy(v) for k,v in original.items()},strict=True)
    np.testing.assert_array_equal(native['classes'],replay['classes'])
    for k in ['scores','boxes2d','dimensions','rotations','center_pixels']:
        np.testing.assert_allclose(native[k],replay[k],rtol=2e-6,atol=2e-5)
    np.testing.assert_allclose(native['centers'],replay['centers'],rtol=2e-6,atol=1e-4)
    for k in original:np.testing.assert_array_equal(original[k],detector.state()[k])
    return True
