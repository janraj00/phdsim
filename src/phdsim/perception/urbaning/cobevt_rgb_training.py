"""Cached single-Car1 adapter inputs; no GT is accepted by feature functions."""
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from phdsim.perception.urbaning.bev_cpu import camera_grid
from phdsim.perception.urbaning.cobevt_rgb_adapter import ResidualBEVAdapter

HEIGHTS = (.2, .8, 1.5, 2.5)


class SpatialEncoder:
    """Frozen 48-channel stride16 ImageNet features; no random compression."""
    def __init__(self, weights_dir, threads):
        from phdsim.experiments.urbaning_rgb_pilot import Encoder
        self.base = Encoder(weights_dir, threads)
        self.model = self.base.model.features[:9].eval().requires_grad_(False)
        self.identity = {**self.base.identity,
            'encoder':'MobileNetV3-small features[:9],48 channels,stride16,frozen',
            'input':'RGB384x640, ImageNet normalization, no augmentation',
            'compression':'none'}

    def __call__(self, images):
        import cv2
        batch=np.stack([cv2.resize(cv2.cvtColor(im,cv2.COLOR_BGR2RGB),(640,384)).transpose(2,0,1)
                        for im in images]).astype(np.float32)/255
        batch=(batch-np.array([.485,.456,.406],np.float32)[None,:,None,None])
        batch/=np.array([.229,.224,.225],np.float32)[None,:,None,None]
        with torch.no_grad():
            maps=self.model(torch.from_numpy(batch)).detach()
        if maps.shape != (6,48,24,40): raise ValueError('Unexpected pinned RGB encoder shape')
        return maps


def lift_rectangular(maps, cameras, image_sizes, xy, ground_z):
    """Four-height calibrated voxel pull on the ORIGINAL metric detector grid.

    Fixed sparse lifting has depth/occlusion ambiguity. It is not depth
    estimation, BEVFusion or the official camera-CoBEVT encoder.
    """
    if len(maps)!=len(cameras) or len(cameras)!=len(image_sizes) or len(maps)==0:
        raise ValueError('Camera/map count differs')
    h,w=xy.shape[:2]; planes=len(HEIGHTS); channels=maps.shape[1]
    points=np.stack([np.concatenate([xy,np.full((h,w,1),ground_z+z)],axis=-1) for z in HEIGHTS])
    total=torch.zeros((channels,planes,h,w)); count=torch.zeros((planes,h,w))
    for feature,(extrinsic,intrinsic),(width,height) in zip(maps,cameras,image_sizes):
        grid,valid=camera_grid(points,extrinsic,intrinsic,width,height)
        value=F.grid_sample(feature[None],torch.from_numpy(grid.reshape(1,planes*h,w,2)),
                            align_corners=False,padding_mode='zeros').reshape(channels,planes,h,w)
        mask=torch.from_numpy(valid)
        total+=value*mask[None];count+=mask
    total/=count.clamp(min=1)[None]
    result=torch.cat([total.permute(1,0,2,3).reshape(channels*planes,h,w),count/len(cameras)])
    if not bool(result.isfinite().all()):raise ValueError('Non-finite RGB BEV')
    return result


def channel_normalizer(arrays, masks=None):
    channels=arrays[0].shape[0]
    sums=torch.zeros(channels,dtype=torch.float64); squares=sums.clone();counts=sums.clone()
    for i,array in enumerate(arrays):
        x=array.double()
        mask=torch.ones_like(x) if masks is None else masks[i].expand_as(x).double()
        sums+=(x*mask).sum((1,2));squares+=(x.square()*mask).sum((1,2));counts+=mask.sum((1,2))
    mean=sums/counts.clamp(min=1)
    std=(squares/counts.clamp(min=1)-mean.square()).clamp(min=1e-4).sqrt()
    return {'mean':mean.float().tolist(),'std':std.float().tolist()}


def rgb_mask(rgb):
    channels=(rgb.shape[0]-len(HEIGHTS))//len(HEIGHTS)
    if channels<1 or channels*len(HEIGHTS)+len(HEIGHTS)!=rgb.shape[0]:
        raise ValueError('Unexpected height-major RGB channels')
    return (rgb[-len(HEIGHTS):]>0).repeat_interleave(channels,dim=0)


def fit_normalizers(features):
    rgbs=[f['rgb'] for f in features]
    return {'lidar':channel_normalizer([f['bev'][0] for f in features]),
            'rgb':channel_normalizer([r[:-len(HEIGHTS)] for r in rgbs],[rgb_mask(r) for r in rgbs])}


def normalize(x,stats):
    mean=torch.tensor(stats['mean'],dtype=x.dtype)[:,None,None]
    std=torch.tensor(stats['std'],dtype=x.dtype)[:,None,None]
    return (x-mean)/std


def context(bev,rgb,mode,stats,xy):
    """Control strictly zeros ALL RGB values/masks; all variants retain LiDAR."""
    if mode not in ('lidar_adapter','lidar_rgb_adapter'):raise ValueError('Unknown adapter mode')
    lidar=normalize(bev[0],stats['lidar'])
    visual=torch.zeros_like(rgb)
    if mode=='lidar_rgb_adapter':
        visual[:-len(HEIGHTS)]=normalize(rgb[:-len(HEIGHTS)],stats['rgb'])*rgb_mask(rgb)
        visual[-len(HEIGHTS):]=rgb[-len(HEIGHTS):]
    coords=torch.from_numpy(np.moveaxis(xy,-1,0).astype(np.float32)).clone()
    coords[0]/=max(float(np.abs(xy[...,0]).max()),1.)
    coords[1]/=max(float(np.abs(xy[...,1]).max()),1.)
    return torch.cat([lidar,visual,coords])[None]


class BoundedAdapter(nn.Module):
    """Zero-start residual, limited to one train standard deviation per channel."""
    def __init__(self,context_channels,bev_channels,std,hidden=16):
        super().__init__()
        self.adapter=ResidualBEVAdapter(context_channels,bev_channels,hidden)
        self.register_buffer('scale',torch.tensor(std,dtype=torch.float32)[None,:,None,None])

    def forward(self,bev,inputs):
        raw=self.adapter(torch.zeros_like(bev),inputs)
        delta=torch.tanh(raw)*self.scale
        return bev+delta,raw


def original_heads(cls_head,reg_head,bev):
    return {'psm':cls_head(bev),'rm':reg_head(bev)}


def shuffled_indices(records):
    """Fixed GT-free cyclic derangement within each original training recording."""
    groups={}
    for i,r in enumerate(records):groups.setdefault(r['sequence'],[]).append(i)
    result=list(range(len(records)))
    for ids in groups.values():
        if len(ids)<2:raise ValueError('Need two frames per recording for shuffle diagnostic')
        for a,b in zip(ids,ids[1:]+ids[:1]):result[a]=b
    return result
