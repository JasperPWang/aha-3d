"""Kimodo SMPL-X NPZ -> fixed-topology mesh cache for Blender.

Run in the external Kimodo Python environment, not Blender's Python.
Uses upstream SMPLXSkin, including its full shape and pose correctives.
Requires the licensed SMPLX_NEUTRAL.npz in Kimodo's smplx22 assets folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp


# Same position transform used by Kimodo's AMASS exporter: Y-up/+Z forward
# becomes Z-up/+Y forward. Apply ONCE, directly to skinned world positions.
KIMODO_TO_BLENDER = np.array([[-1., 0., 0.], [0., 0., 1.], [0., 1., 0.]], dtype=np.float32)


def resample_body(local, root, source_fps, target_fps):
    local = np.asarray(local, dtype=np.float32)
    root = np.asarray(root, dtype=np.float32)
    if local.ndim == 5 and local.shape[0] == 1:
        local = local[0]
    if root.ndim == 3 and root.shape[0] == 1:
        root = root[0]
    if local.ndim != 4 or local.shape[1:] != (22, 3, 3):
        raise ValueError('Expected a single SMPL-X body clip: local_rot_mats [T,22,3,3]')
    if root.shape != (len(local), 3) or len(local) < 1:
        raise ValueError('Expected root_positions [T,3] with matching nonzero frame count')
    if source_fps <= 0 or target_fps <= 0:
        raise ValueError('Frame rates must be positive')
    if not np.isfinite(local).all() or not np.isfinite(root).all():
        raise ValueError('Motion contains nonfinite values')
    if not np.allclose(local.swapaxes(-1, -2) @ local, np.eye(3), atol=2e-3) or not np.allclose(np.linalg.det(local), 1, atol=2e-3):
        raise ValueError('Invalid rotation matrices')
    times = np.arange(max(1, int(round(len(local) * target_fps / source_fps)))) / target_fps
    src_times = np.arange(len(local)) / source_fps
    sample_times = np.minimum(times, src_times[-1])
    root_out = np.stack([np.interp(sample_times, src_times, root[:, i]) for i in range(3)], axis=-1)
    if len(local) == 1:
        local_out = np.repeat(local, len(times), axis=0)
    else:
        local_out = np.stack([
            Slerp(src_times, Rotation.from_matrix(local[:, j]))(sample_times).as_matrix()
            for j in range(22)
        ], axis=1)
    return local_out.astype(np.float32), root_out.astype(np.float32), times


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--motion', required=True, type=Path, help='Native Kimodo .npz, NOT *_amass.npz')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--source-fps', type=float, default=30)
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--chunk-size', type=int, default=8)
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error('--chunk-size must be positive')
    with np.load(args.motion, allow_pickle=False) as data:
        local, root, times = resample_body(data['local_rot_mats'], data['root_positions'], args.source_fps, args.fps)

    import torch
    from kimodo.skeleton import SMPLXSkeleton22
    from kimodo.viz.smplx_skin import SMPLXSkin

    skeleton = SMPLXSkeleton22().cpu()
    asset_dir = Path(skeleton.folder)
    skin_file = asset_dir / 'SMPLX_NEUTRAL.npz'
    if not skin_file.is_file():
        raise FileNotFoundError(f'Download the licensed SMPL-X removed-head-bun NPZ and place it at: {skin_file}')
    skin = SMPLXSkin(skeleton, use_mean_hands=True)
    vertices, joints = [], []
    with torch.inference_mode():
        for start in range(0, len(local), args.chunk_size):
            rotations = torch.from_numpy(local[start:start + args.chunk_size])
            positions = torch.from_numpy(root[start:start + args.chunk_size])
            _, posed, _ = skeleton.fk(rotations, positions)
            vertices.append(skin.skin(rotations, posed).cpu().numpy())
            joints.append(posed.cpu().numpy())
            print(f'Skinned {min(start + args.chunk_size, len(local))}/{len(local)}', flush=True)
    vertices = np.concatenate(vertices) @ KIMODO_TO_BLENDER.T
    joints = np.concatenate(joints) @ KIMODO_TO_BLENDER.T
    faces = skin.faces.cpu().numpy().astype(np.int32)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out, schema_version=np.int32(1), surface_model_type=np.array('smplx'),
        coordinate_system=np.array('Blender Z-up, +Y forward, meters'), fps=np.float64(args.fps),
        time_seconds=times, vertices=vertices.astype(np.float32), faces=faces,
        joints=joints.astype(np.float32), joint_names=np.array(skeleton.bone_order_names),
        vertex_ids=np.arange(vertices.shape[1], dtype=np.int32),
        local_rot_mats_kimodo=local, root_positions_kimodo=root,
        betas=np.load(asset_dir / 'beta.npy'), mean_hands=np.load(asset_dir / 'mean_hands.npy'),
        kimodo_to_blender=KIMODO_TO_BLENDER,
    )
    metadata = {
        'source': str(args.motion.resolve()),
        'source_sha256': hashlib.sha256(args.motion.read_bytes()).hexdigest(),
        'skin_model_sha256': hashlib.sha256(skin_file.read_bytes()).hexdigest(),
        'source_fps': args.source_fps, 'fps': args.fps, 'frames': len(times),
        'duration_seconds': len(times) / args.fps, 'vertices': int(vertices.shape[1]),
        'faces': len(faces), 'body_joints': 22,
        'method': 'Kimodo SMPLXSkin; full beta.npy; mean hands; neutral face; body quaternion SLERP before skinning',
        'status': 'skinned mesh cache; not video reconstruction',
    }
    args.out.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
