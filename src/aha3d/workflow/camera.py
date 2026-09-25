"""Interpolate same-shot Pi3X cameras at explicit output timestamps (CPU)."""
import argparse
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.spatial.transform import Rotation, Slerp

from aha3d.config import keys, timing
from aha3d.io import digest, read, write


def interpolate(cameras, target_times, processed_size, output_size, endpoint='error'):
    frames = cameras['frames']
    ts = np.asarray([f['timestamp_seconds'] for f in frames], dtype=float)
    poses = np.asarray([f['c2w'] for f in frames], dtype=float)
    intrinsics = np.asarray([f['intrinsics'] for f in frames], dtype=float)
    times = np.asarray(target_times, dtype=float)
    if len(ts) < 2 or not np.isfinite(ts).all() or np.any(np.diff(ts) <= 0):
        raise ValueError('Need at least two strictly increasing same-shot observations')
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('Output timestamps must be finite and strictly increasing')
    if poses.shape != (len(ts), 4, 4) or not np.isfinite(poses).all():
        raise ValueError('Invalid c2w matrices')
    rot = poses[:, :3, :3]
    if not np.allclose(rot.swapaxes(-1, -2) @ rot, np.eye(3), atol=2e-4) or not np.allclose(np.linalg.det(rot), 1, atol=2e-4) or not np.allclose(poses[:, 3], [0, 0, 0, 1]):
        raise ValueError('c2w must contain proper rigid rotations')
    if intrinsics.shape != (len(ts), 3, 3) or not np.isfinite(intrinsics).all() or np.any(intrinsics[:, [0, 1], [0, 1]] <= 0):
        raise ValueError('Invalid intrinsics')
    outside = (times < ts[0] - 1e-8) | (times > ts[-1] + 1e-8)
    if endpoint not in ('error', 'hold') or endpoint == 'error' and np.any(outside):
        raise ValueError('Output extends outside observed interval; explicitly select hold if intended')
    clipped = np.clip(times, ts[0], ts[-1])
    out = np.broadcast_to(np.eye(4), (len(times), 4, 4)).copy()
    out[:, :3, :3] = Slerp(ts, Rotation.from_matrix(rot))(clipped).as_matrix()
    out[:, :3, 3] = PchipInterpolator(ts, poses[:, :3, 3])(clipped)
    K = np.stack([np.interp(clipped, ts, intrinsics[:, i, j]) for i in range(3) for j in range(3)], -1).reshape(-1, 3, 3)
    sizes = np.asarray([processed_size, output_size], dtype=float)
    if sizes.shape != (2, 2) or not np.isfinite(sizes).all() or np.any(sizes <= 0):
        raise ValueError('Image sizes must be positive width/height pairs')
    sx, sy = sizes[1] / sizes[0]
    # Convert integer pixel centers to image-boundary centers BEFORE whole-frame resize.
    K[:, 0, 2] += .5; K[:, 1, 2] += .5
    K[:, 0, :] *= sx; K[:, 1, :] *= sy
    return dict(c2w=out, K=K, time_seconds=times, image_size=np.asarray(output_size),
                source_observation_frames=np.asarray([f['source_frame'] for f in frames])), int(outside.sum())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    cfg = read(a.config); inputs = read(a.bundle / 'inputs.json'); cameras = read(a.bundle / 'cameras.json')
    keys(cfg, ['timing', 'image_size', 'continuous_shot_reviewed', 'endpoint', 'source_start_seconds'], 'camera config')
    if [f['source_frame'] for f in cameras['frames']] != inputs['frame_indices'] or not np.allclose(
            [f['timestamp_seconds'] for f in cameras['frames']], inputs['timestamps_seconds'], atol=1e-8, rtol=0):
        raise ValueError('Camera observations differ from bundle frame IDs/timestamps')
    if cfg.get('continuous_shot_reviewed') is not True:
        raise ValueError('Review and split source cuts before interpolation')
    t = timing(cfg['timing'])
    times = np.arange(t['frames']) / float(Fraction(t['fps'])) + cfg.get('source_start_seconds', 0)
    values, held = interpolate(cameras, times, inputs['processed_size_wh'], cfg['image_size'], cfg.get('endpoint', 'error'))
    a.out.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(a.out / 'camera.npz', **values)
    write(a.out / 'camera.json', dict(schema_version=1, timing=t, image_size=cfg['image_size'],
        source_sha256=inputs['source_sha256'], camera_input_sha256=digest(a.bundle / 'cameras.json'),
        config_sha256=digest(a.config), interpolation='PCHIP translation, SLERP rotation, linear intrinsics',
        endpoint=cfg.get('endpoint', 'error'), held_samples=held, cuts='one reviewed continuous shot',
        pixels='image-boundary centers; integer-index principal point converted before whole-image resize',
        scale=cameras.get('units'), world_transform=cameras['world_transform']))


if __name__ == '__main__':
    main()
