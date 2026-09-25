"""Experimental source-preserving Kimodo completion of short hidden-body intervals.

Dense observations AND nonempty text are mandatory. Conditioning is not an exact
preservation guarantee: the final local-pose merge protects each visible joint's
ancestors and verifies source-shaped FK. Root/shape are frozen; this cannot repair
trajectories or move the pelvis onto a different seat. No scene/contact certificate
is implied by the parameter acceptance gate. Model dependencies are imported lazily.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation


JOINT_NAMES = (
    'pelvis', 'left_hip', 'right_hip', 'spine1', 'left_knee', 'right_knee',
    'spine2', 'left_ankle', 'right_ankle', 'spine3', 'left_foot', 'right_foot',
    'neck', 'left_collar', 'right_collar', 'head', 'left_shoulder',
    'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
)
PARENTS = np.array([-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19])
FEATURE_SLICES = {
    'smooth_root_pos': slice(0, 3), 'global_root_heading': slice(3, 5),
    'local_joints_positions': slice(5, 71), 'global_rot_data': slice(71, 203),
    'velocities': slice(203, 269), 'foot_contacts': slice(269, 273),
}
DISTAL_JOINT_IDS = (7, 8, 10, 11, 20, 21)


class CompletionRejected(ValueError):
    """A candidate failed the conservative parameter/FK acceptance gate."""

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


@dataclass(frozen=True)
class CompletionSettings:
    denoising_steps: int = 50
    warm_start_step: int | None = None  # Index in the spaced DDIM schedule, not a training timestep.
    text_guidance: float = 2.0
    constraint_guidance: float = 2.0
    blend_frames: int = 4
    roundtrip_tolerance: float = 2e-5
    preservation_tolerance: float = 1e-7
    max_raw_root_error_m: float = .15
    max_raw_visible_error_m: float = .20
    max_raw_visible_rotation_radians: float = .8
    max_joint_step_radians: float = .70
    max_joint_step_increase_radians: float = .35
    # Source-relative engineering limits at joins, not universal biomechanical
    # limits or claims about the actual hidden action/contact.
    max_boundary_distal_velocity_delta_m_s: float = .5
    max_boundary_distal_acceleration_delta_m_s2: float = 10.

    def validate(self):
        if type(self.denoising_steps) is not int or not 2 <= self.denoising_steps <= 1000:
            raise ValueError('denoising_steps must be an integer from 2 to 1000')
        if self.warm_start_step is not None and (
            type(self.warm_start_step) is not int or not 0 <= self.warm_start_step < self.denoising_steps
        ):
            raise ValueError('warm_start_step must index the selected DDIM schedule')
        if type(self.blend_frames) is not int or self.blend_frames < 1:
            raise ValueError('blend_frames must be a positive integer')
        for name, value in asdict(self).items():
            if name in ('denoising_steps', 'warm_start_step', 'blend_frames'):
                continue
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')


def _rotations(value, shape=None):
    value = np.asarray(value)
    if value.dtype.kind != 'f' or not np.isfinite(value).all():
        raise ValueError('Rotation matrices must be finite floating arrays')
    if shape is not None and value.shape != shape:
        raise ValueError(f'Expected rotation shape {shape}, got {value.shape}')
    if value.shape[-2:] != (3, 3) or not np.allclose(
        value.swapaxes(-1, -2) @ value, np.eye(3), atol=2e-5, rtol=0
    ) or not np.allclose(np.linalg.det(value), 1, atol=2e-5, rtol=0):
        raise ValueError('Expected proper orthonormal rotation matrices; no linear matrix blending')
    return value


def rotation_error(a, b):
    relative = np.asarray(a).swapaxes(-1, -2) @ np.asarray(b)
    return np.linalg.norm(Rotation.from_matrix(relative.reshape(-1, 3, 3)).as_rotvec(), axis=-1).reshape(relative.shape[:-2])


def forward_kinematics(local_rot_mats, root_positions, rest_joints):
    """SMPL-X 22-joint FK, pelvis-position semantics, source-shaped rest offsets."""
    local = np.asarray(local_rot_mats, dtype=np.float64)
    root = np.asarray(root_positions, dtype=np.float64)
    rest = np.asarray(rest_joints, dtype=np.float64)
    global_rot = np.empty_like(local)
    positions = np.empty(local.shape[:-2] + (3,), dtype=np.float64)
    global_rot[:, 0] = local[:, 0]
    positions[:, 0] = root
    for joint in range(1, 22):
        parent = PARENTS[joint]
        global_rot[:, joint] = global_rot[:, parent] @ local[:, joint]
        positions[:, joint] = positions[:, parent] + np.einsum(
            'tij,j->ti', global_rot[:, parent], rest[joint] - rest[parent])
    return global_rot, positions


def ancestor_protection(visible_joint_mask):
    """Include the observed joints themselves to preserve their global rotations."""
    visible = np.asarray(visible_joint_mask)
    if visible.dtype != bool or visible.ndim != 2 or visible.shape[1] != 22:
        raise ValueError('visible_joint_mask must be a boolean [T,22] array')
    protected = visible.copy()
    for joint in range(21, 0, -1):
        protected[:, PARENTS[joint]] |= protected[:, joint]
    protected[:, 0] = True  # First experiment deliberately preserves the trajectory and heading.
    return protected


def boundary_kinematics_report(source_positions, candidate_positions, times, generated, settings):
    """Compare source-shaped distal FK derivatives around edited/protected joins.

    Velocities live at exact timestamp midpoints; acceleration uses the spacing
    between these midpoints. Vector deltas catch direction reversals even when
    speed magnitudes match. An edited ancestor marks its distal descendants.
    Leaf rotation and pose-blendshape surface effects still require mesh review.
    """
    settings.validate()
    reference = np.asarray(source_positions, dtype=float)
    candidate = np.asarray(candidate_positions, dtype=float)
    times = np.asarray(times, dtype=float)
    generated = np.asarray(generated)
    if (reference.ndim != 3 or reference.shape[1:] != (22, 3) or
            candidate.shape != reference.shape or len(reference) < 3 or
            not np.isfinite(reference).all() or not np.isfinite(candidate).all()):
        raise ValueError('Boundary checks require finite source-shaped FK [T,22,3]')
    if times.shape != (len(reference),) or not np.isfinite(times).all() or (np.diff(times) <= 0).any():
        raise ValueError('Boundary checks require exact increasing source timestamps')
    if generated.dtype != bool or generated.shape != reference.shape[:2]:
        raise ValueError('Boundary checks require boolean generated_joint_mask[T,22]')
    influenced = generated.copy()
    for joint in range(1, 22):
        influenced[:, joint] |= influenced[:, PARENTS[joint]]
    influenced = influenced[:, DISTAL_JOINT_IDS]
    transitions = influenced[1:] != influenced[:-1]
    selected = np.zeros_like(transitions)
    radius = settings.blend_frames + 1
    for pair, joint in np.argwhere(transitions):
        selected[max(0, pair - radius):min(len(selected), pair + radius + 1), joint] = True
    dt = np.diff(times)
    velocity_time = (times[1:] + times[:-1]) / 2
    ref_velocity = np.diff(reference[:, DISTAL_JOINT_IDS], axis=0) / dt[:, None, None]
    out_velocity = np.diff(candidate[:, DISTAL_JOINT_IDS], axis=0) / dt[:, None, None]
    ref_acceleration = np.diff(ref_velocity, axis=0) / np.diff(velocity_time)[:, None, None]
    out_acceleration = np.diff(out_velocity, axis=0) / np.diff(velocity_time)[:, None, None]
    acceleration_selected = selected[1:] | selected[:-1]

    def metric(output, source, mask, limit, derivative_times, triplet):
        delta = np.linalg.norm(output - source, axis=-1)
        values = delta[mask]
        maximum = float(values.max()) if values.size else 0.
        worst = None
        if values.size:
            frame, joint = np.unravel_index(np.where(mask, delta, -1.).argmax(), delta.shape)
            worst = {
                'frame_indices': list(range(int(frame), int(frame) + (3 if triplet else 2))),
                'joint': JOINT_NAMES[DISTAL_JOINT_IDS[joint]],
                'derivative_time_seconds': float(derivative_times[frame]),
                'source_magnitude': float(np.linalg.norm(source[frame, joint])),
                'candidate_magnitude': float(np.linalg.norm(output[frame, joint])),
                'vector_delta_magnitude': maximum,
            }
        return {'passed': maximum <= limit, 'limit': float(limit),
                'sample_count': int(values.size), 'maximum': maximum,
                'p95': float(np.percentile(values, 95)) if values.size else 0.,
                'worst_sample': worst}

    velocity = metric(out_velocity, ref_velocity, selected,
                      settings.max_boundary_distal_velocity_delta_m_s,
                      velocity_time, False)
    acceleration = metric(out_acceleration, ref_acceleration, acceleration_selected,
                          settings.max_boundary_distal_acceleration_delta_m_s2,
                          (velocity_time[1:] + velocity_time[:-1]) / 2, True)
    return {
        'passed': velocity['passed'] and acceleration['passed'],
        'scope': 'Source-relative source-shaped distal FK near edited/protected transitions; not hidden-motion truth, contact, slip, or a mesh-surface certificate.',
        'derivatives': 'Forward velocity at exact timestamp midpoints; acceleration between successive velocity midpoints; candidate-minus-source vector norms.',
        'window_radius_frames': radius,
        'distal_joint_names': [JOINT_NAMES[j] for j in DISTAL_JOINT_IDS],
        'transition_pair_start_frame_ids': {JOINT_NAMES[j]: np.flatnonzero(transitions[:, i]).tolist()
                                           for i, j in enumerate(DISTAL_JOINT_IDS)},
        'velocity_pair_start_frame_ids': {JOINT_NAMES[j]: np.flatnonzero(selected[:, i]).tolist()
                                         for i, j in enumerate(DISTAL_JOINT_IDS)},
        'velocity_delta_m_s': velocity,
        'acceleration_delta_m_s2': acceleration,
        'limitations': 'Terminal-joint rotations can move a foot/hand surface without moving its FK joint; source-camera and surface-velocity review remain required.',
    }


def validate_source(source, visible_joint_mask, interval):
    required = ('local_rot_mats', 'root_positions', 'rest_joints', 'joint_names',
                'time_seconds', 'betas', 'source_to_kimodo')
    missing = [name for name in required if name not in source]
    if missing:
        raise ValueError(f'Missing prepared source fields: {missing}')
    local = np.asarray(source['local_rot_mats'])
    if local.ndim != 4:
        raise ValueError('Source must be one actor with [T,22,3,3] rotations')
    frames = len(local)
    _rotations(local, (frames, 22, 3, 3))
    for name, shape in [('root_positions', (frames, 3)), ('rest_joints', (22, 3)),
                        ('time_seconds', (frames,)), ('source_to_kimodo', (4, 4))]:
        array = np.asarray(source[name])
        if array.shape != shape or array.dtype.kind != 'f' or not np.isfinite(array).all():
            raise ValueError(f'{name} must be finite floats with shape {shape}')
    if tuple(np.asarray(source['joint_names']).tolist()) != JOINT_NAMES:
        raise ValueError('Explicit SMPL-X 22-joint anatomical order is required')
    betas = np.asarray(source['betas'])
    if betas.ndim not in (1, 2) or not betas.size or not np.isfinite(betas).all():
        raise ValueError('Finite source shape coefficients are required')
    if betas.ndim == 2 and (betas.shape[0] not in (1, frames) or not np.allclose(betas, betas[:1], atol=1e-6, rtol=0)):
        raise ValueError('Only fixed source shape is supported; provide matching fixed shaped rest joints')
    transform = np.asarray(source['source_to_kimodo'])
    _rotations(transform[:3, :3])
    if not np.array_equal(transform[3], [0, 0, 0, 1]):
        raise ValueError('source_to_kimodo must be a rigid affine transform with scale 1')
    if frames < 3 or not np.allclose(np.diff(source['time_seconds']), 1 / 30, atol=1e-7, rtol=0):
        raise ValueError('This adapter requires timestamp-resampled 30 Hz input; never relabel FPS')
    if len(interval) != 2 or any(type(v) is not int for v in interval):
        raise ValueError('interval must contain integer [start,end) indices')
    start, end = interval
    if not 0 <= start < end <= frames or not 3 <= end - start <= 300:
        raise ValueError('One completion interval must contain 3..300 native frames within the source')
    protected = ancestor_protection(visible_joint_mask)
    if protected.shape != (frames, 22):
        raise ValueError('Visibility timestamps/frames must match the entire source')
    if not visible_joint_mask[start:end].any(axis=1).all():
        raise ValueError('Every completion frame needs visible-body evidence; total disappearance is unsupported')
    if not (~protected[start + 1:end - 1]).any():
        raise ValueError('Visible joints and their ancestors leave no editable hidden joints')
    return protected


def source_from_gvhmr(arrays, rest_joints, source_to_kimodo):
    """Prepare inspect_result.py's native NPZ with supplied shaped SMPL-X rest joints.

    Rest joints must be generated at the source beta and SMPL-X rest pose, without
    world rotation/translation. The pelvis offset is added to SMPL transl. Original
    input arrays are archived under source_gvhmr__ names, avoiding stale incam data.
    """
    prefix = 'smpl_params_global__'
    orient, pose, trans, betas = (np.asarray(arrays[prefix + name]) for name in
                                  ('global_orient', 'body_pose', 'transl', 'betas'))
    frames = len(trans)
    if orient.shape != (frames, 3) or pose.shape not in ((frames, 63), (frames, 21, 3)) or trans.shape != (frames, 3):
        raise ValueError('Expected GVHMR global SMPL-X axis-angle body parameters')
    rest = np.asarray(rest_joints, dtype=float)
    if rest.shape != (22, 3) or not np.isfinite(rest).all():
        raise ValueError('Supply finite source-shaped rest_joints[22,3]')
    rotations = Rotation.from_rotvec(np.concatenate([orient[:, None], pose.reshape(frames, 21, 3)], axis=1).reshape(-1, 3)).as_matrix().reshape(frames, 22, 3, 3)
    source = {f'source_gvhmr__{key}': np.asarray(value).copy() for key, value in arrays.items()}
    source.update(local_rot_mats=rotations, root_positions=np.asarray(trans, dtype=float) + rest[0],
                  rest_joints=rest.copy(), time_seconds=np.asarray(arrays['frame_times_seconds']).copy(),
                  betas=betas.copy(), joint_names=np.asarray(JOINT_NAMES),
                  source_to_kimodo=np.asarray(source_to_kimodo, dtype=float).copy())
    return source


def _numpy(value):
    return value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)


def prepare_conditions(model, source, visible_joint_mask, interval, settings):
    """Encode source-shaped FK, normalize, and constrain visible body at EVERY frame.

    Model statistics/smoothing are used unchanged. Source-shaped positional and
    velocity channels replace mean-shape FK channels. This shape-aware use is
    experimental; the representation roundtrip verifies source parameters and FK,
    not that the fixed-shape training distribution supports all body proportions.
    """
    import torch

    settings.validate()
    protected = validate_source(source, visible_joint_mask, interval)
    rep = model.motion_rep
    if rep.motion_rep_dim != 273 or getattr(model, 'fps', None) != 30:
        raise ValueError('Requires Kimodo 30 Hz / 273-channel SMPL-X motion representation')
    if tuple(model.skeleton.bone_order_names) != JOINT_NAMES:
        raise ValueError('Loaded model skeleton differs from source anatomical order')
    if any(rep.slice_dict.get(name) != sl for name, sl in FEATURE_SLICES.items()):
        raise ValueError('Loaded Kimodo feature layout differs from the audited representation')
    start, end = interval
    local = np.asarray(source['local_rot_mats'][start:end], dtype=float).copy()
    transform = np.asarray(source['source_to_kimodo'])
    basis, offset = transform[:3, :3], transform[:3, 3]
    local[:, 0] = basis @ local[:, 0]
    roots = np.asarray(source['root_positions'][start:end]) @ basis.T + offset
    device = model.device
    tensor = lambda value: torch.as_tensor(np.asarray(value), dtype=torch.float32, device=device)
    with torch.inference_mode():
        raw = rep(tensor(local)[None], tensor(roots)[None], to_normalize=False,
                  lengths=torch.tensor([end - start], device=device))
    if tuple(raw.shape) != (1, end - start, 273) or not torch.isfinite(raw).all():
        raise ValueError('Source feature encoder returned an invalid tensor')
    raw = raw.clone()
    # Keep the first smoothed root XZ at zero, retaining the inverse rigid mapping.
    origin = _numpy(raw[0, 0, :3]).copy()
    origin[1] = 0
    raw[0, :, 0] -= float(origin[0])
    raw[0, :, 2] -= float(origin[2])
    canonical_roots = roots - origin
    global_rot, joints = forward_kinematics(local, canonical_roots, source['rest_joints'])
    hip_vector = joints[:, 2] - joints[:, 1]  # Upstream heading uses right hip minus left hip.
    if (np.linalg.norm(hip_vector[:, [0, 2]], axis=-1) < 1e-8).any():
        raise ValueError('Source-shaped hips do not define a stable horizontal heading')
    heading = np.arctan2(hip_vector[:, 2], -hip_vector[:, 0])
    raw[0, :, 3:5] = tensor(np.column_stack([np.cos(heading), np.sin(heading)]))
    smooth_root = _numpy(raw[0, :, :3]).copy()
    smooth_root[:, 1] = 0
    raw[0, :, 5:71] = tensor((joints - smooth_root[:, None]).reshape(-1, 66))
    raw[0, :, 71:203] = tensor(np.concatenate([global_rot[..., 0], global_rot[..., 1]], axis=-1).reshape(-1, 132))
    velocity = np.diff(joints, axis=0) * 30
    velocity = np.concatenate([velocity, velocity[-1:]], axis=0)
    raw[0, :, 203:269] = tensor(velocity.reshape(-1, 66))
    feet = [7, 10, 8, 11]
    contacts = (np.linalg.norm(velocity[:, feet], axis=-1) < .15) & (joints[:, feet, 1] < .10)
    raw[0, :, 269:273] = tensor(contacts)
    encoded = rep.normalize(raw)
    if not torch.isfinite(encoded).all():
        raise ValueError('Checkpoint normalization produced nonfinite features')
    with torch.inference_mode():
        decoded = rep.inverse(encoded, is_normalized=True, return_numpy=False)
    back_local = _numpy(decoded['local_rot_mats'])[0].astype(float)
    back_local[:, 0] = basis.T @ back_local[:, 0]
    back_root = (_numpy(decoded['root_positions'])[0] + origin - offset) @ basis
    source_local = np.asarray(source['local_rot_mats'][start:end])
    source_root = np.asarray(source['root_positions'][start:end])
    _, expected_joints = forward_kinematics(source_local, source_root, source['rest_joints'])
    _, back_joints = forward_kinematics(back_local, back_root, source['rest_joints'])
    roundtrip = {
        'max_local_rotation_error_radians': float(rotation_error(source_local, back_local).max()),
        'max_root_error_m': float(np.linalg.norm(back_root - source_root, axis=-1).max()),
        'max_source_shaped_fk_error_m': float(np.linalg.norm(back_joints - expected_joints, axis=-1).max()),
    }
    if max(roundtrip.values()) > settings.roundtrip_tolerance:
        raise CompletionRejected('Source representation roundtrip failed before generation', roundtrip)
    mask = torch.zeros_like(encoded, dtype=torch.bool)
    # Root remains frozen, including its true pelvis offset and global rotation.
    mask[..., :5] = True
    observed = protected[start:end].copy()
    observed[[0, -1]] = True  # Complete endpoint poses protect interval joins.
    mask[..., 5:71] = torch.as_tensor(np.repeat(observed, 3, axis=1)[None], device=device)
    mask[..., 71:203] = torch.as_tensor(np.repeat(observed, 6, axis=1)[None], device=device)
    return dict(encoded=encoded, observed_motion=encoded.clone(), motion_mask=mask,
                first_heading_angle=torch.atan2(raw[:, 0, 4], raw[:, 0, 3]),
                canonical_origin=origin, protected=protected, roundtrip=roundtrip,
                source_shaped_conditions=True)


def sample_conditioned(model, conditions, prompt, seed, settings):
    """Real Kimodo denoising API with dense conditions and schedule-correct warm start."""
    import torch

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('A nonempty action prompt is mandatory; text-only fallback is forbidden')
    settings.validate()
    x0 = conditions['encoded']
    if x0.shape[0] != 1 or not conditions['motion_mask'].any(dim=-1).all():
        raise ValueError('Every model frame must carry source constraints')
    device = model.device
    diffusion = model.diffusion
    if settings.denoising_steps > diffusion.num_base_steps:
        raise ValueError('Sampling steps exceed the model training schedule')
    use_timesteps, _ = diffusion.space_timesteps(settings.denoising_steps)
    diffusion.calc_diffusion_vars(use_timesteps)
    generator = torch.Generator(device=device).manual_seed(seed)
    noise = torch.randn(x0.shape, generator=generator, device=device, dtype=x0.dtype)
    start = settings.denoising_steps - 1 if settings.warm_start_step is None else settings.warm_start_step
    current = noise if settings.warm_start_step is None else diffusion.q_sample(
        x0, torch.tensor([start], device=device), noise=noise)
    with torch.inference_mode():
        text_feat, text_lengths = model.text_encoder([prompt.strip()])
        text_feat = text_feat.to(device)
        text_lengths = torch.as_tensor(text_lengths, device=device)
        text_pad = torch.arange(text_feat.shape[1], device=device)[None] < text_lengths[:, None]
        if not text_pad.any():
            raise ValueError('Text encoder produced no valid prompt tokens')
        pad = torch.ones(x0.shape[:2], device=device, dtype=torch.bool)
        steps = torch.tensor([settings.denoising_steps], device=device)
        for index in range(start, -1, -1):
            current = model.denoising_step(
                current, pad, text_feat, text_pad, torch.tensor([index], device=device),
                conditions['first_heading_angle'], conditions['motion_mask'],
                conditions['observed_motion'], steps,
                [settings.text_guidance, settings.constraint_guidance], cfg_type='separated')
            if current.shape != x0.shape or not torch.isfinite(current).all():
                raise CompletionRejected(f'Denoising returned invalid motion at schedule index {index}')
        decoded = model.motion_rep.inverse(current, is_normalized=True, return_numpy=False)
    return decoded, {'warm_start_step': settings.warm_start_step,
                     'start_training_timestep': int(use_timesteps[start].item()),
                     'reverse_steps_executed': start + 1,
                     'source_conditioned_frames': int(conditions['motion_mask'].any(dim=-1).sum().item()),
                     'source_conditioned_features': int(conditions['motion_mask'].sum().item()),
                     'prompt': prompt.strip(), 'seed': int(seed)}


def finalize_candidate(source, visible_joint_mask, interval, candidate_local, candidate_root, settings):
    """Project into valid local rotations, then reject FK or temporal regression."""
    settings.validate()
    protected = validate_source(source, visible_joint_mask, interval)
    start, end = interval
    source_local = np.asarray(source['local_rot_mats'])
    source_root = np.asarray(source['root_positions'])
    candidate_local = _rotations(candidate_local, (end - start, 22, 3, 3))
    candidate_root = np.asarray(candidate_root)
    if candidate_root.shape != (end - start, 3) or not np.isfinite(candidate_root).all():
        raise CompletionRejected('Candidate root has invalid shape/values')
    raw_rot, raw_pos = forward_kinematics(candidate_local, candidate_root, source['rest_joints'])
    baseline_rot, baseline_pos = forward_kinematics(source_local[start:end], source_root[start:end], source['rest_joints'])
    visible = visible_joint_mask[start:end]
    raw = {
        'root_error_m': float(np.linalg.norm(candidate_root - source_root[start:end], axis=-1).max()),
        'visible_position_error_m': float(np.linalg.norm(raw_pos - baseline_pos, axis=-1)[visible].max()),
        'visible_rotation_error_radians': float(rotation_error(baseline_rot, raw_rot)[visible].max()),
    }
    if raw['root_error_m'] > settings.max_raw_root_error_m or raw['visible_position_error_m'] > settings.max_raw_visible_error_m or raw['visible_rotation_error_radians'] > settings.max_raw_visible_rotation_radians:
        raise CompletionRejected('Generated candidate contradicts dense source observations before preservation', {'raw_candidate': raw})
    editable = ~protected[start:end]
    editable[[0, -1]] = False
    # Geodesic blend only. Distance to ANY protected frame tapers edits when a
    # previously hidden joint reappears, not merely at the clip endpoints.
    weights = np.zeros(editable.shape)
    for joint in range(22):
        fixed = np.flatnonzero(~editable[:, joint])
        distance = np.abs(np.arange(end - start)[:, None] - fixed[None]).min(axis=1)
        weights[:, joint] = np.minimum(1., distance / (settings.blend_frames + 1))
    initial = source_local[start:end].astype(float)
    relative = initial.swapaxes(-1, -2) @ candidate_local
    delta = Rotation.from_matrix(relative.reshape(-1, 3, 3)).as_rotvec().reshape(end - start, 22, 3)
    # Do not call float32 codec roundoff a generated motion or overwrite its
    # original source parameter. A source roundtrip alone must fail the no-op gate.
    effective_edit = editable & (np.linalg.norm(delta, axis=-1) * weights > settings.roundtrip_tolerance)
    hard_protected = np.ones_like(protected)
    hard_protected[start:end] = ~effective_edit
    blended = initial @ Rotation.from_rotvec((delta * weights[..., None]).reshape(-1, 3)).as_matrix().reshape(end - start, 22, 3, 3)
    local = source_local.copy()
    local[start:end][effective_edit] = blended[effective_edit].astype(local.dtype)
    # Root, protected local rotations, shape, timestamps and all source metadata
    # are retained byte-for-byte. No raw XYZ or matrix interpolation is used.
    _rotations(local)
    all_rot, all_pos = forward_kinematics(local, source_root, source['rest_joints'])
    ref_rot, ref_pos = forward_kinematics(source_local, source_root, source['rest_joints'])
    visible_error = float(np.linalg.norm(all_pos - ref_pos, axis=-1)[visible_joint_mask].max())
    visible_rot_error = float(rotation_error(ref_rot, all_rot)[visible_joint_mask].max())
    if not np.array_equal(local[hard_protected], source_local[hard_protected]) or max(visible_error, visible_rot_error) > settings.preservation_tolerance:
        raise CompletionRejected('Hard visible-joint/ancestor preservation failed')
    if not np.array_equal(local[:start], source_local[:start]) or not np.array_equal(local[end:], source_local[end:]):
        raise CompletionRejected('Completion altered source frames outside its interval')
    generated = rotation_error(source_local, local) > 1e-8
    affected_pairs = generated[1:] | generated[:-1]
    if not generated.any():
        raise CompletionRejected('Constraints leave no effective generated motion; source remains unchanged')
    output_step = rotation_error(local[:-1], local[1:])
    source_step = rotation_error(source_local[:-1], source_local[1:])
    max_step = float(output_step[affected_pairs].max())
    max_increase = float((output_step - source_step)[affected_pairs].max())
    boundary = boundary_kinematics_report(ref_pos, all_pos, source['time_seconds'], generated, settings)
    temporal_gates = {
        'local_rotation_step': {'passed': max_step <= settings.max_joint_step_radians,
                                'maximum_radians': max_step, 'limit_radians': settings.max_joint_step_radians},
        'local_rotation_step_increase': {'passed': max_increase <= settings.max_joint_step_increase_radians,
                                         'maximum_radians': max_increase,
                                         'limit_radians': settings.max_joint_step_increase_radians},
        'boundary_distal_kinematics': boundary,
    }
    if max_step > settings.max_joint_step_radians or max_increase > settings.max_joint_step_increase_radians:
        raise CompletionRejected('Completion causes an excessive rotation step or temporal regression',
                                 {'max_joint_step_radians': max_step, 'max_step_increase_radians': max_increase,
                                  'temporal_gates': temporal_gates})
    if not boundary['passed']:
        raise CompletionRejected('Completion causes excessive source-relative distal velocity or acceleration near a boundary',
                                 {'raw_candidate': raw, 'visible_fk_max_error_m': visible_error,
                                  'visible_global_rotation_max_error_radians': visible_rot_error,
                                  'max_edited_joint_step_radians': max_step,
                                  'max_edited_step_increase_radians': max_increase,
                                  'temporal_gates': temporal_gates})
    result = {key: deepcopy(value) for key, value in source.items()}
    result.update(local_rot_mats=local, generated_joint_mask=generated,
                  protected_joint_mask=hard_protected, visible_joint_mask=visible_joint_mask.copy())
    # Reconstruct exportable global GVHMR parameters, keeping unaffected
    # axis-angle values exactly as stored (not merely equivalent modulo 2*pi).
    archive_prefix = 'source_gvhmr__smpl_params_global__'
    if archive_prefix + 'body_pose' in source:
        pose = np.asarray(source[archive_prefix + 'body_pose']).copy()
        flat = pose.reshape(len(local), 21, 3)
        edit_body = generated[:, 1:]
        flat[edit_body] = Rotation.from_matrix(local[:, 1:][edit_body]).as_rotvec().astype(flat.dtype)
        result['smpl_params_global__body_pose'] = pose
        for key in ('global_orient', 'transl', 'betas'):
            result['smpl_params_global__' + key] = np.asarray(source[archive_prefix + key]).copy()
    report = {
        'parameter_candidate_accepted': True, 'motion_quality_validated': False,
        'contact_validated': False, 'visible_fk_max_error_m': visible_error,
        'visible_global_rotation_max_error_radians': visible_rot_error,
        'root_preserved_exactly': True, 'shape_preserved_exactly': True,
        'source_timestamps_preserved_exactly': True, 'outside_interval_preserved_exactly': True,
        'raw_candidate': raw, 'max_edited_joint_step_radians': max_step,
        'max_edited_step_increase_radians': max_increase,
        'temporal_gates': temporal_gates,
        'generated_joint_samples': int(generated.sum()),
        'interval_start_end_exclusive': [start, end],
        'provenance': 'GVHMR source estimate with explicitly marked Kimodo-generated hidden-joint samples',
        'limitations': ['Root and visible-joint ancestors are frozen; trajectory drift is not repaired.',
                       'Frozen root/spine can make a different seat or contact target infeasible.',
                       'Dense body constraints and source-shaped features are experimental model use.',
                       'Distal FK transition gates do not certify terminal-joint or pose-blendshape mesh velocities.',
                       'Source-camera mesh review, whole-video timing, and contact validation remain required.'],
    }
    return result, report


def complete_motion(model, source, visible_joint_mask, interval, prompt, *, seed=0, settings=None):
    """One real constrained generation attempt; reject instead of text-only fallback."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('A nonempty action prompt is mandatory')
    settings = CompletionSettings() if settings is None else settings
    visible_joint_mask = np.asarray(visible_joint_mask)
    conditions = prepare_conditions(model, source, visible_joint_mask, interval, settings)
    decoded, sampling = sample_conditioned(model, conditions, prompt, seed, settings)
    local = _numpy(decoded['local_rot_mats'])[0].astype(float)
    transform = np.asarray(source['source_to_kimodo'])
    basis, offset = transform[:3, :3], transform[:3, 3]
    local[:, 0] = basis.T @ local[:, 0]
    root = (_numpy(decoded['root_positions'])[0] + conditions['canonical_origin'] - offset) @ basis
    result, report = finalize_candidate(source, visible_joint_mask, interval, local, root, settings)
    report.update(roundtrip=conditions['roundtrip'], sampling=sampling, settings=asdict(settings))
    return result, report
