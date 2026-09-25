"""Resample rotations before skinning and preserve rational output timestamps."""
import argparse
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation

from aha3d.io import read, write
from aha3d.motion.cache import KIMODO_TO_BLENDER, resample_body


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--motion', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--fps', default='24')
    p.add_argument('--frames', type=int)
    p.add_argument('--source-fps', type=float, default=30)
    p.add_argument('--recipe', type=Path)
    a = p.parse_args()
    target_fps = float(Fraction(a.fps))
    config = read(a.recipe).get('body', {}) if a.recipe else {}
    with np.load(a.motion, allow_pickle=False) as src:
        local, root = src['local_rot_mats'], src['root_positions']
    if local.ndim == 5:
        local = local[0]; root = root[0]
    if config.get('max_root_step') is not None and len(root) > 1:
        if np.linalg.norm(np.diff(root, axis=0), axis=-1).max() > config['max_root_step']:
            raise ValueError('Raw motion exceeds configured root-step limit; inspect it before skinning')
    smoothing = config.get('smoothing')
    if smoothing:
        radius = int(smoothing['radius']); sigma = float(smoothing['sigma'])
        if radius < 1 or sigma <= 0:
            raise ValueError('Smoothing radius and sigma must be positive')
        offsets = np.arange(-radius, radius + 1)
        weights = np.exp(-.5 * (offsets / sigma) ** 2); weights /= weights.sum()
        filtered = np.empty_like(local)
        for joint in range(local.shape[1]):
            base = Rotation.from_matrix(local[:, joint]); increments = np.zeros((len(local), 3))
            for offset, weight in zip(offsets, weights):
                other = Rotation.from_matrix(local[np.clip(np.arange(len(local)) + offset, 0, len(local) - 1), joint])
                increments += weight * (base.inv() * other).as_rotvec()
            filtered[:, joint] = (base * Rotation.from_rotvec(increments)).as_matrix()
        local = filtered
        root = gaussian_filter1d(root, sigma, axis=0, mode='nearest', truncate=radius / sigma)
    local, root, times = resample_body(local, root, a.source_fps, target_fps, a.frames)
    import torch
    from kimodo.skeleton import SMPLXSkeleton22
    from kimodo.exports.smplx import get_amass_parameters
    skeleton = SMPLXSkeleton22().cpu()
    asset = Path(skeleton.folder)
    trans, orient, pose = get_amass_parameters(local, root, skeleton, z_up=True)
    trans = np.asarray(trans).reshape(-1, 3); orient = np.asarray(orient).reshape(-1, 3); pose = np.asarray(pose).reshape(-1, 63)
    hands = np.load(asset / 'mean_hands.npy').reshape(90)
    poses = np.concatenate([orient, pose, np.zeros((len(times), 9)), np.broadcast_to(hands, (len(times), 90))], axis=1)
    with torch.inference_mode():
        _, joints, _ = skeleton.fk(torch.from_numpy(local), torch.from_numpy(root))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    # The add-on's importer accepts integer rates. Give it one pose per nominal
    # frame, then set actual playback rate after import; rotations were already
    # sampled on the precise output timestamps above.
    np.savez_compressed(a.out, trans=trans, poses=poses, gender=np.array('neutral'),
        betas=np.load(asset / 'beta.npy'), mocap_frame_rate=float(max(1, round(target_fps))), output_fps=target_fps,
        surface_model_type=np.array('smplx'), time_seconds=times, local_rot_mats_kimodo=local,
        root_positions_kimodo=root, joint_names=np.array(skeleton.bone_order_names),
        joints_kimodo_zup=joints.numpy() @ KIMODO_TO_BLENDER.T, mean_hands=hands, kimodo_to_blender=KIMODO_TO_BLENDER)
    write(a.out.with_suffix('.json'), {'frames': len(times), 'fps': a.fps, 'source_fps': a.source_fps,
        'duration_seconds': len(times) / target_fps, 'betas': len(np.load(asset / 'beta.npy')),
        'method': 'Quaternion SLERP at output timestamps before skinning; endpoint held if needed', 'smoothing': smoothing})


if __name__ == '__main__':
    main()
