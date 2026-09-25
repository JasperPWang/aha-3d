#!/usr/bin/env python3
"""Experimental Kimodo contact-target editing; source and optional guide stay distinct.

Targets are native GVHMR Y-up SMPL-X22 joint trajectories, not mesh contacts.
Dense source preservation and explicit text are mandatory. No inference/download
occurs during preflight. The final FK/transition gate can reject a generated edit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from aha3d import runtime
from aha3d.motion.completion import (
    CompletionRejected, CompletionSettings, JOINT_NAMES, PARENTS, _numpy,
    _rotations, boundary_kinematics_report, forward_kinematics,
    prepare_conditions, rotation_error, sample_conditioned, validate_source,
)
from tools.kimodo.complete_motion import PIN, load_npz, provenance, validate_video_binding


@dataclass(frozen=True)
class ContactSettings(CompletionSettings):
    warm_start_step: int | None = 8
    blend_frames: int = 12
    max_raw_target_position_error_m: float = .20
    max_target_position_error_m: float = .025
    max_target_rotation_error_radians: float = .05


MASKS = ('source_position_mask', 'source_global_rotation_mask',
         'source_local_rotation_mask', 'target_position_mask', 'target_rotation_mask')


def text_scalar(data, key):
    if key not in data or np.asarray(data[key]).shape != ():
        raise ValueError(f'{key} must be an explicit scalar string')
    value = str(data[key].item())
    if not value.strip():
        raise ValueError(f'{key} cannot be blank')
    return value


def maximum(values, mask):
    return float(np.asarray(values)[mask].max()) if mask.any() else 0.


def known_source_rotations(source, constraints):
    """Local rotations imply world rotations only when the parent's world is known."""
    known = constraints['source_global_rotation_mask'].copy()
    for joint in range(22):
        parent_known = True if joint == 0 else known[:, PARENTS[joint]]
        known[:, joint] |= constraints['source_local_rotation_mask'][:, joint] & parent_known
    return known


def validate_inputs(source, constraints, interval, settings, *, initial=None, source_hash=None):
    settings.validate()
    if settings.warm_start_step is None:
        raise ValueError('Contact editing requires an explicit warm-start schedule index')
    # Reuse strict shape/rotation/time/basis validation only. This artificial mask
    # is not visibility evidence and never becomes a model condition or output.
    validation_mask = np.zeros((len(source['time_seconds']), 22), bool)
    validation_mask[:, 15] = True
    validate_source(source, validation_mask, interval)
    start, end = interval
    if end - start >= 300:
        raise ValueError('Contact editing supports fewer than 300 frames per segment')
    count = len(source['time_seconds'])
    if 'edit_interval' in constraints and not np.array_equal(constraints['edit_interval'], interval):
        raise ValueError('Requested interval differs from the target authoring interval')
    validate_video_binding(source, constraints)
    if source_hash is not None and text_scalar(constraints, 'source_sha256') != source_hash:
        raise ValueError('Contact targets are bound to a different prepared original source')
    if tuple(constraints['joint_names'].tolist()) != JOINT_NAMES:
        raise ValueError('Contact target skeleton differs from source SMPL-X22')
    if not np.array_equal(constraints['time_seconds'], source['time_seconds']):
        raise ValueError('Contact targets and source timestamps must match exactly')
    if text_scalar(constraints, 'coordinate_convention') != 'gvhmr-native-y-up':
        raise ValueError('Contact target coordinates must be gvhmr-native-y-up')
    for key in ('constraint_evidence', 'target_evidence'):
        text_scalar(constraints, key)
    result = deepcopy(constraints)
    result.setdefault('target_rotation_mask', np.zeros((count, 22), bool))
    result.setdefault('target_global_rot_mats', np.broadcast_to(np.eye(3), (count, 22, 3, 3)).copy())
    for name in MASKS:
        value = np.asarray(result[name])
        if value.dtype != bool or value.shape != (count, 22):
            raise ValueError(f'{name} must be boolean [T,22]')
    positions = np.asarray(result['target_positions'])
    if positions.shape != (count, 22, 3) or positions.dtype.kind != 'f' or not np.isfinite(positions).all():
        raise ValueError('target_positions must be finite floating [T,22,3], including unmasked values')
    _rotations(result['target_global_rot_mats'], (count, 22, 3, 3))
    if not result['target_position_mask'][start:end].any():
        raise ValueError('At least one explicit joint contact-position target is required')
    for name in ('target_position_mask', 'target_rotation_mask'):
        if result[name][:start].any() or result[name][end:].any():
            raise ValueError('Contact targets outside the editable interval are not supported')
    # Root may only move under an explicit actual-pelvis target. Every other root
    # sample is fixed; this prevents unrequested trajectory editing.
    result['source_position_mask'][:, 0] |= ~result['target_position_mask'][:, 0]
    global_rot, joints = forward_kinematics(source['local_rot_mats'], source['root_positions'], source['rest_joints'])
    target_delta = np.linalg.norm(positions - joints, axis=-1)
    overlap = result['source_position_mask'] & result['target_position_mask']
    if maximum(target_delta, overlap) > settings.preservation_tolerance:
        raise ValueError('Contact target collides with a hard source position constraint')
    known = known_source_rotations(source, result)
    rotation_delta = rotation_error(global_rot, result['target_global_rot_mats'])
    if maximum(rotation_delta, known & result['target_rotation_mask']) > settings.preservation_tolerance:
        raise ValueError('Contact rotation collides with explicit or implied hard source rotations')
    if (maximum(target_delta[[start, end - 1]], result['target_position_mask'][[start, end - 1]]) > settings.preservation_tolerance or
        maximum(rotation_delta[[start, end - 1]], result['target_rotation_mask'][[start, end - 1]]) > settings.preservation_tolerance):
        raise ValueError('Contact target collides with an immutable interval endpoint')
    # Native conditions are world rotations; an isolated protected local rotation
    # with free ancestors is enforced after sampling, not mislabeled a world key.
    dense = result['source_position_mask'] | known
    if not dense[start:end].any(axis=1).all():
        raise ValueError('Every frame requires an encodable source position/global-rotation constraint')
    # Necessary geometric feasibility: adjacent prescribed joints must have the
    # actual source-shaped bone length, not Kimodo's mean-shape bone length.
    pinned = result['source_position_mask'] | result['target_position_mask']
    prescribed = joints.copy()
    prescribed[result['target_position_mask']] = positions[result['target_position_mask']]
    for joint in range(1, 22):
        parent = PARENTS[joint]
        selected = pinned[:, joint] & pinned[:, parent]
        error = np.abs(np.linalg.norm(prescribed[:, joint] - prescribed[:, parent], axis=-1) -
                       np.linalg.norm(source['rest_joints'][joint] - source['rest_joints'][parent]))
        if maximum(error, selected) > 2 * settings.max_target_position_error_m:
            raise ValueError(f'Adjacent prescribed positions violate source-shaped bone length: {JOINT_NAMES[joint]}')
    if initial is not None:
        validate_source(initial, validation_mask, interval)
        validate_video_binding(source, initial)
        for key in ('time_seconds', 'rest_joints', 'betas', 'joint_names', 'source_to_kimodo'):
            if not np.array_equal(source[key], initial[key]):
                raise ValueError(f'Initial guide differs from the ORIGINAL source geometry/timeline/basis: {key}')
    return result


def encode_for_contact(model, source, constraints, interval, settings, initial=None):
    """Actual normalized 273-channel conditions with distinct warm-start features."""
    import torch

    start, end = interval
    codec_mask = np.zeros((len(source['time_seconds']), 22), bool)
    codec_mask[:, 15] = True  # Codec validation only; discarded below.
    source_codec = prepare_conditions(model, source, codec_mask, interval, settings)
    transform = source['source_to_kimodo']
    basis, offset = transform[:3, :3], transform[:3, 3]
    origin = source_codec['canonical_origin']
    rep = model.motion_rep
    tensor = lambda value: torch.as_tensor(np.asarray(value), dtype=torch.float32, device=model.device)

    def rebase(codec):
        raw = rep.unnormalize(codec['encoded']).clone()
        delta = codec['canonical_origin'] - origin
        raw[..., 0] += float(delta[0]); raw[..., 2] += float(delta[2])
        return raw

    trajectory = deepcopy(source)
    root_target_mask = constraints['target_position_mask'][:, 0]
    trajectory['root_positions'][root_target_mask] = constraints['target_positions'][root_target_mask, 0]
    target_codec = prepare_conditions(model, trajectory, codec_mask, interval, settings)
    raw = rebase(target_codec)
    smoothed_reference = _numpy(raw[0, :, :3]).copy()
    smoothed_reference[:, 1] = 0.
    source_rot, source_pos = forward_kinematics(source['local_rot_mats'][start:end],
        source['root_positions'][start:end], source['rest_joints'])
    positions = source_pos.copy()
    pos_target_mask = constraints['target_position_mask'][start:end]
    positions[pos_target_mask] = constraints['target_positions'][start:end][pos_target_mask]
    positions = positions @ basis.T + offset - origin
    rotations = basis @ source_rot
    rot_target_mask = constraints['target_rotation_mask'][start:end]
    rotations[rot_target_mask] = (basis @ constraints['target_global_rot_mats'][start:end])[rot_target_mask]
    raw[0, :, 5:71] = tensor((positions - smoothed_reference[:, None]).reshape(end - start, 66))
    raw[0, :, 71:203] = tensor(np.concatenate([rotations[..., 0], rotations[..., 1]], axis=-1).reshape(end - start, 132))
    mask = torch.zeros_like(raw, dtype=torch.bool)
    # Smooth XYZ is a conditioning reference. Pelvis XYZ is independently present
    # in joint0 position channels and determines the decoded actual root.
    mask[..., :3] = True
    known = known_source_rotations(source, constraints)[start:end]
    pos_mask = (constraints['source_position_mask'] | constraints['target_position_mask'])[start:end].copy()
    rot_mask = (known | rot_target_mask).copy()
    pos_mask[[0, -1]] = True; rot_mask[[0, -1]] = True
    # Complete endpoint conditions agree with the original source by preflight.
    source_raw = rep.unnormalize(source_codec['encoded'])
    raw[:, [0, -1]] = source_raw[:, [0, -1]]
    mask[0, :, 5:71] = torch.as_tensor(np.repeat(pos_mask, 3, axis=1), device=model.device)
    mask[0, :, 71:203] = torch.as_tensor(np.repeat(rot_mask, 6, axis=1), device=model.device)
    # Heading is derivable from the source root rotation when that root is fixed.
    heading_mask = known[:, 0] | rot_target_mask[:, 0]
    hip_offset = source['rest_joints'][2] - source['rest_joints'][1]
    hip_vector = np.einsum('tij,j->ti', rotations[:, 0], hip_offset)
    heading = np.arctan2(hip_vector[:, 2], -hip_vector[:, 0])
    raw[0, :, 3:5] = tensor(np.column_stack([np.cos(heading), np.sin(heading)]))
    mask[0, :, 3:5] = torch.as_tensor(np.repeat(heading_mask[:, None], 2, axis=1), device=model.device)
    initial_codec = source_codec if initial is None else prepare_conditions(model, initial, codec_mask, interval, settings)
    encoded_initial = source_codec['encoded'] if initial is None else rep.normalize(rebase(initial_codec))
    observed = rep.normalize(raw)
    if not torch.isfinite(observed).all() or not torch.isfinite(encoded_initial).all():
        raise ValueError('Nonfinite normalized contact conditions or guide features')
    return dict(encoded=encoded_initial, observed_motion=observed, motion_mask=mask,
                first_heading_angle=source_codec['first_heading_angle'], canonical_origin=origin,
                roundtrip={'original_source': source_codec['roundtrip'], 'root_target_reference': target_codec['roundtrip'],
                           'initial_guide': initial_codec['roundtrip'] if initial is not None else None},
                source_condition_mask=constraints['source_position_mask'][start:end] | known,
                initial_is_distinct_guide=initial is not None)


def blend_weights(editable, frames):
    weights = np.zeros(editable.shape, dtype=float)
    for joint in range(editable.shape[1]):
        fixed = np.flatnonzero(~editable[:, joint])
        distance = np.abs(np.arange(len(editable))[:, None] - fixed[None]).min(axis=1)
        weights[:, joint] = np.minimum(1., distance / (frames + 1))
    return weights


def load_projector(path):
    """Load an explicit, separately hashed project callback; never auto-discover."""
    path=Path(path).resolve(strict=True)
    if path.suffix!='.py':raise ValueError('Projector must be an explicit Python module file')
    info=provenance(path)
    module_name='kimodo_contact_projector_'+info['sha256'][:16]
    spec=importlib.util.spec_from_file_location(module_name,path)
    if spec is None or spec.loader is None:raise ValueError('Cannot import the specified projector')
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module
    spec.loader.exec_module(module)
    function=getattr(module,'project_clean_motion',None)
    if not callable(function):raise ValueError('Projector must export project_clean_motion')
    dependencies=getattr(module,'PROJECTOR_DEPENDENCY_PATHS',[])
    if not isinstance(dependencies,(list,tuple)):raise ValueError('Projector dependency paths must be a list')
    info['dependencies']=[provenance(Path(p) if Path(p).is_absolute() else path.parent/p) for p in dependencies]
    if provenance(path)['sha256']!=info['sha256']:raise ValueError('Projector changed while being loaded')
    return function,info


def apply_clean_projection(model, pred_clean, projector, source, constraints, interval, settings,
                           canonical_origin, schedule_index, training_timestep, inverse):
    """Decode clean x0, project in native coordinates, rebuild shaped features."""
    import torch
    start,end=interval
    if tuple(pred_clean.shape)!=(1,end-start,273) or not torch.isfinite(pred_clean).all():
        raise ValueError('Clean projector expects one finite [1,N,273] prediction')
    decoded=inverse(pred_clean,is_normalized=True,return_numpy=False)
    transform=source['source_to_kimodo'];basis=transform[:3,:3];offset=transform[:3,3]
    local=_numpy(decoded['local_rot_mats'])[0].astype(float)
    local[:,0]=basis.T@local[:,0]
    roots=(_numpy(decoded['root_positions'])[0]+canonical_origin-offset)@basis
    # Per-call copies prevent a callback from mutating ORIGINAL evidence or the
    # next step's fixed constraints, even if it edits its input arrays in place.
    # The denoising loop is inference-only, but an explicitly selected geometric
    # callback may optimize fresh pose tensors. Enable gradients only here;
    # no denoiser parameter gradients or noisy-state gradients are introduced.
    with torch.inference_mode(False),torch.enable_grad():
        projected=projector(local.copy(),roots.copy(),source=deepcopy(source),constraints=deepcopy(constraints),
                            interval=tuple(interval),schedule_index=int(schedule_index),training_timestep=int(training_timestep))
    if not isinstance(projected,dict) or not {'local_rot_mats','root_positions','report'}<=set(projected):
        raise ValueError('Projector must return local_rot_mats, root_positions and report')
    projected_local=_rotations(projected['local_rot_mats'],(end-start,22,3,3))
    projected_root=np.asarray(projected['root_positions'])
    if (projected_root.shape!=(end-start,3) or projected_root.dtype.kind!='f' or not np.isfinite(projected_root).all()):
        raise ValueError('Projected root positions must be finite float [N,3]')
    if not isinstance(projected['report'],dict):raise ValueError('Projector report must be a dictionary')
    json.dumps(projected['report'],allow_nan=False)
    corrected=deepcopy(source)
    corrected['local_rot_mats'][start:end]=projected_local
    corrected['root_positions'][start:end]=projected_root
    validation_mask=np.zeros((len(source['time_seconds']),22),bool);validation_mask[:,15]=True
    codec=prepare_conditions(model,corrected,validation_mask,interval,settings)
    rebuilt=model.motion_rep.unnormalize(codec['encoded']).clone()
    origin_delta=codec['canonical_origin']-canonical_origin
    rebuilt[...,0]+=float(origin_delta[0]);rebuilt[...,2]+=float(origin_delta[2])
    rebuilt=model.motion_rep.normalize(rebuilt).to(dtype=pred_clean.dtype,device=pred_clean.device)
    if rebuilt.shape!=pred_clean.shape or not torch.isfinite(rebuilt).all():raise ValueError('Projected feature re-encoding failed')
    ref_rot,ref_pos=forward_kinematics(source['local_rot_mats'][start:end],source['root_positions'][start:end],source['rest_joints'])
    out_rot,out_pos=forward_kinematics(projected_local,projected_root,source['rest_joints'])
    _,before_pos=forward_kinematics(local,roots,source['rest_joints'])
    target=constraints['target_positions'][start:end];mask=constraints['target_position_mask'][start:end]
    evidence={'schedule_index':int(schedule_index),'training_timestep':int(training_timestep),
        'input_target_fk_max_m':maximum(np.linalg.norm(before_pos-target,axis=-1),mask),
        'projected_target_fk_max_m':maximum(np.linalg.norm(out_pos-target,axis=-1),mask),
        'maximum_projected_root_change_m':float(np.linalg.norm(projected_root-roots,axis=-1).max()),
        'maximum_projected_local_rotation_change_radians':float(rotation_error(local,projected_local).max()),
        'source_local_rotation_max_radians':maximum(rotation_error(source['local_rot_mats'][start:end],projected_local),constraints['source_local_rotation_mask'][start:end]),
        'source_global_rotation_max_radians':maximum(rotation_error(ref_rot,out_rot),constraints['source_global_rotation_mask'][start:end]),
        'source_position_max_m':maximum(np.linalg.norm(ref_pos-out_pos,axis=-1),constraints['source_position_mask'][start:end]),
        'roundtrip':codec['roundtrip'],'projector_report':projected['report']}
    return rebuilt,evidence


def sample_with_feature_evidence(model, conditions, prompt, seed, settings, *, projector=None,
                                 source=None,constraints=None,interval=None,projection_log=None):
    """Observe final features; optionally project only x0 before unchanged DDIM."""
    inverse = model.motion_rep.inverse
    captured = []
    projecting=False
    projection_records=[]
    original_sampler=None
    def observe(features, *args, **kwargs):
        if not projecting:captured.append(features.detach().clone())
        return inverse(features, *args, **kwargs)
    def before_sampler(module, inputs):
        nonlocal projecting
        if len(inputs)!=4:raise ValueError('Audited DDIM sampler argument layout changed')
        use_timesteps,noisy,pred_clean,t=inputs
        if t.numel()!=1:raise ValueError('One actor/schedule index required for clean projection')
        index=int(t.item());training=int(use_timesteps[index].item())
        projecting=True
        try:
            clean,evidence=apply_clean_projection(model,pred_clean,projector,source,constraints,interval,settings,
                conditions['canonical_origin'],index,training,inverse)
        finally:
            projecting=False
        projection_records.append(evidence)
        if projection_log is not None:
            Path(projection_log).write_text(json.dumps({'projection_stage':'predicted clean x0 before unchanged DDIM',
                'steps':projection_records},indent=2,allow_nan=False)+'\n')
        return use_timesteps,noisy,clean,t
    model.motion_rep.inverse = observe
    try:
        if projector is not None:
            if source is None or constraints is None or interval is None:raise ValueError('Clean projector needs original source, constraints and interval')
            import torch
            if not hasattr(model,'sampler') or not isinstance(model.sampler,torch.nn.Module):
                raise ValueError('Loaded model does not expose the audited torch DDIMSampler')
            # Pinned DDIMSampler overrides __call__, bypassing nn.Module forward
            # hooks. An explicit module proxy intercepts that exact public call.
            original_sampler=model.sampler
            class ProjectedSampler(torch.nn.Module):
                def __init__(self,original):
                    super().__init__();self.original=original
                def forward(self,*inputs):
                    return self.original(*before_sampler(self,inputs))
            model.sampler=ProjectedSampler(original_sampler)
        decoded, sampling = sample_conditioned(model, conditions, prompt, seed, settings)
    finally:
        if original_sampler is not None:model.sampler=original_sampler
        model.motion_rep.inverse = inverse
    if len(captured) != 1:
        raise RuntimeError('Expected one final motion-representation decode during sampling')
    if projector is not None:
        if len(projection_records)!=sampling['reverse_steps_executed']:
            raise RuntimeError('Clean projector was not called at every reverse step')
        sampling['clean_projection_steps']=len(projection_records)
        sampling['clean_projection_stage']='predicted clean x0, before unchanged DDIM sampler'
        sampling['clean_projection_interception']='explicit module proxy around original sampler __call__; no forward hooks'
    return decoded, sampling, captured[0]


def finalize_contact(source, constraints, interval, raw_local, raw_root, settings, *, diagnostic_callback=None):
    """Hard source rotation merge plus source-shaped FK and target/transition gates.

    XYZ interpolation is applied only to root translation. Articulated joints
    remain a valid fixed-shape kinematic skeleton; no free joint XYZ replacement.
    """
    start, end = interval
    source_local, source_root = source['local_rot_mats'], source['root_positions']
    raw_local = _rotations(raw_local, (end - start, 22, 3, 3))
    raw_root = np.asarray(raw_root, dtype=float)
    if raw_root.shape != (end - start, 3) or not np.isfinite(raw_root).all():
        raise CompletionRejected('Invalid sampled root trajectory')
    reference_rot, reference_pos = forward_kinematics(source_local, source_root, source['rest_joints'])
    raw_rot, raw_pos = forward_kinematics(raw_local, raw_root, source['rest_joints'])
    sp, sg, sl, tp, tr = (constraints[name][start:end] for name in MASKS)
    raw_metrics = {
        'source_position_max_m': maximum(np.linalg.norm(raw_pos-reference_pos[start:end], axis=-1), sp),
        'source_global_rotation_max_radians': maximum(rotation_error(reference_rot[start:end], raw_rot), sg),
        'source_local_rotation_max_radians': maximum(rotation_error(source_local[start:end], raw_local), sl),
        'target_position_max_m': maximum(np.linalg.norm(raw_pos-constraints['target_positions'][start:end], axis=-1), tp),
    }
    raw_passed = not (raw_metrics['source_position_max_m'] > settings.max_raw_visible_error_m or
        max(raw_metrics['source_global_rotation_max_radians'], raw_metrics['source_local_rotation_max_radians']) > settings.max_raw_visible_rotation_radians or
        raw_metrics['target_position_max_m'] > settings.max_raw_target_position_error_m)
    editable = ~sl.copy(); editable[[0, -1]] = False
    weight = blend_weights(editable, settings.blend_frames)
    initial_local = source_local[start:end].astype(float)
    delta = Rotation.from_matrix((initial_local.swapaxes(-1,-2) @ raw_local).reshape(-1,3,3)).as_rotvec().reshape(end-start,22,3)
    local = source_local.copy()
    effective = editable & (np.linalg.norm(delta,axis=-1)*weight > settings.roundtrip_tolerance)
    blended = initial_local @ Rotation.from_rotvec((delta*weight[...,None]).reshape(-1,3)).as_matrix().reshape(end-start,22,3,3)
    local[start:end][effective] = blended[effective]
    # Restore requested world rotations through valid child local rotations. A
    # competing exact local key is checked rather than silently overwritten.
    world = np.empty_like(local[start:end]);rotation_conflicts=[]
    for joint in range(22):
        parent = PARENTS[joint]
        current_world = local[start:end,joint] if joint==0 else world[:,parent] @ local[start:end,joint]
        selected = sg[:,joint]
        desired_local = reference_rot[start:end,joint] if joint==0 else world[:,parent].swapaxes(-1,-2) @ reference_rot[start:end,joint]
        if maximum(rotation_error(local[start:end,joint], desired_local), selected & sl[:,joint]) > settings.preservation_tolerance:
            rotation_conflicts.append(JOINT_NAMES[joint])
        change = selected & ~sl[:,joint] & (rotation_error(current_world,reference_rot[start:end,joint]) > settings.preservation_tolerance)
        local[start:end,joint][change] = desired_local[change]
        world[:,joint] = local[start:end,joint] if joint==0 else world[:,parent] @ local[start:end,joint]
    root_editable = ~sp[:,0].copy(); root_editable[[0,-1]]=False
    root_weight = blend_weights(root_editable[:,None],settings.blend_frames)[:,0]
    root_delta = raw_root-source_root[start:end]
    root_effective = root_editable & (np.linalg.norm(root_delta,axis=-1)*root_weight > settings.roundtrip_tolerance)
    roots = source_root.copy()
    roots[start:end][root_effective] = (source_root[start:end]+root_delta*root_weight[:,None])[root_effective]
    _rotations(local)
    out_rot,out_pos = forward_kinematics(local,roots,source['rest_joints'])
    source_metrics = {
        'position_max_m':maximum(np.linalg.norm(out_pos-reference_pos,axis=-1),constraints['source_position_mask']),
        'global_rotation_max_radians':maximum(rotation_error(reference_rot,out_rot),constraints['source_global_rotation_mask']),
        'local_rotation_max_radians':maximum(rotation_error(source_local,local),constraints['source_local_rotation_mask']),
        'local_rotation_parameters_exact':bool(np.array_equal(local[constraints['source_local_rotation_mask']],source_local[constraints['source_local_rotation_mask']]))}
    target_metrics = {
        'position_max_m':maximum(np.linalg.norm(out_pos-constraints['target_positions'],axis=-1),constraints['target_position_mask']),
        'rotation_max_radians':maximum(rotation_error(out_rot,constraints['target_global_rot_mats']),constraints['target_rotation_mask']),
        'position_limit_m':settings.max_target_position_error_m,
        'rotation_limit_radians':settings.max_target_rotation_error_radians}
    generated = rotation_error(source_local,local)>1e-8
    generated_root = np.linalg.norm(roots-source_root,axis=-1)>1e-8
    affected = generated.copy();affected[:,0] |= generated_root
    pairs = generated[1:] | generated[:-1]
    step=rotation_error(local[:-1],local[1:]);ref_step=rotation_error(source_local[:-1],source_local[1:])
    maximum_step=maximum(step,pairs);maximum_increase=maximum(step-ref_step,pairs)
    boundary=boundary_kinematics_report(reference_pos,out_pos,source['time_seconds'],affected,settings)
    gates={
        'raw_source_and_target':dict(raw_metrics,passed=raw_passed),
        'effective_edit':{'passed':bool(affected.any())},
        'source_preservation':dict(source_metrics,passed=source_metrics['local_rotation_parameters_exact'] and max(source_metrics[k] for k in ('position_max_m','global_rotation_max_radians','local_rotation_max_radians'))<=settings.preservation_tolerance),
        'target_fk':dict(target_metrics,passed=target_metrics['position_max_m']<=settings.max_target_position_error_m and target_metrics['rotation_max_radians']<=settings.max_target_rotation_error_radians),
        'local_rotation_steps':{'maximum_radians':maximum_step,'maximum_increase_radians':maximum_increase,'passed':maximum_step<=settings.max_joint_step_radians and maximum_increase<=settings.max_joint_step_increase_radians},
        'boundary_distal_kinematics':boundary}
    report={'raw_candidate':raw_metrics,'gates':gates,'parameter_candidate_accepted':all(g['passed'] for g in gates.values()),
            'contact_validated':False,'motion_quality_validated':False,'generated_joint_samples':int(generated.sum()),
            'generated_root_frames':int(generated_root.sum()),'interval_start_end_exclusive':interval,
            'shape_preserved_exactly':True,'source_timestamps_preserved_exactly':True,'rotation_constraint_conflicts':rotation_conflicts,
            'upper_preservation_scope':'Only the explicit source local/global rotation and position masks; local gesture preservation does not assert absolute source image alignment.',
            'limitations':['Joint target residuals do not certify mesh contact area, interpenetration or source-view fidelity.',
                           'Dense constraints and shaped positions are experimental use of the trained 273-channel model.',
                           'Root target movement can alter source camera alignment; evaluate with original camera transforms.',
                           'Distal FK gates do not measure terminal-joint or pose-blendshape mesh surface velocities.']}
    outside=np.ones(len(local),bool);outside[start+1:end-1]=False
    report['outside_interval_and_endpoints_preserved_exactly']=bool(np.array_equal(local[outside],source_local[outside]) and np.array_equal(roots[outside],source_root[outside]))
    result=deepcopy(source)
    result.update(local_rot_mats=local,root_positions=roots,generated_joint_mask=generated,
                  generated_root_mask=generated_root,source_estimate_local_rot_mats=source_local.copy(),
                  source_estimate_root_positions=source_root.copy())
    for key in MASKS:result[key]=constraints[key].copy()
    result['contact_edit_parameter_candidate_accepted']=np.asarray(report['parameter_candidate_accepted'])
    result['motion_provenance']=np.asarray('Experimental Kimodo-generated contact edit of GVHMR source; acceptance flag and report required; mesh contact unvalidated')
    archive='source_gvhmr__smpl_params_global__'
    if archive+'body_pose' in source:
        pose=source[archive+'body_pose'].copy();flat=pose.reshape(len(local),21,3)
        if generated[:,1:].any():
            flat[generated[:,1:]]=Rotation.from_matrix(local[:,1:][generated[:,1:]]).as_rotvec().astype(flat.dtype)
        orient=source[archive+'global_orient'].copy()
        if generated[:,0].any():
            orient[generated[:,0]]=Rotation.from_matrix(local[:,0][generated[:,0]]).as_rotvec().astype(orient.dtype)
        trans=source[archive+'transl'].copy()
        trans[generated_root]=(roots-source['rest_joints'][0])[generated_root].astype(trans.dtype)
        result.update(smpl_params_global__body_pose=pose,smpl_params_global__global_orient=orient,
                      smpl_params_global__transl=trans,smpl_params_global__betas=source[archive+'betas'].copy())
    if diagnostic_callback is not None:
        diagnostic_callback(result,report)
    if not report['outside_interval_and_endpoints_preserved_exactly']:
        raise CompletionRejected('Contact edit altered immutable source interval boundary',report)
    if not report['parameter_candidate_accepted']:
        failed=[name for name,gate in gates.items() if not gate['passed']]
        prefix='Raw sampled motion contradicts source/target; ' if not raw_passed else 'No effective motion edit; ' if not affected.any() else ''
        raise CompletionRejected(prefix+'Contact candidate failed gates: '+', '.join(failed),report)
    return result,report


def run(args):
    if not args.prompt.strip():raise ValueError('Nonempty text prompt is mandatory')
    if args.output.exists():raise ValueError('Use a fresh claimed output directory')
    settings=ContactSettings(denoising_steps=args.steps,warm_start_step=args.warm_start_step,blend_frames=args.blend_frames)
    source=load_npz(args.source);initial=load_npz(args.initial_motion) if args.initial_motion else None
    interval=[args.start_frame,args.end_frame]
    constraints=validate_inputs(source,load_npz(args.constraints),interval,settings,initial=initial,source_hash=provenance(args.source)['sha256'])
    projector,projector_info=load_projector(args.projector) if args.projector else (None,None)
    report={'schema_version':1,'operation':'Experimental Kimodo joint-target contact editing',
            'source':provenance(args.source),'constraints':provenance(args.constraints),
            'initial_motion':provenance(args.initial_motion) if args.initial_motion else None,
            'initial_motion_role':'Warm-start features only; ORIGINAL source defines all preservation and evaluation',
            'clean_projector':projector_info,
            'settings':asdict(settings),'interval_start_end_exclusive':interval,'prompt':args.prompt,'seed':args.seed,
            'adapter':provenance(__file__),'completion_module':provenance(ROOT/'src/aha3d/motion/completion.py'),
            'constraint_evidence':text_scalar(constraints,'constraint_evidence'),'target_evidence':text_scalar(constraints,'target_evidence'),
            'model_executed':False,'parameter_candidate_accepted':False,'contact_validated':False,'motion_quality_validated':False}
    report['constraint_sample_counts']={name:int(constraints[name][interval[0]:interval[1]].sum()) for name in MASKS}
    report['constraint_sample_counts']['known_source_global_rotations']=int(known_source_rotations(source,constraints)[interval[0]:interval[1]].sum())
    args.output.mkdir(parents=True,exist_ok=False)
    try:
        with (args.output/'effective_constraints.npz').open('xb') as stream:
            np.savez_compressed(stream,**constraints)
        if args.preflight:
            report['preflight_passed']=True
            return 0
        if args.upstream is None or args.checkpoint is None:raise ValueError('Actual execution requires --upstream and --checkpoint')
        upstream=args.upstream.resolve(strict=True)
        git=['git','-c',f'safe.directory={upstream}','-C',str(upstream)]
        revision=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
        if revision!=PIN or subprocess.check_output(git+['status','--porcelain','--untracked-files=no'],text=True).strip():
            raise ValueError('Audited pinned Kimodo checkout is missing or modified')
        checkpoint=args.checkpoint.resolve(strict=True)
        if checkpoint.name!='Kimodo-SMPLX-RP-v1' or not (checkpoint/'config.yaml').is_file():
            raise ValueError('Use the existing canonical Kimodo-SMPLX-RP-v1 checkpoint directory')
        report.update(upstream_commit=revision,checkpoint_files=[provenance(p) for p in sorted(checkpoint.rglob('*')) if p.is_file()],
                      execution='local',run_id=runtime.run_id())
        os.environ.update(CHECKPOINT_DIR=str(checkpoint.parent),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TEXT_ENCODER_MODE='local')
        sys.path.insert(0,str(upstream))
        import torch
        from kimodo import load_model
        report['torch_version']=torch.__version__
        model=load_model('Kimodo-SMPLX-RP-v1',device=args.device)
        conditions=encode_for_contact(model,source,constraints,interval,settings,initial=initial)
        with (args.output/'conditions.npz').open('xb') as stream:
            np.savez_compressed(stream,encoded_initial=_numpy(conditions['encoded']),observed_motion=_numpy(conditions['observed_motion']),
                motion_mask=_numpy(conditions['motion_mask']),canonical_origin=conditions['canonical_origin'],joint_names=np.asarray(JOINT_NAMES))
        report['roundtrip']=conditions['roundtrip']
        report['sampling_attempted']=True
        decoded,sampling,final_features=sample_with_feature_evidence(model,conditions,args.prompt,args.seed,settings,
            projector=projector,source=source,constraints=constraints,interval=interval,
            projection_log=args.output/'projection_steps.json' if projector is not None else None)
        report.update(model_executed=True,sampling=sampling)
        sampling['conditioning_count_scope']='Inherited mask counts include BOTH source preservation features and contact target features; they are not visibility counts.'
        local=_numpy(decoded['local_rot_mats'])[0].astype(float)
        basis=source['source_to_kimodo'][:3,:3];offset=source['source_to_kimodo'][:3,3]
        local[:,0]=basis.T@local[:,0]
        roots=(_numpy(decoded['root_positions'])[0]+conditions['canonical_origin']-offset)@basis
        raw_features=_numpy(model.motion_rep.unnormalize(final_features))[0]
        position_channels=raw_features[:,5:71].reshape(-1,22,3)+raw_features[:,:3][:,None]*[1,0,1]
        position_channels=(position_channels+conditions['canonical_origin']-offset)@basis
        _,raw_shaped_fk=forward_kinematics(local,roots,source['rest_joints'])
        target_mask=constraints['target_position_mask'][interval[0]:interval[1]]
        report['predicted_position_channel_evidence']={
            'feature_origin':'final sampler output after explicit clean geometric projection' if projector is not None else 'final neural sampler output without geometric projection',
            'position_channels_to_targets_max_m':maximum(np.linalg.norm(position_channels-constraints['target_positions'][interval[0]:interval[1]],axis=-1),target_mask),
            'source_shaped_fk_to_targets_max_m':maximum(np.linalg.norm(raw_shaped_fk-constraints['target_positions'][interval[0]:interval[1]],axis=-1),target_mask),
            'position_channels_to_source_shaped_fk_target_samples_max_m':maximum(np.linalg.norm(position_channels-raw_shaped_fk,axis=-1),target_mask),
            'position_channels_to_source_shaped_fk_all_joints_max_m':float(np.linalg.norm(position_channels-raw_shaped_fk,axis=-1).max()),
            'scope':'Final sampler position features versus FK from its rotations and ORIGINAL source-shaped rest joints. With a projector, consistency is imposed by geometric re-encoding; pre-projection errors are recorded separately.'}
        with (args.output/'final_model_features.npz').open('xb') as stream:
            np.savez_compressed(stream,normalized_features=_numpy(final_features),raw_features=raw_features,
                predicted_position_channels_native=position_channels,predicted_rotation_source_shaped_fk_native=raw_shaped_fk)
        with (args.output/'raw_candidate.npz').open('xb') as stream:
            np.savez_compressed(stream,local_rot_mats=local,root_positions=roots,interval_start_end_exclusive=np.asarray(interval),
                time_seconds=source['time_seconds'][interval[0]:interval[1]],source_sha256=np.asarray(report['source']['sha256']))
        def diagnostic_callback(candidate,metrics):
            diagnostic=deepcopy(candidate)
            diagnostic['diagnostic_only']=np.asarray(True)
            with (args.output/'diagnostic_candidate.npz').open('xb') as stream:
                np.savez_compressed(stream,**diagnostic)
            (args.output/'diagnostic_report.json').write_text(json.dumps(metrics,indent=2)+'\n')
        result,metrics=finalize_contact(source,constraints,interval,local,roots,settings,diagnostic_callback=diagnostic_callback)
        report.update(metrics)
        with (args.output/'candidate.npz').open('xb') as stream:np.savez_compressed(stream,**result)
        return 0
    except CompletionRejected as error:
        report.update(error.report,rejection=str(error),parameter_candidate_accepted=False)
        return 2
    except Exception as error:
        report['setup_or_execution_error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','constraints','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('initial-motion','upstream','checkpoint','projector'):p.add_argument('--'+name,type=Path)
    p.add_argument('--device',default='cuda:0')
    p.add_argument('--start-frame',type=int,required=True);p.add_argument('--end-frame',type=int,required=True)
    p.add_argument('--prompt',required=True);p.add_argument('--seed',type=int,default=7)
    p.add_argument('--steps',type=int,default=50);p.add_argument('--warm-start-step',type=int,default=8)
    p.add_argument('--blend-frames',type=int,default=12);p.add_argument('--preflight',action='store_true')
    return run(p.parse_args())


if __name__=='__main__':raise SystemExit(main())
