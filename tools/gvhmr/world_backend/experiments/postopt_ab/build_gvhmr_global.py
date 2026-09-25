#!/usr/bin/env python3
"""GVHMR's OWN world-space output as a comparison arm.

`build_results.py` builds `init` from `smpl_params_incam` lifted into the Pi3X world.
That is the *input* to v1/v2. It is not what GVHMR itself produces in world space:
GVHMR has its own global branch (`smpl_params_global`), gravity-aligned and
contact-aware, and that is the thing v1/v2 are meant to replace. Without it in the
table the comparison has no baseline at all -- only "before and after our own
lifting".

The camera is recovered exactly rather than assumed. `body_pose` and `betas` are
bit-identical between the two parameter sets -- only `global_orient` and `transl`
differ -- so the two joint sets are the same rigid body in two frames, and a Kabsch
fit per frame recovers the camera with no residual. The script asserts that
residual, so a wrong convention cannot pass silently. Reprojection is therefore
identical to `init` by construction, and any 3D difference is GVHMR's global branch
alone.

Two things this arm does NOT get, both deliberate:
  * a metric scale. GVHMR's global translation is in its own units; it never sees a
    metric camera. Distances are comparable within the arm, not against Pi3X.
  * the Pi3X world. It lives in GVHMR's own gravity-aligned frame.
Foot sliding, penetration and acceleration are invariant to the first only up to
that scale factor, so the scale is reported alongside.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('build_results', HERE / 'build_results.py')
BR = importlib.util.module_from_spec(spec)
sys.modules['build_results'] = BR
spec.loader.exec_module(BR)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gvhmr-run', required=True)
    ap.add_argument('--init', required=True, help='results_init.pkl, for kp/bbox/frames')
    ap.add_argument('--smplx-model', required=True)
    ap.add_argument('--out', required=True, help='results_gvhmr.pkl to write')
    a = ap.parse_args()

    device = 'cuda'
    import smplx as smplx_pkg
    body = smplx_pkg.SMPLX(a.smplx_model, use_pca=False, flat_hand_mean=True,
                           num_betas=10).to(device)

    run = Path(a.gvhmr_run)
    hmr = torch.load(run / 'hmr4d_results.pt', map_location='cpu', weights_only=False)
    glob, incam = hmr['smpl_params_global'], hmr['smpl_params_incam']
    init = joblib.load(a.init)
    T = glob['transl'].shape[0]

    betas = glob['betas'].numpy().astype(np.float64)
    mean_betas = betas.mean(0, keepdims=True)
    with torch.no_grad():
        pelvis0 = body(betas=torch.tensor(mean_betas, dtype=torch.float32, device=device),
                       global_orient=torch.zeros(1, 3, device=device),
                       body_pose=torch.zeros(1, 63, device=device)).joints[0, 0]
    pelvis0 = pelvis0.cpu().numpy().astype(np.float64)

    R_g = BR.axis_angle_to_matrix(glob['global_orient'].double()).numpy()

    zeros_ = lambda n, m: torch.zeros(m, n, dtype=torch.float32, device=device)

    def joints_of(params, orient):
        n = orient.shape[0]
        with torch.no_grad():
            return body(global_orient=torch.tensor(orient, dtype=torch.float32, device=device),
                        body_pose=params['body_pose'].float().to(device),
                        betas=torch.tensor(np.repeat(mean_betas, n, 0),
                                           dtype=torch.float32, device=device),
                        transl=params['transl'].float().to(device),
                        left_hand_pose=zeros_(45, n), right_hand_pose=zeros_(45, n),
                        jaw_pose=zeros_(3, n), leye_pose=zeros_(3, n),
                        reye_pose=zeros_(3, n), expression=zeros_(10, n)
                        ).joints[:, :55].cpu().numpy().astype(np.float64)

    J_g = joints_of(glob, glob['global_orient'].numpy())
    J_c = joints_of(incam, incam['global_orient'].numpy())

    # Kabsch per frame: the rigid map taking the global body onto the in-camera one
    Rcw = np.empty((T, 3, 3)); Tcw = np.empty((T, 3))
    mg, mc = J_g.mean(1), J_c.mean(1)
    for i in range(T):
        H = (J_g[i] - mg[i]).T @ (J_c[i] - mc[i])
        U, _, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        Rcw[i] = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
        Tcw[i] = mc[i] - Rcw[i] @ mg[i]
    resid = np.abs((Rcw[:, None] @ J_g[..., None])[..., 0] + Tcw[:, None] - J_c).max()
    if resid > 1e-4:
        raise RuntimeError(f'camera recovery residual {resid:.2e} m -- not a rigid pair')
    print(f'camera recovered by Kabsch, max joint residual {resid:.2e} m')

    Rwc = Rcw.transpose(0, 2, 1)
    Twc = -(Rwc @ Tcw[..., None])[..., 0]

    pose = np.zeros((T, 55 * 3), dtype=np.float64)
    pose[:, :3] = BR.matrix_to_axis_angle(torch.from_numpy(R_g)).numpy()
    pose[:, 3:66] = glob['body_pose'].numpy().astype(np.float64)
    shape = np.repeat(mean_betas, T, axis=0)
    transl = glob['transl'].numpy().astype(np.float64).copy()

    zeros = lambda n: torch.zeros(T, n, dtype=torch.float32, device=device)
    fwd = lambda tr: body(
        global_orient=torch.tensor(pose[:, :3], dtype=torch.float32, device=device),
        body_pose=torch.tensor(pose[:, 3:66], dtype=torch.float32, device=device),
        betas=torch.tensor(shape, dtype=torch.float32, device=device),
        transl=torch.tensor(tr, dtype=torch.float32, device=device),
        left_hand_pose=zeros(45), right_hand_pose=zeros(45), jaw_pose=zeros(3),
        leye_pose=zeros(3), reye_pose=zeros(3), expression=zeros(10))
    with torch.no_grad():
        verts = fwd(transl).vertices
    floor_y = BR.ransac_floor_height(verts[..., 1].min(dim=1).values.cpu().numpy())
    transl[:, 1] -= floor_y
    Twc[:, 1] -= floor_y
    Tcw = -(Rcw @ Twc[..., None])[..., 0]

    p = init['people'][list(init['people'])[0]]
    frames = np.asarray(p['frames'])
    cw = init['camera_world']

    out = {
        'camera_world': {
            'Rwc': Rwc, 'Twc': Twc, 'Rcw': Rcw, 'Tcw': Tcw,
            'pred_cam_R': Rwc, 'pred_cam_T': Twc,
            'img_focal': cw['img_focal'], 'img_center': cw['img_center'],
            'viz_scale': 1.0, 'viz_center': [0.0, 0.0, 0.0],
        },
        'people': {1: {
            'track_id': 1, 'frames': frames,
            'bboxes': p['bboxes'], 'keypoints_2d': p['keypoints_2d'],
            'smplx_world': {'pose': pose[frames].astype(np.float32),
                            'shape': shape[frames].astype(np.float32),
                            'trans': transl[frames].astype(np.float32)},
            'smplx_cam': p['smplx_cam'],
        }},
        'has_slam': True, 'has_hps_world': True, 'has_post_opt': True,
        'n_frames': int(init['n_frames']), 'image_size': init['image_size'],
    }

    # the camera recovery must reproduce the in-camera body exactly
    with torch.no_grad():
        j_w = fwd(transl).joints[:, BR.SMPLX_TO_OP25 if hasattr(BR, 'SMPLX_TO_OP25')
                  else [55, 12, 17, 19, 21, 16, 18, 20, 0, 2, 5, 8, 1, 4, 7,
                        56, 57, 58, 59, 60, 61, 62, 63, 64, 65]]
    j_w = j_w.cpu().numpy().astype(np.float64)
    j_cam = (Rcw[:, None] @ j_w[..., None])[..., 0] + Tcw[:, None]
    K = np.eye(3); K[0, 0] = K[1, 1] = cw['img_focal']
    K[0, 2], K[1, 2] = cw['img_center']
    uv = (K[None, None] @ j_cam[..., None])[..., 0]
    uv = uv[..., :2] / np.clip(uv[..., 2:3], 1e-3, None)
    kp = np.asarray(p['keypoints_2d'])[:, :25]
    m = kp[..., 2] > 0.5
    err = np.linalg.norm(uv[frames] - kp[..., :2], axis=-1)
    reproj = float(np.median(err[m])) if m.any() else float('nan')

    scale = (np.linalg.norm(np.diff(Twc, axis=0), axis=1).sum() /
             max(np.linalg.norm(np.diff(np.asarray(cw['Twc']), axis=0), axis=1).sum(), 1e-9))
    joblib.dump(out, a.out)
    meta = {'frames': int(T), 'floor_y_removed': float(floor_y),
            'reproj_median_px': reproj,
            'camera_path_m_gvhmr_frame': float(np.linalg.norm(np.diff(Twc, axis=0), axis=1).sum()),
            'camera_path_ratio_vs_pi3x': float(scale)}
    Path(str(a.out) + '.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == '__main__':
    main()
