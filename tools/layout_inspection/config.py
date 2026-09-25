"""Validation only: inspection never derives a separate fit for either input."""
import numpy as np


def reference_layers(config, hybrid=False):
    allowed = {'static','person','glass','mirror','geometry_invalid','semantic_unknown','context','context_points'}
    default = ['static','context','glass','mirror','semantic_unknown','context_points'] if hybrid else ['static']
    selected = config.get('reference_layers', default)
    if not isinstance(selected, list) or not set(selected).issubset(allowed):
        raise ValueError('Invalid reference_layers selection')
    return selected


def validate(config, reference_transform, camera_transform):
    if not np.allclose(reference_transform, camera_transform, atol=1e-6):
        raise ValueError('Reference and camera world transforms differ')
    matrix = np.asarray(config['model_to_world'], dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0,0,0,1]):
        raise ValueError('Explicit finite 4x4 model_to_world required')
    if not config.get('model_transform_reason'):
        raise ValueError('Record model transform provenance; no automatic registration')
    for name in ('top', 'front', 'side'):
        view = config['views'][name]
        for key in ('location', 'target'):
            if len(view[key]) != 3 or not np.isfinite(view[key]).all():
                raise ValueError('Invalid camera vector')
        if np.linalg.norm(np.asarray(view['location'])-view['target']) < 1e-6 or view['ortho_scale'] <= 0:
            raise ValueError('Invalid orthographic camera')
        crop = np.asarray(view['crop_xyz_m'], dtype=float)
        if crop.shape != (3, 2) or not np.isfinite(crop).all() or np.any(crop[:,0] >= crop[:,1]):
            raise ValueError('Explicit common finite crop_xyz_m required')
    return matrix
