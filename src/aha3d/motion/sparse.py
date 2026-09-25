"""Generate approximate actions with sparse native wrist and route keyframes.

Keypose authoring changes only conditioning inputs. All output poses, including
transitions, come from Kimodo and its native correction. No external output IK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from aha3d import runtime


def unit(vector):
    vector = np.asarray(vector, dtype=np.float64)
    length = np.linalg.norm(vector)
    if length < 1e-8:
        raise ValueError('Direction must be nonzero')
    return vector / length


def align_vectors(source, destination):
    """Shortest proper rotation, including the antiparallel case."""
    a, b = unit(source), unit(destination)
    dot = float(np.clip(a @ b, -1, 1))
    if dot < -1 + 1e-7:
        axis = unit(np.cross(a, np.eye(3)[np.argmin(np.abs(a))]))
        return 2*np.outer(axis, axis)-np.eye(3)
    cross = np.cross(a, b)
    x, y, z = cross
    skew = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    return np.eye(3)+skew+skew@skew/(1+dot)


def author_keyposes(model, baseline, keys):
    """Author FK-consistent sparse inputs using directions in a body basis.

Only wrist position/rotation and native root/heading fields will be masked.
The shoulder and elbow rotations below describe input poses, not output edits.
"""
    import torch
    skeleton = model.skeleton
    indices = np.array([key['frame'] for key in keys], dtype=np.int64)
    local = baseline['local_rot_mats'][indices].copy()
    root = baseline['root_positions'][indices].copy()
    smooth = baseline['smooth_root_pos'][indices][:, [0, 2]].copy()

    def fk():
        with torch.inference_mode():
            rots, points, _ = skeleton.fk(torch.from_numpy(local).to(model.device),
                                           torch.from_numpy(root).to(model.device))
        return rots.cpu().numpy(), points.cpu().numpy()

    for i, key in enumerate(keys):
        rots, points = fk()
        # Kimodo is Y-up / +Z-forward; right-hip minus left-hip is -X
        # in its neutral pose. Forward is up CROSS anatomical right.
        side = points[i, 2]-points[i, 1]
        side[1] = 0
        current_forward = np.cross([0., 1., 0.], unit(side))
        facing = unit([key['facing_xz'][0], 0., key['facing_xz'][1]])
        yaw = align_vectors(current_forward, facing)
        local[i, 0] = yaw @ local[i, 0]
        if 'root_xz_m' in key:
            delta = np.asarray(key['root_xz_m'])-smooth[i]
            root[i, [0, 2]] += delta
            smooth[i] += delta
        side = np.cross(facing, [0., 1., 0.])
        for bone, tip, parent, field in [(17, 19, 14, 'upper_arm_direction'),
                                         (19, 21, 17, 'forearm_direction')]:
            rots, points = fk()
            lateral, up, forward = key[field]
            desired = lateral*side + np.array([0., up, 0.]) + forward*facing
            rotation = align_vectors(points[i, tip]-points[i, bone], desired)
            local[i, bone] = rots[i, parent].T @ rotation @ rots[i, bone]
    rots, points = fk()
    return indices, local, root, smooth, rots, points


def diagnostics(data, keys, segments, fps=30):
    joints = data['posed_joints']
    relative = joints-joints[:, :1]
    steps = np.linalg.norm(np.diff(relative[:, 21], axis=0), axis=-1)
    root_steps = np.linalg.norm(np.diff(data['root_positions'][:, [0, 2]], axis=0), axis=-1)
    jerk = np.linalg.norm(np.diff(relative, n=3, axis=0), axis=-1)*fps**3
    seams = np.cumsum(segments)[:-1]
    events = sorted(set([150, *seams.tolist(), *keys]))
    return {
        'all_joint_jerk_p99_m_s3': float(np.percentile(jerk, 99)),
        'ending_joint_jerk_p99_m_s3': float(np.percentile(jerk[300:], 99)),
        'max_wrist_step_relative_m': float(steps.max()),
        'max_root_step_m': float(root_steps.max()),
        'min_foot_joint_height_m': float(joints[:, [7, 8, 10, 11], 1].min()),
        'events': [{'frame_zero_based': int(f), 'root_step_m': float(root_steps[f-1]),
                    'wrist_step_m': float(steps[f-1]),
                    'local_max_wrist_step_m': float(steps[max(0, f-6):f+6].max())}
                   for f in events if 0 < f < len(joints)],
        'note': 'Finite differences are diagnostics, not perceptual smoothness guarantees.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    frames = config['segment_frames']
    keys = config['hand_keyframes']
    key_indices = [key['frame'] for key in keys]
    if sorted(set(key_indices)) != key_indices or not all(0 <= f < sum(frames) for f in key_indices):
        raise ValueError('Hand frames must be unique, increasing, and within the clip')
    args.out.mkdir(parents=True, exist_ok=False)
    inputs = args.out/'inputs'
    inputs.mkdir()
    shutil.copyfile(args.config, inputs/'config.json')
    (inputs/'route.json').write_text(json.dumps(config['route'], indent=2)+'\n')
    snapshot = args.out/'snapshot'
    snapshot.mkdir()
    shutil.copyfile(__file__, snapshot/'sparse.py')

    import torch
    from kimodo import load_model
    from kimodo.constraints import RightHandConstraintSet, load_constraints_lst
    from kimodo.tools import seed_everything

    started = time.perf_counter()
    model, name = load_model('Kimodo-SMPLX-RP-v1', device='cuda:0', return_resolved_name=True)
    loaded = time.perf_counter()
    route = load_constraints_lst(str(inputs/'route.json'), model.skeleton)

    def generate(constraints):
        seed_everything(config['seed'])
        output = model(config['prompts'], frames, num_denoising_steps=config['denoising_steps'],
                       constraint_lst=constraints, num_samples=1, multi_prompt=True,
                       num_transition_frames=config['transition_frames'],
                       post_processing=True, return_numpy=True)
        output = {k: v[0] for k, v in output.items() if isinstance(v, np.ndarray)}
        if output['posed_joints'].shape != (sum(frames), 22, 3):
            raise ValueError('Unexpected frame count or skeleton')
        if not all(np.isfinite(v).all() for v in output.values()):
            raise ValueError('Nonfinite output')
        return output

    if args.baseline:
        shutil.copyfile(args.baseline, inputs/'baseline.npz')
        with np.load(inputs/'baseline.npz', allow_pickle=False) as data:
            baseline = {key: data[key] for key in data.files}
    else:
        baseline = generate(route)
        np.savez_compressed(inputs/'baseline.npz', **baseline)
    base_finished = time.perf_counter()
    if baseline['posed_joints'].shape != (sum(frames), 22, 3):
        raise ValueError('Baseline must match duration and skeleton')
    indices, local, root, smooth, rotations, positions = author_keyposes(model, baseline, keys)
    # Native crop_move expects CPU indices and GPU condition values.
    hand = RightHandConstraintSet(model.skeleton, torch.from_numpy(indices),
              torch.from_numpy(positions).to(model.device), torch.from_numpy(rotations).to(model.device),
              torch.from_numpy(smooth).to(model.device))
    saved = hand.get_save_info()
    saved = {k: v.detach().cpu().tolist() if torch.is_tensor(v) else v for k, v in saved.items()}
    (inputs/'constraints.json').write_text(json.dumps(config['route']+[saved], indent=2)+'\n')
    np.savez_compressed(inputs/'native_targets.npz', frame_indices=indices,
                       local_rot_mats=local, global_rot_mats=rotations, posed_joints=positions,
                       root_positions=root, smooth_root_2d=smooth)
    targets = positions[:, 21]
    target_report = {
        'constructor': 'kimodo.constraints.RightHandConstraintSet',
        'position_joints': ['right_wrist'], 'rotation_joints': ['right_wrist'],
        'additional_native_fields': ['smooth_root_xz', 'root_height', 'heading'],
        'frame_indices_zero_based': indices.tolist(), 'time_seconds_native': (indices/30).tolist(),
        'wrist_targets_y_up_m': targets.tolist(), 'root_xz_targets_m': smooth.tolist(),
        'heading_targets': hand.global_root_heading.detach().cpu().tolist(),
        'events': keys, 'reference': config.get('reference', 'Approximate authored action keys'),
        'authorship': 'FK-consistent conditioning poses; only native wrist/root/heading fields are constrained.',
    }
    (args.out/'target_report.json').write_text(json.dumps(target_report, indent=2)+'\n')
    native_started = time.perf_counter()
    output = generate(route+[hand])
    ended = time.perf_counter()
    np.savez_compressed(args.out/'motion.npz', **output)
    relative_rotation = np.einsum('tji,tjk->tik', rotations[:, 21], output['global_rot_mats'][indices, 21])
    angle = np.arccos(np.clip((np.trace(relative_rotation, axis1=-2, axis2=-1)-1)/2, -1, 1))
    metrics = {
        'native': diagnostics(output, key_indices, frames),
        'baseline': diagnostics(baseline, key_indices, frames),
        'target_position_error_m': np.linalg.norm(output['posed_joints'][indices, 21]-targets, axis=-1).tolist(),
        'baseline_target_position_error_m': np.linalg.norm(baseline['posed_joints'][indices, 21]-targets, axis=-1).tolist(),
        'target_wrist_rotation_error_degrees': np.rad2deg(angle).tolist(),
        'root_key_error_m': np.linalg.norm(output['smooth_root_pos'][indices][:, [0, 2]]-smooth, axis=-1).tolist(),
    }
    (args.out/'motion_metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
    report = {
        'model': name, 'config': config, 'native_fps': 30, 'output_frames': sum(frames),
        'model_load_seconds': loaded-started, 'baseline_seconds': base_finished-loaded,
        'native_generation_seconds': ended-native_started, 'total_seconds': ended-started,
        'native_postprocessing': True, 'external_ik': False, 'external_facing_edits': False,
        'external_temporal_smoothing': False, 'blender_used': False, 'skinning_used': False,
        'full_body_keyframes': 0, 'hand_keyframes': len(keys),
        'root_route_samples': sum(len(r['frame_indices']) for r in config['route']),
        'run_id': runtime.run_id(),
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()},
    }
    (args.out/'generation_report.json').write_text(json.dumps(report, indent=2)+'\n')
    print('GENERATION_COMPLETE', json.dumps(metrics), flush=True)


if __name__ == '__main__':
    main()
