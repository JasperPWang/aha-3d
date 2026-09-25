#!/usr/bin/env python3
"""Export per-frame skeletons + camera for the interactive 4D review viewer."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import joblib, numpy as np, torch

# SMPL-X body kinematic tree (first 22 joints)
PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19]
CONTACT_JOINTS = [7, 10, 8, 11]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clip', required=True)
    ap.add_argument('--dir', required=True)
    ap.add_argument('--variants', nargs='+', required=True, help='name=file.pkl')
    ap.add_argument('--smplx-model', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-frames', type=int, default=320)
    a = ap.parse_args()

    import smplx as smplx_pkg
    body = smplx_pkg.SMPLX(a.smplx_model, use_pca=False, flat_hand_mean=True, num_betas=10).cuda()

    out = {'clip': a.clip, 'parents': PARENTS, 'contact_joints_in_22': [7, 10, 8, 11], 'variants': {}}
    for spec in a.variants:
        name, fn = spec.split('=', 1)
        r = joblib.load(Path(a.dir) / fn)
        cw = r['camera_world']
        Rwc, Twc = np.asarray(cw['Rwc']), np.asarray(cw['Twc'])
        nT = len(Twc)
        step = max(1, int(np.ceil(nT / a.max_frames)))
        keep = np.arange(0, nT, step)

        people = []
        for pid, p in r['people'].items():
            fr = np.asarray(p['frames']); sw = p['smplx_world']
            n = len(fr); z = lambda k: torch.zeros(n, k, device='cuda')
            t = lambda x: torch.tensor(np.asarray(x), dtype=torch.float32, device='cuda')
            with torch.no_grad():
                o = body(global_orient=t(sw['pose'][:, :3]), body_pose=t(sw['pose'][:, 3:66]),
                         betas=t(sw['shape'][:, :10]), transl=t(sw['trans']),
                         left_hand_pose=z(45), right_hand_pose=z(45), jaw_pose=z(3),
                         leye_pose=z(3), reye_pose=z(3), expression=z(10))
            J = o.joints[:, :22].cpu().numpy()
            low = o.vertices[..., 1].min(dim=1).values.cpu().numpy()
            conf = 1 / (1 + np.exp(-np.asarray(p['smplx_cam']['static_conf_logits'])[:, :4]))
            sel = np.isin(fr, keep)
            people.append({
                'id': int(pid),
                'frames': fr[sel].astype(int).tolist(),
                'joints': np.round(J[sel], 4).reshape(int(sel.sum()), -1).tolist(),
                'lowest_vertex_y': np.round(low[sel], 4).tolist(),
                'contact': np.round(conf[sel], 3).tolist(),
            })
        out['variants'][name] = {
            'frames': keep.astype(int).tolist(),
            'cam_pos': np.round(Twc[keep], 4).tolist(),
            'cam_rot': np.round(Rwc[keep].reshape(len(keep), 9), 4).tolist(),
            'people': people,
        }
    Path(a.out).write_text(json.dumps(out, separators=(',', ':')))
    print(f'{a.clip}: {Path(a.out).stat().st_size/1e6:.2f} MB, '
          f'{len(out["variants"])} variants, {len(keep)} frames')


if __name__ == '__main__':
    main()
