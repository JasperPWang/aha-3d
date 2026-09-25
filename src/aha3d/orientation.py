"""Explicit asset coordinate contracts; no geometry or front inference.

This module is pure Python. A reviewed/authored declaration describes the actual
asset-root coordinates, not a requested scene heading. Footprint yaw cannot
establish semantic facing. Normalization maps declared fronts to -Y with Z up.
"""
import copy
import math

AXES = {'X': (1, 0, 0), '-X': (-1, 0, 0), 'Y': (0, 1, 0),
        '-Y': (0, -1, 0), 'Z': (0, 0, 1), '-Z': (0, 0, -1)}
TRUSTED = ('authored', 'reviewed')


def _axis(value, label):
    if isinstance(value, str) and value.startswith('+'):
        value = value[1:]
    if not isinstance(value, str) or value not in AXES:
        raise ValueError(label + ' must be a signed X, Y or Z axis')
    return value


def unknown_orientation(origin='source_root'):
    return dict(schema_version=1, front_axis=None, up_axis='Z', symmetry='none',
                origin=origin, semantic_front='generic', status='unknown', evidence='')


def normalize_orientation(data, require_trusted=False):
    if not isinstance(data, dict):
        raise ValueError('Explicit orientation object required; inspect the asset and declare its actual front')
    allowed = {'schema_version', 'front_axis', 'up_axis', 'symmetry', 'origin',
               'semantic_front', 'status', 'evidence'}
    if set(data) - allowed:
        raise ValueError('Unknown orientation fields: ' + ', '.join(sorted(set(data) - allowed)))
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('orientation.schema_version must be 1')
    result = copy.deepcopy(data)
    for key in ('front_axis', 'up_axis', 'symmetry', 'origin', 'semantic_front', 'status'):
        if key not in result:
            raise ValueError('Missing orientation.' + key)
    result['up_axis'] = _axis(result['up_axis'], 'up_axis')
    if result['symmetry'] not in ('none', 'continuous_z'):
        raise ValueError('Unsupported orientation symmetry')
    if result['origin'] not in ('floor_center', 'mount_center', 'source_root'):
        raise ValueError('Unsupported orientation origin')
    if result['semantic_front'] not in ('seating', 'spout', 'door', 'generic', 'none'):
        raise ValueError('Unsupported semantic_front')
    if result['status'] not in ('unknown', 'declared', 'authored', 'reviewed'):
        raise ValueError('Unsupported orientation status')
    result.setdefault('evidence', '')
    if not isinstance(result['evidence'], str):
        raise ValueError('orientation.evidence must be text')
    if result['symmetry'] == 'continuous_z':
        if result['front_axis'] is not None or result['semantic_front'] != 'none':
            raise ValueError('Rotationally symmetric assets have no front_axis or semantic front')
    elif result['front_axis'] is None:
        if result['status'] != 'unknown':
            raise ValueError('Directional assets require a front_axis')
    else:
        result['front_axis'] = _axis(result['front_axis'], 'front_axis')
        if sum(a*b for a, b in zip(AXES[result['front_axis']], AXES[result['up_axis']])) != 0:
            raise ValueError('front_axis and up_axis must be perpendicular')
        if result['semantic_front'] == 'none':
            raise ValueError('Directional assets need a semantic_front')
    if result['status'] in TRUSTED and not result['evidence'].strip():
        raise ValueError('Authored/reviewed orientation requires evidence')
    if require_trusted and result['status'] not in TRUSTED:
        raise ValueError('Orientation is not verified: inspect and explicitly tag the source asset/root first')
    return result


def canonical_rotation(data):
    """Return a proper 3x3 rotation mapping declared source front/up to -Y/Z."""
    orientation = normalize_orientation(data)
    up = AXES[orientation['up_axis']]
    if orientation['symmetry'] == 'continuous_z':
        front = AXES['-Y'] if up[1] == 0 else AXES['-X']
    elif orientation['front_axis'] is None:
        raise ValueError('Cannot normalize an unknown front')
    else:
        front = AXES[orientation['front_axis']]
    right = (up[1]*front[2]-up[2]*front[1], up[2]*front[0]-up[0]*front[2],
             up[0]*front[1]-up[1]*front[0])
    return (right, tuple(-v for v in front), up)


def canonical_orientation(data):
    result = normalize_orientation(data)
    canonical_rotation(result)
    result['up_axis'] = 'Z'
    if result['symmetry'] == 'none':
        result['front_axis'] = '-Y'
    return result


def authored_orientation(semantic_front='generic', origin='floor_center', evidence=''):
    return normalize_orientation(dict(schema_version=1, front_axis='-Y', up_axis='Z',
        symmetry='none', origin=origin, semantic_front=semantic_front, status='authored', evidence=evidence))


def validate_tolerance(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 180:
        raise ValueError('Facing tolerance must be finite degrees in [0, 180]')
    return float(value)
