"""Independent RGB cuboids and fixed decision-level fusion, without GT inputs.

Cube R-CNN reports camera-space corners. Keep those corners for projection QA;
for the existing upright UrbanIng evaluator, use the predicted center, physical
dimensions and the projected local length axis. No LiDAR depth/proposals or GT
is used to determine an RGB box. This is an explicit upright-box approximation.
"""
from pathlib import Path
import json

import numpy as np

from phdsim.evaluation.urbaning_cached import _polygon, polygon_iou, validate_arrays

OMNI_COMMIT = '778bd0210e5e1b584cc52daeba57cae3a3ee8c4e'
D2_COMMIT = '247691a1c292654867deb35cabb27f18d75a1363'
P3D_COMMIT = '75ebeeaea0908c5527e7b1e305fbc7681382db47'
ASSETS = {
    'cubercnn_DLA34_FPN.yaml': '8cbc9fffd7460acd4dfb967acf28ae0ecb7285c86f90e57d20a02a697631c71f',
    'category_meta.json': 'b4c4a697313decb1d2228fa9db516738861031024532e0c2a968a183b0d21ed9',
    'cubercnn_DLA34_FPN.pth': 'fb60a7ae8e9b54bfac3bb46082856e5f4a06e05f3bd4f58295900ce05e5171df',
}
# UrbanIng's classes aggregate finer labels. EScooter/OtherVehicle have no exact
# checkpoint counterpart. All original GT remains in evaluation. A bare bicycle
# is not silently substituted for UrbanIng's Cyclist (rider + bicycle).
CLASS_MAP = {'car': 1, 'van': 1, 'truck': 2, 'bus': 2, 'trailer': 2,
             'cyclist': 3, 'motorcycle': 3, 'pedestrian': 4}


def camera_to_ego(extrinsic):
    e = np.asarray(extrinsic, dtype=float)
    if (e.shape != (4, 4) or not np.isfinite(e).all()
            or not np.allclose(e[3], [0, 0, 0, 1])
            or not np.allclose(e[:3, :3].T @ e[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(e[:3, :3]), 1, atol=1e-5)):
        raise ValueError('Expected rigid Car1-to-optical-camera extrinsic')
    return np.linalg.inv(e)


def upright_boxes(centers, dimensions, rotations, extrinsic):
    """Cube dimensions are W,H,L; its local x axis is L, local z is W."""
    c, d, r = map(lambda x: np.asarray(x, dtype=float), (centers, dimensions, rotations))
    n = len(c)
    if (c.shape != (n, 3) or d.shape != (n, 3) or r.shape != (n, 3, 3)
            or not all(np.isfinite(x).all() for x in (c, d, r))
            or np.any(d <= 0)):
        raise ValueError('Invalid predicted camera cuboids')
    t = camera_to_ego(extrinsic)
    ec = c @ t[:3, :3].T + t[:3, 3]
    er = t[:3, :3] @ r
    axis = er[:, :2, 0]
    if np.any(np.linalg.norm(axis, axis=1) < 1e-6):
        raise ValueError('Predicted length axis has no usable BEV heading')
    yaw = np.arctan2(axis[:, 1], axis[:, 0])
    # Clockwise perimeter per horizontal face; the original evaluator consumes
    # the first four corners. No camera-specific corner order leaks into it.
    unit = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                     [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], dtype=float) / 2
    boxes = unit[None] * d[:, None, [2, 0, 1]]
    x, y = boxes[:, :, 0].copy(), boxes[:, :, 1].copy()
    boxes[:, :, 0] = np.cos(yaw)[:, None]*x - np.sin(yaw)[:, None]*y
    boxes[:, :, 1] = np.sin(yaw)[:, None]*x + np.cos(yaw)[:, None]*y
    return boxes + ec[:, None]


def classwise_nms(boxes, scores, threshold=.2):
    """Fixed BEV hard-NMS; retain original confidences, no calibration/fitting."""
    boxes, scores = np.asarray(boxes), np.asarray(scores)
    if scores.shape != (len(boxes), 2) or not 0 <= threshold <= 1:
        raise ValueError('Expected confidence/class pairs and IoU threshold')
    validate_arrays(boxes, scores[:, 1], scores[:, 0])
    polys = [_polygon(b) for b in boxes]
    order = np.argsort(-scores[:, 0], kind='stable')
    keep = []
    for i in order:
        if any(scores[i, 1] == scores[j, 1] and
               polygon_iou(polys[i], polys[j]) > threshold for j in keep):
            continue
        keep.append(int(i))
    return np.asarray(keep, dtype=int)


def late_fuse(lidar_boxes, lidar_scores, rgb_boxes, rgb_scores, threshold=.2):
    """Union + fixed NMS; new RGB-only objects can survive the union."""
    boxes = np.concatenate([lidar_boxes, rgb_boxes])
    scores = np.concatenate([lidar_scores, rgb_scores])
    keep = classwise_nms(boxes, scores, threshold)
    return boxes[keep], scores[keep], keep


class CubeDetector:
    """Unchanged official network on CPU; inference receives RGB and K only."""
    def __init__(self, model_dir, threads=8):
        import hashlib
        import torch
        from detectron2.config import get_cfg
        from detectron2.data import transforms as T
        from cubercnn.config import get_cfg_defaults
        # Imports register the official components, without using the GPU demo.
        from cubercnn.modeling.proposal_generator import RPNWithIgnore  # noqa:F401
        from cubercnn.modeling.roi_heads import ROIHeads3D  # noqa:F401
        from cubercnn.modeling.backbone import build_dla_from_vision_fpn_backbone  # noqa:F401
        from cubercnn.modeling.meta_arch import build_model
        model_dir = Path(model_dir)
        for name, expected in ASSETS.items():
            if hashlib.sha256((model_dir/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Official Cube R-CNN asset changed: ' + name)
        torch.set_num_threads(threads)
        torch.manual_seed(0)
        cfg = get_cfg(); get_cfg_defaults(cfg)
        cfg.merge_from_file(str(model_dir/'cubercnn_DLA34_FPN.yaml'))
        cfg.MODEL.DEVICE = 'cpu'
        cfg.MODEL.WEIGHTS = str(model_dir/'cubercnn_DLA34_FPN.pth')
        cfg.freeze()
        self.model = build_model(cfg)
        # The checkpoint is the hash-pinned official artifact, not user pickle.
        checkpoint = torch.load(cfg.MODEL.WEIGHTS, map_location='cpu', weights_only=False)
        incompatible = self.model.load_state_dict(checkpoint['model'], strict=False)
        # Detectron buffers can be omitted by its own checkpointer; require all
        # trainable/buffer state except those documented preprocessing buffers.
        missing = set(incompatible.missing_keys) - {'pixel_mean', 'pixel_std'}
        if missing or incompatible.unexpected_keys:
            raise ValueError(f'Checkpoint mismatch: {missing}, {incompatible.unexpected_keys}')
        self.model.eval().requires_grad_(False)
        self.categories = json.loads((model_dir/'category_meta.json').read_text())['thing_classes']
        self.resize = T.ResizeShortestEdge(cfg.INPUT.MIN_SIZE_TEST, cfg.INPUT.MAX_SIZE_TEST)
        self.input_format = cfg.INPUT.FORMAT

    def predict(self, bgr, intrinsic):
        import torch
        image = np.asarray(bgr)
        k = np.asarray(intrinsic, dtype=float)
        if (image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8
                or k.shape != (3, 3) or not np.isfinite(k).all()
                or min(k[0,0], k[1,1]) <= 0):
            raise ValueError('Expected uint8 RGB-camera image and native intrinsic matrix')
        if self.input_format == 'RGB': image = image[:, :, ::-1]
        elif self.input_format != 'BGR': raise ValueError('Unknown official input format')
        h, w = image.shape[:2]
        resized = self.resize.get_transform(image).apply_image(image)
        inputs = {'image': torch.as_tensor(np.ascontiguousarray(resized.transpose(2,0,1))),
                  'height': h, 'width': w, 'K': k.copy()}
        with torch.inference_mode():
            out = self.model([inputs])[0]['instances'].to('cpu')
        return {'centers': out.pred_center_cam.numpy(), 'dimensions': out.pred_dimensions.numpy(),
                'rotations': out.pred_pose.numpy(), 'corners': out.pred_bbox3D.numpy(),
                'scores': out.scores.numpy(), 'classes': out.pred_classes.numpy(),
                'boxes2d': out.pred_boxes.tensor.numpy()}
