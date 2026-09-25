"""CPU camera representability check before room authoring or body integration."""
import argparse
from fractions import Fraction
from pathlib import Path

import numpy as np

from aha3d.config import path
from aha3d.io import digest, read, write
from aha3d.workflow.people import validate_config


def pixel_aspect_pair(ratio):
    """Blender 5.2 stores each render pixel aspect in [1, 200]."""
    if not np.isfinite(ratio) or not 1 / 200 <= ratio <= 200:
        raise ValueError('Pixel aspect ratio is outside Blender representation limits')
    return (1 / ratio, 1.) if ratio < 1 else (1., ratio)


def camera_report(data, t, size, tolerance_px=2.):
    """Predict the ensemble importer's fixed-aspect K error, without Blender."""
    poses, K = np.asarray(data['c2w'], dtype=float), np.asarray(data['K'], dtype=float)
    times = np.asarray(data['time_seconds'])
    n = t['frames']
    if poses.shape != (n, 4, 4) or K.shape != (n, 3, 3) or times.shape != (n,):
        raise ValueError('Camera shapes differ from the declared timeline')
    if not all(np.isfinite(x).all() for x in (poses, K, times)):
        raise ValueError('Nonfinite camera cache')
    if not np.array_equal(data['image_size'], size):
        raise ValueError('Camera raster differs from ensemble')
    if not np.allclose(times - times[0], np.arange(n) / float(Fraction(t['fps'])), atol=1e-7, rtol=0):
        raise ValueError('Camera cache cadence differs from ensemble')
    rot = poses[:, :3, :3]
    if not np.allclose(rot.swapaxes(-1, -2) @ rot, np.eye(3), atol=2e-4, rtol=0) or not np.allclose(
            np.linalg.det(rot), 1, atol=2e-4, rtol=0) or not np.allclose(poses[:, 3], [0, 0, 0, 1]):
        raise ValueError('Camera c2w must be rigid; keep uniform scale separate')
    if np.any(K[:, [0, 1], [0, 1]] <= 0) or not np.allclose(K[:, 2], [0, 0, 1]):
        raise ValueError('Invalid perspective intrinsics')
    if not np.allclose(K[:, 0, 1], 0) or not np.allclose(K[:, 1, 0], 0):
        raise ValueError('Blender perspective camera cannot represent skew')
    if not np.isfinite(tolerance_px) or tolerance_px < 0:
        raise ValueError('Intrinsic tolerance must be finite and nonnegative')
    aspect = float(np.median(K[:, 0, 0] / K[:, 1, 1]))
    aspect_x, aspect_y = pixel_aspect_pair(aspect)
    represented = K.copy()
    represented[:, 1, 1] = K[:, 0, 0] / aspect
    errors = np.abs(represented - K).max(axis=(1, 2))
    worst = int(errors.argmax())
    return dict(schema_version=1, status='passed' if errors[worst] <= tolerance_px else 'needs_review',
        frames_checked=n, fixed_pixel_aspect_ratio=aspect,
        fixed_pixel_aspect_x=aspect_x, fixed_pixel_aspect_y=aspect_y,
        maximum_K_element_error_px=float(errors[worst]), worst_output_frame=t.get('start', 1) + worst,
        intrinsics_tolerance_px=float(tolerance_px),
        pixel_aspect_policy='fixed median fx/fy; keyed lens and shifts',
        limitations='Analytic representation check only; reopen and verify evaluated Blender cameras. Does not validate Pi3X accuracy.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True, help='Ensemble config; body caches need not exist yet')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    cfg = read(a.config); t = validate_config(cfg)
    if not cfg.get('camera'):
        p.error('Preflight requires an explicit camera cache')
    camera = path(a.root, cfg['camera'])
    with np.load(camera, allow_pickle=False) as data:
        report = camera_report(data, t, cfg['image_size'], cfg.get('validation', {}).get('intrinsics_tolerance_px', 2.))
    report.update(camera=str(camera), camera_sha256=digest(camera), config_sha256=digest(a.config), code_sha256=digest(__file__))
    a.out.mkdir(parents=True, exist_ok=False)
    write(a.out / 'camera.json', report)
    print(report['status'], report['maximum_K_element_error_px'], 'px')
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
