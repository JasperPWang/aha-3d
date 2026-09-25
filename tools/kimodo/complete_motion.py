#!/usr/bin/env python3
"""Prepare GVHMR parameters or run experimental dense-observation Kimodo completion.

Outputs are new artifacts, never overwrites. The user must claim output paths
before running. Model execution needs the pinned Kimodo code, locally installed
weights and text encoder, and a local CUDA device (--device, default cuda:0).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d import runtime  # noqa: E402
from aha3d.motion.completion import (  # noqa: E402
    CompletionRejected, CompletionSettings, JOINT_NAMES, complete_motion,
    source_from_gvhmr, validate_source, ancestor_protection,
)

PIN = '1aece8c124d73d255ceff5086d983b844c9f4e94'


def load_npz(path):
    with np.load(path, allow_pickle=False) as arrays:
        return {key: arrays[key].copy() for key in arrays.files}


def provenance(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def constraint_mask(observations, interval, *, require_reviewed_states=False):
    """Keep uncertain parts unchanged without claiming that they were visible."""
    visible = np.asarray(observations['visible_joint_mask'])
    if visible.dtype != bool or visible.ndim != 2 or visible.shape[1] != 22:
        raise ValueError('Actual visibility must be a boolean [T,22] mask')
    constraints = np.asarray(observations.get('constraint_joint_mask', visible))
    if constraints.dtype != bool or constraints.shape != visible.shape or np.any(visible & ~constraints):
        raise ValueError('Conservative constraints must be a boolean superset of actual visibility')
    state = observations.get('visibility_state')
    if require_reviewed_states and state is None:
        raise ValueError('Real completion requires visibility_state to distinguish reviewed hidden from uncertain joints')
    if state is not None:
        state = np.asarray(state)
        if state.shape != visible.shape or state.dtype.kind not in 'iu' or not np.isin(state, [-1, 0, 1]).all():
            raise ValueError('visibility_state must be [T,22] integers: uncertain=-1, hidden=0, visible=1')
        if not np.array_equal(state == 1, visible):
            raise ValueError('Actual visibility differs from reviewed visibility_state')
        start, end = interval
        editable = ~ancestor_protection(constraints)[start:end]
        if np.any(editable & (state[start:end] != 0)):
            raise ValueError('Every editable joint must be reviewed hidden; uncertain parts stay protected')
    if not visible[interval[0]:interval[1]].any(axis=1).all():
        raise ValueError('Each completion frame requires actual visible-body evidence, not only conservative constraints')
    return constraints.copy(), dict(
        actual_visible_joint_samples=int(visible[interval[0]:interval[1]].sum()),
        constraint_joint_samples=int(constraints[interval[0]:interval[1]].sum()),
        conservative_extra_samples=int((constraints & ~visible)[interval[0]:interval[1]].sum()),
        reviewed_visibility_states_provided=state is not None,
        semantics='Actual visibility and conservative preservation are separate; extra constraints do not assert visibility')


def validate_video_binding(source, observations):
    """A matching timeline alone cannot identify the source video or actor."""
    for key in ('source_video_sha256', 'source_actor_id'):
        if key not in source or key not in observations:
            raise ValueError(f'Real completion requires source and visibility binding: {key}')
        expected, actual = str(np.asarray(source[key]).item()), str(np.asarray(observations[key]).item())
        if not expected.strip() or actual != expected:
            raise ValueError(f'Visibility belongs to a different source video or actor: {key}')
    digest = str(source['source_video_sha256'].item())
    if len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
        raise ValueError('Source video SHA256 must be a lowercase hexadecimal digest')
    return {key: str(source[key].item()) for key in ('source_video_sha256', 'source_actor_id')}


def validate_prediction_export(native, prediction):
    """Reject a stale same-length NPZ before attaching the run's actor label."""
    expected = {'K_fullimg': prediction['K_fullimg']}
    for group in ('smpl_params_global', 'smpl_params_incam'):
        for name in ('body_pose', 'global_orient', 'transl', 'betas'):
            expected[f'{group}__{name}'] = prediction[group][name]
    for name, value in expected.items():
        expected_array = value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)
        if name not in native or native[name].dtype != expected_array.dtype or not np.array_equal(native[name], expected_array):
            raise ValueError(f'Native export differs from the actual GVHMR prediction: {name}')
    return list(expected)


def prepare(args):
    if args.output.exists() or args.output.with_suffix('.json').exists():
        raise ValueError('Prepared output or sibling report already exists')
    raw, geometry = load_npz(args.source), load_npz(args.geometry)
    if 'source_sha256' in geometry and str(geometry['source_sha256'].item()) != provenance(args.source)['sha256']:
        raise ValueError('Prepared geometry is bound to a different source file')
    source_betas = raw['smpl_params_global__betas']
    source_shape = source_betas[0] if source_betas.ndim == 2 else source_betas
    if not np.allclose(geometry['betas'], source_shape, atol=1e-6, rtol=0):
        raise ValueError('Geometry rest joints must be supplied for the exact source beta')
    if tuple(geometry['joint_names'].tolist()) != JOINT_NAMES:
        raise ValueError('Geometry must name the source-shaped SMPL-X 22 joints in order')
    motion = source_from_gvhmr(raw, geometry['rest_joints'], geometry['source_to_kimodo'])
    binding = None
    if args.gvhmr_run is not None:
        run = args.gvhmr_run.resolve(strict=True)
        if args.source.resolve() != (run / 'motion_native.npz').resolve(strict=True):
            raise ValueError('Bind the exact motion_native.npz exported from the declared GVHMR run')
        manifest = json.loads((run / 'provenance.json').read_text())
        video = provenance(run / '0_input_video.mp4')
        actor = manifest.get('actor_id', '')
        if video['sha256'] != manifest['normalized_input_sha256'] or not actor.strip():
            raise ValueError('GVHMR normalized source hash or actor identity is missing/stale')
        import torch
        prediction_path = run / 'hmr4d_results.pt'
        prediction = torch.load(prediction_path, map_location='cpu', weights_only=True)
        compared_fields = validate_prediction_export(raw, prediction)
        # Decode the actual source timeline; matching lengths alone is insufficient.
        import av
        with av.open(str(run / '0_input_video.mp4')) as container:
            times = np.asarray([float(frame.pts * frame.time_base) for frame in container.decode(video=0)])
        if times.shape != motion['time_seconds'].shape or not np.allclose(times, motion['time_seconds'], atol=1e-12, rtol=0):
            raise ValueError('GVHMR motion and source video timestamps differ')
        binding = dict(source_video_sha256=video['sha256'], source_actor_id=actor,
                       gvhmr_provenance=provenance(run / 'provenance.json'),
                       prediction=provenance(prediction_path), exactly_compared_prediction_fields=compared_fields)
        motion.update(source_video_sha256=np.asarray(video['sha256']), source_actor_id=np.asarray(actor),
                      source_prediction_sha256=np.asarray(binding['prediction']['sha256']))
    # Verify the prepared schema without treating artificial visibility as evidence.
    temporary_mask = np.zeros((len(motion['time_seconds']), 22), bool)
    temporary_mask[:, [12, 15, 20, 21]] = True
    validate_source(motion, temporary_mask, [0, min(300, len(temporary_mask))])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        np.savez_compressed(stream, **motion)
    report = {'schema_version': 1, 'operation': 'GVHMR parameter conversion only',
              'source': provenance(args.source), 'source_shaped_geometry': provenance(args.geometry),
              'source_frame_count': len(temporary_mask), 'model_executed': False,
              'video_actor_binding': binding,
              'representation_roundtrip_validated': False,
              'note': 'No visibility was inferred; run requires separate whole-interval visibility evidence.'}
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')


def run(args):
    settings = CompletionSettings(
        denoising_steps=args.steps, warm_start_step=args.warm_start_step,
        blend_frames=args.blend_frames,
    )
    settings.validate()
    if not args.prompt.strip():
        raise ValueError('Nonempty text is required together with dense source observations')
    if args.output.exists():
        raise ValueError('Use a fresh claimed output directory')
    source, observations = load_npz(args.source), load_npz(args.visibility)
    binding = validate_video_binding(source, observations)
    if tuple(observations['joint_names'].tolist()) != JOINT_NAMES:
        raise ValueError('Visibility anatomical order differs from the prepared source')
    if not np.array_equal(observations['time_seconds'], source['time_seconds']):
        raise ValueError('Visibility and source timestamps must match exactly')
    evidence = str(observations.get('visibility_evidence', '').item()) if 'visibility_evidence' in observations else ''
    if not evidence.strip() or evidence.strip().lower() in ('unknown', 'none'):
        raise ValueError('Record actual visibility evidence; detector confidence alone is not visibility')
    interval = [args.start_frame, args.end_frame]
    visible, constraint_review = constraint_mask(observations, interval, require_reviewed_states=True)
    validate_source(source, visible, interval)
    upstream = args.upstream.resolve(strict=True)
    revision = subprocess.check_output(
        ['git', '-c', f'safe.directory={upstream}', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != PIN:
        raise ValueError(f'Expected audited Kimodo commit {PIN}, found {revision}')
    dirty = subprocess.check_output(
        ['git', '-c', f'safe.directory={upstream}', '-C', str(upstream), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if dirty:
        raise ValueError('Audited Kimodo checkout has tracked modifications; record and review before running')
    checkpoint = args.checkpoint.resolve(strict=True)
    if checkpoint.name != 'Kimodo-SMPLX-RP-v1' or not (checkpoint / 'config.yaml').is_file():
        raise ValueError('checkpoint must be the existing Kimodo-SMPLX-RP-v1 directory with config.yaml')
    # No automatic model downloads or implicit text-server calls. These settings
    # affect only this child process; the shared environment is unchanged.
    os.environ['CHECKPOINT_DIR'] = str(checkpoint.parent)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TEXT_ENCODER_MODE'] = 'local'
    sys.path.insert(0, str(upstream))
    import torch
    from kimodo import load_model

    report = {'schema_version': 1, 'upstream_commit': revision,
              'source': provenance(args.source), 'visibility': provenance(args.visibility),
              'visibility_evidence': evidence, 'checkpoint_config': provenance(checkpoint / 'config.yaml'),
              'constraint_review': constraint_review,
              'video_actor_binding': binding,
              'checkpoint_directory': str(checkpoint), 'torch_version': torch.__version__,
              'execution': 'local', 'run_id': runtime.run_id(),
              'settings': asdict(settings), 'prompt': args.prompt, 'seed': args.seed,
              'parameter_candidate_accepted': False, 'motion_quality_validated': False}
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        model = load_model('Kimodo-SMPLX-RP-v1', device=args.device)
        candidate, result = complete_motion(model, source, visible, interval, args.prompt,
                                            seed=args.seed, settings=settings)
        # The numerical adapter protects the conservative superset. Preserve the
        # reviewed visibility semantics in the exported candidate as well.
        candidate['constraint_joint_mask'] = visible.copy()
        candidate['visible_joint_mask'] = observations['visible_joint_mask'].copy()
        if 'visibility_state' in observations:
            candidate['visibility_state'] = observations['visibility_state'].copy()
        report.update(result)
        report['preservation_scope'] = 'All actual visible joints plus conservative uncertain-body constraints'
        with (args.output / 'candidate.npz').open('xb') as stream:
            np.savez_compressed(stream, **candidate)
    except CompletionRejected as error:
        report.update(error.report, rejection=str(error), parameter_candidate_accepted=False)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 2
    except Exception as error:
        report.update(setup_or_execution_error=f'{type(error).__name__}: {error}')
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        raise
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='Convert native GVHMR NPZ with supplied source-shaped rest geometry')
    prep.add_argument('--source', type=Path, required=True)
    prep.add_argument('--geometry', type=Path, required=True,
                      help='NPZ: rest_joints[22,3], betas, joint_names, source_to_kimodo[4,4]')
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--gvhmr-run', type=Path,
                      help='Bind the native motion to its actual normalized video and reviewed actor before real completion')
    generate = commands.add_parser('run', help='Dense visible-body constraints plus text; no text-only fallback')
    for name in ('source', 'visibility', 'upstream', 'checkpoint', 'output'):
        generate.add_argument('--' + name, type=Path, required=True)
    generate.add_argument('--device', default='cuda:0')
    generate.add_argument('--start-frame', type=int, required=True)
    generate.add_argument('--end-frame', type=int, required=True, help='Exclusive interval end')
    generate.add_argument('--prompt', required=True)
    generate.add_argument('--seed', type=int, default=0)
    generate.add_argument('--steps', type=int, default=50)
    generate.add_argument('--warm-start-step', type=int,
                          help='Optional index in the spaced DDIM schedule; omitted means Gaussian generation')
    generate.add_argument('--blend-frames', type=int, default=4)
    args = parser.parse_args()
    return prepare(args) if args.command == 'prepare' else run(args)


if __name__ == '__main__':
    raise SystemExit(main())
