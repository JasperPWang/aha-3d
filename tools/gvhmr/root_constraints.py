"""Fixed-body root corrections with explicit training support and finite contacts.

Room coordinates are right handed and Z-up. Units are the input room's nominal
metres. A passed contact gate concerns only the declared body patch and finite
surface; it does not certify whole-body collision freedom or measured contact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import least_squares


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def active_mask(body):
    count = len(body['time_seconds'])
    active = np.asarray(body.get('track_active', np.ones(count, bool)))
    if active.shape != (count,) or active.dtype != bool or not active.any():
        raise ValueError('track_active must be boolean[T] with an active prefix')
    if np.any(np.diff(active.astype(int)) > 0) or not active[0]:
        raise ValueError('Only an active prefix followed by terminal inactivity is supported')
    ids = np.asarray(body.get('source_frame_indices', np.arange(count)))
    if ids.shape != (count,) or ids.dtype.kind not in 'iu' or not np.array_equal(ids, np.arange(count)):
        raise ValueError('Full source_frame_indices must enumerate the retained full timeline')
    times = np.asarray(body['time_seconds'], float)
    if not np.isfinite(times).all() or (np.diff(times) <= 0).any():
        raise ValueError('Finite strictly increasing full source times required')
    return active


def observation_masks(body, obs):
    ids = np.asarray(obs['frame_indices'])
    if ids.dtype.kind not in 'iu' or ids.ndim != 1 or len(ids) == 0 or ids.min() < 0 or ids.max() >= len(body['time_seconds']) or (np.diff(ids) <= 0).any():
        raise ValueError('Unique increasing observation frame indices required')
    valid, train = np.asarray(obs['valid']), np.asarray(obs['train'])
    w = np.asarray(obs['weights'], float)
    target = np.asarray(obs['root_targets'], float)
    if valid.dtype != bool or train.dtype != bool or valid.shape != ids.shape or train.shape != ids.shape or w.shape != ids.shape or target.shape != (len(ids), 3):
        raise ValueError('Invalid observation schema')
    if not np.isfinite(w).all() or (w < 0).any() or not np.isfinite(target[valid]).all():
        raise ValueError('Nonfinite observations or negative weights')
    eligible = valid & (w > 0) & active_mask(body)[ids]
    return eligible & train, eligible & ~train


def frames_mask(intervals, count):
    mask = np.zeros(count, bool)
    for interval in intervals:
        if len(interval) != 2 or any(not isinstance(x, (int, np.integer)) for x in interval):
            raise ValueError('Intervals must be integer half-open source-frame pairs')
        start, end = interval
        if not 0 <= start < end <= count:
            raise ValueError('Interval outside retained timeline')
        mask[start:end] = True
    return mask


def event_strength(intervals, count, ramp_frames=0):
    """Raised-cosine objective strength; acceptance still checks the entire event."""
    strength = frames_mask(intervals, count).astype(float)
    if ramp_frames:
        for start, end in intervals:
            phase = np.minimum(np.arange(end - start), np.arange(end - start)[::-1]) / ramp_frames
            strength[start:end] = np.maximum(0., .5 - .5 * np.cos(np.pi * np.clip(phase, 0, 1)))
    return strength


def _ids(values, limit, label):
    a = np.asarray(values)
    if a.ndim != 1 or not len(a) or a.dtype.kind not in 'iu' or len(np.unique(a)) != len(a) or a.min() < 0 or a.max() >= limit:
        raise ValueError('Invalid ' + label)
    return a


def closest_surface(points, vertices, faces):
    """Exact Euclidean point/triangle distances, including edges and vertices."""
    points = np.asarray(points, float)
    triangles = np.asarray(vertices, float)[faces]
    best = np.full(len(points), np.inf)
    closest = np.zeros_like(points)
    # Triangle loop bounds memory for source-shaped hand patches and body meshes.
    for a, b, c in triangles:
        ab, ac = b - a, c - a
        normal = np.cross(ab, ac)
        nn = normal @ normal
        if nn < 1e-20:
            raise ValueError('Degenerate surface triangle')
        projected = points - (((points - a) @ normal) / nn)[:, None] * normal
        v0 = projected - a
        d00, d01, d11 = ab @ ab, ab @ ac, ac @ ac
        denominator = d00 * d11 - d01 * d01
        u = ((v0 @ ab) * d11 - (v0 @ ac) * d01) / denominator
        v = ((v0 @ ac) * d00 - (v0 @ ab) * d01) / denominator
        inside = (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10)
        candidates = [projected]
        for e0, e1 in ((a, b), (b, c), (c, a)):
            edge = e1 - e0
            ratio = np.clip((points - e0) @ edge / (edge @ edge), 0, 1)
            candidates.append(e0 + ratio[:, None] * edge)
        for i, q in enumerate(candidates):
            distance = np.linalg.norm(points - q, axis=1)
            if i == 0:
                distance[~inside] = np.inf
            take = distance < best
            best[take], closest[take] = distance[take], q[take]
    return best, closest


def load_contacts(path, body, source_body_hash):
    """Load reviewed finite geometry and immutable contact cohorts.

    JSON binds source video, actor, room basis and exact initial body. Each contact
    declares intervals, train_frame_indices, landmark kind/indices, a surface NPZ
    and hash, unit outward plane normal/offset, target gap, and acceptance limits.
    Surface NPZ has vertices[M,3], faces[F,3]; convex planes are optional for solid
    penetration (keys convex_planes_0,..., outward n.x+d <=0 inside). Without
    solids the complete mesh must be coplanar with the declared finite plane.
    """
    path = Path(path)
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or data.get('source_body_sha256') != source_body_hash:
        raise ValueError('Contact manifest must bind the exact initial body')
    for key in ('source_video_sha256', 'source_actor_id', 'room_basis_sha256'):
        if data.get(key) != str(body[key]):
            raise ValueError('Contact source binding mismatch: ' + key)
    if not data.get('reviewed_by') or not data.get('review_scope'):
        raise ValueError('Explicit source contact review provenance required')
    result = []
    for declaration in data['contacts']:
        c = dict(declaration)
        normal = np.asarray(c['plane_normal'], float)
        if normal.shape != (3,) or not np.isfinite(normal).all() or abs(np.linalg.norm(normal) - 1) > 1e-7:
            raise ValueError('Contact plane normal must be unit length')
        c['normal'] = normal
        c['plane_offset'] = float(c['plane_offset'])
        if not np.isfinite(c['plane_offset']):
            raise ValueError('Nonfinite contact plane')
        kind = c['landmark']['kind']
        if kind not in ('vertices', 'joints'):
            raise ValueError('Contact landmark must select vertices or joints')
        c['indices'] = _ids(c['landmark']['indices'], body[kind].shape[1], 'landmark indices')
        c['kind'] = kind
        c['event_mask'] = frames_mask(c['intervals'], len(body['time_seconds'])) & active_mask(body)
        c['diagnostic_mask'] = frames_mask(c.get('diagnostic_intervals', []), len(body['time_seconds'])) & active_mask(body)
        train = _ids(c['train_frame_indices'], len(c['event_mask']), 'contact training frames')
        if not c['event_mask'][train].all():
            raise ValueError('Every contact training frame must be reviewed and active')
        ramp = c.get('ramp_frames', 0)
        if not isinstance(ramp, int) or ramp < 0:
            raise ValueError('ramp_frames must be a nonnegative integer')
        c['frame_strength'] = event_strength(c['intervals'], len(c['event_mask']), ramp)
        c['train_ids'] = np.sort(train)
        c['heldout_ids'] = np.flatnonzero(c['event_mask'] & ~np.isin(np.arange(len(c['event_mask'])), train))
        surface = (path.parent / c['surface_file']).resolve()
        if sha256(surface) != c['surface_sha256']:
            raise ValueError('Contact surface hash mismatch')
        with np.load(surface, allow_pickle=False) as mesh:
            c['vertices'] = np.array(mesh['vertices'], float)
            c['faces'] = np.array(mesh['faces'])
            c['solids'] = [np.array(mesh[k], float) for k in sorted(mesh.files) if k.startswith('convex_planes_')]
        v, f = c['vertices'], c['faces']
        if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all() or f.ndim != 2 or f.shape[1] != 3 or f.dtype.kind not in 'iu' or not f.size or f.min() < 0 or f.max() >= len(v):
            raise ValueError('Finite indexed contact triangle mesh required')
        if c['solids']:
            for planes in c['solids']:
                if planes.ndim != 2 or planes.shape[1] != 4 or len(planes) < 4 or not np.isfinite(planes).all() or np.max(abs(np.linalg.norm(planes[:, :3], axis=1) - 1)) > 1e-6:
                    raise ValueError('Invalid convex supporting planes')
        elif np.max(abs(v @ normal + c['plane_offset'])) > 1e-6:
            raise ValueError('Without convex solids the finite contact mesh must be planar')
        for key in ('target_gap_m', 'max_gap_m', 'max_penetration_m', 'weight'):
            c[key] = float(c[key])
            if not np.isfinite(c[key]) or c[key] < 0 or (key == 'weight' and c[key] == 0):
                raise ValueError('Invalid nonnegative contact limit or weight: ' + key)
        if c.get('plant'):
            plant = c['plant']
            if not plant.get('reviewed_by') or not plant.get('review_scope'):
                raise ValueError('Planted contact requires explicit review, not inferred stance')
            plant_train = _ids(plant.get('train_frame_indices', c['train_ids']), len(c['event_mask']), 'planted training frames')
            if not c['event_mask'][plant_train].all():
                raise ValueError('Planted training frames must be reviewed and active')
            c['plant_train_ids'] = np.sort(plant_train)
            for key in ('weight', 'max_slip_m_s'):
                if not np.isfinite(plant[key]) or plant[key] <= 0:
                    raise ValueError('Positive planted-contact weight and slip limit required')
        c['surface_path'] = str(surface)
        result.append(c)
    if not result:
        raise ValueError('No contact constraints supplied')
    return result, data


def contact_points(body, contact, ids, offsets=None):
    points = np.asarray(body[contact['kind']][ids][:, contact['indices']], float)
    if offsets is not None:
        points = points + np.asarray(offsets)[ids, None]
    return points


def plant_series(body, contact, offsets=None):
    """Static-support speeds on adjacent event frames, keeping point identities.

    The root-only optimizer penalizes centroid speed. That can leave rotational
    sliding, so acceptance also checks the fastest corresponding patch point.
    Neither quantity establishes that a source-video foot was truly planted.
    """
    frames = np.flatnonzero(contact['event_mask'])
    points = contact_points(body, contact, frames, offsets)
    adjacent = np.diff(frames) == 1
    dt = np.diff(np.asarray(body['time_seconds'])[frames])
    centers = points.mean(axis=1)
    centroid = np.linalg.norm(np.diff(centers, axis=0), axis=1) / dt
    vertex = (np.linalg.norm(np.diff(points, axis=0), axis=2) / dt[:, None]).max(axis=1)
    ids = contact.get('plant_train_ids', contact['train_ids'])
    pairs = [[int(a), int(b)] for a, b in zip(ids[:-1], ids[1:])
             if contact['event_mask'][a:b + 1].all()]
    return dict(frame_pairs=np.column_stack((frames[:-1], frames[1:]))[adjacent],
                centroid_speed_m_s=centroid[adjacent], corresponding_point_max_speed_m_s=vertex[adjacent],
                training_endpoint_pairs=pairs)


def contact_metrics(body, contacts, offsets=None):
    reports = []
    for c in contacts:
        rows = []
        for frame in np.flatnonzero(c['event_mask'] | c.get('diagnostic_mask', np.zeros_like(c['event_mask']))):
            points = contact_points(body, c, [frame], offsets)[0]
            distances, _ = closest_surface(points, c['vertices'], c['faces'])
            if c['solids']:
                penetration = np.zeros(len(points))
                for planes in c['solids']:
                    signed = (points @ planes[:, :3].T + planes[:, 3]).max(axis=1)
                    penetration = np.maximum(penetration, np.maximum(0, -signed))
            else:
                signed = points @ c['normal'] + c['plane_offset']
                projection = points - signed[:, None] * c['normal']
                tangential, _ = closest_surface(projection, c['vertices'], c['faces'])
                penetration = np.where(tangential < 1e-7, np.maximum(0, -signed), 0)
            gap_training = bool(frame in c['train_ids'])
            plant_training = bool(c.get('plant') and frame in c.get('plant_train_ids', c['train_ids']))
            cohort = ('training' if gap_training else 'plant_training_only' if plant_training else
                      'heldout_contact_objectives' if c['event_mask'][frame] else 'diagnostic_only')
            rows.append(dict(frame=int(frame), training=gap_training, contact_gap_training=gap_training,
                             plant_endpoint_training=plant_training, any_contact_objective_training=gap_training or plant_training,
                             cohort=cohort, acceptance_cohort=bool(c['event_mask'][frame]),
                             minimum_patch_surface_distance_m=float(distances.min()),
                             maximum_patch_penetration_m=float(penetration.max()),
                             vertices_within_10mm=int((distances <= .01).sum()),
                             minimum_plane_gap_m=float((points @ c['normal'] + c['plane_offset']).min())))
        gated_rows = [r for r in rows if r['acceptance_cohort']]
        max_gap = max((r['minimum_patch_surface_distance_m'] for r in gated_rows), default=None)
        max_pen = max((r['maximum_patch_penetration_m'] for r in gated_rows), default=None)
        accepted = bool(gated_rows and max_gap <= c['max_gap_m'] and max_pen <= c['max_penetration_m'])
        slip_report = None
        if c.get('plant'):
            series = plant_series(body, c, offsets)
            peak = float(series['centroid_speed_m_s'].max()) if len(series['frame_pairs']) else None
            point_peak = float(series['corresponding_point_max_speed_m_s'].max()) if len(series['frame_pairs']) else None
            limit = c['plant']['max_slip_m_s']
            slip_report = dict(max_patch_centroid_speed_m_s=peak, max_corresponding_point_speed_m_s=point_peak,
                               limit_m_s=limit, frame_pair_count=len(series['frame_pairs']),
                               centroid_passed=peak is not None and peak <= limit,
                               corresponding_point_passed=point_peak is not None and point_peak <= limit,
                               gate_version=2, training_endpoint_pairs=series['training_endpoint_pairs'],
                               objective_scope='Selected patch centroid speed; root translation cannot remove source patch rotation',
                               scope='Corresponding selected patch points versus static room; all adjacent active event pairs, including contact/plant heldout endpoints')
            accepted &= point_peak is not None and point_peak <= limit
        reports.append(dict(name=c['name'], accepted=bool(accepted), max_gap_m=max_gap, max_penetration_m=max_pen, plant=slip_report,
                            limits=dict(max_gap_m=c['max_gap_m'], max_penetration_m=c['max_penetration_m']),
                            rows=rows, scope='Declared finite surface and selected patch only; near-vertex count is not contact area'))
    return reports


def fit_constant_contact(body, contacts):
    """One train-only normal translation, preserving every temporal derivative."""
    if len(contacts) != 1:
        raise ValueError('constant_normal supports one contact; use smooth_contact for multiple constraints')
    c = contacts[0]
    if c.get('ramp_frames', 0):
        raise ValueError('constant_contact uses a median; use smooth_contact for objective ramps')
    points = contact_points(body, c, c['train_ids'])
    minimum = (points @ c['normal'] + c['plane_offset']).min(axis=1)
    amount = c['target_gap_m'] - float(np.median(minimum))
    offset = np.broadcast_to(amount * c['normal'], (len(body['time_seconds']), 3)).copy()
    return offset, dict(method='constant_normal', amount_m=amount, translation=offset[0].tolist(),
                        training_frame_indices=c['train_ids'].tolist(), finite_extent_fitted=False,
                        limitation='Plane normal only fit; finite mesh contact acceptance checked separately')


def spline_basis(times, support_frames, spacing):
    times = np.asarray(times, float)
    support = np.asarray(support_frames, int)
    if len(np.unique(support)) < 2 or not np.isfinite(spacing) or spacing <= 0:
        raise ValueError('Two distinct training times and positive knot spacing required')
    lo, hi = times[support.min()], times[support.max()]
    knots = np.r_[np.arange(lo, hi, spacing), hi]
    spline = CubicSpline(knots, np.eye(len(knots)), bc_type=((1, np.zeros(len(knots))), (1, np.zeros(len(knots)))))
    clipped = np.clip(times, lo, hi)
    B, D2 = spline(clipped), spline(clipped, 2)
    inside = (times >= lo) & (times <= hi)
    D2[~inside] = 0
    return B, D2, inside, knots, spline


def fit_smooth_residual(body, obs, *, knot_spacing_seconds=1., acceleration_penalty=.01,
                        offset_penalty=.002, contacts=(), max_nfev=100, scene_constraints=None, max_scene_iterations=120,
                        depth_weight=1.):
    """C1 root correction; depth_weight=0 retains depth only for diagnostics."""
    if acceleration_penalty <= 0 or offset_penalty <= 0:
        raise ValueError('Positive temporal and amplitude regularization required')
    if not np.isfinite(depth_weight) or depth_weight < 0:
        raise ValueError('Finite nonnegative depth_weight required')
    train, heldout = observation_masks(body, obs)
    ids = obs['frame_indices']
    depth_train = train if depth_weight > 0 else np.zeros_like(train)
    support = list(ids[depth_train])
    for c in contacts:
        support.extend(c['train_ids'])
        if c.get('plant'):
            support.extend(c.get('plant_train_ids', c['train_ids']))
    if scene_constraints is not None:
        support.extend(np.flatnonzero(active_mask(body))[[0, -1]])
    B, D2, inside, knots, spline = spline_basis(body['time_seconds'], np.unique(support), knot_spacing_seconds)
    inside &= active_mask(body)
    q = np.asarray(body['joints'][:, 0], float)
    w = np.sqrt(depth_weight * obs['weights'][depth_train] / max(float(obs['weights'][depth_train].sum()), 1e-12))
    A = np.vstack([B[ids[depth_train]] * w[:, None], np.sqrt(acceleration_penalty / inside.sum()) * D2[inside],
                   np.sqrt(offset_penalty / inside.sum()) * B[inside]])
    target = np.vstack([(obs['root_targets'][depth_train] - q[ids[depth_train]]) * w[:, None], np.zeros((2 * inside.sum(), 3))])
    coefficients = np.linalg.lstsq(A, target, rcond=None)[0]
    success, evaluations = True, 0
    scene_optimizer = None
    if scene_constraints is not None:
        from tools.gvhmr.full_scene_constraints import solve_scene_coefficients
        coefficients, scene_optimizer = solve_scene_coefficients(body, scene_constraints, contacts, B, A, target, coefficients, max_iterations=max_scene_iterations)
        success, evaluations = scene_optimizer['optimizer_success'], scene_optimizer['optimizer_evaluations']
    elif contacts:
        def residual(flat):
            coef = flat.reshape(-1, 3)
            chunks = [(A @ coef - target).ravel()]
            for c in contacts:
                points = contact_points(body, c, c['train_ids']) + (B[c['train_ids']] @ coef)[:, None]
                signed = points @ c['normal'] + c['plane_offset']
                closest_index = signed.argmin(axis=1)
                selected = points[np.arange(len(points)), closest_index]
                plane_gap = signed.min(axis=1)
                plane_projected = selected - plane_gap[:, None] * c['normal']
                _, nearest = closest_surface(plane_projected, c['vertices'], c['faces'])
                strength = c.get('frame_strength', np.ones(len(body['time_seconds'])))[c['train_ids']]
                scale = np.sqrt(c['weight'] * strength / len(points))
                chunks.append(scale * (plane_gap - c['target_gap_m']))
                chunks.append((scale[:, None] * (plane_projected - nearest)).ravel())
                if c.get('plant'):
                    train_frames = c.get('plant_train_ids', c['train_ids'])
                    plant_points = contact_points(body, c, train_frames) + (B[train_frames] @ coef)[:, None]
                    centers = plant_points.mean(axis=1)
                    # Never bridge a release interval or use a heldout frame.
                    eligible_pairs = np.array([c['event_mask'][a:b + 1].all() for a, b in zip(train_frames[:-1], train_frames[1:])])
                    if eligible_pairs.any():
                        speed = np.diff(centers, axis=0) / np.diff(body['time_seconds'][train_frames])[:, None]
                        plant_strength = c.get('frame_strength', np.ones(len(body['time_seconds'])))[train_frames]
                        pair_strength = np.minimum(plant_strength[:-1], plant_strength[1:])[eligible_pairs]
                        chunks.append((np.sqrt(c['plant']['weight'] * pair_strength / eligible_pairs.sum())[:, None] * speed[eligible_pairs]).ravel())
            return np.concatenate(chunks)
        fitted = least_squares(residual, coefficients.ravel(), max_nfev=max_nfev, ftol=1e-9, xtol=1e-9, gtol=1e-9)
        coefficients = fitted.x.reshape(-1, 3)
        success, evaluations = bool(fitted.success), int(fitted.nfev)
    offsets = B @ coefficients
    active = active_mask(body)
    report = dict(method='smooth_contact' if contacts else 'smooth_residual', optimizer_success=success,
                  optimizer_evaluations=evaluations, knots_seconds=knots.tolist(), coefficients=coefficients.tolist(),
                  depth_weight=float(depth_weight), training_depth_frames=ids[depth_train].tolist(),
                  diagnostic_depth_frames=ids[train | heldout].tolist(), heldout_depth_frames=ids[heldout].tolist(),
                  contact_training_frames={c['name']: c['train_ids'].tolist() for c in contacts},
                  plant_training_frames={c['name']: c.get('plant_train_ids', c['train_ids']).tolist() for c in contacts if c.get('plant')},
                  knot_spacing_seconds=knot_spacing_seconds, acceleration_penalty=acceleration_penalty,
                  offset_penalty=offset_penalty, max_added_acceleration_m_s2=float(np.linalg.norm(D2[active] @ coefficients, axis=1).max()),
                  max_root_offset_m=float(np.linalg.norm(offsets[active], axis=1).max()),
                  boundary_derivative_max_m_s=float(abs(spline(knots[[0, -1]], 1) @ coefficients).max()),
                  max_added_velocity_m_s=float(np.linalg.norm(spline(np.clip(body['time_seconds'][active], knots[0], knots[-1]), 1) @ coefficients, axis=1).max()),
                  contact_weighting='Optional declared raised-cosine event objective ramp; final gap/penetration/slip gates still inspect all active event frames',
                  boundary='C1: zero residual velocity at support endpoints; constant offsets outside; acceleration may jump',
                  inactive_semantics='Offsets evaluated for storage continuity; inactive frames excluded from fitting and metrics')
    if scene_optimizer is not None:
        report.update(scene_optimizer)
        report['method'] = 'smooth_scene_contact'
    return offsets, report


def vertical_origin(body, obs, config):
    """Constant Z from reviewed support TRAIN rows; no inference of foot plants."""
    if not config.get('reviewed_by') or not config.get('review_scope'):
        raise ValueError('Vertical origin requires an explicit support review')
    selected = _ids(config['vertex_indices'], body['vertices'].shape[1], 'support vertex indices')
    interval = frames_mask(config['intervals'], len(body['time_seconds']))
    train, heldout = observation_masks(body, obs)
    ids = obs['frame_indices'][train & interval[obs['frame_indices']]]
    if len(ids) < 3:
        raise ValueError('At least three active supported training rows required for vertical origin')
    height = np.asarray(body['vertices'][:, selected, 2], float).min(axis=1)
    desired = float(config.get('floor_z_m', 0.)) + float(config.get('target_gap_m', .002))
    if not np.isfinite(desired):
        raise ValueError('Finite floor and gap required')
    amount = desired - float(np.median(height[ids]))
    offsets = np.zeros((len(height), 3)); offsets[:, 2] = amount
    return offsets, dict(method='vertical_origin', offset_z_m=amount, training_frame_indices=ids.tolist(),
                         reviewed_intervals=config['intervals'], review_scope=config['review_scope'],
                         limitation='Constant origin correction under reviewed support assumption; cannot fix sliding or time-varying penetration')
