"""Terminal track activity is distinct from observation/occlusion support."""
import numpy as np


def track_active_mask(value, frames):
    """One track segment has an active prefix and optional terminal inactive tail."""
    if not isinstance(frames, (int, np.integer)) or isinstance(frames, bool) or frames < 1:
        raise ValueError('Track timeline must contain at least one frame')
    if value is None:
        return np.ones(frames, dtype=bool)
    active = np.asarray(value)
    if active.dtype != np.bool_ or active.shape != (frames,):
        raise ValueError('track_active must be boolean [T]')
    if not frames or not active[0] or np.any(np.diff(active.astype(np.int8)) > 0):
        raise ValueError('track_active must be a nonempty active prefix; reentry requires a new track')
    return active.copy()


def source_frame_mapping(value, frames):
    mapping = np.arange(frames) if value is None else np.asarray(value)
    if mapping.shape != (frames,) or mapping.dtype.kind not in 'iu' or not np.array_equal(mapping, np.arange(frames)):
        raise ValueError('source_frame_indices must retain every zero-origin source frame [0:T]')
    return mapping.copy()
