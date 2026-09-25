#!/usr/bin/env python3
"""Prepare source-shaped SMPL-X rest joints for complete_motion.py prepare.

Requires a real native GVHMR NPZ, the user's licensed neutral SMPL-X numeric NPZ,
and an explicit source basis. No neutral-shape substitution, model download,
pickle loading, inference, motion resampling, or scene alignment is performed.
Claim the output path with tools/task_claim.py before running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.motion.completion import JOINT_NAMES, PARENTS  # noqa: E402

GVHMR_PIN = 'cac2d9dacc6b4b6f145ca02c2e6e616719fff916'
GLOBAL_BASIS_REFERENCE = (
    'https://github.com/mkocabas/GVHMR_BEDLAM2/blob/' + GVHMR_PIN
    + '/hmr4d/model/gvhmr/pipeline/gvhmr_pipeline.py#L346'
)
SHAPE_REFERENCE = (
    'https://github.com/mkocabas/GVHMR_BEDLAM2/blob/' + GVHMR_PIN
    + '/hmr4d/utils/body_model/smplx_lite.py#L98'
)


def finite_float(value, name):
    array = np.asarray(value)
    if array.dtype.kind != 'f' or not np.isfinite(array).all():
        raise ValueError(f'{name} must contain finite floating point values')
    return array


def fixed_source_betas(source):
    """Validate the native parameter group; never guess missing shape or axes."""
    prefix = 'smpl_params_global__'
    required = [prefix + key for key in ('global_orient', 'body_pose', 'transl', 'betas')]
    required.append('frame_times_seconds')
    missing = [key for key in required if key not in source]
    if missing:
        raise ValueError(f'Missing native GVHMR fields: {missing}')
    trans = finite_float(source[prefix + 'transl'], 'transl')
    if trans.ndim != 2 or trans.shape[1] != 3 or len(trans) < 1:
        raise ValueError('transl must describe one actor with shape [T,3]')
    frames = len(trans)
    orient = finite_float(source[prefix + 'global_orient'], 'global_orient')
    pose = finite_float(source[prefix + 'body_pose'], 'body_pose')
    if orient.shape != (frames, 3) or pose.shape not in ((frames, 63), (frames, 21, 3)):
        raise ValueError('Expected native axis-angle global_orient[T,3] and body_pose[T,63]')
    times = finite_float(source['frame_times_seconds'], 'frame_times_seconds')
    if times.shape != (frames,) or (np.diff(times) <= 0).any():
        raise ValueError('Source timestamps must increase and match the parameter frames')
    betas = finite_float(source[prefix + 'betas'], 'betas')
    if betas.shape == (10,):
        return betas.copy(), frames
    if betas.shape not in ((1, 10), (frames, 10)):
        raise ValueError('Exactly 10 source betas are required, shaped [10], [1,10], or [T,10]')
    if not np.allclose(betas, betas[:1], atol=1e-6, rtol=0):
        raise ValueError('Source betas vary over time; fixed source-shaped geometry is required')
    return betas[0].copy(), frames


def source_shaped_rest_joints(model, betas):
    """J_regressor @ (v_template + shapedirs[:, :, :10] @ source_beta).

    Results retain the SMPL-X template pelvis offset and its original rest basis.
    Do not center them or apply the world-to-Kimodo basis to these rest offsets.
    """
    beta = finite_float(betas, 'betas')
    if beta.shape != (10,):
        raise ValueError('Exactly one source beta[10] is required')
    template = finite_float(model['v_template'], 'v_template')
    shapedirs = finite_float(model['shapedirs'], 'shapedirs')
    regressor = finite_float(model['J_regressor'], 'J_regressor')
    tree = np.asarray(model['kintree_table'])
    if template.shape != (10475, 3) or regressor.shape != (55, 10475):
        raise ValueError('Expected neutral SMPL-X topology: 10475 vertices and 55 joints')
    if shapedirs.ndim != 3 or shapedirs.shape[:2] != template.shape or shapedirs.shape[2] < 10:
        raise ValueError('SMPL-X shapedirs must contain the first 10 source shape directions')
    if tree.shape != (2, 55) or tree.dtype.kind not in 'iu':
        raise ValueError('Expected integer SMPL-X kintree_table[2,55]')
    if not np.array_equal(tree[1], np.arange(55)):
        raise ValueError('SMPL-X joint IDs are reordered; explicit 22-joint order is required')
    parents = tree[0, :22].astype(np.int64).copy()
    if int(parents[0]) not in (-1, 2**32 - 1):
        raise ValueError('Unrecognized root parent sentinel')
    parents[0] = -1
    if not np.array_equal(parents, PARENTS):
        raise ValueError('SMPL-X parents differ from the required 22-joint anatomical order')
    if not np.allclose(regressor.sum(axis=1), 1, atol=1e-4, rtol=0):
        raise ValueError('Joint regressor rows must sum to one')
    shaped = template.astype(np.float64) + np.einsum(
        'vck,k->vc', shapedirs[:, :, :10].astype(np.float64), beta.astype(np.float64))
    rest = regressor[:22].astype(np.float64) @ shaped
    if not np.isfinite(rest).all() or (np.linalg.norm(rest[1:] - rest[PARENTS[1:]], axis=1) < 1e-6).any():
        raise ValueError('Source-shaped skeleton contains invalid or zero-length bones')
    return rest


def explicit_basis(source_basis=None, source_to_kimodo=None):
    """Identity only for explicitly declared native GVHMR global Y-up output."""
    if (source_basis is None) == (source_to_kimodo is None):
        raise ValueError('Supply exactly one explicit source basis or rigid transform')
    if source_basis is not None:
        if source_basis != 'gvhmr-y-up':
            raise ValueError('Only explicitly declared native gvhmr-y-up supports identity')
        return np.eye(4), {
            'source_basis': source_basis,
            'basis_authority': 'caller declaration of native smpl_params_global provenance',
            'upstream_reference': GLOBAL_BASIS_REFERENCE,
            'upstream_contract': 'get_smpl_params_w_Rt_v2 returns GV0(ay) after any->ay rotation',
            'target_basis': 'Kimodo SMPL-X metric Y-up',
            'basis_inferred_from_pose': False,
        }
    transform = finite_float(source_to_kimodo, 'source_to_kimodo').astype(np.float64)
    if transform.shape != (4, 4) or not np.array_equal(transform[3], [0, 0, 0, 1]):
        raise ValueError('Explicit transform must be rigid affine [4,4]')
    rotation = transform[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7, rtol=0) or not np.isclose(
        np.linalg.det(rotation), 1, atol=1e-7, rtol=0
    ):
        raise ValueError('Explicit transform must contain proper rotation with scale one')
    return transform.copy(), {
        'source_basis': 'caller supplied rigid transform',
        'basis_authority': 'caller supplied source_to_kimodo',
        'target_basis': 'Kimodo SMPL-X metric Y-up',
        'basis_inferred_from_pose': False,
    }


def file_provenance(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return {'path': str(path), 'size_bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def prepare_geometry(source_path, body_model_path, output_path, *, source_basis=None, transform_path=None):
    output_path = Path(output_path)
    body_model_path = Path(body_model_path)
    if output_path.suffix != '.npz':
        raise ValueError('Geometry output must have .npz extension')
    report_path = output_path.with_suffix('.json')
    if output_path.exists() or report_path.exists():
        raise FileExistsError('Geometry output or sibling provenance report already exists')
    if body_model_path.name.upper() != 'SMPLX_NEUTRAL.NPZ':
        raise ValueError('Supply the licensed SMPLX_NEUTRAL.npz file explicitly')
    with np.load(source_path, allow_pickle=False) as native:
        beta, frames = fixed_source_betas(native)
    with np.load(body_model_path, allow_pickle=False) as model:
        # Access only numeric geometry. Other metadata may contain pickled objects.
        rest = source_shaped_rest_joints(model, beta)
    transform_input = None if transform_path is None else np.load(transform_path, allow_pickle=False)
    if transform_input is not None and not isinstance(transform_input, np.ndarray):
        if hasattr(transform_input, 'close'):
            transform_input.close()
        raise ValueError('Transform must be a numeric .npy [4,4] file')
    transform, basis_report = explicit_basis(source_basis, transform_input)
    source_record, body_record = file_provenance(source_path), file_provenance(body_model_path)
    report = {
        'schema_version': 1, 'operation': 'source-shaped SMPL-X rest geometry only',
        'source': source_record, 'body_model': body_record, 'source_frames': frames,
        'betas': beta.tolist(), 'fixed_shape_tolerance': 1e-6,
        'shape_formula': 'J_regressor @ (v_template + shapedirs[:, :, :10] @ beta)',
        'shape_reference': SHAPE_REFERENCE, 'geometry_dtype': str(rest.dtype),
        'joint_names': list(JOINT_NAMES), 'parents': PARENTS.tolist(),
        'root_position_contract': 'pelvis_position = smpl_transl + rest_joints[0]',
        'rest_joints_transformed_or_centered': False,
        'source_to_kimodo': transform.tolist(), 'basis': basis_report,
        'source_parameters_or_timing_modified': False, 'learned_model_executed': False,
        'visibility_inferred': False, 'scene_alignment_validated': False,
    }
    if transform_path is not None:
        report['transform_file'] = file_provenance(transform_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('xb') as stream:
        np.savez_compressed(
            stream, rest_joints=rest, betas=beta, joint_names=np.asarray(JOINT_NAMES),
            parents=PARENTS, source_to_kimodo=transform,
            source_sha256=np.asarray(source_record['sha256']),
            body_model_sha256=np.asarray(body_record['sha256']),
            source_basis=np.asarray(basis_report['source_basis']),
            root_position_contract=np.asarray(report['root_position_contract']),
        )
    with report_path.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Native GVHMR motion_native.npz')
    parser.add_argument('--body-model', type=Path, required=True, help='Licensed SMPLX_NEUTRAL.npz')
    basis = parser.add_mutually_exclusive_group(required=True)
    basis.add_argument('--source-basis', choices=('gvhmr-y-up',),
                       help='Assert unaligned native GVHMR smpl_params_global in GV0(ay)')
    basis.add_argument('--source-to-kimodo', type=Path,
                       help='Explicit rigid source-world to Kimodo Y-up transform as numeric .npy [4,4]')
    parser.add_argument('--output', type=Path, required=True, help='Fresh claimed geometry NPZ')
    args = parser.parse_args(argv)
    report = prepare_geometry(args.source, args.body_model, args.output,
                              source_basis=args.source_basis, transform_path=args.source_to_kimodo)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
