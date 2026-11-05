"""Small CPU BEV detector; calibrated voxel sampling, no proposal inputs.

A research prototype, not a reproduction of Simple-BEV or BEVFusion. ImageNet
features are frozen. Separate heads can use RGB, Car1 point grids, or both.
"""
import math
import hashlib
import io
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from phdsim.evaluation.urbaning_cached import _radius_mask, _polygon, polygon_iou

MODES = ('rgb', 'lidar', 'rgb_lidar')
GRID = {'size': 200, 'extent': 110., 'height_offsets': [.2, .8, 1.5, 2.5],
        'rgb_channels': 16, 'image_hw': [384, 640]}


def read_pcd(path, expected_sha):
    """Read hashed uncompressed PCD written by the pinned Open3D converter."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Car1 point payload changed')
    header = {}; stream = io.BytesIO(raw)
    while True:
        line = stream.readline()
        if not line: raise ValueError('Incomplete PCD header')
        text = line.decode('ascii').strip()
        if not text or text.startswith('#'): continue
        parts = text.split(); header[parts[0].upper()] = parts[1:]
        if parts[0].upper() == 'DATA': break
    offset = stream.tell()
    names = header['FIELDS']; sizes = list(map(int,header['SIZE'])); types = header['TYPE']
    counts = list(map(int,header.get('COUNT',['1']*len(names))))
    if len({len(names),len(sizes),len(types),len(counts)}) != 1 or len(set(names)) != len(names):
        raise ValueError('Invalid PCD fields')
    count = int(header['POINTS'][0]); encoding = header['DATA'][0]
    if count < 0 or count > 10_000_000 or not {'x','y','z'} <= set(names):
        raise ValueError('Invalid PCD point count or coordinates')
    if encoding == 'binary':
        fields = []
        for name,size,kind,n in zip(names,sizes,types,counts):
            if kind not in ('F','I','U') or size not in (1,2,4,8) or n < 1:
                raise ValueError('Unsupported PCD field')
            dtype = np.dtype('<'+{'F':'f','I':'i','U':'u'}[kind]+str(size))
            fields.append((name,dtype) if n == 1 else (name,dtype,(n,)))
        dtype = np.dtype(fields)
        if len(raw)-offset != count*dtype.itemsize: raise ValueError('PCD byte size differs')
        data = np.frombuffer(raw, dtype=dtype, count=count, offset=offset)
        points = np.column_stack([data[n] for n in ('x','y','z')]).astype(np.float32)
    elif encoding == 'ascii':
        data = np.loadtxt(io.BytesIO(raw[offset:]),ndmin=2)
        if data.shape != (count,sum(counts)): raise ValueError('PCD ASCII shape differs')
        starts = np.cumsum([0]+counts[:-1])
        points = data[:,[starts[names.index(n)] for n in ('x','y','z')]].astype(np.float32)
    else:
        raise ValueError('Expected uncompressed PCD from pinned converter; no silent conversion')
    if points.shape != (count,3) or not np.isfinite(points).all():
        raise ValueError('Invalid PCD xyz data')
    return points


def geometry(box):
    center = box.mean(axis=0)
    edge = box[1]-box[0]
    a, b = np.linalg.norm(edge[:2]), np.linalg.norm((box[3]-box[0])[:2])
    h = box[:, 2].max()-box[:, 2].min()
    yaw = np.arctan2(edge[1], edge[0])
    return center, float(a), float(b), float(h), float(yaw)


def fit_priors(records):
    """Offline TRAIN labels only; no predictions are used for target selection."""
    ground, values, counts = [], {c: [] for c in range(1, 5)}, {c: 0 for c in range(1, 5)}
    for record in records:
        for box, label in zip(record['gt_boxes'][_radius_mask(record['gt_boxes'])],
                              record['gt_labels'][_radius_mask(record['gt_boxes'])]):
            center, a, b, h, yaw = geometry(box)
            if min(a, b, h) <= 0:
                raise ValueError('Degenerate GT geometry')
            c = int(label); counts[c] += 1
            values[c].append([0, 0, np.log(a), np.log(b), center[2], np.log(h),
                              np.cos(2*yaw), np.sin(2*yaw)])
            if np.linalg.norm(center[:2]) < 30:
                ground.append(float(box[:, 2].min()))
    if not ground or any(not v for v in values.values()):
        raise ValueError('Training needs a near-ground prior and all four classes')
    priors = []
    for c in range(1, 5):
        x = np.asarray(values[c]); p = np.median(x, axis=0)
        direction = x[:, 6:8].mean(axis=0)
        p[6:8] = direction/max(np.linalg.norm(direction), 1e-6)
        priors.append(p.tolist())
    return {'ground_z': float(np.median(ground)), 'regression': priors,
            'training_gt_instances': {str(c): n for c, n in counts.items()},
            'semantics': 'all radius-filtered training GT, not correctly detected LiDAR proposals'}


def voxel_points(grid, ground_z):
    size, extent = grid['size'], grid['extent']
    xy = (np.arange(size)+.5)*(2*extent/size)-extent
    y, x = np.meshgrid(xy, xy, indexing='ij')
    return np.stack([np.stack([x, y, np.full_like(x, ground_z+z)], axis=-1)
                     for z in grid['height_offsets']]).astype(np.float32)


def camera_grid(points, optical_from_ego, intrinsic, width, height):
    """Normalized pixel grid for grid_sample(align_corners=False)."""
    shape = points.shape[:-1]
    p = points.reshape(-1, 3).astype(np.float64)
    camera = p@optical_from_ego[:3, :3].T+optical_from_ego[:3, 3]
    projected = camera@intrinsic.T
    depth = camera[:, 2]
    uv = projected[:, :2]/np.maximum(depth[:, None], .01)
    valid = ((depth > .1) & (uv[:, 0] >= 0) & (uv[:, 0] < width)
             & (uv[:, 1] >= 0) & (uv[:, 1] < height))
    normalized = 2*(uv+.5)/np.array([width, height])-1
    normalized[~valid] = 2
    return normalized.reshape(*shape, 2).astype(np.float32), valid.reshape(shape)


def lift_features(maps, cameras, image_sizes, points):
    """Bilinear voxel pull; only image features and calibrated geometry enter."""
    heights, size, _, _ = points.shape
    channels = maps.shape[1]
    total = torch.zeros((channels, heights, size, size))
    count = torch.zeros((heights, size, size))
    for feature, (e, k), (width, height) in zip(maps, cameras, image_sizes):
        grid, valid = camera_grid(points, e, k, width, height)
        g = torch.from_numpy(grid.reshape(1, heights*size, size, 2))
        sampled = F.grid_sample(feature[None], g, align_corners=False,
                                padding_mode='zeros').reshape(channels, heights, size, size)
        mask = torch.from_numpy(valid)
        total += sampled*mask[None]
        count += mask
    total /= count.clamp(min=1)[None]
    # Height-major channels, followed by geometric view-count channels.
    image = total.permute(1, 0, 2, 3).reshape(heights*channels, size, size)
    return torch.cat([image, count/len(cameras)]).numpy().astype(np.float16)


def point_grid(points, grid, ground_z):
    size, extent = grid['size'], grid['extent']
    indices = np.floor((points[:, :2]+extent)/(2*extent/size)).astype(int)
    z = points[:, 2]-ground_z
    keep = ((indices >= 0).all(axis=1) & (indices < size).all(axis=1) & (z >= -1) & (z <= 6))
    ij, z = indices[keep], z[keep]
    flat = ij[:, 1]*size+ij[:, 0]
    count = np.bincount(flat, minlength=size*size)
    sums = np.bincount(flat, weights=z, minlength=size*size)
    maximum = np.full(size*size, -np.inf)
    np.maximum.at(maximum, flat, z)
    maximum[count == 0] = 0
    return np.stack([np.minimum(np.log1p(count)/np.log(65), 1),
                     np.clip(maximum/4, -1, 1),
                     np.clip(sums/np.maximum(count, 1)/4, -1, 1)]).reshape(3, size, size).astype(np.float16)


def input_tensor(rgb, lidar, mode, grid):
    """Explicit modality gate: RGB predictions are independent of LiDAR values."""
    if mode not in MODES:
        raise ValueError('Unknown mode')
    a = torch.from_numpy(rgb.astype(np.float32)) if mode != 'lidar' else torch.zeros(rgb.shape)
    b = torch.from_numpy(lidar.astype(np.float32)) if mode != 'rgb' else torch.zeros(lidar.shape)
    size = grid['size']; xy = torch.linspace(-1+1/size, 1-1/size, size)
    y, x = torch.meshgrid(xy, xy, indexing='ij')
    return torch.cat([a, b, torch.stack([x, y])])[None]


class Detector(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.body = nn.Sequential(nn.Conv2d(channels, 24, 1), nn.GroupNorm(4, 24), nn.SiLU(),
                                  nn.Conv2d(24, 24, 3, padding=1), nn.GroupNorm(4, 24), nn.SiLU(),
                                  nn.Conv2d(24, 24, 3, padding=1), nn.GroupNorm(4, 24), nn.SiLU())
        self.heat = nn.Conv2d(24, 4, 1)
        self.reg = nn.Conv2d(24, 32, 1)
        nn.init.constant_(self.heat.bias, math.log(.05/.95))
        nn.init.zeros_(self.reg.weight); nn.init.zeros_(self.reg.bias)

    def forward(self, x):
        x = self.body(x)
        return self.heat(x), self.reg(x).reshape(len(x), 4, 8, x.shape[2], x.shape[3])


def targets(boxes, labels, priors, grid):
    size, extent = grid['size'], grid['extent']; cell = 2*extent/size
    heat = np.zeros((4, size, size), dtype=np.float32)
    locations, regression, occupied = [], [], set()
    stats = {'radius_gt': 0, 'outside_center_grid': 0, 'same_class_cell_collisions': 0}
    keep = _radius_mask(boxes)
    for box, label in zip(boxes[keep], labels[keep]):
        stats['radius_gt'] += 1
        c = int(label)-1; center, a, b, h, yaw = geometry(box)
        floating = (center[:2]+extent)/cell
        x, y = np.floor(floating).astype(int)
        if not (0 <= x < size and 0 <= y < size):
            stats['outside_center_grid'] += 1; continue
        if (c, y, x) in occupied:
            stats['same_class_cell_collisions'] += 1; continue
        occupied.add((c, y, x))
        sigma = max(.7, min(2., min(a, b)/cell/6))
        radius = int(np.ceil(3*sigma))
        lo_x, hi_x = max(0, x-radius), min(size, x+radius+1)
        lo_y, hi_y = max(0, y-radius), min(size, y+radius+1)
        yy, xx = np.meshgrid(np.arange(lo_y, hi_y)-y, np.arange(lo_x, hi_x)-x, indexing='ij')
        gaussian = np.exp(-(xx*xx+yy*yy)/(2*sigma*sigma))
        heat[c, lo_y:hi_y, lo_x:hi_x] = np.maximum(heat[c, lo_y:hi_y, lo_x:hi_x], gaussian)
        p = np.asarray(priors['regression'][c])
        raw = np.array([floating[0]-x-.5, floating[1]-y-.5, np.log(a), np.log(b),
                        center[2], np.log(h), np.cos(2*yaw), np.sin(2*yaw)])
        residual = raw-p; residual[4] /= 2
        locations.append((c, y, x)); regression.append(residual)
    return {'heat': torch.from_numpy(heat)[None],
            'locations': np.asarray(locations, dtype=int).reshape(-1, 3),
            'regression': torch.tensor(np.asarray(regression).reshape(-1, 8), dtype=torch.float32),
            'statistics': stats}


def loss(outputs, target):
    logits, reg = outputs; truth = target['heat']
    probability = logits.sigmoid().clamp(1e-4, 1-1e-4)
    positive = truth == 1; negative = truth < 1
    a = -torch.log(probability)*(1-probability).square()*positive
    b = -torch.log(1-probability)*probability.square()*(1-truth).pow(4)*negative
    classification = (a.sum()+b.sum())/positive.sum().clamp(min=1)
    loc = target['locations']
    if len(loc):
        c, y, x = loc.T
        values = reg[0, c, :, y, x]
        regression = F.smooth_l1_loss(values, target['regression'])
    else:
        regression = reg.sum()*0
    return classification+regression, {'heat': float(classification.detach()), 'box': float(regression.detach())}


def corners(center, a, b, h, yaw):
    local = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                      [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], dtype=float)*np.array([a,b,h])/2
    c, s = np.cos(yaw), np.sin(yaw)
    return local@np.array([[c,-s,0],[s,c,0],[0,0,1]]).T+center


def decode(outputs, priors, grid, threshold=.05, topk=40, nms_iou=.2):
    logits, reg = outputs
    probability = logits.sigmoid()
    peaks = probability == F.max_pool2d(probability, 3, stride=1, padding=1)
    probability = (probability*peaks)[0].detach().cpu().numpy()
    regression = reg[0].detach().cpu().numpy()
    size, extent = grid['size'], grid['extent']; cell = 2*extent/size
    all_boxes, all_scores = [], []
    for c in range(4):
        flat = probability[c].ravel(); order = np.argsort(-flat, kind='stable')[:topk]
        candidates = []
        for i in order:
            if flat[i] < threshold: continue
            y, x = divmod(int(i), size); delta = regression[c, :, y, x]
            p = np.asarray(priors['regression'][c]); value = delta+p
            center = [(x+.5+np.clip(delta[0], -.75, .75))*cell-extent,
                      (y+.5+np.clip(delta[1], -.75, .75))*cell-extent,
                      p[4]+2*np.clip(delta[4], -3, 3)]
            a, b = np.clip(np.exp(np.clip(value[2:4], -3, 4)), .2, 30)
            h = float(np.clip(np.exp(np.clip(value[5], -3, 3)), .2, 8))
            yaw = float(np.arctan2(value[7], value[6])/2)
            box = corners(center, a, b, h, yaw); polygon = _polygon(box)
            if any(polygon_iou(polygon, old[2]) > nms_iou for old in candidates): continue
            candidates.append((box, float(flat[i]), polygon))
        for box, score, _ in candidates:
            all_boxes.append(box); all_scores.append([score, c+1])
    return np.asarray(all_boxes).reshape(-1,8,3), np.asarray(all_scores).reshape(-1,2)
