"""Carry GVHMR predicted foot contacts into scene refinement; no new detector.

The four static-head channels correspond to SMPL-X joints 7, 10, 8, 11.
Predictions remain model evidence, never manually reviewed contact ground truth.
"""
from pathlib import Path
import json

import numpy as np
from scipy.special import expit

from tools.gvhmr.root_constraints import active_mask, sha256

JOINT_IDS = [7, 10, 8, 11]


def from_export(body_path, export_path, scene, *, velocity_weight=1000., height_weight=100., target_gap=.002):
    """Read the exact exported v2 input and its unchanged GVHMR static logits."""
    import joblib
    body = dict(np.load(body_path, allow_pickle=False))
    receipt = json.loads(Path(export_path).read_text())
    if receipt['body']['sha256'] != sha256(body_path):
        raise ValueError('Foot evidence must bind the exact exported body')
    inputs = receipt['inputs']
    for name in ('results', 'meta', 'model'):
        if sha256(inputs[name]['path']) != inputs[name]['sha256']:
            raise ValueError('Foot evidence input hash mismatch: ' + name)
    meta = json.loads(Path(inputs['meta']['path']).read_text())
    if meta['source_video_sha256'] != str(body['source_video_sha256']) or meta['actor_id'] != str(body['source_actor_id']):
        raise ValueError('Foot evidence source/actor mismatch')
    results = joblib.load(inputs['results']['path'])
    if len(results['people']) != 1 or results['n_frames'] != len(body['time_seconds']):
        raise ValueError('One actor and the complete source timeline required')
    person = next(iter(results['people'].values()))
    ids = np.asarray(person['frames'])
    if not np.array_equal(ids, np.flatnonzero(active_mask(body))):
        raise ValueError('Foot contact active-frame mapping differs from body')
    if not np.allclose(body['time_seconds'], np.arange(len(body['time_seconds']))/meta['fps'], atol=1e-7):
        raise ValueError('Foot contact source timing mismatch')
    logits = np.asarray(person['smplx_cam']['static_conf_logits'])[:, :4]
    if logits.shape != (len(ids), 4) or not np.isfinite(logits).all():
        raise ValueError('Finite four-channel GVHMR static logits required')
    confidence = np.zeros((len(body['time_seconds']), 4))
    confidence[ids] = expit(logits)
    with np.load(inputs['model']['path'], allow_pickle=False) as model:
        parts = np.asarray(model['weights']).argmax(axis=1)
    vertex_ids = np.asarray(body['vertex_ids'])
    if vertex_ids.shape != (body['vertices'].shape[1],) or not np.array_equal(vertex_ids, np.arange(len(parts))):
        raise ValueError('Foot patches require the complete native SMPL-X topology')
    patches = [np.flatnonzero(parts == joint) for joint in JOINT_IDS]
    foot = prepare(body, confidence, patches, scene, velocity_weight=velocity_weight,
                   height_weight=height_weight, target_gap=target_gap)
    foot['provenance'] = dict(export_path=str(Path(export_path).resolve()), export_sha256=sha256(export_path),
                              inputs={k: inputs[k] for k in ('results', 'meta', 'model')},
                              evidence='GVHMR static-head predictions carried unchanged by v2; no new/manual detector')
    return foot


def prepare(body, confidence, patches, scene, *, velocity_weight=1000., height_weight=100., target_gap=.002):
    active = active_mask(body)
    conf = np.asarray(confidence, float)
    if conf.shape != (len(active), 4) or not np.isfinite(conf).all() or np.any((conf < 0) | (conf > 1)):
        raise ValueError('Contact confidence must be finite [T,4] probabilities')
    if not all(np.isfinite(x) and x > 0 for x in (velocity_weight, height_weight)) or not np.isfinite(target_gap) or target_gap < 0:
        raise ValueError('Positive foot weights and nonnegative height target required')
    if len(patches) != 4 or any(len(p) == 0 for p in patches):
        raise ValueError('Four nonempty native foot patches required')
    strength = conf * (conf > .5) * active[:, None]
    pairs = np.minimum(strength[1:], strength[:-1])
    pairs *= (np.diff(body['source_frame_indices']) == 1)[:, None]
    dt = np.diff(body['time_seconds'])
    joint_velocity = np.diff(np.asarray(body['joints'][:, JOINT_IDS], float), axis=0)/dt[:, None, None]
    low = np.zeros_like(conf)
    for channel, patch in enumerate(patches):
        p = body['vertices'][:, patch]
        low[:, channel] = p[:, :, 2].min(axis=1)
    # The authored floor's origin is reused, not re-estimated from feet.
    offset = float(scene['floor_offset'])
    low += offset
    return dict(confidence=conf, strength=strength, pairs=pairs, dt=dt,
                joint_velocity=joint_velocity, sole_height=low, patches=patches,
                velocity_weight=float(velocity_weight), height_weight=float(height_weight), target_gap=float(target_gap),
                floor_vertices=scene['floor_vertices'], floor_faces=scene['floor_faces'], floor_offset=offset)


def objective(foot, offsets):
    """Quadratic foot velocity/sole-height loss and exact translation gradient."""
    grad = np.zeros_like(offsets)
    dv = np.diff(offsets, axis=0)/foot['dt'][:, None]
    v = foot['joint_velocity'] + dv[:, None]
    w = foot['velocity_weight'] * foot['pairs']/max(1., float(foot['pairs'].sum()))
    value = float(np.sum(w[:, :, None] * v*v))
    g = 2*np.sum(w[:, :, None]*v, axis=1)/foot['dt'][:, None]
    grad[1:] += g; grad[:-1] -= g
    h = foot['sole_height'] + offsets[:, 2, None] - foot['target_gap']
    w = foot['height_weight']*foot['strength']/max(1., float(foot['strength'].sum()))
    value += float(np.sum(w*h*h))
    grad[:, 2] += 2*np.sum(w*h, axis=1)
    return value, grad


def metrics(body, foot):
    from tools.gvhmr.full_scene_constraints import floor_inside_xy
    v = np.diff(np.asarray(body['joints'][:, JOINT_IDS], float), axis=0)/foot['dt'][:, None, None]
    on = foot['pairs'] > 0
    speed = np.linalg.norm(v, axis=-1)
    height = np.column_stack([body['vertices'][:, ids, 2].min(axis=1)+foot['floor_offset'] for ids in foot['patches']])
    covered = np.zeros_like(height, dtype=bool)
    patch_speed = np.zeros_like(speed)
    for c, ids in enumerate(foot['patches']):
        p = body['vertices'][:, ids]
        low = p[np.arange(len(p)), p[:, :, 2].argmin(axis=1)]
        covered[:, c] = floor_inside_xy(low, foot['floor_vertices'], foot['floor_faces'])
        # Fixed corresponding patch vertices: diagnostic includes foot rotation.
        patch_speed[:, c] = np.linalg.norm(np.diff(p.astype(float), axis=0), axis=-1).max(axis=1)/foot['dt']
    samples = speed[on]; h = height[foot['strength'] > 0]
    report = dict(contact_samples=int(on.sum()), contact_frames=int(np.any(foot['strength'] > 0, axis=1).sum()),
                  slip_mean_m_s=float(samples.mean()) if samples.size else None,
                  slip_p90_m_s=float(np.percentile(samples, 90)) if samples.size else None,
                  slip_fraction_over_5cm_s=float((samples > .05).mean()) if samples.size else None,
                  patch_point_speed_mean_m_s=float(patch_speed[on].mean()) if samples.size else None,
                  support_abs_height_mean_m=float(abs(h).mean()) if h.size else None,
                  support_max_gap_m=float(np.maximum(h, 0).max()) if h.size else None,
                  support_max_penetration_m=float(np.maximum(-h, 0).max()) if h.size else None,
                  support_outside_floor_samples=int(((foot['strength'] > 0) & ~covered).sum()),
                  evidence='Model-predicted contacts, not observed ground truth; patch speed includes rotation')
    arrays = dict(confidence=foot['confidence'], contact_pair_mask=on, joint_speed_m_s=speed,
                  patch_max_speed_m_s=patch_speed, sole_height_m=height, floor_covered=covered)
    return report, arrays
