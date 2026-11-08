"""Four-class native ROI-head adaptation. GT is offline supervision only."""
import types
import numpy as np

GROUPS = (('car', 'van'), ('truck', 'bus', 'trailer'),
          ('cyclist', 'motorcycle'), ('pedestrian',))
CLASS_NAMES = ('Vehicle', 'Heavy_Vehicle', '2Wheeler', 'Pedestrian')
TRAIN_SEQUENCES = ('20241126_0001_crossing2_00', '20241126_0017_crossing1_00')
EPOCHS = 4
LEARNING_RATE = 1e-4


def train_key(key):
    parts = key.split(':')
    if len(parts) != 3 or parts[0] not in TRAIN_SEQUENCES or parts[2] != '100000':
        raise ValueError('Only the two declared Car1 TRAIN recordings may fit the detector')


def collapse_rows(array, categories, block=1, background=False):
    """Fixed mean initialization, not probability aggregation or a fitted mapping."""
    a = np.asarray(array)
    n = len(categories)
    if a.shape[0] != (n + int(background))*block:
        raise ValueError('Unexpected class-dependent tensor shape')
    shaped = a.reshape(n + int(background), block, *a.shape[1:])
    rows = []
    for group in GROUPS:
        indices = [categories.index(name) for name in group if name in categories]
        if not indices:
            raise ValueError('No official initializer for coarse class '+str(group))
        rows.append(shaped[indices].mean(0))
    if background:
        rows.append(shaped[-1].copy())
    return np.stack(rows).reshape((4 + int(background))*block, *a.shape[1:])


def projected_targets(boxes, labels, extrinsic, intrinsic, width, height):
    """Weak 2D boxes projected from annotated 3D cuboids; not visible-box labels.

    Fully front-facing boxes >=12px and >=50% in-image area supervise positives.
    Small/truncated/near-plane-straddling boxes become per-object ignore regions;
    one bad projection never drops the other objects from its image.
    """
    from phdsim.perception.urbaning.rgb3d_late import camera_to_ego
    from phdsim.evaluation.urbaning_cached import _radius_mask
    camera_to_ego(extrinsic)
    boxes = np.asarray(boxes, float).reshape(-1, 8, 3)
    labels = np.asarray(labels)
    if labels.shape != (len(boxes),) or np.any(~np.isin(labels, (1, 2, 3, 4))):
        raise ValueError('Expected four-class UrbanIng labels')
    optical = boxes @ extrinsic[:3, :3].T + extrinsic[:3, 3]
    allowed_radius = _radius_mask(boxes)
    rows = []
    for i, (box, cam) in enumerate(zip(boxes, optical)):
        near_plane_ignore = False
        if np.any(cam[:, 2] <= .1):
            if cam[:, 2].max() > .1:
                # Clip this cuboid against the camera near plane and mark only
                # its image rectangle as ignored. Do not discard every other
                # valid object in this camera frame.
                vertices = list(cam[cam[:, 2] > .1])
                for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
                             (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)):
                    if (cam[a, 2] > .1) != (cam[b, 2] > .1):
                        t = (.1-cam[a, 2])/(cam[b, 2]-cam[a, 2])
                        vertices.append(cam[a]+t*(cam[b]-cam[a]))
                clipped = np.asarray(vertices) @ intrinsic.T
                clipped = clipped[:, :2]/clipped[:, 2:3]
                if not np.isfinite(clipped).all():
                    raise ValueError('Nonfinite near-plane clipped projection')
                lo, hi = clipped.min(0), clipped.max(0)
                rect = np.r_[np.maximum(lo, (0, 0)), np.minimum(hi, (width, height))]
                near_plane_ignore = np.all(rect[2:] > rect[:2])
                if not near_plane_ignore:
                    continue
                area = 0.
            else:
                continue
        else:
            p = cam @ intrinsic.T
            uv = p[:, :2] / p[:, 2:3]
            lo, hi = uv.min(0), uv.max(0)
            area = np.maximum(hi-lo, 0).prod()
            rect = np.r_[np.maximum(lo, (0, 0)), np.minimum(hi, (width, height))]
        size = rect[2:]-rect[:2]
        if np.any(size <= 0):
            continue
        ignore = near_plane_ignore or not (allowed_radius[i] and np.all(size >= 12)
                                           and area > 0 and size.prod()/area >= .5)
        edges = np.stack((box[1]-box[0], box[3]-box[0], box[4]-box[0]))
        length, box_width, box_height = np.linalg.norm(edges, axis=1)
        if min(length, box_width, box_height) <= 0:
            raise ValueError('Degenerate annotated cuboid')
        x = extrinsic[:3, :3] @ (edges[0]/length)
        y = extrinsic[:3, :3] @ (-edges[2]/box_height)
        pose = np.stack((x, y, np.cross(x, y)), axis=1)
        if not np.allclose(pose.T @ pose, np.eye(3), atol=1e-5) or np.linalg.det(pose) < .99999:
            raise ValueError('Invalid proper camera-space target rotation')
        center = cam.mean(0)
        if near_plane_ignore and center[2] <= .1:
            # The ROI is ignored by native sampling; finite positive placeholders
            # keep the Instances fields well formed without inventing supervision.
            center = np.array([0., 0., .1])
        pixel = intrinsic @ center
        pixel = pixel[:2]/pixel[2]
        rows.append({'gt_index': i, 'box2d': rect, 'class': -1 if ignore else int(labels[i])-1,
                     'near_plane_ignore': bool(near_plane_ignore),
                     'center': center, 'pixel': pixel,
                     'dimensions': np.array((box_width, box_height, length)), 'pose': pose})
    return rows


def install_empty_sampler(roi):
    """Fix pinned upstream's empty-GT indexing; keep native positive sampler.

    Do not drop empty cameras: they provide actual background classification
    updates. Ignore-only images remove proposals inside ignore rectangles.
    """
    import torch
    from detectron2.structures import Boxes
    original = roi.label_and_sample_proposals

    def sample(self, proposals, targets):
        if len(targets) != 1 or bool((targets[0].gt_classes >= 0).any()):
            return original(proposals, targets)
        p, target = proposals[0], targets[0]
        valid = torch.ones(len(p), dtype=torch.bool, device=p.proposal_boxes.tensor.device)
        for ignore in target.gt_boxes.tensor:
            b = p.proposal_boxes.tensor
            intersection = (torch.minimum(b[:, 2:], ignore[2:])-
                            torch.maximum(b[:, :2], ignore[:2])).clamp(min=0).prod(1)
            area = (b[:, 2:]-b[:, :2]).clamp(min=0).prod(1).clamp(min=1e-6)
            valid &= intersection/area < self.ignore_thresh
        indices = torch.where(valid)[0]
        indices = indices[torch.randperm(len(indices), device=indices.device)[:self.batch_size_per_image]]
        p = p[indices]
        if len(p) == 0:
            raise ValueError('No usable background proposals; refuse an empty/NaN classification update')
        p.gt_classes = torch.full((len(p),), self.num_classes, dtype=torch.long, device=indices.device)
        p.gt_boxes = Boxes(p.proposal_boxes.tensor.clone())
        p.gt_boxes3D = torch.zeros((len(p), 9), device=indices.device)
        p.gt_poses = torch.eye(3, device=indices.device).repeat(len(p), 1, 1)
        return [p]
    roi.label_and_sample_proposals = types.MethodType(sample, roi)


class FineTuneDetector:
    """Reuse native Cube R-CNN with four supervised coarse outputs on CPU."""
    def __init__(self, model_dir, threads):
        import torch
        from phdsim.perception.urbaning.rgb3d_late import CubeDetector
        self.detector = CubeDetector(model_dir, threads, variant='outdoor')
        self.model = self.detector.model
        self.source_categories = list(self.detector.categories)
        roi = self.model.roi_heads
        head, predictor = roi.cube_head, roi.box_predictor
        if roi.cluster_bins != 1 or roi.z_type != 'direct' or head.pose_type != '6d':
            raise ValueError('Require pinned direct-depth, single-bin, 6D-pose outdoor checkpoint')

        def linear(layer, block, background=False):
            w = collapse_rows(layer.weight.detach().numpy(), self.source_categories, block, background)
            b = collapse_rows(layer.bias.detach().numpy(), self.source_categories, block, background)
            new = torch.nn.Linear(layer.in_features, len(b))
            with torch.no_grad():
                new.weight.copy_(torch.from_numpy(w)); new.bias.copy_(torch.from_numpy(b))
            return new
        predictor.cls_score = linear(predictor.cls_score, 1, True)
        if predictor.bbox_pred.out_features != 4:
            predictor.bbox_pred = linear(predictor.bbox_pred, 4)
        for name, block in (('bbox_3D_dims', 3), ('bbox_3D_center_deltas', 2),
                            ('bbox_3D_pose', 6), ('bbox_3D_center_depth', 1),
                            ('bbox_3D_uncertainty', 1)):
            if hasattr(head, name):
                setattr(head, name, linear(getattr(head, name), block))
        for name, axis in (('priors_dims_per_cat', 1), ('priors_z_scales', 0)):
            source = getattr(roi, name).detach().numpy()
            moved = np.moveaxis(source, axis, 0)
            collapsed = np.moveaxis(collapse_rows(moved, self.source_categories), 0, axis)
            setattr(roi, name, torch.nn.Parameter(torch.from_numpy(collapsed), requires_grad=False))
        roi.num_classes = head.num_classes = predictor.num_classes = 4
        # Canonical aliases are used only by the existing prediction converter.
        self.detector.categories = ['car', 'truck', 'motorcycle', 'pedestrian']
        roi.batch_size_per_image = 128
        self.model.eval().requires_grad_(False)
        for module in (roi.box_head, roi.box_predictor, roi.cube_head):
            module.requires_grad_(True)
        install_empty_sampler(roi)

    def predict(self, image, intrinsic):
        self.model.eval()
        return self.detector.predict(image, intrinsic)

    def training_input(self, bgr, intrinsic, rows):
        import torch
        from detectron2.structures import Boxes, Instances
        image = bgr[:, :, ::-1] if self.detector.input_format == 'RGB' else bgr
        transform = self.detector.resize.get_transform(image)
        resized = transform.apply_image(image)
        n = len(rows)
        target = Instances(resized.shape[:2])
        target.gt_classes = torch.tensor([r['class'] for r in rows], dtype=torch.long)
        rect = np.array([r['box2d'] for r in rows], np.float32).reshape(n, 4)
        target.gt_boxes = Boxes(torch.as_tensor(transform.apply_box(rect)))
        pix = np.array([r['pixel'] for r in rows], np.float32).reshape(n, 2)
        pix = transform.apply_coords(pix)
        depths = np.array([r['center'][2] for r in rows], np.float32).reshape(n, 1)
        dims = np.array([r['dimensions'] for r in rows], np.float32).reshape(n, 3)
        centers = np.array([r['center'] for r in rows], np.float32).reshape(n, 3)
        target.gt_boxes3D = torch.from_numpy(np.c_[pix, depths, dims, centers].astype(np.float32))
        target.gt_poses = torch.as_tensor(np.array([r['pose'] for r in rows], np.float32).reshape(n, 3, 3))
        return {'image': torch.as_tensor(np.ascontiguousarray(resized.transpose(2, 0, 1))),
                'height': bgr.shape[0], 'width': bgr.shape[1], 'K': intrinsic.copy(), 'instances': target}

    def losses(self, inputs):
        """Frozen backbone/RPN eval forwards; native ROI foreground/background loss."""
        import torch
        self.model.eval()
        self.model.roi_heads.train()
        with torch.no_grad():
            images = self.model.preprocess_image([inputs])
            features = self.model.backbone(images.tensor)
            proposals, _ = self.model.proposal_generator(images, features, None)
        ratios = [inputs['height']/images.image_sizes[0][0]]
        _, losses = self.model.roi_heads(images, features, proposals,
                                        [torch.as_tensor(inputs['K'], dtype=torch.float32)],
                                        ratios, [inputs['instances']])
        if not losses or not all(bool(torch.isfinite(v).all()) for v in losses.values()):
            raise ValueError('Nonfinite/empty native ROI losses')
        return losses

    def trainable_state(self):
        return {k: v.detach().cpu().clone() for k, v in self.model.state_dict().items()
                if k.startswith(('roi_heads.box_head.', 'roi_heads.box_predictor.', 'roi_heads.cube_head.'))}

    def load_trainable(self, state):
        expected = self.trainable_state()
        if set(state) != set(expected) or any(state[k].shape != expected[k].shape for k in state):
            raise ValueError('Fine-tuned state keys/shapes differ')
        self.model.load_state_dict(state, strict=False)
