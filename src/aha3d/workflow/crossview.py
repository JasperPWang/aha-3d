"""Independent static ORB correspondences with each dense NPZ member loaded once."""
import argparse
from pathlib import Path
import time

import numpy as np
from aha3d.io import digest, read, write


def load_arrays(bundle, loader=np.load):
    with loader(bundle / 'inputs.npz') as z:
        rgb = z['rgb']
    with loader(bundle / 'predictions.npz') as z:
        # NpzFile has no array cache: indexing it inside the match loop decompresses repeatedly.
        arrays = {key: z[key] for key in ('points', 'conf', 'non_edge')}
    return rgb, arrays


def evaluate(bundle, cfg, out):
    import cv2
    started = time.perf_counter()
    cam = read(bundle / 'cameras.json'); transform = np.asarray(cam['world_transform'])
    frames = {f['source_frame']: f for f in cam['frames']}
    rows = {f['source_frame']: i for i, f in enumerate(cam['frames'])}
    imgs, pred = load_arrays(bundle)
    loaded = time.perf_counter()
    orb = cv2.ORB_create(nfeatures=cfg.get('nfeatures', 3000), edgeThreshold=9, fastThreshold=8)
    features = {}
    for key, rects in cfg['exclude_rectangles'].items():
        f = int(key); im = imgs[rows[f]]; mask = np.full(im.shape[:2], 255, np.uint8)
        for x0, y0, x1, y1 in rects:
            if not (0 <= x0 < x1 <= im.shape[1] and 0 <= y0 < y1 <= im.shape[0]):
                raise ValueError('Static mask rectangle outside processed raster')
            mask[y0:y1, x0:x1] = 0
        features[f] = orb.detectAndCompute(cv2.cvtColor(im, cv2.COLOR_RGB2GRAY), mask)
    records = []
    for a, b in cfg['pairs']:
        ka, da = features[a]; kb, db = features[b]
        pairs = [] if da is None or db is None else cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
        good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < cfg.get('ratio', .72) * pair[1].distance]
        rt = np.linalg.inv(frames[b]['c2w']); K = np.asarray(frames[b]['intrinsics']); r = rows[a]
        matched = []
        for m in good:
            uv = np.asarray(ka[m.queryIdx].pt); target = np.asarray(kb[m.trainIdx].pt)
            u, v = np.rint(uv).astype(int)
            if not (0 <= u < imgs.shape[2] and 0 <= v < imgs.shape[1]):
                continue
            confidence = 1 / (1 + np.exp(-float(np.asarray(pred['conf'][r, v, u]).item())))
            if confidence < cfg.get('confidence', .7) or not pred['non_edge'][r, v, u]:
                continue
            xyz = pred['points'][r, v, u] @ transform[:3, :3].T + transform[:3, 3]
            q = xyz @ rt[:3, :3].T + rt[:3, 3]
            if not np.isfinite(q).all() or q[2] <= 0:
                continue
            projected = (K @ q)[:2] / q[2]
            matched.append(dict(source_uv=uv.tolist(), observed_target_uv=target.tolist(), projected_target_uv=projected.tolist(),
                error_px_processed=float(np.linalg.norm(projected-target)), descriptor_distance=float(m.distance)))
        errors = [m['error_px_processed'] for m in matched]
        records.append(dict(source_frame=a, target_frame=b, matches=len(matched),
            median_error_px=float(np.median(errors)) if errors else None,
            p90_error_px=float(np.percentile(errors, 90)) if errors else None, correspondences=matched))
        vis = cv2.drawMatches(cv2.cvtColor(imgs[rows[a]], cv2.COLOR_RGB2BGR), ka,
            cv2.cvtColor(imgs[rows[b]], cv2.COLOR_RGB2BGR), kb, good[:40], None, flags=2)
        cv2.imwrite(str(out / f'matches_{a:04d}_{b:04d}.jpg'), vis)
    report = dict(method='ORB descriptor ratio selected independently of 3D; manually masked static regions',
        units='processed-image pixels', limits='Repeated patterns can mismatch; no absolute scale/pose accuracy claim', pairs=records,
        seconds=dict(load_arrays=loaded-started, total=time.perf_counter()-started),
        dense_member_reads={'rgb': 1, 'points': 1, 'conf': 1, 'non_edge': 1},
        inputs_sha256={name: digest(bundle / name) for name in ('inputs.json', 'cameras.json')}, config=cfg)
    write(out / 'report.json', report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True); p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    evaluate(a.bundle, read(a.config), a.out)


if __name__ == '__main__':
    main()
