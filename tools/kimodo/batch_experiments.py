#!/usr/bin/env python3
"""Run frozen, visibility-reviewed completion experiments with one real model load.

Claim manifest/output paths before use. All cases require video/actor-bound source
and dense visibility evidence. Failed candidates are preserved for scene review;
their structural preservation merge never overrides their original rejection.
This is experimental hidden-part replacement, not whole-video regeneration or a
contact solver. Scene-specific contact experiments use contact_edit.py separately.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from aha3d import runtime
from aha3d.motion.completion import (
    CompletionRejected, CompletionSettings, JOINT_NAMES, _rotations,
    finalize_candidate, forward_kinematics, prepare_conditions, rotation_error,
    sample_conditioned, validate_source,
)
from tools.kimodo.complete_motion import (
    PIN, constraint_mask, load_npz, provenance, validate_video_binding,
)

PROTOCOL = dict(denoising_steps=50, seed=7, blend_frames=4,
                variants={'pure_noise': None, 'low_noise_8': 8, 'medium_noise_24': 24})
ADAPTERS = (
    'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp',
    'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised',
)
LOWER_BODY_IDS = (1, 2, 4, 5, 7, 8, 10, 11)
REPLACEMENT_AUTHORIZATION = 'deliberate_lower_body_replacement_visible_lower_body_may_change'


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def checked_file(record):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
        raise ValueError('Each input requires exactly path and sha256')
    path = Path(record['path'])
    if not path.is_absolute():
        path = ROOT / path
    actual = provenance(path)
    if actual['sha256'] != record['sha256']:
        raise ValueError('Frozen input hash mismatch: ' + str(path))
    return Path(actual['path'])


def validate_case(case):
    """CPU-only source/visibility preflight; no confidence-derived visibility."""
    if not isinstance(case.get('id'), str) or not re.fullmatch(r'[a-z0-9_]+', case['id']):
        raise ValueError('Case IDs must be safe lowercase identifiers')
    prompt = case.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Nonempty source-action text is mandatory')
    if case.get('kind') not in ('reviewed_hidden_part_completion', 'deliberate_lower_body_replacement'):
        raise ValueError('Choose an explicit reviewed completion or deliberate lower-body replacement mode')
    interval = case.get('interval')
    if not isinstance(interval, list) or len(interval) != 2 or any(type(x) is not int for x in interval):
        raise ValueError('An integer start/end-exclusive interval is required')
    if interval[1] - interval[0] >= 300:
        raise ValueError('Each model context must contain fewer than 300 frames')
    source_path, visible_path = checked_file(case['source']), checked_file(case['visibility'])
    source, observations = load_npz(source_path), load_npz(visible_path)
    binding = validate_video_binding(source, observations)
    if tuple(observations['joint_names'].tolist()) != JOINT_NAMES:
        raise ValueError('Visibility anatomical order differs from SMPL-X22')
    if not np.array_equal(source['time_seconds'], observations['time_seconds']):
        raise ValueError('Source and visibility PTS must match exactly')
    evidence = str(np.asarray(observations.get('visibility_evidence', '')).item()).strip()
    if not evidence or evidence.lower() in ('none', 'unknown'):
        raise ValueError('Actual source visibility review evidence is required')
    if case['kind'] == 'reviewed_hidden_part_completion':
        mask, review = constraint_mask(observations, interval, require_reviewed_states=True)
    else:
        # This distinct, explicitly authorized experiment releases source-visible
        # lower-body estimates without relabelling them hidden. Occlusion policy
        # above stays unchanged, including its unknown/visible edit rejection.
        if case.get('editing_authorization') != REPLACEMENT_AUTHORIZATION or not str(case.get('editing_reason', '')).strip():
            raise ValueError('Visible lower-body replacement requires explicit authorization and reason')
        released = case.get('released_joint_ids')
        if not isinstance(released, list) or not released or any(type(j) is not int for j in released) or len(set(released)) != len(released) or not set(released) <= set(LOWER_BODY_IDS):
            raise ValueError('Only explicitly listed lower-body joints may be released')
        visible, state = observations['visible_joint_mask'], observations.get('visibility_state')
        if visible.dtype != bool or visible.shape != (len(source['time_seconds']), 22) or state is None:
            raise ValueError('Actual full-timeline visibility and state are required for replacement')
        state = np.asarray(state)
        if state.shape != visible.shape or state.dtype.kind not in 'iu' or not np.isin(state, [-1, 0, 1]).all() or not np.array_equal(state == 1, visible):
            raise ValueError('Replacement retains actual visible/hidden/uncertain annotations exactly')
        a, b = interval
        upper = np.ones(22, bool); upper[list(LOWER_BODY_IDS) + [0]] = False
        observed_upper = visible[a:b, upper].any(axis=1)
        allow_estimates = case.get('allow_unobserved_source_estimates', False)
        if type(allow_estimates) is not bool:
            raise ValueError('Unobserved source-estimate permission must be explicit boolean')
        if not observed_upper.all() and (not allow_estimates or not str(case.get('unobserved_constraints_scope', '')).strip()):
            raise ValueError('Unobserved upper-body estimates require a separate explicit declaration and scope')
        mask = np.ones(visible.shape, bool)
        mask[a:b, released] = False
        review = dict(semantics='Deliberate generated lower-body replacement, not hidden completion; visible released legs lose exact source preservation',
                      actual_visible_released_joint_samples=int(visible[a:b, released].sum()),
                      all_upper_local_rotations_and_ancestors_protected=True,
                      actual_observed_upper_frames=int(observed_upper.sum()),
                      frames_without_positive_upper_visibility_annotation=int((~observed_upper).sum()),
                      unobserved_source_estimates_authorized=allow_estimates,
                      unobserved_constraints_scope=case.get('unobserved_constraints_scope'),
                      released_joint_ids=released, editing_authorization=case['editing_authorization'],
                      editing_reason=case['editing_reason'])
    protected = validate_source(source, mask, interval)
    # A renderable native export must preserve the actual source archive.
    prefix = 'source_gvhmr__smpl_params_global__'
    for name in ('body_pose', 'global_orient', 'transl', 'betas'):
        if prefix + name not in source:
            raise ValueError('Prepared source requires original native global SMPL-X parameters')
    report = dict(id=case['id'], source=provenance(source_path), visibility=provenance(visible_path),
                  interval=interval, prompt=prompt.strip(), video_actor_binding=binding,
                  visibility_evidence=evidence, constraint_review=review,
                  editable_joint_names=[JOINT_NAMES[j] for j in np.flatnonzero((~protected[interval[0]:interval[1]]).any(axis=0))],
                  source_frames=len(source['time_seconds']), fps=30,
                  source_basis='Recorded source_to_kimodo rigid transform; native export retains source basis',
                  shape_policy='Exact source beta and source-shaped rest skeleton; no rescaling',
                  unknown_visibility_never_editable=case['kind'] == 'reviewed_hidden_part_completion',
                  kind=case['kind'])
    return source, observations, mask, report


def validate_manifest(manifest):
    if manifest.get('schema_version') != 1 or manifest.get('protocol') != PROTOCOL:
        raise ValueError('Manifest must freeze the exact reviewed 50-step, seed7, blend4, pure/8/24 protocol')
    cases = manifest.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('At least one reviewed case is required')
    checked = [validate_case(case) for case in cases]
    names = [case['id'] for case in cases]
    if len(names) != len(set(names)):
        raise ValueError('Case IDs must be unique')
    contact_names = []
    for case in manifest.get('contact_cases', []):
        validate_contact_case(case)
        contact_names.append(case['id'])
    if len(set(names + contact_names)) != len(names + contact_names):
        raise ValueError('Completion and contact case IDs must be distinct')
    return checked


def validate_contact_case(case):
    """Frozen medium-noise contact ablation; preservation stays in contact_edit."""
    from tools.kimodo.contact_edit import ContactSettings, validate_inputs
    if not isinstance(case.get('id'), str) or not re.fullmatch(r'[a-z0-9_]+', case['id']):
        raise ValueError('Contact case requires a safe explicit ID')
    if case.get('warm_start_step') != 24 or case.get('steps') != 50 or case.get('seed') != 7 or case.get('blend_frames') != 18:
        raise ValueError('This contact comparison requires the frozen medium24/50, seed7, blend18 protocol')
    if not isinstance(case.get('prompt'), str) or not case['prompt'].strip():
        raise ValueError('Actual source-action contact text is mandatory')
    paths = {key: checked_file(case[key]) for key in ('source', 'constraints', 'initial_motion', 'projector', 'target_manifest')}
    if not case.get('implementation_bindings'):
        raise ValueError('Frozen contact comparison requires adapter/projector dependency hashes')
    for record in case['implementation_bindings']:
        checked_file(record)
    authored = json.loads(paths['target_manifest'].read_text())
    if not authored.get('declared_before_generation') or authored['prompt'] != case['prompt'] or authored['edit_interval_start_end_exclusive'] != case['interval']:
        raise ValueError('Contact prompt/interval differs from the frozen target experiment')
    if authored['target_sha256'] != case['constraints']['sha256'] or authored['source_sha256'] != case['source']['sha256']:
        raise ValueError('Contact original source or targets differ from the frozen authoring manifest')
    source, initial = load_npz(paths['source']), load_npz(paths['initial_motion'])
    settings = ContactSettings(warm_start_step=24, blend_frames=18)
    constraints = validate_inputs(source, load_npz(paths['constraints']), case['interval'], settings,
                                  initial=initial, source_hash=case['source']['sha256'])
    return source, constraints, initial, paths, settings


def run_contact_case(model, encoder, case, folder):
    """Reuse loaded real model/text, existing clean projection and unchanged gates."""
    from tools.kimodo.contact_edit import (encode_for_contact, finalize_contact, load_projector,
                                          maximum, sample_with_feature_evidence)
    source, constraints, initial, paths, settings = validate_contact_case(case)
    projector, projector_info = load_projector(paths['projector'])
    folder.mkdir()
    report = dict(schema_version=1, kind='frozen_contact_medium_noise_ablation', case=case,
                  settings=asdict(settings), model_executed=False, parameter_candidate_accepted=False,
                  contact_validated=False, motion_quality_validated=False, clean_projector=projector_info,
                  adapter=provenance(ROOT / 'tools/kimodo/contact_edit.py'), stage_wall_seconds={},
                  initial_motion_role='Guide initialization only; ORIGINAL source controls preservation and evaluation',
                  matched_geometric_control=case.get('matched_geometric_control'),
                  comparison='Only warm-start schedule strength changes from the frozen final low8 experiment')
    np.savez_compressed(folder / 'effective_constraints.npz', **constraints)
    started = time.perf_counter()
    conditions = encode_for_contact(model, source, constraints, case['interval'], settings, initial=initial)
    synchronize(model.device)
    report['stage_wall_seconds']['geometry_and_roundtrip'] = time.perf_counter() - started
    report['roundtrip'] = conditions['roundtrip']
    np.savez_compressed(folder / 'conditions.npz', encoded_initial=conditions['encoded'].detach().cpu().numpy(),
        observed_motion=conditions['observed_motion'].detach().cpu().numpy(), motion_mask=conditions['motion_mask'].detach().cpu().numpy(),
        canonical_origin=conditions['canonical_origin'])
    encoder([case['prompt']])
    report['text_encoding'] = encoder.records[case['prompt']]
    model.diffusion.calc_diffusion_vars(model.diffusion.space_timesteps(50)[0])
    alpha = float(model.diffusion.alphas_cumprod[24].item())
    report['noise'] = dict(schedule_index=24, alpha_bar=alpha, signal_multiplier=float(np.sqrt(alpha)),
                           noise_multiplier=float(np.sqrt(1-alpha)), initialization='q_sample of the unchanged geometric guide')
    projector_seconds = []

    def measured_projector(*args, **kwargs):
        start = time.perf_counter()
        try:
            return projector(*args, **kwargs)
        finally:
            projector_seconds.append(time.perf_counter() - start)

    write_json(folder / 'report.json', report)
    synchronize(model.device); started = time.perf_counter()
    decoded, sampling, features = sample_with_feature_evidence(model, conditions, case['prompt'], 7, settings,
        projector=measured_projector, source=source, constraints=constraints, interval=case['interval'],
        projection_log=folder / 'projection_steps.json')
    synchronize(model.device)
    total = time.perf_counter() - started
    report['stage_wall_seconds'].update(sampling_including_geometry=total, geometric_solve=sum(projector_seconds),
        sampling_and_codec_excluding_geometric_callback=total-sum(projector_seconds))
    report.update(model_executed=True, sampling=sampling, projector_call_seconds=projector_seconds)
    local, roots = decoded_native(decoded, source, conditions)
    a, b = case['interval']
    raw_features = model.motion_rep.unnormalize(features).detach().cpu().numpy()[0]
    positions = raw_features[:, 5:71].reshape(-1, 22, 3) + raw_features[:, :3][:, None] * [1, 0, 1]
    basis, offset = source['source_to_kimodo'][:3, :3], source['source_to_kimodo'][:3, 3]
    positions = (positions + conditions['canonical_origin'] - offset) @ basis
    _, fk = forward_kinematics(local, roots, source['rest_joints'])
    target, mask = constraints['target_positions'][a:b], constraints['target_position_mask'][a:b]
    report['position_channel_evidence'] = dict(
        position_channels_to_target_max_m=maximum(np.linalg.norm(positions-target, axis=-1), mask),
        actual_source_shaped_fk_to_target_max_m=maximum(np.linalg.norm(fk-target, axis=-1), mask),
        channels_to_fk_all_joints_max_m=float(np.linalg.norm(positions-fk, axis=-1).max()),
        scope='Post-projection final features; per-step pre-projection learned errors are retained separately')
    np.savez_compressed(folder / 'raw_interval.npz', local_rot_mats=local, root_positions=roots,
        interval=np.asarray(case['interval']), normalized_features=features.detach().cpu().numpy(),
        position_channels_native=positions, actual_source_shaped_fk_native=fk)
    holder = {}

    def retain(candidate, metrics):
        holder['candidate'] = deepcopy(candidate)
        holder['metrics'] = deepcopy(metrics)

    started = time.perf_counter()
    try:
        candidate, metrics = finalize_contact(source, constraints, case['interval'], local, roots, settings,
                                               diagnostic_callback=retain)
        report.update(metrics)
    except CompletionRejected as error:
        report.update(error.report, rejection=str(error), parameter_candidate_accepted=False)
        if 'candidate' not in holder:
            raise
        candidate = holder['candidate']
    report['stage_wall_seconds']['finalize'] = time.perf_counter() - started
    candidate['candidate_status'] = np.asarray('parameter_passed_scene_unvalidated' if report['parameter_candidate_accepted'] else 'REJECTED_DIAGNOSTIC_ONLY')
    candidate['parameter_candidate_accepted'] = np.asarray(report['parameter_candidate_accepted'])
    # Finger weights are explicitly authored skin inputs; do not call them
    # predicted by the body-only22-joint model or silently fold them into it.
    report['finger_skinning_contract'] = dict(source='Separate frozen contact constraints',
        weight_key='authored_left_hand_open_weight', provenance='Authored left-only finger opening; not model22-joint output',
        skin_script='scenes/clip39_sitting_room/contact_experiments/skin_palm_candidate.py')
    np.savez_compressed(folder / 'candidate.npz', **candidate)
    report['outputs'] = {name: provenance(folder / name) for name in ('candidate.npz', 'raw_interval.npz', 'effective_constraints.npz', 'projection_steps.json')}
    write_json(folder / 'report.json', report)
    print(json.dumps(dict(case=case['id'], accepted=report['parameter_candidate_accepted'],
                          rejection=report.get('rejection'), stage_wall_seconds=report['stage_wall_seconds'])), flush=True)
    return report


def native_export(source, local, roots, generated):
    """Build full native parameters, preserving source values at unaffected samples."""
    local = _rotations(local, np.asarray(source['local_rot_mats']).shape)
    roots = np.asarray(roots)
    if roots.shape != np.asarray(source['root_positions']).shape or not np.isfinite(roots).all():
        raise ValueError('Native export requires finite full-duration pelvis positions')
    result = {k: deepcopy(v) for k, v in source.items()}
    result.update(local_rot_mats=local.copy(), root_positions=roots.copy(), generated_joint_mask=generated.copy())
    prefix = 'source_gvhmr__smpl_params_global__'
    for key in ('body_pose', 'global_orient', 'transl', 'betas'):
        result['smpl_params_global__' + key] = np.asarray(source[prefix + key]).copy()
    body = result['smpl_params_global__body_pose'].reshape(len(local), 21, 3)
    changed = generated[:, 1:]
    if changed.any():
        body[changed] = Rotation.from_matrix(local[:, 1:][changed]).as_rotvec().astype(body.dtype)
    # This helper also exports raw diagnostic roots/orientations when they differ.
    root_rot_changed = generated[:, 0]
    if root_rot_changed.any():
        orient = result['smpl_params_global__global_orient']
        orient[root_rot_changed] = Rotation.from_matrix(local[:, 0][root_rot_changed]).as_rotvec().astype(orient.dtype)
    moved = np.any(roots != source['root_positions'], axis=1)
    if moved.any():
        transl = result['smpl_params_global__transl']
        transl[moved] = (roots[moved] - source['rest_joints'][0]).astype(transl.dtype)
    return result


def preservation_merge(source, mask, interval, candidate_local, settings):
    """Structural copy of the existing hard merge, with no acceptance decision.

    This is retained even if the unchanged finalizer rejects the raw constraints
    or transition gates. Tests require equality with that finalizer when it passes.
    """
    protected = validate_source(source, mask, interval)
    start, end = interval
    candidate_local = _rotations(candidate_local, (end - start, 22, 3, 3))
    editable = ~protected[start:end]
    editable[[0, -1]] = False
    weights = np.zeros(editable.shape)
    for joint in range(22):
        fixed = np.flatnonzero(~editable[:, joint])
        distance = np.abs(np.arange(end - start)[:, None] - fixed[None]).min(axis=1)
        weights[:, joint] = np.minimum(1., distance / (settings.blend_frames + 1))
    initial = source['local_rot_mats'][start:end].astype(float)
    delta = Rotation.from_matrix((initial.swapaxes(-1, -2) @ candidate_local).reshape(-1, 3, 3)).as_rotvec().reshape(end - start, 22, 3)
    effective = editable & (np.linalg.norm(delta, axis=-1) * weights > settings.roundtrip_tolerance)
    hard = np.ones_like(protected)
    hard[start:end] = ~effective
    blended = initial @ Rotation.from_rotvec((delta * weights[..., None]).reshape(-1, 3)).as_matrix().reshape(end - start, 22, 3, 3)
    local = source['local_rot_mats'].copy()
    local[start:end][effective] = blended[effective].astype(local.dtype)
    generated = rotation_error(source['local_rot_mats'], local) > 1e-8
    result = native_export(source, local, source['root_positions'], generated)
    result['protected_joint_mask'] = hard
    return result


def finalize_with_diagnostic(source, observations, mask, interval, local, roots, settings):
    diagnostic = preservation_merge(source, mask, interval, local, settings)
    try:
        accepted, report = finalize_candidate(source, mask, interval, local, roots, settings)
        for key in ('local_rot_mats', 'root_positions', 'generated_joint_mask', 'protected_joint_mask',
                    'smpl_params_global__body_pose', 'smpl_params_global__transl'):
            if not np.array_equal(accepted[key], diagnostic[key]):
                raise RuntimeError('Diagnostic merge differs from the unchanged accepted finalizer')
        diagnostic = accepted
    except CompletionRejected as error:
        report = dict(error.report, rejection=str(error), parameter_candidate_accepted=False,
                      motion_quality_validated=False, contact_validated=False)
    diagnostic.update(constraint_joint_mask=mask.copy(), visible_joint_mask=observations['visible_joint_mask'].copy(),
                      visibility_state=observations['visibility_state'].copy(),
                      parameter_candidate_accepted=np.asarray(report['parameter_candidate_accepted']),
                      candidate_status=np.asarray('parameter_passed_scene_unvalidated' if report['parameter_candidate_accepted'] else 'REJECTED_DIAGNOSTIC_ONLY'))
    _, ref = forward_kinematics(source['local_rot_mats'], source['root_positions'], source['rest_joints'])
    _, final = forward_kinematics(diagnostic['local_rot_mats'], diagnostic['root_positions'], source['rest_joints'])
    report['diagnostic_preservation'] = dict(
        visible_fk_max_error_m=float(np.linalg.norm(final - ref, axis=-1)[observations['visible_joint_mask']].max()),
        protected_fk_max_error_m=float(np.linalg.norm(final - ref, axis=-1)[mask].max()),
        source_root_exact=bool(np.array_equal(diagnostic['root_positions'], source['root_positions'])),
        generated_joint_samples=int(diagnostic['generated_joint_mask'].sum()),
        gate_acceptance_not_changed_by_diagnostic_export=True)
    return diagnostic, report


@contextmanager
def verified_adapter_loads(records):
    """Observe existing PEFT loads; never merge/apply an adapter an extra time."""
    import torch
    from peft import PeftModel, get_peft_model_state_dict
    from safetensors.torch import load_file
    from huggingface_hub import hf_hub_download
    original = PeftModel.from_pretrained.__func__

    def observed(cls, model, model_id, *args, **kwargs):
        result = original(cls, model, model_id, *args, **kwargs)
        if model_id not in ADAPTERS:
            raise ValueError('Unexpected text adapter: ' + str(model_id))
        path = hf_hub_download(model_id, 'adapter_model.safetensors', local_files_only=True)
        expected = load_file(path, device='cpu')
        actual = get_peft_model_state_dict(result, adapter_name=kwargs.get('adapter_name', 'default'), save_embedding_layers=False)
        matching = set(expected) == set(actual) and bool(expected)
        mismatched = []
        for key in set(expected) & set(actual):
            target = actual[key].detach().cpu()
            if target.shape != expected[key].shape or not torch.equal(target, expected[key].to(target.dtype)):
                mismatched.append(key)
        matching = matching and not mismatched
        records.append(dict(repository=model_id, weights=provenance(path), expected_keys=len(expected),
                            loaded_keys=len(actual), missing_keys=sorted(set(expected) - set(actual)),
                            extra_keys=sorted(set(actual) - set(expected)), mismatched_keys=sorted(mismatched),
                            exactly_equal_after_dtype_conversion=matching))
        if not matching:
            raise ValueError('Loaded text adapter weights differ from local trained checkpoint')
        return result

    PeftModel.from_pretrained = classmethod(observed)
    try:
        yield
        if tuple(row['repository'] for row in records) != ADAPTERS:
            raise ValueError('Both real text adapters must be observed and verified')
    finally:
        PeftModel.from_pretrained = classmethod(original)


class CachedTextEncoder:
    """Reuse actual text features and count actual tokenizer inputs, without APIs."""
    def __init__(self, encoder):
        self.encoder, self.cache, self.records = encoder, {}, {}

    def __call__(self, text):
        if not isinstance(text, list) or len(text) != 1 or not text[0].strip():
            raise ValueError('One nonempty prompt per case is required')
        key = text[0]
        if key in self.cache:
            return self.cache[key]
        tokenizer_owner = self.encoder.model
        original = tokenizer_owner.tokenize
        token_counts = []

        def observed(sentences, *args, **kwargs):
            tokens = original(sentences, *args, **kwargs)
            token_counts.extend(int(x) for x in tokens['attention_mask'].sum(dim=-1).detach().cpu().tolist())
            return tokens

        tokenizer_owner.tokenize = observed
        started = time.perf_counter()
        try:
            value = self.encoder(text)
            synchronize(value[0].device)
        finally:
            tokenizer_owner.tokenize = original
        self.cache[key] = value
        self.records[key] = dict(prompt=key, tokenizer_input_token_counts=token_counts,
                                 tokenizer_count_scope='Actual LLM2Vec tokenize attention masks including model formatting/instruction; not generated tokens',
                                 text_encode_seconds=time.perf_counter() - started,
                                 external_LLM_API_calls=0)
        return value


def synchronize(device):
    import torch
    if str(device).startswith('cuda'):
        torch.cuda.synchronize(device)


def decoded_native(decoded, source, conditions):
    def array(v):
        return v.detach().cpu().numpy() if hasattr(v, 'detach') else np.asarray(v)
    local = array(decoded['local_rot_mats'])[0].astype(float).copy()
    basis, offset = source['source_to_kimodo'][:3, :3], source['source_to_kimodo'][:3, 3]
    local[:, 0] = basis.T @ local[:, 0]
    roots = (array(decoded['root_positions'])[0] + conditions['canonical_origin'] - offset) @ basis
    return local, roots


def sample_capture(model, conditions, prompt, settings):
    """Use the tested sampler verbatim; retain final learned feature channels."""
    original = model.motion_rep.inverse
    retained = {}

    def observed(features, *args, **kwargs):
        retained['features'] = features.detach().clone()
        return original(features, *args, **kwargs)

    model.motion_rep.inverse = observed
    try:
        decoded, report = sample_conditioned(model, conditions, prompt, PROTOCOL['seed'], settings)
    finally:
        model.motion_rep.inverse = original
    return decoded, report, retained['features']


def run(manifest_path, output, upstream, checkpoint, device):
    manifest = json.loads(manifest_path.read_text())
    checked = validate_manifest(manifest)
    if output.exists():
        raise FileExistsError('Fresh claimed batch output required')
    upstream = upstream.resolve(strict=True)
    git = ['git', '-c', f'safe.directory={upstream}', '-C', str(upstream)]
    revision = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if revision != PIN or subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('Requires clean audited pinned Kimodo checkout')
    checkpoint = checkpoint.resolve(strict=True)
    if checkpoint.name != 'Kimodo-SMPLX-RP-v1' or not (checkpoint / 'config.yaml').is_file():
        raise ValueError('Existing canonical Kimodo-SMPLX-RP-v1 checkpoint required')
    if device.startswith('cuda'):
        runtime.require_gpu('Kimodo batch experiments')
    os.environ.update(CHECKPOINT_DIR=str(checkpoint.parent), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TEXT_ENCODER_MODE='local')
    sys.path.insert(0, str(upstream))
    output.mkdir(parents=True)
    snapshot = output / 'executed_code'; snapshot.mkdir()
    code_paths = [Path(__file__).resolve(), ROOT / 'src/aha3d/motion/completion.py',
                  ROOT / 'tools/kimodo/complete_motion.py', ROOT / 'tools/kimodo/contact_edit.py']
    for case in manifest.get('contact_cases', []):
        code_paths.extend(checked_file(r) for r in case['implementation_bindings'])
        code_paths.append(checked_file(case['projector']))
    code_records = []
    for path in sorted(set(code_paths)):
        dest = snapshot / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        code_records.append(dict(original=provenance(path), snapshot=provenance(dest)))
    shutil.copyfile(manifest_path, output / 'executed_manifest.json')
    report = dict(schema_version=1, status='loading', manifest=provenance(manifest_path),
                  protocol=PROTOCOL, upstream_commit=PIN,
                  checkpoint_files={str(p.relative_to(checkpoint)): provenance(p) for p in sorted(checkpoint.rglob('*')) if p.is_file()},
                  implementation=provenance(__file__), completion_implementation=provenance(ROOT / 'src/aha3d/motion/completion.py'),
                  executed_code=code_records, model_load_count=0, model_load_seconds=None, adapter_verification=[], cases=[],
                  external_LLM_API_calls=0, agent_token_usage=None,
                  agent_usage_scope='Agent conversation usage is not available to this program and is not estimated')
    write_json(output / 'batch_report.json', report)
    import torch
    from kimodo import load_model
    if device.startswith('cuda') and (not torch.cuda.is_available() or torch.cuda.device_count() != 1):
        raise ValueError('Exactly one visible CUDA device is required')
    start_load = time.perf_counter()
    try:
        with verified_adapter_loads(report['adapter_verification']):
            model = load_model('Kimodo-SMPLX-RP-v1', device=device)
        synchronize(model.device)
        report.update(model_load_seconds=time.perf_counter() - start_load, model_load_count=1,
                      torch_version=torch.__version__, status='running')
        encoder = CachedTextEncoder(model.text_encoder)
        model.text_encoder = encoder
        write_json(output / 'batch_report.json', report)
        for case, (source, observations, mask, preflight) in zip(manifest['cases'], checked):
            # Recheck frozen inputs immediately before each case after shared load.
            checked_file(case['source']); checked_file(case['visibility'])
            folder = output / case['id']; folder.mkdir()
            settings = CompletionSettings()
            begin = time.perf_counter()
            conditions = prepare_conditions(model, source, mask, case['interval'], settings)
            synchronize(model.device)
            geometry_seconds = time.perf_counter() - begin
            # A zero-edit roundtrip tests the actual trained representation first.
            zero = native_export(source, source['local_rot_mats'], source['root_positions'], np.zeros(mask.shape, bool))
            zero.update(candidate_status=np.asarray('CODEC_CONTROL_SOURCE_UNCHANGED'), parameter_candidate_accepted=np.asarray(False))
            zero_folder = folder / 'zero_edit_roundtrip'; zero_folder.mkdir()
            np.savez_compressed(zero_folder / 'candidate.npz', **zero)
            zero_report = dict(kind='actual_model_codec_roundtrip_source_control', roundtrip=conditions['roundtrip'],
                               source=case['source'], visibility=case['visibility'], generated_motion=False,
                               model_representation_used=True, denoiser_executed=False,
                               output=provenance(zero_folder / 'candidate.npz'),
                               stage_wall_seconds={'geometry_and_roundtrip': geometry_seconds, 'sampling': 0.0},
                               contact_validated=False, motion_quality_validated=False)
            write_json(zero_folder / 'report.json', zero_report)
            text_was_cached = case['prompt'].strip() in encoder.cache
            encoder([case['prompt'].strip()])
            case_report = dict(preflight, geometry_and_roundtrip_seconds=geometry_seconds,
                               text_encoding=encoder.records[case['prompt'].strip()], text_features_reused=text_was_cached,
                               text_encode_seconds_charged_to_this_case=0.0 if text_was_cached else encoder.records[case['prompt'].strip()]['text_encode_seconds'],
                               variants=[])
            for name, warm_step in PROTOCOL['variants'].items():
                variant = folder / name; variant.mkdir()
                settings = CompletionSettings(warm_start_step=warm_step)
                model.diffusion.calc_diffusion_vars(model.diffusion.space_timesteps(50)[0])
                index = 49 if warm_step is None else warm_step
                alpha = float(model.diffusion.alphas_cumprod[index].item())
                item = dict(id=name, source=case['source'], visibility=case['visibility'], preflight=preflight,
                            settings=asdict(settings), seed=7, prompt=case['prompt'].strip(),
                            noise=dict(schedule_index=index, alpha_bar=alpha,
                                       signal_multiplier=0.0 if warm_step is None else float(np.sqrt(alpha)),
                                       noise_multiplier=1.0 if warm_step is None else float(np.sqrt(1 - alpha)),
                                       initialization='unit Gaussian' if warm_step is None else 'q_sample of original source at actual spaced schedule index'),
                            stage_wall_seconds={}, parameter_candidate_accepted=False, motion_quality_validated=False,
                            contact_validated=False, model_loaded_once_for_batch=True)
                item['preservation_gate_mask_semantics'] = ('Actual visible plus conservative constraints' if case['kind'] == 'reviewed_hidden_part_completion'
                    else 'Declared protected upper body/root only; source-visible released lower body is intentionally editable')
                write_json(variant / 'report.json', item)
                synchronize(model.device); started = time.perf_counter()
                decoded, sampling, features = sample_capture(model, conditions, case['prompt'].strip(), settings)
                synchronize(model.device)
                item['stage_wall_seconds']['sampling'] = time.perf_counter() - started
                item['sampling'] = sampling
                item['model_executed'] = True
                local, roots = decoded_native(decoded, source, conditions)
                np.savez_compressed(variant / 'raw_interval.npz', local_rot_mats=local, root_positions=roots,
                                    interval=np.asarray(case['interval']), normalized_features=features.detach().cpu().numpy())
                # Full raw diagnostic is never the adopted source-preserving candidate.
                raw_local, raw_root = source['local_rot_mats'].copy(), source['root_positions'].copy()
                a, b = case['interval']; raw_local[a:b], raw_root[a:b] = local, roots
                generated = rotation_error(source['local_rot_mats'], raw_local) > 1e-8
                raw = native_export(source, raw_local, raw_root, generated)
                raw.update(candidate_status=np.asarray('RAW_UNPRESERVED_DIAGNOSTIC_ONLY'), parameter_candidate_accepted=np.asarray(False))
                np.savez_compressed(variant / 'raw_full_native.npz', **raw)
                started = time.perf_counter()
                candidate, final = finalize_with_diagnostic(source, observations, mask, case['interval'], local, roots, settings)
                item.update(final)
                item['stage_wall_seconds']['finalize_and_preservation_geometry'] = time.perf_counter() - started
                item['stage_wall_seconds']['geometric_contact_solve'] = 0.0
                np.savez_compressed(variant / 'candidate.npz', **candidate)
                item['outputs'] = {p: provenance(variant / p) for p in ('candidate.npz', 'raw_interval.npz', 'raw_full_native.npz')}
                item['limitations'] = ['Generated hidden articulation has no source-video ground truth.',
                    'Source trajectory, shape and declared protected joints/ancestors are frozen.',
                    'In deliberate lower-body replacement, visible released legs are generated and no longer exactly source-preserved.',
                    'No room contact objective is applied in this occlusion-only experiment.',
                    'Parameter rejection is retained even though a renderable diagnostic merge is exported.',
                    'Whole-scene skinning, silhouette and contact/style review remain separate.']
                write_json(variant / 'report.json', item)
                case_report['variants'].append({'id': name, 'report': provenance(variant / 'report.json'),
                                                'parameter_candidate_accepted': item['parameter_candidate_accepted'],
                                                'stage_wall_seconds': item['stage_wall_seconds']})
                print(json.dumps(dict(case=case['id'], variant=name, accepted=item['parameter_candidate_accepted'],
                                      rejection=item.get('rejection'), sampling_seconds=item['stage_wall_seconds']['sampling'])), flush=True)
            write_json(folder / 'case_report.json', case_report)
            report['cases'].append(case_report)
            write_json(output / 'batch_report.json', report)
        report['contact_cases'] = []
        for case in manifest.get('contact_cases', []):
            result = run_contact_case(model, encoder, case, output / case['id'])
            report['contact_cases'].append(dict(id=case['id'], report=provenance(output / case['id'] / 'report.json'),
                parameter_candidate_accepted=result['parameter_candidate_accepted'], stage_wall_seconds=result['stage_wall_seconds']))
            write_json(output / 'batch_report.json', report)
        report['status'] = 'complete_parameter_experiments_scene_review_pending'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        write_json(output / 'batch_report.json', report)
        raise
    write_json(output / 'batch_report.json', report)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('check', 'run'))
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--upstream', type=Path, default=ROOT / 'runs/kimodo-code-audit-20260912/upstream')
    p.add_argument('--checkpoint', type=Path, default=ROOT / 'kimodo_blender/checkpoints/Kimodo-SMPLX-RP-v1')
    p.add_argument('--device', default='cuda:0')
    args = p.parse_args()
    if args.operation == 'check':
        values = validate_manifest(json.loads(args.manifest.read_text()))
        print(json.dumps(dict(manifest=provenance(args.manifest), protocol=PROTOCOL,
                             cases=[row[3] for row in values],
                             contact_cases=[{'id': c['id'], 'source': c['source'], 'constraints': c['constraints'],
                                 'warm_start_step': c['warm_start_step']} for c in json.loads(args.manifest.read_text()).get('contact_cases', [])],
                             model_executed=False), indent=2))
    else:
        if args.output is None:
            p.error('--output is required for run')
        run(args.manifest, args.output, args.upstream, args.checkpoint, args.device)


if __name__ == '__main__':
    main()
