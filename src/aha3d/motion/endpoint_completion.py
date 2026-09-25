"""Whole-body Kimodo inpainting with reliable frames on both sides of a gap.

Unlike the partial-body completion experiment, no GVHMR root or pose inside the
gap is a condition. Only reliable endpoint windows are supplied to the model.
"""
import numpy as np
from .completion import forward_kinematics, rotation_error, CompletionRejected, JOINT_NAMES, _rotations


def propose_gaps(keypoints, active, *, confidence=.5, min_visible=5, context=3,
                 image_size=None, mask_support=None):
    kp = np.asarray(keypoints)
    active = np.asarray(active)
    if kp.ndim != 3 or kp.shape[1:] != (17, 3) or active.shape != (len(kp),) or active.dtype != bool:
        raise ValueError('Expected COCO17 keypoints [T,17,3] and boolean lifecycle [T]')
    if context not in (2, 3) or not 1 <= min_visible <= 17 or not 0 < confidence <= 1:
        raise ValueError('Use 2/3 context frames, 1..17 joints and confidence in (0,1]')
    visible = np.isfinite(kp).all(-1) & (kp[..., 2] >= confidence)
    if image_size is not None:
        width, height = image_size
        visible &= (kp[..., 0] >= 0) & (kp[..., 0] < width) & (kp[..., 1] >= 0) & (kp[..., 1] < height)
    if mask_support is not None:
        support = np.asarray(mask_support)
        if support.shape != visible.shape or support.dtype != bool:
            raise ValueError('Mask support must be boolean [T,17]')
        visible &= support
    counts = visible.sum(1)
    low = active & (counts < min_visible)
    reliable = active & ~low
    edges = np.flatnonzero(np.diff(np.r_[False, low, False]))
    gaps = []
    for start, end in edges.reshape(-1, 2):
        left = right = 0
        while left < context and start-left-1 >= 0 and reliable[start-left-1]:
            left += 1
        while right < context and end+right < len(kp) and reliable[end+right]:
            right += 1
        status = 'ready' if min(left, right) >= 2 else 'unresolved_missing_reliable_context'
        if status == 'ready' and end-start+left+right > 300:
            status = 'unresolved_exceeds_model_window'
        gaps.append(dict(start=int(start), end=int(end), left=left, right=right, status=status,
                         constraints=list(range(int(start-left), int(start))) + list(range(int(end), int(end+right)))))
    return dict(visible_counts=counts.tolist(), low_evidence=low.tolist(), gaps=gaps,
                confidence_threshold=confidence, min_visible_keypoints=min_visible, context_frames=context,
                visibility_scope='Detector confidence/raster/mask support is evidence, not calibrated occlusion ground truth')


def transition_report(local, roots, rest, gap, fps=30, max_velocity_jump=1., max_rotation_step=.7):
    """Check actual seams against velocities observed in reliable context windows."""
    _, joints = forward_kinematics(local, roots, rest)
    velocity = np.diff(joints, axis=0)*fps
    start, end = gap['start'], gap['end']
    left = np.linalg.norm(velocity[start-1] - velocity[start-2], axis=-1)
    right = np.linalg.norm(velocity[end-1] - velocity[end], axis=-1)
    rot = rotation_error(local[start-1:end], local[start:end+1])
    speed_jump = float(max(left.max(), right.max()))
    return dict(passed=speed_jump <= max_velocity_jump and float(rot.max()) <= max_rotation_step,
                max_boundary_velocity_jump_m_s=speed_jump,
                max_boundary_acceleration_m_s2=speed_jump*fps,
                max_rotation_step_radians=float(rot.max()),
                velocity_jump_limit_m_s=max_velocity_jump, rotation_step_limit_radians=max_rotation_step)


def splice_endpoint_motion(local, roots, gap, generated_local, generated_root):
    """C2 endpoint bridge plus Kimodo residual, using only reliable source keys.

    The residual envelope and its first two derivatives vanish at both ends.
    Rotations are blended on SO(3), never as matrices or Euler angles. No rejected
    GVHMR gap sample, whole-clip smoothing, IK or facing edit enters this splice.
    Finite-frame FK continuity is still tested after this continuous-time bridge.
    """
    from scipy.interpolate import CubicSpline
    from scipy.spatial.transform import Rotation, RotationSpline
    start, end = gap['start'], gap['end']
    keys = np.asarray(gap['constraints'])
    query = np.arange(start, end)
    bridge_root = CubicSpline(keys, roots[keys])(query)
    bridge = np.stack([RotationSpline(keys, Rotation.from_matrix(local[keys, joint]))(query).as_matrix()
                       for joint in range(22)], axis=1)
    u = (query-(start-1))/(end-start+1)
    weight = 64*u**3*(1-u)**3
    relative = bridge.swapaxes(-1, -2) @ generated_local
    tangent = Rotation.from_matrix(relative.reshape(-1, 3, 3)).as_rotvec().reshape(-1, 22, 3)
    blended = bridge @ Rotation.from_rotvec((tangent*weight[:, None, None]).reshape(-1, 3)).as_matrix().reshape(-1, 22, 3, 3)
    return blended, bridge_root + (generated_root-bridge_root)*weight[:, None]


def generate_gap(model, local, roots, rest, gap, prompt, *, seed=7, steps=50, diagnostic_path=None):
    """Native full-body constraints; gap poses/roots are never read by Kimodo."""
    import torch
    from kimodo.constraints import FullBodyConstraintSet
    from kimodo.tools import seed_everything
    if gap['status'] != 'ready' or not prompt.strip():
        raise ValueError('Completion requires two reliable windows and an action prompt')
    if model.fps != 30 or tuple(model.skeleton.bone_order_names) != JOINT_NAMES:
        raise ValueError('Endpoint completion requires the native 30 Hz SMPL-X22 skeleton')
    start, end = gap['start'], gap['end']
    lo, hi = start-gap['left'], end+gap['right']
    indices = np.asarray(gap['constraints'])
    rotations, positions = forward_kinematics(local[indices], roots[indices], rest)
    # A fixed horizontal translation is numerical conditioning, never scale/floor fitting.
    origin = roots[indices[0]].copy(); origin[1] = 0
    positions -= origin
    tensor = lambda value: torch.as_tensor(value, dtype=torch.float32, device=model.device)
    constraints = FullBodyConstraintSet(model.skeleton, torch.as_tensor(indices-lo),
                                       tensor(positions), tensor(rotations))
    seed_everything(seed)
    result = model([prompt], [hi-lo], constraint_lst=[constraints], num_samples=1,
                   num_denoising_steps=steps, multi_prompt=False,
                   post_processing=True, return_numpy=True)
    candidate_local = np.asarray(result['local_rot_mats'])[0]
    candidate_root = np.asarray(result['root_positions'])[0] + origin
    if candidate_local.shape != (hi-lo, 22, 3, 3) or candidate_root.shape != (hi-lo, 3):
        raise CompletionRejected('Kimodo returned a different timeline or skeleton')
    if not np.isfinite(candidate_local).all() or not np.isfinite(candidate_root).all():
        raise CompletionRejected('Kimodo returned nonfinite motion')
    _rotations(candidate_local)
    anchor_error = dict(root_m=float(np.linalg.norm(candidate_root[indices-lo]-roots[indices], axis=-1).max()),
                        rotation_radians=float(rotation_error(local[indices], candidate_local[indices-lo]).max()))
    if diagnostic_path is not None:
        np.savez_compressed(diagnostic_path, local_rot_mats=candidate_local, root_positions=candidate_root,
                            rest_joints=rest, source_frame_indices=np.arange(lo, hi),
                            constraint_frame_indices=indices, quality_accepted=np.asarray(False))
    if anchor_error['root_m'] > .05 or anchor_error['rotation_radians'] > .10:
        raise CompletionRejected('Decoded endpoint constraints drifted', dict(anchor_error=anchor_error))
    merged_local, merged_root = local.copy(), roots.copy()
    native_local, native_root = local.copy(), roots.copy()
    native_local[start:end] = candidate_local[start-lo:end-lo]
    native_root[start:end] = candidate_root[start-lo:end-lo]
    native_temporal = transition_report(native_local, native_root, rest, gap)
    merged_local[start:end], merged_root[start:end] = splice_endpoint_motion(
        local, roots, gap, candidate_local[start-lo:end-lo], candidate_root[start-lo:end-lo])
    temporal = transition_report(merged_local, merged_root, rest, gap)
    report = dict(anchor_error=anchor_error, temporal=temporal, native_temporal=native_temporal,
                  splice='C2 endpoint bridge plus SO(3) Kimodo residual; no rejected gap samples',
                  constraint_frames=indices.tolist(),
                  prompt=prompt, seed=seed, generated_interval=[start, end],
                  outside_interval_preserved_exactly=True, gap_gvhmr_used_as_condition=False)
    contacts = np.asarray(result['foot_contacts'])[0, start-lo:end-lo]
    if contacts.shape != (end-start, 4) or not np.isfinite(contacts).all():
        raise CompletionRejected('Missing Kimodo foot-contact evidence')
    _, joints = forward_kinematics(merged_local, merged_root, rest)
    velocity = np.gradient(joints, 1/30, axis=0)
    feet = [7, 10, 8, 11]
    support = (np.linalg.norm(velocity[start:end, feet], axis=-1) < .15) & (joints[start:end, feet, 1] < .10)
    report['generated_foot_contacts'] = ((contacts > .5) & support).tolist()
    report['contact_scope'] = 'Native Kimodo foot labels conservatively gated by spliced FK speed/height; no wrist evidence'
    if not temporal['passed']:
        raise CompletionRejected('Generated motion fails boundary continuity checks', report)
    return merged_local, merged_root, report
