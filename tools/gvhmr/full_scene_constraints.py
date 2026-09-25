"""Static finite-floor and convex-object constraints on a full active body mesh.

Geometry is never modified. These are vertex-containment checks on explicit
convex components, not a complete triangle/self-intersection collision engine.
All times outside track_active remain NaN in final geometry metrics.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from tools.gvhmr.root_constraints import active_mask, closest_surface, contact_points, plant_series, sha256


def _mesh(archive, prefix):
    vertices = np.asarray(archive[prefix + '__vertices'], float)
    faces = np.asarray(archive[prefix + '__faces'])
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all() or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in 'iu' or not faces.size or faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError('Finite indexed triangle mesh required: ' + prefix)
    return vertices, faces


def load_scene_constraints(path, body, original_body_hash):
    path = Path(path).resolve()
    spec = json.loads(path.read_text())
    if spec.get('schema_version') != 1 or spec.get('source_body_sha256') != original_body_hash:
        raise ValueError('Scene constraints must bind the exact initial body')
    for key in ('source_video_sha256', 'source_actor_id', 'room_basis_sha256'):
        if spec.get(key) != str(body[key]):
            raise ValueError('Scene source binding mismatch: ' + key)
    if spec.get('scope') != 'all_active_vertices' or not spec.get('reviewed_by'):
        raise ValueError('Explicit all_active_vertices scope and geometry reviewer required')
    for key in ('max_floor_penetration_m', 'max_object_penetration_m', 'floor_weight', 'object_weight'):
        if not np.isfinite(spec[key]) or spec[key] < 0 or (key.endswith('weight') and spec[key] == 0):
            raise ValueError('Invalid scene limit or weight: ' + key)
    geometry_path = (path.parent / spec['geometry_file']).resolve()
    if sha256(geometry_path) != spec['geometry_sha256']:
        raise ValueError('Scene geometry archive hash mismatch')
    source_blend = (path.parent / spec['source_blend']).resolve()
    if sha256(source_blend) != spec['source_blend_sha256']:
        raise ValueError('Authored source scene hash mismatch')
    archive = dict(np.load(geometry_path, allow_pickle=False))
    floor_vertices, floor_faces = _mesh(archive, spec['floor']['key'])
    normal = np.asarray(spec['floor']['normal'], float)
    offset = float(spec['floor']['offset'])
    if normal.shape != (3,) or not np.allclose(normal, [0., 0., 1.], atol=1e-8) or not np.isfinite(offset) or np.max(abs(floor_vertices @ normal + offset)) > 1e-6:
        raise ValueError('Current full-scene floor must be a finite horizontal Z-up triangle surface')
    supports = [dict(vertices=floor_vertices, faces=floor_faces, offset=offset, key=spec['floor']['key'])]
    for declaration in spec.get('additional_supports', []):
        v, f = _mesh(archive, declaration['key'])
        n = np.asarray(declaration['normal'], float); d = float(declaration['offset'])
        if n.shape != (3,) or not np.allclose(n, [0., 0., 1.], atol=1e-8) or not np.isfinite(d) or np.max(abs(v @ n + d)) > 1e-6:
            raise ValueError('Additional supports must be finite horizontal Z-up triangle surfaces')
        supports.append(dict(vertices=v, faces=f, offset=d, key=declaration['key']))
    coverage = np.asarray(spec['floor']['coverage_vertex_indices'])
    if coverage.ndim != 1 or coverage.dtype.kind not in 'iu' or not len(coverage) or len(np.unique(coverage)) != len(coverage) or coverage.min() < 0 or coverage.max() >= body['vertices'].shape[1]:
        raise ValueError('Explicit anatomical floor-coverage indices required')
    objects = []
    names = set()
    for definition in spec['objects']:
        name, key = definition['name'], definition['key']
        if name in names:
            raise ValueError('Unique scene object names required')
        names.add(name)
        vertices, faces = _mesh(archive, key)
        planes = np.asarray(archive[key + '__planes'], float)
        if planes.ndim != 2 or planes.shape[1] != 4 or len(planes) < 4 or not np.isfinite(planes).all() or np.max(abs(np.linalg.norm(planes[:, :3], axis=1) - 1)) > 1e-6:
            raise ValueError('Unit outward convex planes required: ' + name)
        tolerance = float(definition.get('convexity_tolerance_m', .0005))
        if tolerance < 0 or tolerance > .0005 or np.max(vertices @ planes[:, :3].T + planes[:, 3]) > tolerance:
            raise ValueError('Scene mesh is not inside its declared convex halfspaces: ' + name)
        # A component is finite and closed: every undirected mesh edge occurs twice.
        edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
        if not np.all(np.unique(edges, axis=0, return_counts=True)[1] == 2):
            raise ValueError('Closed convex object mesh required: ' + name)
        objects.append(dict(name=name, vertices=vertices, faces=faces, planes=planes,
                            lower=vertices.min(axis=0), upper=vertices.max(axis=0), key=key))
    if not objects:
        raise ValueError('At least one explicit non-floor convex component required')
    return dict(spec=spec, path=str(path), geometry_path=str(geometry_path), source_blend=str(source_blend),
                floor_vertices=floor_vertices, floor_faces=floor_faces, floor_normal=normal,
                floor_offset=offset, floor_surfaces=supports, coverage_vertex_indices=coverage, objects=objects)


def floor_inside_xy(points, vertices, faces):
    """Finite floor coverage, including edges; normal projection preserves XY."""
    xy = np.asarray(points)[..., :2]
    inside = np.zeros(xy.shape[:-1], bool)
    for triangle in vertices[faces, :2]:
        a, b, c = triangle
        ab, ac = b - a, c - a
        determinant = ab[0] * ac[1] - ab[1] * ac[0]
        if abs(determinant) < 1e-14:
            raise ValueError('Degenerate finite floor triangle')
        q = xy - a
        u = (q[..., 0] * ac[1] - q[..., 1] * ac[0]) / determinant
        v = (ab[0] * q[..., 1] - ab[1] * q[..., 0]) / determinant
        inside |= (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8)
    return inside


def object_depth(points, component):
    """Deepest body vertex in a convex component and its translation gradient."""
    within = np.all((points >= component['lower']) & (points <= component['upper']), axis=1)
    indices = np.flatnonzero(within)
    if not len(indices):
        return 0., 0, np.zeros(3), -1
    planes = component['planes']
    signed = points[indices] @ planes[:, :3].T + planes[:, 3]
    boundary_plane = signed.argmax(axis=1)
    sdf = signed[np.arange(len(indices)), boundary_plane]
    count = int(np.count_nonzero(sdf < 0))
    deepest = int(sdf.argmin())
    depth = max(0., -float(sdf[deepest]))
    gradient = -planes[boundary_plane[deepest], :3] if depth > 0 else np.zeros(3)
    return depth, count, gradient, int(indices[deepest]) if depth > 0 else -1


def evaluate_scene(body, scene, offsets=None, *, objective=False):
    """Every active frame and every body vertex; optional exact piecewise gradient."""
    active = active_mask(body)
    count = len(active)
    offsets = np.zeros((count, 3)) if offsets is None else np.asarray(offsets, float)
    if offsets.shape != (count, 3) or not np.isfinite(offsets).all():
        raise ValueError('Finite full-timeline root offsets required')
    floor_min = np.full(count, np.nan); floor_pen = floor_min.copy()
    floor_covered = floor_min.copy(); support_outside = floor_min.copy()
    object_pen = np.full((count, len(scene['objects'])), np.nan)
    object_counts = object_pen.copy()
    gradients = np.zeros((count, 3)); total = 0.
    floor_weight = float(scene['spec']['floor_weight']) / active.sum()
    object_weight = float(scene['spec']['object_weight']) / active.sum()
    for frame in np.flatnonzero(active):
        points = np.asarray(body['vertices'][frame], float) + offsets[frame]
        covered = np.zeros(len(points), bool); signed = np.full(len(points), np.inf)
        supports = scene.get('floor_surfaces', [dict(vertices=scene['floor_vertices'], faces=scene['floor_faces'], offset=scene['floor_offset'])])
        for support in supports:
            mask = floor_inside_xy(points, support['vertices'], support['faces'])
            covered |= mask
            signed[mask] = np.minimum(signed[mask], points[mask, 2] + support['offset'])
        floor_covered[frame] = covered.sum()
        support_outside[frame] = np.count_nonzero(~covered[scene['coverage_vertex_indices']])
        if covered.any():
            floor_min[frame] = float(signed[covered].min())
            floor_pen[frame] = max(0., -floor_min[frame])
            if objective:
                # Fit toward zero penetration; thresholds remain independent gates.
                total += floor_weight * floor_pen[frame] ** 2
                gradients[frame, 2] -= 2 * floor_weight * floor_pen[frame]
        lower, upper = points.min(axis=0), points.max(axis=0)
        for index, component in enumerate(scene['objects']):
            # A whole-body AABB rejection is exact for disjoint components.
            # Avoid scanning every vertex for every distant room component.
            if np.any(upper < component['lower']) or np.any(lower > component['upper']):
                object_pen[frame, index] = 0.
                object_counts[frame, index] = 0
                continue
            depth, inside_count, gradient, _ = object_depth(points, component)
            object_pen[frame, index] = depth; object_counts[frame, index] = inside_count
            if objective:
                total += object_weight * depth ** 2
                gradients[frame] += 2 * object_weight * depth * gradient
    arrays = dict(time_seconds=np.asarray(body['time_seconds']), track_active=active,
                  source_frame_indices=np.asarray(body.get('source_frame_indices', np.arange(count))),
                  floor_min_signed_m=floor_min, floor_penetration_m=floor_pen,
                  floor_covered_vertex_count=floor_covered, floor_support_outside_vertex_count=support_outside,
                  object_max_penetration_m=object_pen, object_inside_vertex_count=object_counts,
                  object_names=np.asarray([c['name'] for c in scene['objects']]))
    if objective:
        return total, gradients
    return arrays


def scene_report(arrays, scene):
    active = arrays['track_active']
    spec = scene['spec']
    floor = arrays['floor_penetration_m'][active]
    objects = arrays['object_max_penetration_m'][active]
    support_outside = arrays['floor_support_outside_vertex_count'][active]
    complete = bool(np.isfinite(floor).all() and np.isfinite(objects).all())
    maximum_floor = float(np.nanmax(floor)) if np.isfinite(floor).any() else None
    maximum_object = float(np.nanmax(objects)) if np.isfinite(objects).any() else None
    accepted = bool(complete and maximum_floor <= spec['max_floor_penetration_m'] and maximum_object <= spec['max_object_penetration_m'] and not np.any(support_outside))
    rows = []
    for frame in range(len(active)):
        row = dict(source_frame=int(arrays['source_frame_indices'][frame]), time_seconds=float(arrays['time_seconds'][frame]), active=bool(active[frame]))
        if active[frame]:
            row.update(floor_min_signed_m=float(arrays['floor_min_signed_m'][frame]) if np.isfinite(arrays['floor_min_signed_m'][frame]) else None,
                       floor_penetration_m=float(arrays['floor_penetration_m'][frame]) if np.isfinite(arrays['floor_penetration_m'][frame]) else None,
                       floor_support_outside_vertex_count=int(arrays['floor_support_outside_vertex_count'][frame]),
                       object_max_penetration_m=arrays['object_max_penetration_m'][frame].tolist(),
                       object_inside_vertex_count=arrays['object_inside_vertex_count'][frame].astype(int).tolist())
        rows.append(row)
    return dict(schema_version=1, accepted=accepted, active_frames=int(active.sum()), inactive_frames=int((~active).sum()),
                max_floor_penetration_m=maximum_floor, max_object_penetration_m=maximum_object,
                floor_frames_over_limit=int(np.count_nonzero(floor > spec['max_floor_penetration_m'])),
                object_frames_over_limit=int(np.count_nonzero(np.max(objects, axis=1) > spec['max_object_penetration_m'])),
                floor_support_outside_frames=int(np.count_nonzero(support_outside)),
                limits=dict(max_floor_penetration_m=spec['max_floor_penetration_m'], max_object_penetration_m=spec['max_object_penetration_m']),
                object_names=arrays['object_names'].tolist(), rows=rows,
                scope='All active frames and all source-shaped body vertices against frozen finite floor and listed convex components',
                exclusions=spec.get('exclusions', []) + ['Vertex containment omits triangle-only crossings and self-intersection.', 'An accepted scene guard is not measured source contact or complete scene collision safety.'],
                input_hashes={scene['path']: sha256(scene['path']), scene['geometry_path']: sha256(scene['geometry_path']), scene['source_blend']: sha256(scene['source_blend'])})


def save_scene_metrics(folder, body, scene, *, body_cache_path=None):
    folder = Path(folder)
    arrays = evaluate_scene(body, scene)
    np.savez_compressed(folder / 'scene_metrics.npz', **arrays)
    report = scene_report(arrays, scene)
    report.update(source_video_sha256=str(body['source_video_sha256']), actor_id=str(body['source_actor_id']),
                  room_basis_sha256=str(body['room_basis_sha256']), scene_sha256=sha256(scene['source_blend']),
                  scene_geometry_sha256=sha256(scene['geometry_path']))
    cache = Path(body_cache_path) if body_cache_path is not None else folder / 'body_room.npz'
    report['body_cache_sha256'] = sha256(cache)
    report['body_cache_path'] = str(cache.resolve())
    report['metrics_sha256'] = sha256(folder / 'scene_metrics.npz')
    (folder / 'scene_metrics.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def solve_scene_coefficients(body, scene, contacts, B, A, target, initial_coefficients, *, max_iterations=120, foot_contacts=None, collision_correction=False):
    """Fit smooth whole-body translations; preserve every source joint rotation.

    Contact-only is the source-human default. Collision checks remain diagnostic;
    the explicit collision_correction switch is for historical experiment replay.
    """
    ncoef = len(initial_coefficients)
    history = []
    calls = 0
    def objective(flat):
        nonlocal calls
        calls += 1
        coefficient = flat.reshape(ncoef, 3)
        residual = A @ coefficient - target
        value = float(np.sum(residual ** 2)); gradient = 2 * A.T @ residual
        for c in contacts:
            ids = c['train_ids']
            points = contact_points(body, c, ids) + (B[ids] @ coefficient)[:, None]
            signed = points @ c['normal'] + c['plane_offset']
            selected = points[np.arange(len(ids)), signed.argmin(axis=1)]
            gap = signed.min(axis=1)
            projected = selected - gap[:, None] * c['normal']
            _, nearest = closest_surface(projected, c['vertices'], c['faces'])
            strength = c.get('frame_strength', np.ones(len(B)))[ids]
            w = c['weight'] * strength / len(ids)
            tangent = projected - nearest
            diff = gap - c['target_gap_m']
            value += float(np.sum(w * (diff ** 2 + np.sum(tangent ** 2, axis=1))))
            tangent -= (tangent @ c['normal'])[:, None] * c['normal']
            point_gradient = 2 * w[:, None] * (diff[:, None] * c['normal'] + tangent)
            gradient += B[ids].T @ point_gradient
            if c.get('plant'):
                ids = c.get('plant_train_ids', c['train_ids'])
                if len(ids) > 1:
                    centers = contact_points(body, c, ids).mean(axis=1) + B[ids] @ coefficient
                    eligible = np.array([c['event_mask'][a:b + 1].all() for a, b in zip(ids[:-1], ids[1:])])
                    if eligible.any():
                        dt = np.diff(body['time_seconds'][ids])
                        derivative = (B[ids[1:]] - B[ids[:-1]]) / dt[:, None]
                        speed = np.diff(centers, axis=0) / dt[:, None]
                        strength = c.get('frame_strength', np.ones(len(B)))[ids]
                        w = c['plant']['weight'] * np.minimum(strength[:-1], strength[1:])[eligible] / eligible.sum()
                        value += float(np.sum(w[:, None] * speed[eligible] ** 2))
                        gradient += derivative[eligible].T @ (2 * w[:, None] * speed[eligible])
        if foot_contacts is not None:
            from tools.gvhmr.foot_contacts import objective as foot_objective
            foot_value, foot_gradient = foot_objective(foot_contacts, B @ coefficient)
            value += foot_value; gradient += B.T @ foot_gradient
        if collision_correction:
            scene_value, per_frame_gradient = evaluate_scene(body, scene, B @ coefficient, objective=True)
            value += scene_value; gradient += B.T @ per_frame_gradient
        return value, gradient.ravel()
    initial_value, _ = objective(initial_coefficients.ravel())
    def callback(flat):
        history.append(float(np.linalg.norm(flat)))
    fitted = minimize(objective, initial_coefficients.ravel(), method='L-BFGS-B', jac=True, callback=callback,
                      options=dict(maxiter=max_iterations, ftol=1e-11, gtol=1e-7, maxls=30))
    return fitted.x.reshape(ncoef, 3), dict(optimizer_success=bool(fitted.success), optimizer_message=str(fitted.message),
        optimizer_iterations=int(fitted.nit), optimizer_evaluations=calls, initial_objective=initial_value,
        final_objective=float(fitted.fun), collision_correction=bool(collision_correction),
        objective='TRAIN depth/contact and temporal translation regularization' + (' plus full-mesh containment' if collision_correction else '; collision diagnostics only; source pose fixed'),
        geometric_support_scope='Full active prefix; no new observed trajectory claimed outside source depth support')


def save_contact_series(folder, body, contacts, scene, contact_reports, *, body_cache_path=None):
    """Source-indexed selected-contact series alongside the global scene checks."""
    folder = Path(folder); count = len(body['time_seconds']); n = len(contacts)
    gap = np.full((count, n), np.nan); penetration = gap.copy(); slip = gap.copy(); point_slip = gap.copy()
    cohort = np.zeros((count, n), np.int8); descriptors = []
    gap_train = np.zeros((count, n), bool); plant_train = gap_train.copy(); event = gap_train.copy()
    for index, (contact, report) in enumerate(zip(contacts, contact_reports)):
        gap_train[contact['train_ids'], index] = True
        event[:, index] = contact['event_mask']
        if contact.get('plant'):
            plant_train[contact.get('plant_train_ids', contact['train_ids']), index] = True
        for row in report['rows']:
            f = row['frame']; gap[f, index] = row['minimum_patch_surface_distance_m']; penetration[f, index] = row['maximum_patch_penetration_m']
            cohort[f, index] = {'training': 1, 'heldout_contact_objectives': 2, 'diagnostic_only': 3, 'plant_training_only': 4}[row['cohort']]
        event_ids = np.flatnonzero(contact['event_mask'])
        ending_ids = np.empty(0, int)
        if contact.get('plant'):
            series = plant_series(body, contact)
            ending_ids = series['frame_pairs'][:, 1]
            slip[ending_ids, index] = series['centroid_speed_m_s']
            point_slip[ending_ids, index] = series['corresponding_point_max_speed_m_s']
        for field, kind, label, values, limit in [('contact_gap_m', 'contact_gap', 'minimum patch gap', gap[:, index], contact['max_gap_m']),
                                          ('contact_penetration_m', 'contact_penetration', 'maximum patch penetration', penetration[:, index], contact['max_penetration_m']),
                                          ('contact_slip_m_s', 'slip', 'patch centroid speed only', slip[:, index], contact.get('plant', {}).get('max_slip_m_s')),
                                          ('contact_point_slip_m_s', 'slip', 'maximum corresponding patch-point speed', point_slip[:, index], contact.get('plant', {}).get('max_slip_m_s'))]:
            frames = np.flatnonzero(np.isfinite(values))
            if not len(frames):
                continue
            acceptance_ids = ending_ids if kind == 'slip' else event_ids
            descriptors.append(dict(id=contact['name'] + '__' + field, label=contact['name'] + ': ' + label, unit='m/s' if kind == 'slip' else 'm',
                                    field=field, column=index, source_frames=frames.tolist(), max_value=float(values[frames].max()), kind=kind,
                                    threshold=limit, acceptance_source_frames=acceptance_ids.tolist(),
                                    temporal_semantics='adjacent_event_pair_ending_frame' if kind == 'slip' else 'source_frame',
                                    review_scope='Declared source-reviewed hypothesis only; diagnostic-only wider intervals are not acceptance observations'))
    arrays = dict(time_seconds=body['time_seconds'], track_active=active_mask(body), source_frame_indices=body.get('source_frame_indices', np.arange(count)),
                  contact_names=np.asarray([c['name'] for c in contacts], dtype=str), contact_gap_m=gap,
                  contact_penetration_m=penetration, contact_slip_m_s=slip, contact_point_slip_m_s=point_slip, contact_cohort=cohort,
                  contact_gap_train_mask=gap_train, plant_train_endpoint_mask=plant_train,
                  union_constraint_train_mask=gap_train | plant_train, contact_event_mask=event)
    np.savez_compressed(folder / 'contact_metrics.npz', **arrays)
    meta = dict(schema_version=1, contact_gate_version=2, body_cache_sha256=sha256(body_cache_path if body_cache_path is not None else folder / 'body_room.npz'), source_video_sha256=str(body['source_video_sha256']),
                actor_id=str(body['source_actor_id']), scene_sha256=sha256(scene['source_blend']), scene_geometry_sha256=sha256(scene['geometry_path']),
                metrics_sha256=sha256(folder / 'contact_metrics.npz'), series=descriptors,
                cohort_codes={'0': 'not evaluated', '1': 'contact-gap training key (may also train plant)',
                              '2': 'not trained by contact-gap or plant objectives; not globally heldout', '3': 'diagnostic-only interval', '4': 'plant training endpoint only'},
                cohort_scope='Depth training is separate; all active body geometry participates in scene constraints and temporal regularization. No global heldout claim.',
                contact_patch_provenance=[dict(name=c['name'], kind=c['kind'], indices=c['indices'].tolist(), intervals=c['intervals'],
                                               train_frame_indices=c['train_ids'].tolist(),
                                               plant_train_frame_indices=c.get('plant_train_ids', c['train_ids']).tolist() if c.get('plant') else [],
                                               plant_training_endpoint_pairs=plant_series(body, c)['training_endpoint_pairs'] if c.get('plant') else [],
                                               surface_sha256=c['surface_sha256']) for c in contacts])
    (folder / 'contact_metrics.json').write_text(json.dumps(meta, indent=2, allow_nan=False) + '\n')
    return meta
