"""Reuse a source-bound reconstructed floor; never fit ground from a human.

The prior describes the plane in the SAME aligned world as camera_tracks.npz.
One rigid transform maps that world to Y-up, floor Y=0. Its inverse is retained
for scene export. This is a coordinate change, not a body-height correction.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

import numpy as np


def load_prior(path, source_sha256):
    path = Path(path)
    data = json.loads(path.read_text())
    if data.get('source_video_sha256') != source_sha256:
        raise ValueError('Scene ground belongs to a different source video')
    if data.get('coordinate_frame') != 'pi3x-aligned-world' or data.get('scale') != 1:
        raise ValueError('Ground must use the camera aligned-world basis at scale 1')
    if not data.get('evidence') or data.get('accepted') is not True:
        raise ValueError('A previously accepted scene floor with fit evidence is required')
    plane = np.asarray(data['plane'], float)
    up = np.asarray(data['upright'], float)
    if plane.shape != (4,) or up.shape != (3,) or not np.isfinite(np.r_[plane, up]).all():
        raise ValueError('Expected finite plane [nx,ny,nz,d] and upright [x,y,z]')
    if np.linalg.norm(plane[:3]) < 1e-8 or np.linalg.norm(up) < 1e-8:
        raise ValueError('Zero floor normal/upright')
    plane /= np.linalg.norm(plane[:3]); up /= np.linalg.norm(up)
    if plane[:3] @ up < 0:
        plane *= -1
    if not np.allclose(plane[:3], up, atol=1e-4, rtol=0):
        raise ValueError('This flat-ground adapter requires a floor perpendicular to upright')
    # Prefer world X as horizontal heading, with a stable fallback near poles.
    x = np.eye(3)[0] - up * up[0]
    if np.linalg.norm(x) < 1e-6:
        x = np.eye(3)[1] - up * up[1]
    x /= np.linalg.norm(x)
    transform = np.eye(4)
    transform[:3, :3] = np.stack([x, up, np.cross(x, up)])
    transform[1, 3] = plane[3]
    return dict(data, plane=plane.tolist(), upright=up.tolist(),
                world_to_ground=transform.tolist(), ground_to_world=np.linalg.inv(transform).tolist(),
                prior_path=str(path.absolute()), prior_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def ground_cameras(c2w, prior):
    from tools.gvhmr.camera_tracks import rigid
    return np.asarray(prior['world_to_ground']) @ rigid(c2w)


def yaw_rotation_6d(value):
    """SO(2) placement: preserve the supplied upright exactly during v2 fitting.

    Called only for v2's constant placement variable, never for body rotations.
    The upstream 6D convention stores the first two ROWS of the matrix.
    """
    import torch
    angle = torch.atan2(value[..., 2], value[..., 0])
    c, s = angle.cos(), angle.sin()
    z, o = torch.zeros_like(c), torch.ones_like(c)
    return torch.stack([c, z, s, z, o, z, -s, z, c], -1).reshape(*angle.shape, 3, 3)


def scene_orientation(optimizer):
    """Global and lifted branches already share the scene frame: do not fit G."""
    def orient(cfg, results, people_ids, mask, Rwc0, Twc0, Rco, j_cam, j_world_init, device):
        import torch
        rwc = Rwc0[None].expand(len(people_ids), -1, -1, -1).clone()
        twc = Twc0[None].expand(len(people_ids), -1, -1).clone()
        for index, pid in enumerate(people_ids):
            frames = torch.nonzero(mask[index] > 0, as_tuple=False).squeeze(-1)
            aa = results['people'][pid]['smplx_cam']['global_orient_world']
            target = optimizer.axis_angle_to_matrix(torch.as_tensor(aa, dtype=Rwc0.dtype, device=device))
            correction = target @ (Rwc0[frames] @ Rco[index, frames]).mT
            pelvis = j_world_init[index, frames, optimizer.PELVIS_IDX]
            rwc[index, frames] = correction @ Rwc0[frames]
            twc[index, frames] = (correction @ (Twc0[frames]-pelvis)[..., None])[..., 0]+pelvis
        joints = torch.einsum('ptij,ptkj->ptki', rwc, j_cam) + twc[:, :, None]
        return rwc, twc, joints
    return orient


@contextmanager
def gvhmr_scene_context(c2w, prior):
    """Replace world rollout and body-derived ground origin inside DemoPL.predict.

    In-camera fitting, contact-aware velocity and upstream IK remain unchanged.
    GVHMR jointly predicts its gravity branch; this skips its *use*, not a model.
    Hooks are process-local, restored even on failure; installed code is untouched.
    """
    import torch
    import hmr4d.model.gvhmr.pipeline.gvhmr_pipeline as pipeline
    from pytorch3d.transforms import axis_angle_to_matrix, matrix_to_axis_angle
    from hmr4d.utils.geo.hmr_global import rollout_local_transl_vel

    cameras = ground_cameras(c2w, prior)
    original_rollout, original_pp = pipeline.get_smpl_params_w_Rt_v2, pipeline.pp_static_joint
    report = dict(gravity_source='reconstructed_scene', floor_source='reconstructed_scene',
                  separate_gravity_model_calls=0, joint_gravity_head_still_evaluated=True,
                  body_ground_fit_applied=False, rollout_calls=0, postprocess_calls=0, prior=prior)

    def rollout(global_orient_gv, local_transl_vel, global_orient_c, cam_angvel):
        if global_orient_c.shape[:2] != (1, len(cameras)):
            raise ValueError('Scene camera timeline differs from active GVHMR prefix')
        rotation = torch.as_tensor(cameras[:, :3, :3], device=global_orient_c.device,
                                   dtype=global_orient_c.dtype)[None]
        orient = matrix_to_axis_angle(rotation @ axis_angle_to_matrix(global_orient_c))
        report['rollout_calls'] += 1
        return dict(global_orient=orient, transl=rollout_local_transl_vel(local_transl_vel, orient))

    def postprocess(outputs, endecoder):
        # Upstream contact velocity stays intact. Undo ONLY its arbitrary global
        # origin by anchoring the first pelvis to the scene camera observation.
        trans = original_pp(outputs, endecoder)
        world = dict(outputs['pred_smpl_params_global'], transl=trans)
        jworld = endecoder.fk_v2(**world)[:, 0, 0]
        jcamera = endecoder.fk_v2(**outputs['pred_smpl_params_incam'])[:, 0, 0]
        camera = torch.as_tensor(cameras[0], device=trans.device, dtype=trans.dtype)
        target = (camera[:3, :3] @ jcamera[..., None])[..., 0] + camera[:3, 3]
        report['postprocess_calls'] += 1
        return trans + (target - jworld)[:, None]

    pipeline.get_smpl_params_w_Rt_v2, pipeline.pp_static_joint = rollout, postprocess
    try:
        yield report
    finally:
        pipeline.get_smpl_params_w_Rt_v2, pipeline.pp_static_joint = original_rollout, original_pp


def export_prior(cameras_path, fit_path, out):
    """Convert an existing raw-to-room floor fit into the camera bundle basis."""
    cameras = json.loads(Path(cameras_path).read_text())
    fit = json.loads(Path(fit_path).read_text())
    fit = fit.get('floor_alignment', fit)
    if 'T_bundle_world_to_room' in fit and fit.get('accepted_floor_rectangles_processed_pixels'):
        expected = next((value for key, value in fit['input_hashes'].items() if key.endswith('/cameras.json')), None)
        if expected != hashlib.sha256(Path(cameras_path).read_bytes()).hexdigest():
            raise ValueError('Reviewed room basis belongs to a different camera bundle')
        aligned_to_room = np.asarray(fit['T_bundle_world_to_room'], float)
        floor_reference = fit['accepted_floor_rectangles_processed_pixels']
    elif 'raw_to_room' in fit and fit.get('floor_reference'):
        raw_to_room = np.asarray(fit['raw_to_room'], float)
        aligned_to_room = raw_to_room @ np.linalg.inv(np.asarray(cameras['world_transform']))
        floor_reference = fit['floor_reference']
    else:
        raise ValueError('Require an existing reviewed floor fit, not camera-up alone')
    data = dict(schema_version=1, source_video_sha256=fit['source_video_sha256'],
                coordinate_frame='pi3x-aligned-world', scale=1, accepted=True,
                plane=aligned_to_room[2].tolist(), upright=aligned_to_room[2, :3].tolist(),
                evidence=dict(fit_path=str(Path(fit_path).absolute()),
                              fit_sha256=hashlib.sha256(Path(fit_path).read_bytes()).hexdigest(),
                              camera_sha256=hashlib.sha256(Path(cameras_path).read_bytes()).hexdigest(),
                              floor_reference=floor_reference,
                              limitations=fit.get('limitations', [])))
    Path(out).write_text(json.dumps(data, indent=2) + '\n')
    return load_prior(out, data['source_video_sha256'])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cameras', required=True, type=Path)
    parser.add_argument('--fit', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new output prior')
    export_prior(args.cameras, args.fit, args.out)
