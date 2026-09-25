"""Export a scene-ground v2 result into a saved room's rigid camera basis.

Export preserves scale and floor height, with optional constant XY placement.
Explicit refinement solves smooth root translation against reviewed finite contacts
and saved room geometry; it does not generate motion or select a delivery.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def fingerprint(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return dict(path=str(path), sha256=h.hexdigest())


def camera_basis(source, target, position_tolerance=.01, rotation_tolerance=.1):
    """One scale-1 transform using paired cameras, including their orientation."""
    from scipy.spatial.transform import Rotation
    source, target = np.asarray(source, float), np.asarray(target, float)
    if source.shape != target.shape or source.ndim != 3 or source.shape[1:] != (4, 4) or len(source) < 3:
        raise ValueError('At least three matching camera observations required')
    for cameras in (source, target):
        r = cameras[:, :3, :3]
        if (not np.isfinite(cameras).all() or not np.allclose(cameras[:, 3], [0, 0, 0, 1])
                or not np.allclose(r @ r.transpose(0, 2, 1), np.eye(3), atol=1e-5)
                or not np.allclose(np.linalg.det(r), 1, atol=1e-5)):
            raise ValueError('Finite right-handed rigid cameras required')
    r = Rotation.from_matrix(target[:, :3, :3] @ source[:, :3, :3].transpose(0, 2, 1)).mean().as_matrix()
    t = np.median(target[:, :3, 3] - source[:, :3, 3] @ r.T, axis=0)
    position = np.linalg.norm(source[:, :3, 3] @ r.T + t - target[:, :3, 3], axis=1)
    angles = np.degrees(Rotation.from_matrix(target[:, :3, :3] @ (r @ source[:, :3, :3]).transpose(0, 2, 1)).magnitude())
    if position.max() > position_tolerance or angles.max() > rotation_tolerance:
        raise ValueError('Room and inference cameras do not share one fixed rigid basis')
    transform = np.eye(4); transform[:3, :3] = r; transform[:3, 3] = t
    return transform, dict(position_max_m=float(position.max()), rotation_max_degrees=float(angles.max()),
                           observations=len(source), body_scale=1., trajectory_scale=1.)


def room_mesh(points, transform):
    return np.asarray(points) @ transform[:3, :3].T + transform[:3, 3]


def horizontal_placement(joints, times, active, observations, bindings):
    """Translate one whole clip in XY from reviewed training depth; keep floor Z."""
    for key, value in bindings.items():
        if str(observations[key]) != value:
            raise ValueError('Placement observations have a different ' + key)
    ids = observations['frame_indices']
    if ids.dtype.kind not in 'iu' or np.any(ids < 0) or np.any(ids >= len(times)):
        raise ValueError('Invalid placement source frames')
    if not np.allclose(observations['time_seconds'], times[ids], atol=1e-6):
        raise ValueError('Placement source timestamps differ')
    valid, train = observations['valid'], observations['train']
    if valid.dtype != bool or train.dtype != bool:
        raise ValueError('Boolean observation validity and training masks required')
    use = valid & train & active[ids] & (observations['weights'] > 0)
    targets = observations['root_targets']
    if use.sum() < 3 or not np.isfinite(targets[use]).all():
        raise ValueError('At least three finite reviewed training depth targets required')
    delta = np.zeros(3)
    delta[:2] = np.median(targets[use, :2] - joints[ids[use], 0, :2], axis=0)
    return delta, dict(translation_room_m=delta.tolist(), training_source_frames=ids[use].tolist(),
                       scope='Fixed XY translation from cached estimated depth; no scale, Z or temporal fitting')


def export(a):
    # Keep lightweight coordinate helpers usable without the licensed ML runtime.
    import joblib
    import torch
    import smplx
    results = joblib.load(a.results)
    meta = json.loads(a.meta.read_text())
    inputs = {name: fingerprint(getattr(a, name)) for name in
              ('results', 'meta', 'model', 'video', 'cameras', 'room_cameras')}
    if inputs['video']['sha256'] != meta['source_video_sha256']:
        raise ValueError('Source video differs from body inference')
    prior = meta.get('scene_ground')
    if not prior or results.get('scene_ground') != prior:
        raise ValueError('Matching scene-ground provenance required')
    if len(results['people']) != 1:
        raise ValueError('Export one reviewed actor at a time')
    person = next(iter(results['people'].values()))
    ids = np.asarray(person['frames'], int); n = results['n_frames']; fps = float(meta['fps'])
    if not np.array_equal(ids, np.arange(len(ids))) or not 0 < len(ids) <= n:
        raise ValueError('Reviewed active-prefix frame mapping required')
    with np.load(a.cameras, allow_pickle=False) as z:
        src = z['observation_c2w']; obs_ids = z['observation_frame_indices']; times = z['time_seconds']
    with np.load(a.room_cameras, allow_pickle=False) as z:
        room = z['dense_c2w_room_cv']; room_times = z['dense_time_seconds']
        if 'source_video_sha256' in z and str(z['source_video_sha256']) != meta['source_video_sha256']:
            raise ValueError('Room camera source video differs')
    if len(times) != n or len(room) != n or not np.allclose(times, room_times, atol=1e-6):
        raise ValueError('Room and motion source timestamps differ')
    transform, alignment = camera_basis(src, room[obs_ids])
    ground_to_room = transform @ np.asarray(prior['ground_to_world'])
    if not np.allclose(ground_to_room[:3, 1], [0, 0, 1], atol=1e-5) or abs(ground_to_room[2, 3]) > 1e-5:
        raise ValueError('Room support does not match the supplied scene floor/upright')
    model = smplx.SMPLX(str(a.model), use_pca=False, flat_hand_mean=True, num_betas=10).to(a.device)
    sw = person['smplx_world']; meshes, joints = [], []
    for start in range(0, len(ids), 64):
        pose, shape, trans = [torch.as_tensor(np.asarray(sw[k])[start:start+64], dtype=torch.float32, device=a.device)
                              for k in ('pose', 'shape', 'trans')]
        zero = lambda count: torch.zeros(len(pose), count, device=a.device)
        with torch.no_grad():
            out = model(global_orient=pose[:, :3], body_pose=pose[:, 3:66], betas=shape[:, :10], transl=trans,
                        left_hand_pose=pose[:, 75:120], right_hand_pose=pose[:, 120:165],
                        jaw_pose=zero(3), leye_pose=zero(3), reye_pose=zero(3), expression=zero(10))
        meshes.append(room_mesh(out.vertices.cpu().numpy(), ground_to_room))
        joints.append(room_mesh(out.joints.cpu().numpy(), ground_to_room))
    def pad(values):
        values = np.concatenate(values)
        return np.concatenate([values, np.repeat(values[-1:], n-len(values), axis=0)]).astype(np.float32)
    vertices, joints = pad(meshes), pad(joints)
    placement = None
    if getattr(a, 'placement_observations', None):
        inputs['placement_observations'] = fingerprint(a.placement_observations)
        with np.load(a.placement_observations, allow_pickle=False) as z:
            observations = dict(z)
        delta, placement = horizontal_placement(joints, times, np.arange(n)<len(ids), observations,
            dict(source_video_sha256=meta['source_video_sha256'], source_actor_id=meta['actor_id'],
                 room_basis_sha256=inputs['room_cameras']['sha256']))
        vertices = (vertices + delta).astype(np.float32)
        joints = (joints + delta).astype(np.float32)
    a.out.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(a.out/'body_room.npz', schema_version=1, vertices=vertices, joints=joints,
                        faces=model.faces.astype(np.int32), vertex_ids=np.arange(vertices.shape[1]),
                        fps=fps, time_seconds=times, source_frame_indices=np.arange(n), track_active=np.arange(n)<len(ids),
                        body_scale=1., surface_model_type='smplx', source_video_sha256=meta['source_video_sha256'],
                        source_actor_id=meta['actor_id'], room_basis_sha256=inputs['room_cameras']['sha256'],
                        motion_source='scene-guided GVHMR with v2; fixed room basis; no new generation',
                        completion_present=bool(meta.get('completion')))
    report = dict(schema_version=1, inputs=inputs, actor_id=meta['actor_id'], frames=n, active_frames=len(ids), fps=fps,
                  world_to_room=transform.tolist(), ground_to_room=ground_to_room.tolist(), alignment=alignment,
                  body=fingerprint(a.out/'body_room.npz'), completion_present=bool(meta.get('completion')), placement=placement,
                  scope='Rigid export only; finite room/contact and source-style acceptance require separate review')
    (a.out/'export.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def refine(a):
    """Fit source-bound finite contacts without resizing or generating motion."""
    import time
    from tools.gvhmr.root_constraints import active_mask, load_contacts, contact_metrics, spline_basis
    from tools.gvhmr.full_scene_constraints import (load_scene_constraints, solve_scene_coefficients,
                                                    save_scene_metrics, save_contact_series)
    body = dict(np.load(a.body, allow_pickle=False))
    source = fingerprint(a.body)
    contacts, _ = load_contacts(a.contacts, body, source['sha256'])
    scene = load_scene_constraints(a.scene_constraints, body, source['sha256'])
    from tools.gvhmr import foot_contacts
    foot_export = getattr(a, 'foot_export', None)
    if foot_export is None and (a.body.parent/'export.json').is_file():
        foot_export = a.body.parent/'export.json'
    foot = foot_contacts.from_export(a.body, foot_export, scene,
              velocity_weight=getattr(a, 'foot_velocity_weight', 1000.),
              height_weight=getattr(a, 'foot_height_weight', 100.),
              target_gap=getattr(a, 'foot_target_gap', .002)) if foot_export is not None else None
    active = active_mask(body); n = int(active.sum()); times = body['time_seconds']
    if a.acceleration_penalty <= 0 or a.offset_penalty <= 0 or a.iterations < 1:
        raise ValueError('Positive regularization and iteration limit required')
    B, D2, _, knots, spline = spline_basis(times, np.flatnonzero(active), a.knot_spacing)
    A = np.vstack([np.sqrt(a.acceleration_penalty/n)*D2[active], np.sqrt(a.offset_penalty/n)*B[active]])
    coefficients = np.zeros((B.shape[1], 3))
    warm_start = getattr(a, 'warm_start_report', None)
    if warm_start is not None:
        previous = json.loads(warm_start.read_text())
        candidate = np.asarray(previous['coefficients'], float)
        if (previous['inputs']['body']['sha256'] != source['sha256'] or
                not np.array_equal(previous['knots_seconds'], knots) or
                candidate.shape != coefficients.shape or not np.isfinite(candidate).all()):
            raise ValueError('Warm start must match initial body and spline basis')
        coefficients = candidate
    a.out.mkdir(parents=True, exist_ok=False)
    before = a.out/'before'; before.mkdir()
    before_contacts = contact_metrics(body, contacts)
    save_scene_metrics(before, body, scene, body_cache_path=a.body)
    save_contact_series(before, body, contacts, scene, before_contacts, body_cache_path=a.body)
    if foot is not None:
        foot_before, arrays = foot_contacts.metrics(body, foot)
        np.savez_compressed(before/'foot_metrics.npz', **arrays)
    started = time.monotonic()
    coefficients, report = solve_scene_coefficients(body, scene, contacts, B, A, np.zeros((len(A), 3)),
                                                    coefficients, max_iterations=a.iterations, foot_contacts=foot)
    offsets = B @ coefficients
    result = dict(body)
    result['vertices'] = (body['vertices'] + offsets[:, None]).astype(np.float32)
    result['joints'] = (body['joints'] + offsets[:, None]).astype(np.float32)
    result['root_correction_room'] = offsets.astype(np.float32)
    result['motion_source'] = np.asarray('v2 mesh with finite-surface root-only contact refinement; no new generation')
    after = a.out/'after'; after.mkdir()
    np.savez_compressed(after/'body_room.npz', **result)
    after_contacts = contact_metrics(result, contacts)
    after_scene = save_scene_metrics(after, result, scene, body_cache_path=after/'body_room.npz')
    save_contact_series(after, result, contacts, scene, after_contacts, body_cache_path=after/'body_room.npz')
    if foot is not None:
        foot_after, arrays = foot_contacts.metrics(result, foot)
        np.savez_compressed(after/'foot_metrics.npz', **arrays)
        report['predicted_foot_contacts'] = dict(before=foot_before, after=foot_after,
              provenance=foot['provenance'], velocity_weight=foot['velocity_weight'],
              height_weight=foot['height_weight'], target_gap_m=foot['target_gap'], threshold=.5,
              slip_mean_not_worse=foot_before['slip_mean_m_s'] is not None and foot_after['slip_mean_m_s'] <= foot_before['slip_mean_m_s']+1e-5,
              slip_p90_not_worse=foot_before['slip_p90_m_s'] is not None and foot_after['slip_p90_m_s'] <= foot_before['slip_p90_m_s']+1e-5)
    shape_error = float(np.max(abs((result['vertices']-result['joints'][:, :1]) -
                                  (body['vertices']-body['joints'][:, :1]))))
    if shape_error > 3e-6:
        raise ValueError('Contact correction changed body-relative geometry')
    report.update(objective='Reviewed contact keys plus supplied GVHMR predicted foot velocity/sole height, all-active finite floor/listed objects and smooth root regularization; no depth objective',
                  inputs={name: fingerprint(getattr(a, name)) for name in ('body', 'contacts', 'scene_constraints')},
                  body=fingerprint(after/'body_room.npz'), elapsed_seconds=time.monotonic()-started,
                  contacts_before=before_contacts, contacts_after=after_contacts,
                  contact_constraints_passed=all(c['accepted'] for c in after_contacts),
                  scene_constraints_passed=after_scene['accepted'], shape_preservation_max_error_m=shape_error,
                  max_root_offset_m=float(np.linalg.norm(offsets[active], axis=1).max()),
                  max_added_velocity_m_s=float(np.linalg.norm(spline(times[active], 1) @ coefficients, axis=1).max()),
                  max_added_acceleration_m_s2=float(np.linalg.norm(D2[active] @ coefficients, axis=1).max()),
                  parameters=dict(knot_spacing=a.knot_spacing, acceleration_penalty=a.acceleration_penalty,
                                  offset_penalty=a.offset_penalty, iterations=a.iterations),
                  coefficients=coefficients.tolist(), knots_seconds=knots.tolist(),
                  warm_start=fingerprint(warm_start) if warm_start is not None else None,
                  accepted=False, visual_review='pending',
                  scope='Declared contacts and finite/convex geometry only; numerical flags do not select a delivery')
    (a.out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    e = sub.add_parser('export', help='Skin v2 and map it into the saved room basis')
    for name in ('results', 'meta', 'model', 'video', 'cameras', 'room-cameras', 'out'):
        e.add_argument('--'+name, type=Path, required=True)
    e.add_argument('--device', default='cuda')
    e.add_argument('--placement-observations', type=Path,
                   help='Optional source-bound reviewed depth targets for fixed XY placement')
    r = sub.add_parser('refine', help='Apply explicitly reviewed finite contacts to an exported mesh')
    for name in ('body', 'contacts', 'scene-constraints', 'out'):
        r.add_argument('--'+name, type=Path, required=True)
    r.add_argument('--knot-spacing', type=float, default=.5)
    r.add_argument('--acceleration-penalty', type=float, default=.01)
    r.add_argument('--offset-penalty', type=float, default=.05)
    r.add_argument('--iterations', type=int, default=300)
    r.add_argument('--foot-export', type=Path, help='Exact v2 mesh export receipt; defaults to export.json beside body')
    r.add_argument('--foot-velocity-weight', type=float, default=1000.)
    r.add_argument('--foot-height-weight', type=float, default=100.)
    r.add_argument('--foot-target-gap', type=float, default=.002, help='Sole support target in metres')
    r.add_argument('--warm-start-report', type=Path, help='Continue matching root-spline coefficients from a previous report')
    a = p.parse_args()
    export(a) if a.command == 'export' else refine(a)


if __name__ == '__main__':
    main()
