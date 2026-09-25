#!/usr/bin/env python3
"""Adapt a GVHMR_BEDLAM2 run + Pi3X camera track into PromptHMR's `results` dict.

Why this exists
---------------
`pipeline/postprocessing.py` (v1) and `pipeline/postprocessing_v2.py` (v2) are
PromptHMR pipeline stages: they consume the dict that `pipeline/world.py`
produces. PromptHMR itself is not installed in this checkout, but GVHMR_BEDLAM2
is, and it predicts the *same* SMPL-X parameterisation. The one thing GVHMR does
not provide is a metric camera translation -- it keeps only DPVO's rotations --
so the camera comes from the project's reviewed Pi3X bundle instead, which is
metric ("predicted metres; uncalibrated").

That substitution is what makes the A/B meaningful: v2's `log_scale` corrects
exactly the kind of uncalibrated-metric error Pi3X carries.

Construction mirrors `pipeline/world.py`:
  1. lift the trusted camera-space SMPL-X bodies into the Pi3X world with the
     per-frame c2w,
  2. rotate that Z-up world to the Y-up convention the post-optimisers assume,
  3. RANSAC the floor to y=0 (same algorithm as prompt_hmr.vis.traj).

Known deviations from a native PromptHMR run, identical for v1 and v2 so the
comparison stays fair:
  * ViTPose here is COCO-17, so the OpenPose-25 slots with no COCO source
    (neck, mid-hip, toes, heels) carry zero confidence and are ignored.
  * one reviewed actor per GVHMR run, not PromptHMR's multi-person tracking.
  * the Pi3X camera is interpolated from sparse reviewed observations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import torch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))



def _load(name, relpath):
    """Import a standalone module by path.

    pipeline/__init__.py imports the detector stack (filterpy, ViTPose, ...) and
    prompt_hmr/__init__.py imports yacs; neither is needed here and neither is
    guaranteed in the GVHMR runtime, so the two leaf modules are loaded directly.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, REPO / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_rc = _load('phmr_rotation_conversions', 'prompt_hmr/utils/rotation_conversions.py')
axis_angle_to_matrix = _rc.axis_angle_to_matrix
matrix_to_axis_angle = _rc.matrix_to_axis_angle

# Pi3X world is Z-up; both post-optimisers assume Y-up with the floor at y=0.
Z_UP_TO_Y_UP = np.array([[1.0, 0.0, 0.0],
                         [0.0, 0.0, 1.0],
                         [0.0, -1.0, 0.0]])


# COCO-17 index for each OpenPose-25 slot; None = no COCO source, left at conf 0.
# pipeline/kp_utils.convert_kps cannot do this: its COCO table says 'nose' and its
# OpenPose table says 'OP Nose', so the name join is empty and it returns zeros.
COCO17_TO_OP25 = [
    0,      # 0  OP Nose      <- nose
    None,   # 1  OP Neck      <- synthesised from both shoulders
    6,      # 2  OP RShoulder
    8,      # 3  OP RElbow
    10,     # 4  OP RWrist
    5,      # 5  OP LShoulder
    7,      # 6  OP LElbow
    9,      # 7  OP LWrist
    None,   # 8  OP MidHip    <- synthesised from both hips
    12,     # 9  OP RHip
    14,     # 10 OP RKnee
    16,     # 11 OP RAnkle
    11,     # 12 OP LHip
    13,     # 13 OP LKnee
    15,     # 14 OP LAnkle
    2,      # 15 OP REye
    1,      # 16 OP LEye
    4,      # 17 OP REar
    3,      # 18 OP LEar
    None, None, None, None, None, None,   # 19-24 toes and heels: absent from COCO-17
]


def coco17_to_openpose25(kp):
    """(T,17,3) COCO-17 -> (T,25,3) OpenPose-25; unmapped slots keep confidence 0."""
    out = np.zeros((kp.shape[0], 25, 3), dtype=np.float64)
    for dst, src in enumerate(COCO17_TO_OP25):
        if src is not None:
            out[:, dst] = kp[:, src]
    # Neck and MidHip are midpoints; confidence is the weaker of the two endpoints
    for dst, (a, b) in ((1, (5, 6)), (8, (11, 12))):
        out[:, dst, :2] = 0.5 * (kp[:, a, :2] + kp[:, b, :2])
        out[:, dst, 2] = np.minimum(kp[:, a, 2], kp[:, b, 2])
    return out


def ransac_floor_height(points_y, inlier_thresh=0.05, iters=10000, seed=0):
    """Same estimator as prompt_hmr.vis.traj.fit_floor_height(method='ransac')."""
    zs = np.sort(np.asarray(points_y, dtype=np.float64))
    rng = np.random.RandomState(seed)
    best_inliers, best_z = 0, 0.0
    for _ in range(iters):
        z = zs[rng.randint(len(zs))]
        inliers = int(np.sum(np.abs(zs - z) < inlier_thresh))
        if inliers > best_inliers:
            best_inliers, best_z = inliers, z
    return float(np.median(zs[np.abs(zs - best_z) < inlier_thresh]))


def transform_smpl_params(root_orient, transl, R, t, pelvis0):
    """Port of pipeline/world.py:transform_smpl_params (numpy, batched)."""
    transl = (R @ (pelvis0[None, :, None] + transl[..., None]))[..., 0] + t - pelvis0[None]
    root_orient = R @ root_orient
    return root_orient, transl


def build(gvhmr_run, camera_tracks, smplx_model_path, actor_id, out_dir, device='cuda'):
    import smplx as smplx_pkg

    gvhmr_run, camera_tracks = Path(gvhmr_run), Path(camera_tracks)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    hmr = torch.load(gvhmr_run / 'hmr4d_results.pt', map_location='cpu', weights_only=False)
    bbx = torch.load(gvhmr_run / 'preprocess' / 'bbx.pt', map_location='cpu', weights_only=False)
    vit = torch.load(gvhmr_run / 'preprocess' / 'vitpose.pt', map_location='cpu', weights_only=False)
    cams = np.load(camera_tracks, allow_pickle=True)

    incam = hmr['smpl_params_incam']
    T = incam['transl'].shape[0]
    # the network's own world-frame orientation (global branch); v2 takes its
    # orientation from this and its position from the camera
    orient_world = hmr['smpl_params_global']['global_orient'].numpy().astype(np.float64)
    K = hmr['K_fullimg'].numpy().astype(np.float64)

    # With a reviewed lifecycle the run is split: the top-level file is the full
    # clip with an inactive tail padded in, and the model outputs live under
    # active_inference/ for the active prefix only. The tail is explicitly not
    # estimated motion, so it must not become a body here.
    active = hmr.get('track_active')
    active = np.ones(T, bool) if active is None else np.asarray(active).astype(bool)
    if 'net_outputs' in hmr:
        static_logits = hmr['net_outputs']['static_conf_logits'][0].float().numpy()
    else:
        act = torch.load(gvhmr_run / 'active_inference' / 'hmr4d_results.pt',
                         map_location='cpu', weights_only=False)
        prefix = act['net_outputs']['static_conf_logits'][0].float().numpy()
        static_logits = np.zeros((T, prefix.shape[1]), dtype=np.float64)
        static_logits[:len(prefix)] = prefix
        if int(active.sum()) != len(prefix):
            raise ValueError(f'active prefix {int(active.sum())} != inference {len(prefix)}')

    c2w = np.asarray(cams['c2w'], dtype=np.float64)
    if len(c2w) != T:
        raise ValueError(f'camera track has {len(c2w)} frames, GVHMR has {T}')
    img_w, img_h = (int(v) for v in cams['image_size'])

    # --- camera: Pi3X Z-up -> Y-up, OpenCV camera axes throughout -----------
    Rwc = Z_UP_TO_Y_UP[None] @ c2w[:, :3, :3]
    Twc = (Z_UP_TO_Y_UP[None] @ c2w[:, :3, 3][..., None])[..., 0]

    # --- bodies: camera space (trusted) -> world, via the camera -----------
    body = smplx_pkg.SMPLX(str(smplx_model_path), use_pca=False,
                           flat_hand_mean=True, num_betas=10).to(device)

    betas = incam['betas'].numpy().astype(np.float64)
    mean_betas = betas.mean(0, keepdims=True)
    with torch.no_grad():
        pelvis0 = body(betas=torch.tensor(mean_betas, dtype=torch.float32, device=device),
                       global_orient=torch.zeros(1, 3, device=device),
                       body_pose=torch.zeros(1, 63, device=device)).joints[0, 0]
    pelvis0 = pelvis0.cpu().numpy().astype(np.float64)

    root_cam = axis_angle_to_matrix(incam['global_orient'].double()).numpy()
    transl_cam = incam['transl'].numpy().astype(np.float64)
    root_w, transl_w = transform_smpl_params(root_cam, transl_cam, Rwc, Twc, pelvis0)

    # full 55-joint SMPL-X axis-angle pose; GVHMR predicts body only
    pose = np.zeros((T, 55 * 3), dtype=np.float64)
    pose[:, :3] = matrix_to_axis_angle(torch.from_numpy(root_w)).numpy()
    pose[:, 3:66] = incam['body_pose'].numpy().astype(np.float64)
    shape = np.repeat(mean_betas, T, axis=0)

    # --- floor to y=0 (RANSAC on the lowest vertex per frame) ---------------
    zeros = lambda n: torch.zeros(T, n, dtype=torch.float32, device=device)
    with torch.no_grad():
        # every optional field must be passed explicitly: the model was created
        # with batch_size=1, so its internal buffers would not broadcast to T
        verts = body(global_orient=torch.tensor(pose[:, :3], dtype=torch.float32, device=device),
                     body_pose=torch.tensor(pose[:, 3:66], dtype=torch.float32, device=device),
                     betas=torch.tensor(shape, dtype=torch.float32, device=device),
                     transl=torch.tensor(transl_w, dtype=torch.float32, device=device),
                     left_hand_pose=zeros(45), right_hand_pose=zeros(45),
                     jaw_pose=zeros(3), leye_pose=zeros(3), reye_pose=zeros(3),
                     expression=zeros(10)).vertices
    floor_y = ransac_floor_height(verts[..., 1].min(dim=1).values.cpu().numpy())
    transl_w[:, 1] -= floor_y
    Twc[:, 1] -= floor_y

    Rcw = Rwc.transpose(0, 2, 1)
    Tcw = -(Rcw @ Twc[..., None])[..., 0]

    # --- 2D keypoints: COCO-17 -> OpenPose-25 (missing slots stay conf 0) ---
    kp25 = coco17_to_openpose25(vit.numpy().astype(np.float64))

    bbx_xyxy = bbx['bbx_xyxy'].numpy().astype(np.float64)
    valid = ((bbx_xyxy[:, 2] - bbx_xyxy[:, 0]) > 1) & ((bbx_xyxy[:, 3] - bbx_xyxy[:, 1]) > 1)
    valid &= active                       # nothing after the reviewed terminal exit
    frames = np.nonzero(valid)[0].astype(np.int64)

    results = {
        'camera_world': {
            'Rwc': Rwc, 'Twc': Twc, 'Rcw': Rcw, 'Tcw': Tcw,
            'pred_cam_R': Rwc, 'pred_cam_T': Twc,
            'img_focal': float(K[:, 0, 0].mean()),
            'img_center': np.array([K[:, 0, 2].mean(), K[:, 1, 2].mean()]),
            'viz_scale': 1.0, 'viz_center': [0.0, 0.0, 0.0],
        },
        'people': {
            1: {
                'track_id': 1,
                'frames': frames,
                'bboxes': bbx_xyxy[frames],
                'keypoints_2d': kp25[frames],
                'smplx_world': {'pose': pose[frames].astype(np.float32),
                                'shape': shape[frames].astype(np.float32),
                                'trans': transl_w[frames].astype(np.float32)},
                'smplx_cam': {'static_conf_logits': static_logits[frames],
                              'trans': transl_cam[frames],
                              'global_orient_world': orient_world[frames]},
            }
        },
        'has_slam': True, 'has_hps_world': True, 'has_post_opt': False,
        'n_frames': T, 'image_size': [img_w, img_h],
    }

    # --- sanity: reproject the lifted world joints back into the image -------
    # If the Z-up/Y-up swap or the c2w convention were wrong this explodes, so it
    # is the cheapest end-to-end check that the coordinate chain is consistent.
    SMPLX_TO_OP25 = [55, 12, 17, 19, 21, 16, 18, 20, 0, 2, 5, 8, 1, 4, 7,
                     56, 57, 58, 59, 60, 61, 62, 63, 64, 65]
    with torch.no_grad():
        j_w = body(global_orient=torch.tensor(pose[:, :3], dtype=torch.float32, device=device),
                   body_pose=torch.tensor(pose[:, 3:66], dtype=torch.float32, device=device),
                   betas=torch.tensor(shape, dtype=torch.float32, device=device),
                   transl=torch.tensor(transl_w, dtype=torch.float32, device=device),
                   left_hand_pose=zeros(45), right_hand_pose=zeros(45),
                   jaw_pose=zeros(3), leye_pose=zeros(3), reye_pose=zeros(3),
                   expression=zeros(10)).joints[:, SMPLX_TO_OP25]
    j_w = j_w.cpu().numpy().astype(np.float64)
    j_cam = (Rcw[:, None] @ j_w[..., None])[..., 0] + Tcw[:, None]
    uv = (K[:, None] @ j_cam[..., None])[..., 0]
    uv = uv[..., :2] / np.clip(uv[..., 2:3], 1e-3, None)
    conf = kp25[..., 2] > 0.5
    err = np.linalg.norm(uv - kp25[..., :2], axis=-1)
    bbh = np.clip(bbx_xyxy[:, 3] - bbx_xyxy[:, 1], 1, None)
    reproj_px = float(np.median(err[conf])) if conf.any() else float('nan')
    reproj_rel = float(np.median((err / bbh[:, None])[conf])) if conf.any() else float('nan')

    joblib.dump(results, out_dir / 'results_init.pkl')
    meta = {
        'gvhmr_run': str(gvhmr_run), 'camera_tracks': str(camera_tracks),
        'actor_id': actor_id, 'frames_total': int(T), 'frames_valid': int(len(frames)),
        'frames_active': int(active.sum()),
        'img_focal': results['camera_world']['img_focal'],
        'img_center': results['camera_world']['img_center'].tolist(),
        'image_size': [img_w, img_h],
        'floor_y_removed': floor_y,
        'camera_path_len_m': float(np.linalg.norm(np.diff(Twc, axis=0), axis=1).sum()),
        'camera_observations': int(cams['observation_c2w'].shape[0]),
        'kp25_nonzero_conf_slots': sorted(int(i) for i in np.nonzero(kp25[frames][..., 2].max(0))[0]),
        'kp25_conf_gt0.5_per_frame': float((kp25[frames][..., 2] > 0.5).sum(1).mean()),
        'init_reproj_median_px': reproj_px,
        'init_reproj_median_frac_bbox_height': reproj_rel,
    }
    (out_dir / 'adapter_meta.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gvhmr-run', required=True)
    ap.add_argument('--camera-tracks', required=True)
    ap.add_argument('--smplx-model', required=True)
    ap.add_argument('--actor-id', default='reviewed_actor')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    build(a.gvhmr_run, a.camera_tracks, a.smplx_model, a.actor_id, a.out)


if __name__ == '__main__':
    main()
