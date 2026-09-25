"""Validate and resample native SMPL-X rotations before skinning."""
from __future__ import annotations


import numpy as np
from scipy.spatial.transform import Rotation, Slerp


# Same position transform used by Kimodo's AMASS exporter: Y-up/+Z forward
# becomes Z-up/+Y forward. Apply ONCE, directly to skinned world positions.
KIMODO_TO_BLENDER = np.array([[-1., 0., 0.], [0., 0., 1.], [0., 1., 0.]], dtype=np.float32)


def resample_body(local, root, source_fps, target_fps, frames=None):
    local = np.asarray(local, dtype=np.float32)
    root = np.asarray(root, dtype=np.float32)
    if local.ndim == 5 and local.shape[0] == 1:
        local = local[0]
    if root.ndim == 3 and root.shape[0] == 1:
        root = root[0]
    if local.ndim != 4 or local.shape[1:] != (22, 3, 3):
        raise ValueError('Expected a single SMPL-X body clip: local_rot_mats [T,22,3,3]')
    if root.shape != (len(local), 3) or len(local) < 1:
        raise ValueError('Expected root_positions [T,3] with matching nonzero frame count')
    if not np.isfinite(source_fps) or not np.isfinite(target_fps) or source_fps <= 0 or target_fps <= 0:
        raise ValueError('Frame rates must be positive')
    if not np.isfinite(local).all() or not np.isfinite(root).all():
        raise ValueError('Motion contains nonfinite values')
    if not np.allclose(local.swapaxes(-1, -2) @ local, np.eye(3), atol=2e-3) or not np.allclose(np.linalg.det(local), 1, atol=2e-3):
        raise ValueError('Invalid rotation matrices')
    count = frames if frames is not None else max(1, int(round(len(local) * target_fps / source_fps)))
    if not isinstance(count, int) or count < 1:
        raise ValueError('Output frame count must be positive')
    times = np.arange(count) / target_fps
    src_times = np.arange(len(local)) / source_fps
    sample_times = np.minimum(times, src_times[-1])
    root_out = np.stack([np.interp(sample_times, src_times, root[:, i]) for i in range(3)], axis=-1)
    if len(local) == 1:
        local_out = np.repeat(local, len(times), axis=0)
    else:
        local_out = np.stack([
            Slerp(src_times, Rotation.from_matrix(local[:, j]))(sample_times).as_matrix()
            for j in range(22)
        ], axis=1)
    return local_out.astype(np.float32), root_out.astype(np.float32), times
