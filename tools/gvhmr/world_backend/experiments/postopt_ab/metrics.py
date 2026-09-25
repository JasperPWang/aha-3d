#!/usr/bin/env python3
"""Compare post-optimiser variants on one clip: reprojection, contact, floor, smoothness.

Every metric is computed from the saved `results` dicts with the same body model,
so init / v1 / v2 are measured identically.

  reproj_px            median 2D error on confident ViTPose joints. Auxiliary:
                       the 2D term is an input to the optimisers, not truth.
  contact_slip_mps     world speed of a foot joint while its contact head fires.
                       Should be ~0; this is the foot-skating measure.
  penetration_cm       how far the lowest body vertex goes below the floor.
  contact_height_cm    height of the lowest vertex while in contact (float/sink).
  root_accel           RMS root acceleration; jitter proxy.
Also dumps per-frame series for the review viewer.
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

REPO = Path(__file__).resolve().parents[2]
CONTACT_JOINTS = [7, 10, 8, 11]          # L_Ankle, L_foot, R_Ankle, R_foot
SMPLX_TO_OP25 = [55, 12, 17, 19, 21, 16, 18, 20, 0, 2, 5, 8, 1, 4, 7,
                 56, 57, 58, 59, 60, 61, 62, 63, 64, 65]
IGNORE_OP = [8, 9, 12]
CONTACT_THRESH = 0.5
CONF_THRESH = 0.5


def _rc():
    s = importlib.util.spec_from_file_location('rc', REPO / 'prompt_hmr/utils/rotation_conversions.py')
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def forward(body, pose, shape, trans, device):
    n = len(pose)
    z = lambda k: torch.zeros(n, k, dtype=torch.float32, device=device)
    t = lambda x: torch.tensor(np.asarray(x), dtype=torch.float32, device=device)
    with torch.no_grad():
        o = body(global_orient=t(pose[:, :3]), body_pose=t(pose[:, 3:66]),
                 betas=t(shape[:, :10]), transl=t(trans),
                 left_hand_pose=t(pose[:, 75:120]), right_hand_pose=t(pose[:, 120:165]),
                 jaw_pose=z(3), leye_pose=z(3), reye_pose=z(3), expression=z(10))
    return o.joints, o.vertices


def evaluate(results, body, fps, device='cuda'):
    cw = results['camera_world']
    K = np.eye(3); K[0, 0] = K[1, 1] = cw['img_focal']
    K[0, 2], K[1, 2] = cw['img_center'][0], cw['img_center'][1]

    per_person, series = {}, {}
    for pid, p in results['people'].items():
        fr = np.asarray(p['frames'])
        # v2 fits one placement per person, so each body is bound to its OWN camera
        # and must be reprojected through that one. Falling back to the shared
        # camera here would measure the disagreement between two people's worlds,
        # not the quality of either fit.
        pcw = p.get('camera_world', cw)
        Rcw, Tcw = np.asarray(pcw['Rcw']), np.asarray(pcw['Tcw'])
        sw = p['smplx_world']
        joints, verts = forward(body, np.asarray(sw['pose']), np.asarray(sw['shape']),
                                np.asarray(sw['trans']), device)

        # ---- reprojection -------------------------------------------------
        j_op = joints[:, SMPLX_TO_OP25].cpu().numpy().astype(np.float64)
        jc = (Rcw[fr][:, None] @ j_op[..., None])[..., 0] + Tcw[fr][:, None]
        uv = (K[None, None] @ jc[..., None])[..., 0]
        uv = uv[..., :2] / np.clip(uv[..., 2:3], 1e-3, None)
        kp = np.asarray(p['keypoints_2d'])[:, :25]
        use = np.ones(25, bool); use[IGNORE_OP] = False
        m = (kp[..., 2] > CONF_THRESH) & use[None]
        # Held-out set: both optimisers only fit joints with conf > 0.9, so the
        # 0.5 < conf <= 0.9 band was never part of either objective. It is the
        # one 2D number here that is not also a training loss.
        held = (kp[..., 2] > CONF_THRESH) & (kp[..., 2] <= 0.9) & use[None]
        err = np.linalg.norm(uv - kp[..., :2], axis=-1)
        bbh = np.clip(np.asarray(p['bboxes'])[:, 3] - np.asarray(p['bboxes'])[:, 1], 1, None)

        # ---- contact slip --------------------------------------------------
        cj = joints[:, CONTACT_JOINTS].cpu().numpy().astype(np.float64)   # (n,4,3)
        conf = 1 / (1 + np.exp(-np.asarray(p['smplx_cam']['static_conf_logits'])[:, :4]))
        step = np.diff(fr) == 1                                  # consecutive source frames only
        spd = np.linalg.norm(np.diff(cj, axis=0), axis=-1) * fps  # (n-1,4) m/s
        on = (np.minimum(conf[1:], conf[:-1]) > CONTACT_THRESH) & step[:, None]
        slip = spd[on] if on.any() else np.array([np.nan])

        # ---- floor ----------------------------------------------------------
        low = verts[..., 1].min(dim=1).values.cpu().numpy().astype(np.float64)
        in_contact = (conf.max(1) > CONTACT_THRESH)
        pen = np.clip(-low, 0, None)

        # ---- smoothness ------------------------------------------------------
        root = np.asarray(sw['trans'], dtype=np.float64)
        acc = (root[2:] + root[:-2] - 2 * root[1:-1]) * fps ** 2
        ok3 = (np.diff(fr, 2) == 0) & (np.diff(fr)[:-1] == 1)
        acc_n = np.linalg.norm(acc[ok3], axis=-1) if ok3.any() else np.array([np.nan])

        per_person[int(pid)] = {
            'frames': int(len(fr)),
            'reproj_px_median': float(np.median(err[m])) if m.any() else None,
            'reproj_frac_bbox_median': float(np.median((err / bbh[:, None])[m])) if m.any() else None,
            'reproj_px_median_heldout': float(np.median(err[held])) if held.any() else None,
            'heldout_samples': int(held.sum()),
            'contact_slip_mps_mean': float(np.nanmean(slip)),
            'contact_slip_mps_median': float(np.nanmedian(slip)),
            'contact_slip_mps_p90': float(np.nanpercentile(slip, 90)),
            # share of planted-foot samples still moving faster than 5 cm/s
            'contact_slip_frac_over_5cms': float(np.nanmean(slip > 0.05)),
            'contact_samples': int(on.sum()),
            'penetration_cm_mean': float(pen.mean() * 100),
            'penetration_cm_max': float(pen.max() * 100),
            'frac_frames_penetrating_1cm': float((pen > 0.01).mean()),
            'contact_height_cm_median': float(np.median(low[in_contact]) * 100) if in_contact.any() else None,
            'root_accel_rms': float(np.sqrt(np.nanmean(acc_n ** 2))),
        }
        series[f'p{pid}_frames'] = fr
        series[f'p{pid}_root'] = root
        series[f'p{pid}_lowest_vertex_y'] = low
        series[f'p{pid}_contact_conf'] = conf
        series[f'p{pid}_reproj_px'] = np.where(m, err, np.nan).astype(np.float32)
    return per_person, series, {'camera_Twc': np.asarray(cw['Twc']),
                                'camera_path_m': float(np.linalg.norm(np.diff(np.asarray(cw['Twc']), axis=0), axis=1).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', nargs='+', required=True, help='name=path.pkl')
    ap.add_argument('--smplx-model', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--fps', type=float, default=30.0)
    a = ap.parse_args()
    _rc()
    import smplx as smplx_pkg
    body = smplx_pkg.SMPLX(a.smplx_model, use_pca=False, flat_hand_mean=True, num_betas=10).cuda()

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    table, allseries = {}, {}
    for spec in a.results:
        name, path = spec.split('=', 1)
        pp, ser, cam = evaluate(joblib.load(path), body, a.fps)
        table[name] = {'people': pp, 'camera': {'path_m': cam['camera_path_m']}}
        for k, v in ser.items():
            allseries[f'{name}__{k}'] = v
        allseries[f'{name}__camera_Twc'] = cam['camera_Twc']

    (out / 'metrics.json').write_text(json.dumps(table, indent=2))
    np.savez_compressed(out / 'series.npz', **allseries)

    keys = [('contact_slip_mps_mean', 'SLIP mean'), ('contact_slip_mps_median', 'slip med'),
            ('contact_slip_mps_p90', 'slip p90'),
            ('reproj_px_median_heldout', 'reproj HO'), ('reproj_px_median', 'reproj px'),
            ('penetration_cm_mean', 'penet cm'), ('penetration_cm_max', 'penet max cm'),
            ('contact_height_cm_median', 'foot h cm'), ('root_accel_rms', 'accel rms')]
    print(f"\n{'variant':8} {'cam path m':>10} " + ' '.join(f'{lbl:>12}' for _, lbl in keys))
    for name, v in table.items():
        p = v['people'][list(v['people'])[0]]
        row = ' '.join(f"{(p[k] if p[k] is not None else float('nan')):12.3f}" for k, _ in keys)
        print(f"{name:8} {v['camera']['path_m']:10.3f} {row}")
    print(f"\nwrote {out/'metrics.json'} and {out/'series.npz'}")


if __name__ == '__main__':
    main()
