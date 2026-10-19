"""Offline scientific previews of source measurements and reference annotations."""

from collections import Counter
from pathlib import Path

import numpy as np

from .geometry import (BOX_EDGES, box_corners, project_points, read_lidar,
                       rectified_image, sensor_to_global, transform_points)


def render_previews(directory: Path, calibration: dict, frame: dict,
                    annotations: list[dict], output: Path) -> dict:
    import cv2
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.patches import Polygon

    members = frame['members']
    rgb = [key for key in members if key.endswith('front_left_camera')]
    thermal = [key for key in members if key.endswith('thermal_camera')]
    cameras = rgb[:2] + thermal[:2]
    if len(cameras) != 4:
        raise ValueError('Preview needs two front-left RGB cameras and two thermal cameras')
    colors = {'Car': '#65dd83', 'Van': '#65dd83', 'Pedestrian': '#ff766a',
              'Truck': '#ffcf61', 'Bus': '#ffcf61', 'Cyclist': '#83bfff'}
    figure, axes = plt.subplots(2, 2, figsize=(16, 9), layout='constrained')
    projected_counts = {}
    for axis, stream in zip(axes.flat, cameras):
        filename = members[stream]
        image = cv2.imread(str(directory / stream / filename), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Preview image could not be decoded')
        image, intrinsic = rectified_image(image, calibration[stream]['intrinsics'])
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        camera_to_global = sensor_to_global(calibration, stream, int(Path(filename).stem), directory)
        axis.imshow(image)
        visible = 0
        for label in annotations:
            pixels, positive = project_points(box_corners(label), camera_to_global, intrinsic)
            inside = positive & (pixels[:, 0] >= 0) & (pixels[:, 0] < image.shape[1]) \
                & (pixels[:, 1] >= 0) & (pixels[:, 1] < image.shape[0])
            if not positive.all() or not inside.any():
                continue
            visible += 1
            color = colors.get(label['class_name'], '#e6b3ff')
            for a, b in BOX_EDGES:
                axis.plot(pixels[[a, b], 0], pixels[[a, b], 1], color=color, linewidth=0.8, alpha=0.9)
        projected_counts[stream] = visible
        offset_ms = (int(Path(filename).stem) * 1_000_000 - frame['timestamp_ns']) / 1e6
        axis.set_title(f'{stream}\n{offset_ms:+.0f} ms from anchor; {visible} projected reference boxes', fontsize=10)
        axis.set_xlim(0, image.shape[1])
        axis.set_ylim(image.shape[0], 0)
        axis.set_axis_off()
    figure.suptitle('UrbanIng-V2X source images with ground-truth 3D boxes\n'
                    'Rectified views; annotation-time objects projected at each camera pose. No predictions.',
                    fontsize=13)
    figure.savefig(output / 'camera_reference_overlay.png', dpi=130)
    plt.close(figure)

    lidar_names = [name for name in members if name.endswith('lidar')]
    global_points, profiles, roundtrips = {}, {}, {}
    for stream in lidar_names:
        filename = members[stream]
        points, profile = read_lidar(directory / stream / filename)
        matrix = sensor_to_global(calibration, stream, int(Path(filename).stem), directory)
        selected = points[::max(1, len(points)//80000)]
        global_points[stream] = transform_points(selected, matrix)
        recovered = transform_points(global_points[stream], np.linalg.inv(matrix))
        roundtrips[stream] = float(np.max(np.abs(recovered - selected)))
        profiles[stream] = profile
    primary = next(name for name in lidar_names if name.startswith('vehicle1'))
    roadside = [name for name in lidar_names if name.startswith('crossing')]
    figure, axes = plt.subplots(1, 2, figsize=(16, 8), layout='constrained')
    groups = [[primary], [primary] + roadside]
    for axis, group, title in zip(axes, groups, ('Vehicle 1 LiDAR', 'Vehicle 1 and roadside LiDARs')):
        axis.set_facecolor('#101b2a')
        for stream in group:
            points = global_points[stream]
            selected = points[(points[:, 2] > -2) & (points[:, 2] < 5)]
            color = '#6daeff' if stream == primary else '#ffb765'
            axis.scatter(selected[:, 0], selected[:, 1], s=0.25, alpha=0.45, c=color, rasterized=True)
        for label in annotations:
            corners = box_corners(label)
            # Top-down hull ordering for the product-order corner definition.
            hull = corners[[0, 2, 6, 4], :2]
            axis.add_patch(Polygon(hull, fill=False, edgecolor=colors.get(label['class_name'], '#d4c0f0'),
                                   linewidth=0.7, alpha=0.9))
        axis.set_aspect('equal')
        axis.set_xlim(-100, 100)
        axis.set_ylim(-80, 80)
        axis.set_xlabel('Global x (m)')
        axis.set_ylabel('Global y (m)')
        axis.set_title(title)
        axis.grid(alpha=0.15)
    figure.suptitle('Source point clouds in a shared coordinate frame with reference boxes\n'
                    'Geometric aggregation for inspection. No learned fusion or detection.', fontsize=13)
    figure.savefig(output / 'lidar_reference_bev.png', dpi=130)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(11, 7), layout='constrained')
    stream_names = sorted(members)
    offsets = [(int(Path(members[name]).stem)*1_000_000 - frame['timestamp_ns'])/1e6
               if members[name] else np.nan for name in stream_names]
    axis.barh(stream_names, offsets, color=['#ffb765' if 'thermal' in name else '#6daeff'
                                          for name in stream_names])
    axis.axvline(0, color='black', linewidth=0.8)
    axis.set_xlabel('Source measurement time minus association anchor (ms)')
    axis.set_title('Source synchronization preserves distinct sensor times')
    axis.grid(axis='x', alpha=0.2)
    figure.savefig(output / 'sensor_time_offsets.png', dpi=130)
    plt.close(figure)
    return {'projected_reference_boxes': projected_counts,
            'lidar_payloads': profiles, 'transform_roundtrip_max_error_m': roundtrips,
            'annotation_class_counts': dict(Counter(label['class_name'] for label in annotations)),
            'point_plot_subsampling': 'up to approximately 80000 points per sensor before height filtering',
            'point_plot_height_range_m': [-2, 5]}
