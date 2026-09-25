"""One rigid floor/wall basis from SAM3-selected Pi3X surfaces; never ground truth."""
import argparse
import copy
import json
from pathlib import Path

import numpy as np

from .semantic import validate_cache
from .reference_geometry import human_exclusion_mask


def unit(value):
    value = np.asarray(value, dtype=float)
    length = np.linalg.norm(value)
    if not np.isfinite(length) or length < 1e-8:
        raise ValueError('Cannot establish a stable direction')
    return value / length


def camera_basis(cameras):
    """Camera-up fallback has no floor; stable even when first camera looks down."""
    up = unit(-cameras[:, :3, 1].mean(0))
    right = cameras[0, :3, 0]
    right = right - up * (right @ up)
    if np.linalg.norm(right) < 1e-8:
        axis = np.eye(3)[np.argmin(np.abs(up))]
        right = axis - up * (axis @ up)
    return unit(right), up


def rigid_basis(right, up, origin):
    right = unit(right - up * (right @ up))
    transform = np.eye(4)
    transform[:3, :3] = np.stack([right, unit(np.cross(up, right)), up])
    transform[:3, 3] = -transform[:3, :3] @ origin
    return transform


def fit_plane(points, frames, up, kind, *, tolerance=.03, min_points=100):
    """Bounded robust fit, with distributed support and per-view stability checks."""
    if len(points) < min_points or len(np.unique(frames)) < 2:
        return None, 'Need at least two frames and sufficient surface points'
    rng = np.random.default_rng(42)
    best = None
    best_count = 0

    def allowed(normal):
        cosine = abs(normal @ up)
        return cosine >= .5 if kind == 'floor' else cosine <= np.sin(np.deg2rad(12))

    for _ in range(256):
        a, b, c = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(b-a, c-a)
        if np.linalg.norm(normal) < 1e-8:
            continue
        normal = unit(normal)
        if not allowed(normal):
            continue
        inside = np.abs((points-a) @ normal) <= tolerance
        if inside.sum() > best_count:
            best, best_count = inside, int(inside.sum())
    minimum_fraction = .5 if kind == 'floor' else .2
    if best is None or best_count < max(min_points, minimum_fraction * len(points)):
        return None, 'No plane with sufficient consensus'
    for _ in range(2):
        fit = points[best]
        center = fit.mean(0)
        _, _, axes = np.linalg.svd(fit-center, full_matrices=False)
        normal = axes[-1]
        if normal @ up < 0:
            normal = -normal
        offset = -normal @ center
        best = np.abs(points @ normal + offset) <= tolerance
    if not allowed(normal) or best.sum() < max(min_points, minimum_fraction * len(points)):
        return None, 'Refined plane lost orientation or consensus support'
    fit = points[best]
    span = np.percentile(fit @ axes[:2].T, 95, axis=0) - np.percentile(fit @ axes[:2].T, 5, axis=0)
    if min(span) < .3:
        return None, 'Surface support is too narrow in one direction'
    checks = []
    stable = 0
    for frame in np.unique(frames):
        source = points[frames == frame]
        samples = points[(frames == frame) & best]
        item = dict(source_frame=int(frame), samples=len(source), inliers=len(samples))
        item['inlier_fraction'] = len(samples)/len(source)
        item['stable'] = False
        if len(samples) >= 30:
            _, singular, view_axes = np.linalg.svd(samples-samples.mean(0), full_matrices=False)
            angle = float(np.rad2deg(np.arccos(np.clip(abs(view_axes[-1] @ normal), 0, 1))))
            item.update(normal_difference_degrees=angle,
                        median_residual_predicted_m=float(np.median(np.abs(samples @ normal+offset))))
            item['stable'] = bool(angle <= 8 and singular[1]/np.sqrt(len(samples)) >= .08)
            stable += int(item['stable'])
        checks.append(item)
    if stable < 2:
        return None, 'Plane lacks stable two-dimensional support in two views'
    residual = np.abs(fit @ normal + offset)
    return dict(normal=normal, offset=float(offset), inliers=best,
                report=dict(normal_raw=normal.tolist(), offset_raw=float(offset),
                    sampled_points=len(points), sampled_inliers=int(best.sum()),
                    inlier_fraction=float(best.mean()), span_predicted_m=span.tolist(),
                    residual_median_predicted_m=float(np.median(residual)),
                    residual_p90_predicted_m=float(np.percentile(residual, 90)),
                    views=checks)), None


def solve(floor_points, floor_frames, wall_points, wall_frames, cameras):
    """Return hypothesis and fit evidence without deforming or Manhattan-snapping geometry."""
    cameras = np.asarray(cameras, float)
    if cameras.ndim != 3 or cameras.shape[1:] != (4, 4) or not len(cameras) or not np.isfinite(cameras).all():
        raise ValueError('Invalid cameras')
    if (not np.allclose(cameras[:, 3], [0, 0, 0, 1]) or
            not np.allclose(cameras[:, :3, :3].transpose(0, 2, 1) @ cameras[:, :3, :3], np.eye(3), atol=1e-4) or
            np.any(np.linalg.det(cameras[:, :3, :3]) < .999)):
        raise ValueError('Cameras must be proper rigid transforms')
    right, up = camera_basis(cameras)
    origin = cameras[0, :3, 3].copy()
    report = dict(status='camera-up only; no floor accepted', floor=None, walls=[],
                  yaw_status='camera-right fallback', blockers=[], metric_scale='predicted metres; uncalibrated',
                  visual_review_required=True, floor_plane_is_measured_ground_truth=False)
    floor, reason = fit_plane(floor_points, floor_frames, up, 'floor')
    if floor is None:
        report['blockers'].append('floor: ' + reason)
        return rigid_basis(right, up, origin), report, None, []
    normal, offset = floor['normal'], floor['offset']
    heights = cameras[:, :3, 3] @ normal + offset
    if np.mean(heights > .2) < .8:
        report['blockers'].append('floor: cameras are not consistently above the proposed floor')
        return rigid_basis(right, up, origin), report, None, []
    up = normal
    origin -= (origin @ up + offset) * up
    # Regenerate horizontal fallback if the fitted up differs greatly from the camera prior.
    right = rigid_basis(right, up, origin)[0, :3]
    report.update(status='floor hypothesis; visual confirmation required', floor=floor['report'])
    report['floor']['camera_heights_predicted_m'] = heights.tolist()
    remaining = np.arange(len(wall_points))
    walls = []
    for _ in range(4):
        wall, reason = fit_plane(wall_points[remaining], wall_frames[remaining], up, 'wall')
        if wall is None:
            if not walls:
                report['blockers'].append('wall: ' + reason)
            break
        indices = remaining[wall['inliers']]
        wall['indices'] = indices
        walls.append(wall)
        remaining = remaining[~wall['inliers']]
    if walls:
        dominant = max(walls, key=lambda wall: len(wall['indices']))
        direction = unit(np.cross(dominant['normal'], up))
        if direction @ right < 0:
            direction = -direction
        right = direction
        report.update(status='floor and wall hypotheses; visual confirmation required',
                      yaw_status='dominant wall-floor intersection parallel to X',
                      dominant_wall=next(i for i,w in enumerate(walls) if w is dominant))
        for wall in walls:
            line = unit(np.cross(wall['normal'], up))
            angle = float(np.rad2deg(np.arccos(np.clip(abs(line @ right), 0, 1))))
            wall['report']['angle_to_x_degrees'] = angle
            wall['report']['axis_deviation_degrees'] = min(angle, 90-angle)
            report['walls'].append(wall['report'])
    return rigid_basis(right, up, origin), report, floor, walls


def reviewed_frames(review, meta, ids, cache):
    """Review actual frame masks, recording their source and cache paths."""
    if review is None:
        return {k: set(ids.tolist()) for k in ('floor', 'wall')}, 'pending_visual_review'
    if (Path(review.get('bundle', '')).resolve() != Path(meta['bundle']).resolve() or
            Path(review.get('semantic_cache', '')).resolve() != Path(cache).resolve() or
            not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()):
        raise ValueError('Mask review source/cache path or reviewer differs')
    selected = {}
    for kind in ('floor', 'wall'):
        entries = review.get(kind)
        if not isinstance(entries, list):
            raise ValueError('Review needs floor and wall lists, including empty rejected selections')
        selected[kind] = set()
        for entry in entries:
            frame = entry.get('source_frame')
            if (type(frame) is not int or frame not in ids or frame in selected[kind] or
                    not isinstance(entry.get('observation'), str) or not entry['observation'].strip()):
                raise ValueError('Review needs distinct valid source frames and concrete observations')
            selected[kind].add(frame)
    return selected, 'reviewed mask selection; geometric alignment still requires visual review'


def sample_surface(points, valid, mask, ids, selected):
    """Balanced per-view sampling retains exact source pixels, without loading dense data per pixel."""
    rng = np.random.default_rng(42)
    xyz, source = [], []
    limit = max(100, min(1500, 20000 // max(1, len(selected))))
    for slot, frame in enumerate(ids):
        if int(frame) not in selected:
            continue
        pixels = np.argwhere(valid[slot] & mask[slot])
        if len(pixels) > limit:
            pixels = pixels[rng.choice(len(pixels), limit, replace=False)]
        xyz.append(points[slot, pixels[:, 0], pixels[:, 1]])
        source.append(np.column_stack([np.full(len(pixels), frame), pixels]))
    return (np.concatenate(xyz) if xyz else np.empty((0, 3)),
            np.concatenate(source).astype(int) if source else np.empty((0, 3), int))


def build(bundle, cache, cameras_path, out, *, review_path=None, confidence=.5, human_mask_radius=3):
    if not np.isfinite(confidence) or not 0 < confidence < 1 or human_mask_radius < 0:
        raise ValueError('Invalid confidence or human exclusion radius')
    bundle, cache, cameras_path, out = map(Path, (bundle, cache, cameras_path, out))
    if out.exists():
        raise FileExistsError(out)
    with np.load(bundle/'inputs.npz', allow_pickle=False) as data:
        rgb, ids = data['rgb'], data['frame_indices']
    masks, known, meta = validate_cache(cache, bundle, ids, rgb.shape[1:3], require_structure=True)
    if not known.all():
        raise ValueError('Structural masks must cover every inference frame')
    camera = json.loads(cameras_path.read_text())
    with np.load(bundle/'predictions.npz', allow_pickle=False) as data:
        points, raw_conf = data['points'], data['conf']
        edge, poses = data['non_edge'], data['camera_poses']
        local, intrinsics = data['local_points'], data['intrinsics']
    if (points.shape != rgb.shape or local.shape != points.shape or raw_conf.shape != (*points.shape[:-1], 1)
            or edge.shape != points.shape[:-1] or poses.shape != (len(ids), 4, 4)):
        raise ValueError('Pi3X dense arrays do not match source images')
    old = np.asarray(camera['world_transform'], float)
    if (old.shape != (4, 4) or not np.isfinite(old).all() or not np.allclose(old[3], [0,0,0,1]) or
            not np.allclose(old[:3,:3].T @ old[:3,:3], np.eye(3), atol=1e-4) or np.linalg.det(old[:3,:3]) < .999):
        raise ValueError('Input camera basis must be proper rigid; metric scale is separate')
    if ([f['source_frame'] for f in camera['frames']] != ids.tolist() or
            not np.allclose([f['c2w'] for f in camera['frames']], old @ poses, atol=1e-4) or
            not np.allclose([f['intrinsics'] for f in camera['frames']], intrinsics, atol=1e-4)):
        raise ValueError('Camera identity/calibration differs from raw Pi3X bundle')
    inputs = json.loads((bundle/'inputs.json').read_text())
    if (inputs['frame_indices'] != ids.tolist() or
            not np.allclose([f['timestamp_seconds'] for f in camera['frames']], inputs['timestamps_seconds'], atol=1e-8)):
        raise ValueError('Camera timing differs from source inputs')
    review = json.loads(Path(review_path).read_text()) if review_path else None
    selections, review_status = reviewed_frames(review, meta, ids, cache)
    quality = 1 / (1 + np.exp(-np.clip(raw_conf[..., 0], -50, 50)))
    valid = (np.isfinite(points).all(-1) & np.isfinite(local).all(-1) & (local[..., 2] > 0) &
             np.isfinite(raw_conf[..., 0]) & (quality > confidence) & edge.astype(bool))
    excluded = human_exclusion_mask(masks['person'], human_mask_radius) | masks['glass'] | masks['mirror']
    # Ambiguous class overlap is excluded rather than assigned a floor/wall meaning.
    valid &= ~excluded & ~(masks['floor'] & masks['wall'])
    samples = {kind: sample_surface(points, valid, masks[kind], ids, selections[kind]) for kind in ('floor', 'wall')}
    fp, fs = samples['floor']; wp, ws = samples['wall']
    transform, report, floor, walls = solve(fp, fs[:, 0], wp, ws[:, 0], poses)
    aligned = copy.deepcopy(camera)
    aligned['world_transform'] = transform.tolist()
    for frame, pose in zip(aligned['frames'], transform @ poses):
        frame['c2w'] = pose.tolist()
    floor_info = dict(status=report['status'], floor_plane_is_measured_ground_truth=False,
                      world_transform_raw_to_aligned=transform.tolist())
    if floor is not None:
        floor_info.update(plane_normal_raw=floor['normal'].tolist(), plane_offset_raw=floor['offset'])
    aligned['floor_alignment'] = floor_info
    aligned['convention'] = 'camera-to-world OpenCV (right,down,forward); room world Z up'
    aligned['units'] = 'predicted metres; uncalibrated'
    aligned['structural_alignment'] = dict(report='alignment.json', mask_review_status=review_status,
                                           visual_review_required=True, yaw_status=report['yaw_status'])
    report.update(schema_version=1, mask_review_status=review_status,
                  selected_mask_frames={k: sorted(v) for k,v in selections.items()},
                  world_transform=transform.tolist(), previous_world_transform=old.tolist(),
                  confidence_min=confidence, human_mask_radius_pixels=human_mask_radius,
                  inputs=[str(path.resolve()) for path in
                          [bundle/'inputs.npz', bundle/'inputs.json', bundle/'predictions.npz',
                           cache/'manifest.json', cache/'masks.npz', cameras_path] +
                          ([Path(review_path)] if review_path else [])])
    out.mkdir(parents=True, exist_ok=False)
    selected_floor = floor['inliers'] if floor else np.zeros(len(fp), bool)
    wall_ids = np.full(len(wp), -1, int)
    for i, wall in enumerate(walls):
        wall_ids[wall['indices']] = i
    np.savez_compressed(out/'support.npz', floor_points_raw=fp, floor_source_frame_yx=fs,
                        floor_inliers=selected_floor, wall_points_raw=wp, wall_source_frame_yx=ws, wall_plane=wall_ids)
    from PIL import Image
    evidence = []
    for kind, source, accepted in [('floor', fs, selected_floor), ('wall', ws, wall_ids >= 0)]:
        available = sorted(set(source[:,0].tolist()))
        chosen = [available[i] for i in np.unique(np.linspace(0,len(available)-1,min(5,len(available))).round().astype(int))] if available else []
        for frame in chosen:
            slot = int(np.flatnonzero(ids == frame)[0])
            overlay = rgb[slot].copy()
            mask = masks[kind][slot]
            overlay[mask] = (overlay[mask]*.5 + np.array([255,160,0])*.5).astype(np.uint8)
            pixels = source[(source[:,0] == frame) & accepted, 1:]
            overlay[pixels[:,0], pixels[:,1]] = [0,255,255]
            path = out/f'{frame:06d}_{kind}_support.png'
            Image.fromarray(np.concatenate([rgb[slot], overlay], axis=1)).save(path)
            evidence.append(dict(source_frame=frame, category=kind, path=path.name))
    report['evidence'] = evidence
    report['evidence_legend'] = 'Left: source. Right: amber SAM3 mask; cyan sampled geometric inliers. Not a visual acceptance receipt.'
    (out/'cameras.json').write_text(json.dumps(aligned, indent=2, allow_nan=False)+'\n')
    (out/'alignment.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'semantic-cache', 'cameras', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--confidence', type=float, default=.5)
    parser.add_argument('--human-mask-radius', type=int, default=3)
    args = parser.parse_args()
    result = build(args.bundle, args.semantic_cache, args.cameras, args.out,
                   review_path=args.review, confidence=args.confidence, human_mask_radius=args.human_mask_radius)
    print(json.dumps({'status': result['status'], 'blockers': result['blockers']}))


if __name__ == '__main__':
    main()
