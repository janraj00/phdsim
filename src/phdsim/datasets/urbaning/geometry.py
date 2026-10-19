"""Directed geometry matching the upstream SDK's computations, using float64."""

import itertools
import json
from pathlib import Path

import numpy as np

BOX_EDGES = tuple((i, i ^ bit) for i in range(8) for bit in (1, 2, 4) if i < (i ^ bit))


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError('Expected a finite homogeneous transform')
    return np.asarray(points, dtype=np.float64)[..., :3] @ matrix[:3, :3].T + matrix[:3, 3]


def sensor_to_global(calibration: dict, stream: str, timestamp_ms: int,
                     directory: Path) -> np.ndarray:
    extrinsic = calibration[stream]['extrinsics']
    if stream.startswith('vehicle'):
        vehicle = stream.split('_')[0]
        # Upstream Sequence uses the preceding 10 ms state at each sensor's own timestamp.
        state = directory / f'{vehicle}_state' / f'{timestamp_ms // 10 * 10}.json'
        gTv = np.asarray(json.loads(state.read_text(encoding='utf-8'))['gTv'], dtype=np.float64)
        if stream.endswith('lidar'):
            return gTv @ np.asarray(extrinsic['vTl'], dtype=np.float64)
        return gTv @ np.linalg.inv(np.asarray(extrinsic['cTv'], dtype=np.float64))
    if stream.endswith('lidar'):
        return np.asarray(extrinsic['gTl'], dtype=np.float64)
    return np.linalg.inv(np.asarray(extrinsic['cTg'], dtype=np.float64))


def box_corners(annotation: dict) -> np.ndarray:
    local = np.array(list(itertools.product((-0.5, 0.5), repeat=3)))
    local *= np.asarray(annotation['dimensions_lwh_m'])
    angle = annotation['yaw_rad']
    c, s = np.cos(angle), np.sin(angle)
    rotation = np.array(((c, -s, 0), (s, c, 0), (0, 0, 1)))
    return local @ rotation.T + np.asarray(annotation['position_m'])


def rectified_image(image: np.ndarray, intrinsic: dict) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    matrix = np.asarray(intrinsic['IntrinsicMatrix'], dtype=np.float64).reshape(3, 3).T
    size = tuple(int(x) for x in reversed(intrinsic['ImageSize']))
    if image.shape[1::-1] != size:
        raise ValueError('Image dimensions disagree with calibration')
    if 'DistortionCoefficients' in intrinsic:
        distortion = np.asarray(intrinsic['DistortionCoefficients'], dtype=np.float64)
        new = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
            matrix, distortion, size, np.eye(3), balance=0)
        mapx, mapy = cv2.fisheye.initUndistortRectifyMap(
            matrix, distortion, np.eye(3), new, size, cv2.CV_32FC1)
    else:
        radial = np.asarray(intrinsic['RadialDistortion'], dtype=np.float64)
        tangential = np.asarray(intrinsic['TangentialDistortion'], dtype=np.float64)
        distortion = np.insert(radial, 2, tangential)
        new = cv2.getOptimalNewCameraMatrix(matrix, distortion, size, alpha=0)[0]
        mapx, mapy = cv2.initUndistortRectifyMap(matrix, distortion, None, new, size, cv2.CV_32FC1)
    return cv2.remap(image, mapx, mapy, cv2.INTER_LINEAR), new


def project_points(points: np.ndarray, camera_to_global: np.ndarray,
                   intrinsic: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    camera = transform_points(points, np.linalg.inv(camera_to_global))
    positive = camera[:, 2] > 0.01
    projected = camera @ intrinsic.T
    pixels = np.full((len(camera), 2), np.nan)
    pixels[positive] = projected[positive, :2] / projected[positive, 2:3]
    return pixels, positive


def read_lidar(path: str | Path) -> tuple[np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as archive:
        required = ('x', 'y', 'z', 'intensity', 'time_offset_ms')
        if not all(key in archive for key in required):
            raise ValueError('LiDAR is missing required native channels')
        columns = {key: archive[key] for key in archive.files}
        lengths = {len(array) for array in columns.values()}
        if len(lengths) != 1 or any(array.ndim != 1 for array in columns.values()):
            raise ValueError('LiDAR channel dimensions disagree')
        points = np.column_stack([columns[key] for key in ('x', 'y', 'z')])
        if not np.isfinite(points).all():
            raise ValueError('Non-finite LiDAR coordinates')
        profile = {'encoding': 'npz', 'point_count': len(points),
                   'channels': {key: str(array.dtype) for key, array in columns.items()},
                   'time_offset_ms_min': float(np.min(columns['time_offset_ms'])),
                   'time_offset_ms_max': float(np.max(columns['time_offset_ms']))}
        return points, profile
