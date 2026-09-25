"""Fit a root trajectory to actor-associated depth without resizing the body.

All points must already share one rigid room basis. Depth-derived observations
remain estimated surface measurements, not ground-truth pelvis positions. Source
identity, pixel/camera transforms and any surface-to-root correction belong to
the observation producer and must be retained in its provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy.ndimage import binary_erosion
from scipy.optimize import least_squares


def sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(np.asarray(value), -60, 60)))


def sample_surface(depth, confidence, non_edge, actor_mask, uv, K, c2w,
                   *, radius=5, min_pixels=9, confidence_threshold=0.5,
                   max_depth_mad=0.04, max_inlier_range=0.20):
    """Robust depth on the requested pixel ray, restricted to the target mask.

    Caller must separately establish that the anatomical observation is visible
    and belongs to this person. Scores and a propagated mask cannot prove that.
    """
    depth = np.asarray(depth, dtype=float)
    confidence = np.asarray(confidence, dtype=float).squeeze()
    mask = np.asarray(actor_mask)
    edge = np.asarray(non_edge)
    uv = np.asarray(uv, dtype=float)
    K, c2w = np.asarray(K, float), np.asarray(c2w, float)
    if depth.ndim != 2 or confidence.shape != depth.shape or mask.shape != depth.shape or edge.shape != depth.shape:
        raise ValueError('Depth, confidence and masks must share one pixel grid')
    if mask.dtype != bool or edge.dtype != bool:
        raise ValueError('Explicit boolean masks required')
    if K.shape != (3, 3) or c2w.shape != (4, 4) or not np.isfinite(K).all() or not np.isfinite(c2w).all():
        raise ValueError('Finite OpenCV intrinsics and c2w required')
    if uv.shape != (2,) or not np.isfinite(uv).all():
        return None, {'valid': False, 'reason': 'invalid landmark'}
    x, y = np.rint(uv).astype(int)
    h, w = depth.shape
    if not (0 <= x < w and 0 <= y < h):
        return None, {'valid': False, 'reason': 'landmark outside frame'}
    interior = binary_erosion(mask, iterations=2)
    if not interior[y, x]:
        return None, {'valid': False, 'reason': 'landmark outside target-mask interior'}
    yy, xx = np.ogrid[:h, :w]
    patch = (xx - uv[0]) ** 2 + (yy - uv[1]) ** 2 <= radius ** 2
    valid = patch & interior & edge & np.isfinite(depth) & (depth > 0)
    valid &= np.isfinite(confidence) & (sigmoid(confidence) > confidence_threshold)
    z = depth[valid]
    if len(z) < min_pixels:
        return None, {'valid': False, 'reason': 'insufficient supported target pixels', 'pixels': int(len(z))}
    center = np.median(z)
    mad = np.median(np.abs(z - center))
    if mad > max_depth_mad:
        return None, {'valid': False, 'reason': 'broad or mixed depth layers',
                      'depth_mad': float(mad), 'pixels': int(len(z))}
    # Reject depth discontinuities within the local actor patch. The absolute
    # floor is a declared nominal-unit tolerance, not an error calibration.
    keep = np.abs(z - center) <= max(0.04, 3.0 * 1.4826 * mad)
    if keep.sum() < min_pixels:
        return None, {'valid': False, 'reason': 'insufficient depth inliers'}
    if keep.mean() < 0.75 or np.ptp(z[keep]) > max_inlier_range:
        return None, {'valid': False, 'reason': 'ambiguous depth cluster',
                      'inlier_fraction': float(keep.mean())}
    depth_value = float(np.median(z[keep]))
    ray = np.linalg.solve(K, np.r_[uv, 1.0])
    local = ray * (depth_value / ray[2])
    world = c2w[:3, :3] @ local + c2w[:3, 3]
    return world, {'valid': True, 'pixels': int(keep.sum()), 'uv': uv.tolist(),
                   'camera_depth': depth_value, 'depth_mad': float(mad),
                   'depth_range': [float(z[keep].min()), float(z[keep].max())]}


def _observations(roots, frame_indices, targets, valid, weights, train):
    roots, targets = np.asarray(roots, float), np.asarray(targets, float)
    ids = np.asarray(frame_indices)
    valid, train = np.asarray(valid), np.asarray(train)
    weights = np.asarray(weights, float)
    if roots.ndim != 2 or roots.shape[1] != 3 or not np.isfinite(roots).all():
        raise ValueError('Finite full-timeline roots[T,3] required')
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(np.unique(ids)) != len(ids) or np.any(np.diff(ids) <= 0):
        raise ValueError('Unique increasing source-frame indices required')
    if len(ids) < 2 or ids.min() < 0 or ids.max() >= len(roots):
        raise ValueError('Observation frames outside source timeline')
    if targets.shape != (len(ids), 3) or valid.shape != ids.shape or train.shape != ids.shape or weights.shape != ids.shape:
        raise ValueError('Observation arrays must have the same row count')
    if valid.dtype != bool or train.dtype != bool:
        raise ValueError('Explicit validity and immutable train masks required')
    if not np.isfinite(targets[valid]).all() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError('Valid observations and weights must be finite')
    eligible = valid & (weights > 0)
    if (eligible & train).sum() < 3:
        raise ValueError('At least three supported training rows required')
    return roots, ids, targets, eligible, weights, train


def distance_stats(values):
    values = np.asarray(values, float)
    if not values.size:
        return {'count': 0, 'median_m': None, 'p90_m': None, 'max_m': None}
    return {'count': int(values.size), 'median_m': float(np.median(values)),
            'p90_m': float(np.percentile(values, 90)), 'max_m': float(values.max())}


def fit_trajectory(roots, frame_indices, targets, valid, weights, train,
                   *, fit_scale=True, scale_bounds=(0.1, 10.0), residual_scale=0.05, track_active=None):
    """Robust positive trajectory scale/XYZ translation, using training rows only."""
    roots, ids, target, valid, weights, train = _observations(
        roots, frame_indices, targets, valid, weights, train)
    if track_active is not None:
        active = np.asarray(track_active)
        if active.shape != (len(roots),) or active.dtype != bool:
            raise ValueError('Explicit track_active boolean[T] required')
        valid = valid & active[ids]
        if (valid & train).sum() < 3:
            raise ValueError('At least three active supported training rows required')
    use = valid & train
    x, y, w = roots[ids[use]], target[use], weights[use]
    anchor = np.average(x, axis=0, weights=w)
    spread = float(np.sqrt(np.average(np.sum((x - anchor) ** 2, axis=1), weights=w)))
    if fit_scale and spread < 0.03:
        raise ValueError('Trajectory scale is unidentifiable for near-stationary training roots')
    if not (0 < scale_bounds[0] < scale_bounds[1] and residual_scale > 0):
        raise ValueError('Positive ordered bounds and residual scale required')
    translation0 = np.median(y - x, axis=0)

    def unpack(p):
        return (float(np.exp(p[0])), p[1:]) if fit_scale else (1.0, p)

    def residual(p):
        scale, translation = unpack(p)
        predicted = anchor + scale * (x - anchor) + translation
        return ((predicted - y) * np.sqrt(w[:, None])).ravel()

    p0 = np.r_[0.0, translation0] if fit_scale else translation0
    bounds = (np.r_[np.log(scale_bounds[0]), [-np.inf] * 3],
              np.r_[np.log(scale_bounds[1]), [np.inf] * 3]) if fit_scale else (-np.inf, np.inf)
    fit = least_squares(residual, p0, bounds=bounds, loss='soft_l1',
                        f_scale=residual_scale, max_nfev=500,
                        xtol=1e-11, ftol=1e-11, gtol=1e-11)
    scale, translation = unpack(fit.x)
    corrected = anchor + scale * (roots - anchor) + translation
    errors = np.linalg.norm(corrected[ids] - target, axis=1)
    report = {'trajectory_scale': scale, 'body_scale': 1.0,
              'anchor': anchor.tolist(), 'translation': translation.tolist(),
              'training_root_rms_radius_m': spread, 'optimizer_success': bool(fit.success),
              'train': distance_stats(errors[valid & train]),
              'heldout': distance_stats(errors[valid & ~train]),
              'scale_at_bound': bool(fit_scale and min(abs(scale - scale_bounds[0]), abs(scale - scale_bounds[1])) < 1e-4),
              'source_frame_indices': ids.tolist(), 'train_row_mask': train.tolist(),
              'valid_row_mask': valid.tolist(), 'parameter_count': 4 if fit_scale else 3,
              'objective': 'training-only soft_l1 3D estimated-root residual',
              'contact_accepted': False, 'metric_scale_validated': False}
    return corrected, report


def move_fixed_size_body(vertices, joints, corrected_roots):
    """Apply one translation per frame; preserve all body-relative geometry."""
    vertices, joints, corrected_roots = (np.asarray(v) for v in (vertices, joints, corrected_roots))
    if vertices.ndim != 3 or joints.ndim != 3 or vertices.shape[0] != joints.shape[0] or vertices.shape[-1] != 3 or joints.shape[-1] != 3:
        raise ValueError('Expected matching vertices[T,V,3] and joints[T,J,3]')
    if corrected_roots.shape != (len(vertices), 3) or not all(np.isfinite(v).all() for v in (vertices, joints, corrected_roots)):
        raise ValueError('Finite full-timeline geometry and roots required')
    offsets = corrected_roots.astype(float) - joints[:, 0].astype(float)
    return vertices.astype(float) + offsets[:, None], joints.astype(float) + offsets[:, None], offsets


# Only arrays whose meaning survives a room-space root translation remain
# authoritative. Every other source field is retained as explicit provenance.
STABLE_BODY_FIELDS = frozenset({
    'schema_version', 'faces', 'vertex_ids', 'time_seconds', 'fps', 'body_scale',
    'surface_model_type', 'joint_names', 'body_joint_names', 'foot_names',
    'left_vertex_ids', 'right_vertex_ids', 'lbs_weights', 'image_size',
    'source_video_sha256', 'source_actor_id', 'room_basis_sha256', 'motion_source',
    'body_pose', 'betas', 'interval_start_seconds', 'interval_end_seconds',
    'reviewed_stationary', 'track_active', 'source_frame_indices',
    'track_lifecycle_sha256', 'track_lifecycle_json',
})


def candidate_metadata(body):
    """Keep fixed anatomy/identity; archive all source world geometry and metrics.

    Bare native-ground transl/global_orient and derived foot/body arrays must
    not masquerade as corrected output. Unknown fields are archived too, so a
    new cached world-space field cannot silently bypass this policy.
    """
    result, archived = {}, []
    for key, value in body.items():
        if key in ('vertices', 'joints'):
            continue  # Replaced by corrected arrays after this metadata pass.
        stable = key in STABLE_BODY_FIELDS or key.startswith(('source_native__', 'original_input__'))
        target = key if stable else 'original_input__' + key
        if target in result:
            raise ValueError('Source provenance name collision: ' + target)
        result[target] = value
        if target != key:
            archived.append(key)
    return result, sorted(archived)


def validate_binding(body, obs, body_path):
    from tools.gvhmr.root_constraints import active_mask, observation_masks, sha256
    if 'body_scale' not in body or np.asarray(body['body_scale']).shape != () or float(body['body_scale']) != 1.0:
        raise ValueError('An explicitly unscaled body is required')
    active_mask(body)
    for key in ('source_video_sha256', 'source_actor_id', 'room_basis_sha256'):
        if key not in body or key not in obs or str(body[key]) != str(obs[key]):
            raise ValueError('Missing/mismatched source binding: ' + key)
    body_hash = sha256(body_path)
    if 'source_body_sha256' not in obs or str(obs['source_body_sha256']) != body_hash:
        raise ValueError('Depth observations are not bound to this exact source body')
    observation_masks(body, obs)
    ids = obs['frame_indices']
    if np.asarray(obs['time_seconds']).shape != ids.shape or not np.allclose(body['time_seconds'][ids], obs['time_seconds'], atol=1e-8, rtol=0):
        raise ValueError('Observation times differ from body source frames')
    return body_hash


def _depth_report(body, obs):
    from tools.gvhmr.root_constraints import observation_masks
    train, heldout = observation_masks(body, obs)
    errors = np.linalg.norm(body['joints'][obs['frame_indices'], 0] - obs['root_targets'], axis=1)
    return {'train': distance_stats(errors[train]), 'heldout': distance_stats(errors[heldout]),
            'heldout_scope': 'Conditional on the supplied frozen scene/cameras/body and source review; no independent depth ground truth'}


def _write_body(output, body, roots, report, parent_path, original_hash, stage_index=None):
    from tools.gvhmr.root_constraints import sha256, active_mask
    v, j, offsets = move_fixed_size_body(body['vertices'], body['joints'], roots)
    if stage_index is None:
        metadata, archived = candidate_metadata(body)
    else:
        metadata, archived = {}, []
        for key, value in body.items():
            if key in ('vertices', 'joints'):
                continue
            stable = key in STABLE_BODY_FIELDS or key.startswith(('source_native__', 'original_input__', 'stage_input_'))
            target = key if stable else f'stage_input_{stage_index:02d}__' + key
            if target in metadata:
                raise ValueError('Stage provenance collision: ' + target)
            metadata[target] = value
            if target != key:
                archived.append(key)
    result = dict(metadata, vertices=v.astype('f4'), joints=j.astype('f4'), trajectory_offsets=offsets,
                  body_scale=np.asarray(1.), trajectory_parent_body_sha256=np.asarray(sha256(parent_path)),
                  trajectory_original_body_sha256=np.asarray(original_hash),
                  trajectory_offsets_semantics=np.asarray('Add once to immediate parent mesh/joints; no body scaling; inactive storage rows are not motion estimates'))
    if 'trajectory_scale' in report:
        result['trajectory_scale'] = np.asarray(report['trajectory_scale'])
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / 'body_room.npz', **result)
    saved = dict(np.load(output / 'body_room.npz', allow_pickle=False))
    report['archived_source_fields'] = sorted(archived)
    report['saved_body_relative_vertex_error_m'] = float(np.abs(
        (saved['vertices'].astype(float) - saved['joints'][:, :1].astype(float))
        - (body['vertices'].astype(float) - body['joints'][:, :1].astype(float))).max())
    report['saved_body_relative_joint_error_m'] = float(np.abs(
        (saved['joints'].astype(float) - saved['joints'][:, :1].astype(float))
        - (body['joints'].astype(float) - body['joints'][:, :1].astype(float))).max())
    report['saved_pelvis_target_error_m'] = float(np.abs(saved['joints'][:, 0] - roots).max())
    report['body_relative_geometry_gate_m'] = 2e-6
    report['body_relative_geometry_passed'] = max(report['saved_body_relative_vertex_error_m'], report['saved_body_relative_joint_error_m']) <= 2e-6
    report['active_frame_count'] = int(active_mask(saved).sum())
    report['inactive_frame_count'] = int((~active_mask(saved)).sum())
    report['body_scale'] = 1.
    report['native_parameters_semantics'] = 'Original input provenance only; corrected mesh, joints and immediate-parent trajectory offsets are authoritative'
    report['output_sha256'] = sha256(output / 'body_room.npz')
    return saved


def run_workflow(body_path, observation_path, output, workflow_path):
    from tools.gvhmr.root_constraints import (active_mask, sha256, load_contacts, fit_smooth_residual,
                                             fit_constant_contact, vertical_origin, contact_metrics)
    body_path, observation_path, output, workflow_path = map(Path, (body_path, observation_path, output, workflow_path))
    original = dict(np.load(body_path, allow_pickle=False))
    obs = dict(np.load(observation_path, allow_pickle=False))
    original_hash = validate_binding(original, obs, body_path)
    protocol = json.loads(workflow_path.read_text())
    if protocol.get('schema_version') != 1 or protocol.get('source_body_sha256') != original_hash or protocol.get('observations_sha256') != sha256(observation_path):
        raise ValueError('Workflow must bind the exact initial body and observations')
    contacts, contact_declaration = [], None
    if protocol.get('contacts_file'):
        contact_path = (workflow_path.parent / protocol['contacts_file']).resolve()
        contacts, contact_declaration = load_contacts(contact_path, original, original_hash)
    scene_constraints = None
    if protocol.get('scene_constraints_file'):
        from tools.gvhmr.full_scene_constraints import load_scene_constraints
        scene_path = (workflow_path.parent / protocol['scene_constraints_file']).resolve()
        scene_constraints = load_scene_constraints(scene_path, original, original_hash)
    names = [s['name'] for s in protocol['stages']]
    if not names or len(set(names)) != len(names) or any(not name.replace('_', '').isalnum() for name in names):
        raise ValueError('Unique simple stage names required')
    output.mkdir(parents=True, exist_ok=False)
    stages, current, parent_path = [], original, body_path
    for index, stage in enumerate(protocol['stages']):
        start = time.perf_counter()
        method, options = stage['method'], dict(stage.get('options', {}))
        roots = np.asarray(current['joints'][:, 0], float)
        if method == 'scale_translation':
            roots, report = fit_trajectory(roots, obs['frame_indices'], obs['root_targets'], obs['valid'],
                                           obs['weights'], obs['train'], track_active=active_mask(current), **options)
        elif method in ('smooth_residual', 'smooth_contact', 'smooth_scene_contact'):
            if method == 'smooth_contact' and not contacts:
                raise ValueError('smooth_contact requires reviewed contact constraints')
            if method == 'smooth_scene_contact' and scene_constraints is None:
                raise ValueError('smooth_scene_contact requires frozen scene_constraints_file')
            offsets, report = fit_smooth_residual(current, obs, contacts=contacts if method != 'smooth_residual' else (),
                                                   scene_constraints=scene_constraints if method == 'smooth_scene_contact' else None, **options)
            roots = roots + offsets
        elif method == 'constant_contact':
            offsets, report = fit_constant_contact(current, contacts)
            roots = roots + offsets
        elif method == 'vertical_offset':
            amount = float(options['offset_z_m'])
            if not np.isfinite(amount):
                raise ValueError('Finite explicit vertical offset required')
            roots[:, 2] += amount
            report = dict(method=method, offset_z_m=amount, training_frame_indices=[],
                          scope='Explicit user-supplied constant vertical translation; no fitted floor claim')
        elif method == 'vertical_origin':
            offsets, report = vertical_origin(current, obs, options)
            roots = roots + offsets
        else:
            raise ValueError('Unsupported root-only stage: ' + method)
        active = active_mask(current)
        delta = roots - current['joints'][:, 0].astype(float)
        dt = np.diff(current['time_seconds'])
        velocity = np.diff(delta, axis=0) / dt[:, None]
        acceleration = np.diff(velocity, axis=0) / ((dt[1:] + dt[:-1]) * .5)[:, None]
        report.setdefault('max_added_velocity_m_s', float(np.linalg.norm(velocity[active[1:] & active[:-1]], axis=1).max()) if active.sum() > 1 else 0.)
        report.setdefault('max_added_acceleration_m_s2', float(np.linalg.norm(acceleration[active[2:] & active[1:-1] & active[:-2]], axis=1).max()) if active.sum() > 2 else 0.)
        report.setdefault('max_root_offset_m', float(np.linalg.norm(delta[active], axis=1).max()))
        report.update(stage=stage['name'], method=method, input_parent_sha256=sha256(parent_path),
                      metric_scale_validated=False, source_motion_accuracy_validated=False)
        out = output / stage['name']
        current = _write_body(out, current, roots, report, parent_path, original_hash, index)
        report.update(_depth_report(current, obs))
        report['contacts'] = contact_metrics(current, contacts) if contacts else []
        if scene_constraints is not None:
            from tools.gvhmr.full_scene_constraints import save_scene_metrics, save_contact_series
            scene_report = save_scene_metrics(out, current, scene_constraints)
            report['scene_constraints'] = {k: v for k, v in scene_report.items() if k != 'rows'}
            save_contact_series(out, current, contacts, scene_constraints, report['contacts'])
        limits = stage.get('limits', {})
        allowed_limits = {'max_added_velocity_m_s', 'max_added_acceleration_m_s2', 'max_root_offset_m'}
        if set(limits) - allowed_limits:
            raise ValueError('Unknown engineering limit')
        report['engineering_limits'] = limits
        report['engineering_limits_passed'] = all(key in report and np.isfinite(value) and value >= 0 and report[key] <= value for key, value in limits.items())
        report['contact_constraints_passed'] = all(c['accepted'] for c in report['contacts']) if contacts else None
        report['accepted'] = bool(report['body_relative_geometry_passed'] and report.get('optimizer_success', True)
                                  and not report.get('scale_at_bound', False) and report['engineering_limits_passed']
                                  and (not contacts or report['contact_constraints_passed'])
                                  and (scene_constraints is None or scene_report['accepted']))
        report['acceptance_scope'] = 'Declared geometry, numerical and finite-contact gates only; a passing fit is not source-motion or scene truth'
        report['wall_seconds'] = time.perf_counter() - start
        (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        stages.append(dict(name=stage['name'], method=method, body=str((out / 'body_room.npz').resolve()),
                           report=str((out / 'report.json').resolve()), accepted=report['accepted'],
                           output_sha256=report['output_sha256'], train=report['train'], heldout=report['heldout']))
        parent_path = out / 'body_room.npz'
    summary = dict(schema_version=1, stages=stages, final_accepted=stages[-1]['accepted'],
                   input_hashes={str(p.resolve()): sha256(p) for p in (body_path, observation_path, workflow_path, Path(__file__), Path(__file__).with_name('root_constraints.py'))},
                   contact_manifest=contact_declaration, body_scale=1., diagnostic_candidates_retained=True,
                   contact_priority='Every later stage rechecks declared finite contacts; vertical floor shifts can conflict and remain rejected diagnostics')
    if scene_constraints is not None:
        summary['input_hashes'].update({str(Path(scene_constraints[key])): sha256(scene_constraints[key]) for key in ('path', 'geometry_path', 'source_blend')})
        helper = Path(__file__).with_name('full_scene_constraints.py')
        summary['input_hashes'][str(helper.resolve())] = sha256(helper)
    if contacts:
        summary['input_hashes'][str(contact_path)] = sha256(contact_path)
        for c in contacts:
            summary['input_hashes'][c['surface_path']] = sha256(c['surface_path'])
    (output / 'report.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body', type=Path, required=True)
    p.add_argument('--observations', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--translation-only', action='store_true')
    p.add_argument('--workflow', type=Path, help='Source-bound ordered stage protocol JSON; overrides the legacy single-fit mode')
    a = p.parse_args()
    if a.workflow:
        if a.translation_only:
            p.error('Set fit_scale:false in the workflow instead of --translation-only')
        print(json.dumps(run_workflow(a.body, a.observations, a.output, a.workflow), indent=2))
        return
    from tools.gvhmr.root_constraints import active_mask, sha256
    body = dict(np.load(a.body, allow_pickle=False))
    obs = dict(np.load(a.observations, allow_pickle=False))
    body_hash = validate_binding(body, obs, a.body)
    corrected, report = fit_trajectory(body['joints'][:, 0], obs['frame_indices'], obs['root_targets'],
                                      obs['valid'], obs['weights'], obs['train'],
                                      fit_scale=not a.translation_only, track_active=active_mask(body))
    _write_body(a.output, body, corrected, report, a.body, body_hash)
    report['input_hashes'] = {str(q.resolve()): sha256(q) for q in (a.body, a.observations, Path(__file__))}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
