"""Explicit whole-body placement; no pose edits or time-varying facing corrections."""
from fractions import Fraction
import math

import numpy as np
from aha3d.config import keys, timing


def validate_config(cfg):
    keys(cfg, ['schema_version', 'timing', 'image_size', 'camera', 'people', 'validation', 'preview_frames'], 'ensemble')
    if cfg.get('schema_version') != 1:
        raise ValueError('Unsupported ensemble schema')
    t = timing(cfg['timing'])
    size = cfg['image_size']
    if len(size) != 2 or any(type(x) is not int or x <= 0 for x in size):
        raise ValueError('image_size must be positive integer width and height')
    ids, labels = set(), set()
    for p in cfg['people']:
        keys(p, ['id', 'label', 'cache', 'scale', 'yaw', 'anchor_xy', 'ground_z', 'z_offset'], 'person')
        if type(p['id']) is not int or not 1 <= p['id'] <= 32767 or p['id'] in ids:
            raise ValueError('Person IDs must be unique integers in [1,32767]')
        if not isinstance(p['label'], str) or not p['label'].strip() or p['label'] in labels:
            raise ValueError('Person labels must be unique and nonempty')
        ids.add(p['id']); labels.add(p['label'])
        if not isinstance(p['cache'], str) or not p['cache']:
            raise ValueError('Each person requires a cache path')
        if len(p['anchor_xy']) != 2 or not np.isfinite(p['anchor_xy']).all():
            raise ValueError('anchor_xy must contain two finite coordinates')
        if not math.isfinite(p.get('scale', 1)) or p.get('scale', 1) <= 0 or not math.isfinite(p.get('yaw', 0)):
            raise ValueError('Scale must be positive and yaw finite')
        if p.get('ground_z') is not None and not math.isfinite(p['ground_z']):
            raise ValueError('ground_z must be finite or null')
        validate_vertical_placement(p)
    validation = cfg.get('validation', {})
    keys(validation, ['collisions', 'floor_min', 'minimum_in_frame', 'sample_frames', 'camera_pose_tolerance', 'intrinsics_tolerance_px'], 'ensemble validation')
    if validation.get('collisions', 'report') not in ('off', 'report', 'error'):
        raise ValueError('Invalid collision policy')
    for name in ('camera_pose_tolerance', 'intrinsics_tolerance_px'):
        if name in validation and (not math.isfinite(validation[name]) or validation[name] < 0):
            raise ValueError('Camera tolerances must be finite and nonnegative')
    if not 0 <= validation.get('minimum_in_frame', 0) <= 1:
        raise ValueError('minimum_in_frame must be in [0,1]')
    for samples in (cfg.get('preview_frames', []), validation.get('sample_frames', 'all')):
        if samples != 'all' and (not isinstance(samples, list) or any(type(f) is not int or not t['start'] <= f <= t['end'] for f in samples)):
            raise ValueError('Sample frames must lie on the output timeline')
    return t


def validate_vertical_placement(person):
    if not math.isfinite(person.get('z_offset', 0.)):
        raise ValueError('z_offset must be finite')
    if 'z_offset' in person and person.get('ground_z') is not None:
        raise ValueError('Choose constant z_offset or per-frame ground_z, not both')


def place_cache(data, person, t):
    validate_vertical_placement(person)
    result = {k: np.array(v, copy=True) for k, v in data.items()}
    if len(result['vertices']) != t['frames'] or abs(float(result['fps']) - float(Fraction(t['fps']))) > 1e-4:
        raise ValueError('Cache timing differs: resample rotations before skinning')
    expected = np.arange(t['frames']) / float(Fraction(t['fps']))
    if not np.allclose(result['time_seconds'], expected, atol=1e-6, rtol=0):
        raise ValueError('Cache timestamps differ from output cadence')
    scale = person.get('scale', 1.)
    for key in ('vertices', 'joints'):
        if not np.isfinite(result[key]).all():
            raise ValueError('Nonfinite body cache')
        result[key] *= scale
    if person.get('ground_z') is not None:
        dz = person['ground_z'] - result['vertices'][:, :, 2].min(axis=1)
        for key in ('vertices', 'joints'):
            result[key][:, :, 2] += dz[:, None]
        result['vertical_ground_correction_m'] = dz
    result['uniform_body_scale'] = np.float32(scale)
    angle = math.radians(person.get('yaw', 0)); c, s = math.cos(angle), math.sin(angle)
    matrix = np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    matrix[:2, 3] = np.asarray(person['anchor_xy']) - matrix[:2, :2] @ result['joints'][0, 0, :2]
    # World metres, after stature scaling; one transform preserves all native Z changes.
    matrix[2, 3] = person.get('z_offset', 0.)
    return result, matrix
