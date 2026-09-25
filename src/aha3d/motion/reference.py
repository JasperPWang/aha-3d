"""Compile reviewed SAM/Pi3X pose observations into native Kimodo hand guidance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .. import runtime
from .sparse import align_vectors


UP = np.array([0., 1., 0.])


def finite(value, shape, name):
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f'{name}: expected finite {shape}')
    return array


def unit(value):
    a = np.asarray(value, dtype=np.float64)
    if not np.isfinite(a).all() or np.linalg.norm(a) < 1e-6:
        raise ValueError('Degenerate or nonfinite direction')
    return a / np.linalg.norm(a)


def rotation(value):
    r = finite(value, (3, 3), 'rotation')
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1, atol=1e-5):
        raise ValueError('Expected a proper rotation, without scale/reflection')
    return r


def intrinsic(value):
    k = finite(value, (3, 3), 'intrinsics')
    if min(k[0, 0], k[1, 1]) <= 0 or not np.allclose(k[2], [0, 0, 1]):
        raise ValueError('Invalid camera intrinsics')
    return k


def project(points, k):
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all() or np.any(p[:, 2] <= 1e-6):
        raise ValueError('Camera points must be finite and in front of camera')
    h = p @ intrinsic(k).T
    return h[:, :2] / h[:, 2:]


def camera_to_world(points, pose):
    pose = finite(pose, (4, 4), 'camera-to-world')
    rotation(pose[:3, :3])
    if not np.allclose(pose[3], [0, 0, 0, 1]):
        raise ValueError('Invalid homogeneous camera pose')
    return np.asarray(points) @ pose[:3, :3].T + pose[:3, 3]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def unique_frames(records):
    frames = [x['source_frame'] for x in records]
    if any(type(i) is not int or i < 0 for i in frames) or len(set(frames)) != len(frames):
        raise ValueError('Source frame IDs must be unique nonnegative integers')
    return dict(zip(frames, records))


def build_guidance(observations, cameras, selection):
    """Directions are retargeted; SAM absolute body/root position is never constrained."""
    if observations.get('schema_version') != 1 or selection.get('schema_version') != 1:
        raise ValueError('Unsupported observation/selection schema')
    if observations.get('coordinate_convention') != 'opencv_camera_metres_with_translation':
        raise ValueError('Expected camera-space points with translation applied exactly once')
    names = observations['keypoint_names']
    if len(names) != len(set(names)):
        raise ValueError('Duplicate landmark names')
    index = {name: i for i, name in enumerate(names)}
    obs = unique_frames(observations['frames'])
    cams = unique_frames(cameras['frames'])
    if observations['processed_size_wh'] != cameras['processed_size_wh']:
        raise ValueError('Observation and Pi3X image sizes differ')
    # Z-up Pi3X world -> Y-up Kimodo, including user-authored room yaw.
    r = rotation(selection['world_to_kimodo_rotation'])
    if not np.allclose(r @ [0., 0., 1.], UP, atol=1e-5):
        raise ValueError('World-to-Kimodo rotation must map world Z up to Kimodo Y up')
    total = selection['native_frames']
    if type(total) is not int or total <= 0 or selection.get('native_fps', 30) != 30:
        raise ValueError('Use positive native_frames and the deployed native 30 fps')
    events = selection['events']
    if not events:
        raise ValueError('Select at least one reviewed event')
    result = []
    seen = set()
    for event in events:
        supported = {'source_frame', 'side', 'reviewed', 'review_note', 'bbox_xyxy',
                     'target_time_seconds', 'facing_xz', 'root_xz_m'}
        if set(event) - supported:
            raise ValueError(f'Unsupported event fields: {sorted(set(event) - supported)}')
        if event.get('reviewed') is not True or not str(event.get('review_note', '')).strip():
            raise ValueError('Each event requires visual review and a review_note')
        side = event.get('side', 'right')
        if side not in ('left', 'right'):
            raise ValueError('Only left/right hand directions are supported')
        source_frame = event['source_frame']
        if type(source_frame) is not int or source_frame not in obs or source_frame not in cams:
            raise ValueError('Event needs an exact matching SAM and Pi3X source frame')
        sample, camera = obs[source_frame], cams[source_frame]
        ts = float(sample['timestamp_seconds'])
        camera_ts = float(camera['timestamp_seconds'])
        if not np.isfinite([ts, camera_ts]).all() or abs(ts - camera_ts) > 1e-6:
            raise ValueError('SAM/Pi3X timestamps differ')
        target_time = float(event.get('target_time_seconds', ts - selection.get('source_start_seconds', 0)))
        if not np.isfinite(target_time) or not 0 <= target_time < total / 30:
            raise ValueError('Target event lies outside native clip duration')
        frame = int(np.floor(target_time * 30 + .5))
        if frame >= total:
            raise ValueError('Event rounds outside native clip; choose an explicit earlier target time')
        if (frame, side) in seen:
            raise ValueError('Two events map to the same native frame and hand')
        seen.add((frame, side))
        required = [f'{side}-shoulder', f'{side}-elbow', f'{side}-wrist', 'left-hip', 'right-hip']
        try:
            ids = [index[name] for name in required]
        except KeyError as exc:
            raise ValueError(f'Missing landmark {exc}') from exc
        points = finite(sample['keypoints_camera_m'], (len(names), 3), 'keypoints')
        uv = finite(sample['keypoints_2d'], (len(names), 2), '2D keypoints')
        projected = project(points[ids], camera['intrinsics'])
        error = float(np.linalg.norm(projected - uv[ids], axis=1).max())
        if error > 2.0:
            raise ValueError('Projection mismatch exceeds 2 pixels; check conventions/intrinsics')
        width, height = cameras['processed_size_wh']
        if np.any(uv[ids] < 0) or np.any(uv[ids] > [width - 1, height - 1]):
            raise ValueError('Required landmarks fall outside the source image')
        world = camera_to_world(points, camera['c2w'])
        p = world @ r.T
        shoulder, elbow, wrist, left, right = p[ids]
        anatomical_right = right - left
        anatomical_right[1] = 0
        inferred_facing = unit(np.cross(UP, unit(anatomical_right)))
        # Body-relative observations stay in the inferred body basis even when
        # the desired room heading is overridden.
        body_side = unit(np.cross(inferred_facing, UP))
        basis = np.column_stack([body_side, UP, inferred_facing])
        facing = inferred_facing
        if 'facing_xz' in event:
            xz = finite(event['facing_xz'], (2,), 'facing_xz')
            facing = unit([xz[0], 0, xz[1]])
        key = dict(frame=frame, side=side, source_frame=source_frame,
                   source_timestamp_seconds=ts, target_time_seconds=target_time,
                   quantization_error_seconds=frame / 30 - target_time,
                   facing_xz=facing[[0, 2]].tolist(),
                   upper_arm_direction=(basis.T @ unit(elbow - shoulder)).tolist(),
                   forearm_direction=(basis.T @ unit(wrist - elbow)).tolist(),
                   projection_max_error_px=error, review_note=event['review_note'])
        if 'root_xz_m' in event:
            key['root_xz_m'] = finite(event['root_xz_m'], (2,), 'authored root_xz_m').tolist()
        result.append(key)
    return sorted(result, key=lambda k: (k['frame'], k['side']))


def compile_constraints(baseline, keys, native_frames, route=None):
    """Use the installed SMPL-X skeleton on CPU; no generative weights required."""
    import torch
    from kimodo.constraints import LeftHandConstraintSet, RightHandConstraintSet, load_constraints_lst
    from kimodo.skeleton import SMPLXSkeleton22

    skeleton = SMPLXSkeleton22().cpu()
    local_all = finite(baseline['local_rot_mats'], (native_frames, 22, 3, 3), 'baseline rotations')
    if not np.allclose(local_all.swapaxes(-1, -2) @ local_all, np.eye(3), atol=1e-4) or not np.allclose(np.linalg.det(local_all), 1, atol=1e-4):
        raise ValueError('Invalid baseline rotations')
    roots = finite(baseline['root_positions'], (native_frames, 3), 'baseline roots')
    smooths = finite(baseline['smooth_root_pos'], (native_frames, 3), 'baseline smooth root')
    constraints, reports = [], []
    route = [] if route is None else route
    # Only root guidance may be merged, to avoid duplicate full-body/hand masks.
    route_frames = set()
    for entry in route:
        if entry.get('type') != 'root2d':
            raise ValueError('Additional constraints may only contain root2d')
        frames = entry['frame_indices']
        if frames != sorted(set(frames)) or any(type(f) is not int or not 0 <= f < native_frames for f in frames):
            raise ValueError('Invalid root route frame indices')
        if route_frames.intersection(frames):
            raise ValueError('Duplicate root route frame across constraint sets')
        route_frames.update(frames)
        finite(entry['smooth_root_2d'], (len(frames), 2), 'root route positions')
        if 'global_root_heading' in entry:
            heading = np.asarray(entry['global_root_heading'])
            if not np.isfinite(heading).all():
                raise ValueError('Nonfinite root route heading')
    route_sets = load_constraints_lst(route, skeleton)
    def fk(local, root):
        with torch.inference_mode():
            rot, pos, _ = skeleton.fk(torch.tensor(local, dtype=torch.float32), torch.tensor(root, dtype=torch.float32))
        return rot.numpy(), pos.numpy()
    # Combine both hands at a shared time before emitting masks, so root/heading agree.
    for frame in sorted({key['frame'] for key in keys}):
        events = [key for key in keys if key['frame'] == frame]
        if not 0 <= frame < native_frames:
            raise ValueError('Key lies outside baseline')
        local = local_all[[frame]].astype(np.float32).copy()
        root = roots[[frame]].astype(np.float32).copy()
        smooth = smooths[[frame]][:, [0, 2]].astype(np.float32).copy()
        first = events[0]
        facing = unit([first['facing_xz'][0], 0, first['facing_xz'][1]])
        for event in events[1:]:
            if not np.allclose(first['facing_xz'], event['facing_xz']) or first.get('root_xz_m') != event.get('root_xz_m'):
                raise ValueError('Hands at the same time must agree on facing and authored root')
        rot, pos = fk(local, root)
        right = pos[0, 2] - pos[0, 1]; right[1] = 0
        local[0, 0] = align_vectors(unit(np.cross(UP, unit(right))), facing) @ local[0, 0]
        if 'root_xz_m' in first:
            delta = np.asarray(first['root_xz_m']) - smooth[0]
            root[0, [0, 2]] += delta; smooth[0] += delta
        body_side = unit(np.cross(facing, UP))
        for event in events:
            side = event['side']
            for bone_name, tip_name, parent_name, field in [
                (f'{side}_shoulder', f'{side}_elbow', f'{side}_collar', 'upper_arm_direction'),
                (f'{side}_elbow', f'{side}_wrist', f'{side}_shoulder', 'forearm_direction')]:
                bone, tip, parent = [skeleton.bone_index[n] for n in (bone_name, tip_name, parent_name)]
                rot, pos = fk(local, root)
                lateral, vertical, forward = finite(event[field], (3,), field)
                desired = unit(lateral * body_side + vertical * UP + forward * facing)
                change = align_vectors(pos[0, tip] - pos[0, bone], desired)
                local[0, bone] = rot[0, parent].T @ change @ rot[0, bone]
        rot, pos = fk(local, root)
        for event in events:
            cls = RightHandConstraintSet if event['side'] == 'right' else LeftHandConstraintSet
            hand = cls(skeleton, torch.tensor([frame]), torch.from_numpy(pos), torch.from_numpy(rot), torch.from_numpy(smooth))
            saved = {k: v.detach().cpu().tolist() if torch.is_tensor(v) else v for k, v in hand.get_save_info().items()}
            loaded = cls.from_dict(skeleton, saved)
            err = float(np.max(np.abs(loaded.global_joints_positions.numpy() - pos)))
            if err > 1e-5:
                raise ValueError('Native constraint FK round-trip failed')
            # Root route values at the hand key must agree with its unavoidable root mask.
            for route_set in route_sets:
                for i, f in enumerate(route_set.frame_indices.tolist()):
                    if f == frame and not np.allclose(route_set.smooth_root_2d[i].numpy(), smooth[0], atol=1e-4):
                        raise ValueError('Root route conflicts with hand-key root; revise authored guidance')
                    if f == frame and route_set.global_root_heading is not None and not np.allclose(route_set.global_root_heading[i].numpy(), hand.global_root_heading[0].numpy(), atol=1e-4):
                        raise ValueError('Root route heading conflicts with hand key')
            constraints.append(saved)
            wrist = skeleton.bone_index[f"{event['side']}_wrist"]
            reports.append(dict(event=event, wrist_target_m=pos[0, wrist].tolist(),
                                root_position_m=root[0].tolist(), smooth_root_xz_m=smooth[0].tolist(),
                                heading=hand.global_root_heading.tolist(), fk_roundtrip_max_error_m=err))
    return route + constraints, reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--pi3x', type=Path, required=True, help='Original reference bundle')
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True, help='Native single-clip 30 fps Kimodo NPZ')
    parser.add_argument('--route', type=Path, help='Optional root2d constraints JSON')
    parser.add_argument('--temporal-support-selection', type=Path,
                        help='Reviewed neighboring poses; fit arm directions, emit only original keys')
    parser.add_argument('--temporal-window-seconds', type=float, default=.2)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output exists; choose a new claimed directory')
    obs = json.loads(args.observations.read_text())
    pi_inputs = args.pi3x / 'inputs.json'; cam_path = args.pi3x / 'cameras.json'
    manifest = json.loads(pi_inputs.read_text())
    if obs['source_sha256'] != manifest['source_sha256'] or obs['pi3x_inputs_sha256'] != digest(pi_inputs) or obs['pi3x_cameras_sha256'] != digest(cam_path):
        raise ValueError('Observations belong to a different or modified Pi3X bundle')
    cameras = json.loads(cam_path.read_text()); selection = json.loads(args.selection.read_text())
    keys = build_guidance(obs, cameras, selection)
    from .temporal import diagnostics, refit
    raw_keys = keys
    temporal_report = {'enabled': False, 'pairs': diagnostics(keys)}
    if args.temporal_support_selection:
        support_selection = json.loads(args.temporal_support_selection.read_text())
        # Support and target must share registration, timing and target body setup.
        if {k: v for k, v in support_selection.items() if k != 'events'} != {k: v for k, v in selection.items() if k != 'events'}:
            raise ValueError('Temporal support must share the target selection header')
        support = build_guidance(obs, cameras, support_selection)
        keys, temporal_report = refit(keys, support, window_seconds=args.temporal_window_seconds)
        temporal_report['enabled'] = True
    with np.load(args.baseline, allow_pickle=False) as data:
        baseline = {k: data[k] for k in ('local_rot_mats', 'root_positions', 'smooth_root_pos')}
    route = json.loads(args.route.read_text()) if args.route else None
    constraints, reports = compile_constraints(baseline, keys, selection['native_frames'], route)
    args.out.mkdir(parents=True, exist_ok=False)
    dump(args.out / 'temporal-report.json', temporal_report)
    dump(args.out / 'guidance-raw.json', {'schema_version': 1, 'events': raw_keys})
    dump(args.out / 'constraints.json', constraints)
    dump(args.out / 'guidance.json', {'schema_version': 1, 'events': keys})
    inputs = [args.observations, args.selection, args.baseline, pi_inputs, cam_path]
    if args.route: inputs.append(args.route)
    if args.temporal_support_selection: inputs.append(args.temporal_support_selection)
    dump(args.out / 'report.json', dict(schema_version=1, status='compiled; generated motion and room review pending',
         targets=reports, additional_native_fields=['smooth_root_xz', 'root_height', 'heading'],
         wrist_orientation_policy='Baseline local wrist rotation inherited through retargeted arm; no SAM twist recovery',
         absolute_sam_root_used=False, contact_fit=False, native_fps=30, native_frames=selection['native_frames'],
         source_sha256=obs['source_sha256'], inputs={str(p.resolve()): digest(p) for p in inputs},
         source_hashes={str(p): digest(p) for p in [Path(__file__), Path(__file__).with_name('sparse.py'), Path(__file__).with_name('temporal.py')]},
         run_id=runtime.run_id()))
    print(args.out / 'constraints.json')


if __name__ == '__main__':
    main()
