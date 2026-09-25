"""Measure horizontal furniture surfaces in cached Pi3X coordinates.

Python: session = MeasurementSession(bundle); result = session.measure(request)
CLI: python -m aha3d.workflow.furniture --bundle B --config C --out O
Only NumPy and Pillow are needed. SAM3 masks are optional inputs, not a dependency.
"""
import argparse
import math
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image, ImageDraw

from aha3d import runtime
from aha3d.io import digest, read, write


def require(ok, message):
    if not ok:
        raise ValueError(message)


def rigid(value, name):
    value = np.asarray(value, dtype=float)
    require(value.shape == (4, 4) and np.isfinite(value).all(), name + ': invalid matrix')
    require(np.allclose(value[3], [0, 0, 0, 1]) and
            np.allclose(value[:3, :3].T @ value[:3, :3], np.eye(3), atol=1e-4) and
            np.linalg.det(value[:3, :3]) > .999, name + ': expected rigid proper transform')
    return value


def pixels(value, width, height, count=None):
    uv = np.asarray(value, dtype=float)
    require(uv.ndim == 2 and uv.shape[1] == 2 and np.isfinite(uv).all(), 'Expected finite pixel pairs')
    require(count is None or len(uv) == count, 'Expected %s pixel pairs' % count)
    require(len(uv) >= 3 and (uv >= 0).all() and (uv[:, 0] <= width-1).all() and
            (uv[:, 1] <= height-1).all(), 'Pixels outside processed image')
    return uv


def hull_xy(points):
    """Counter-clockwise convex hull without a SciPy/OpenCV dependency."""
    pts = sorted(set(map(tuple, np.asarray(points, dtype=float))))
    require(len(pts) >= 3, 'Not enough distinct footprint points')
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    halves = []
    for seq in (pts, pts[::-1]):
        half = []
        for p in seq:
            while len(half) >= 2 and cross(half[-2], half[-1], p) <= 0:
                half.pop()
            half.append(p)
        halves.append(half[:-1])
    hull = np.asarray(halves[0] + halves[1])
    require(len(hull) >= 3, 'Collinear footprint')
    return hull


def rectangle_xy(points):
    """Minimum-area rectangle enclosing the supplied XY observations."""
    hull = hull_xy(points)
    best = None
    for edge in np.roll(hull, -1, axis=0)-hull:
        u = edge/np.linalg.norm(edge); v = np.array([-u[1], u[0]])
        axes = np.stack([u, v]); q = hull @ axes.T
        lo, hi = q.min(0), q.max(0); size = hi-lo
        area = float(np.prod(size))
        if best is None or area < best[0]:
            center = (hi+lo)/2 @ axes
            best = (area, center, size, axes)
    _, center, size, axes = best
    if size[1] > size[0]:
        size = size[::-1]; axes = np.stack([axes[1], -axes[0]])
    yaw = float(np.degrees(np.arctan2(axes[0, 1], axes[0, 0])) % 180)
    u = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
    axes = np.stack([u, [-u[1], u[0]]])
    corners = center + np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * size/2 @ axes
    require(size.min() > 1e-5, 'Degenerate footprint rectangle')
    return dict(center_xy_m=center.tolist(), size_xy_m=size.tolist(), yaw_deg=yaw,
                corners_xy_m=corners.tolist())


def fit_plane(points, threshold=.025, min_fraction=.35, max_tilt_deg=15, seed=0):
    """Robust plane fit; reject non-horizontal or poorly supported hypotheses."""
    xyz = np.asarray(points, dtype=float)
    require(xyz.ndim == 2 and xyz.shape[1] == 3 and len(xyz) >= 30 and
            np.isfinite(xyz).all(), 'Need at least 30 finite surface points')
    rng = np.random.default_rng(seed)
    subset = xyz[rng.choice(len(xyz), min(4000, len(xyz)), replace=False)]
    best = None; cos_limit = math.cos(math.radians(max_tilt_deg))
    for _ in range(192):
        a, b, c = subset[rng.choice(len(subset), 3, replace=False)]
        n = np.cross(b-a, c-a); length = np.linalg.norm(n)
        if length < 1e-8:
            continue
        n /= length
        if abs(n[2]) < cos_limit:
            continue
        mask = np.abs((subset-a) @ n) <= threshold
        count = int(mask.sum())
        if best is None or count > best[0]:
            best = (count, n, -n @ a)
    require(best is not None, 'No horizontal plane found in selection')
    _, n, d = best
    inliers = np.abs(xyz @ n+d) <= threshold
    for _ in range(3):
        require(inliers.sum() >= 30, 'Too few plane inliers')
        selected = xyz[inliers]; center = selected.mean(0)
        _, singular, vt = np.linalg.svd(selected-center, full_matrices=False)
        require(singular[1] > 1e-4, 'Surface samples are collinear')
        n = vt[-1]
        if n[2] < 0:
            n = -n
        d = float(-n @ center)
        inliers = np.abs(xyz @ n+d) <= threshold
    fraction = float(inliers.mean())
    require(n[2] >= cos_limit and fraction >= min_fraction and inliers.sum() >= 30,
            'Weak/tilted plane: inlier fraction %.3f, tilt %.2f deg' %
            (fraction, np.degrees(np.arccos(np.clip(n[2], -1, 1)))))
    residual = np.abs(xyz[inliers] @ n+d)
    return dict(normal=n.tolist(), offset_m=d, inlier_count=int(inliers.sum()),
                candidate_count=len(xyz), inlier_fraction=fraction,
                residual_p50_m=float(np.median(residual)),
                residual_p95_m=float(np.percentile(residual, 95)),
                tilt_deg=float(np.degrees(np.arccos(np.clip(n[2], -1, 1))))), inliers


def ray_plane(uv, K, c2w, plane):
    rays = np.c_[uv, np.ones(len(uv))] @ np.linalg.inv(K).T @ c2w[:3, :3].T
    n = np.asarray(plane['normal']); denominator = rays @ n
    require((np.abs(denominator) > 1e-5).all(), 'Corner ray parallel to plane')
    distance = -(c2w[:3, 3] @ n + plane['offset_m'])/denominator
    require(np.isfinite(distance).all() and (distance > 0).all(), 'Corner plane intersection behind camera')
    return c2w[:3, 3] + rays * distance[:, None]


def project(xyz, K, c2w):
    camera = (xyz-c2w[:3, 3]) @ c2w[:3, :3]
    require((camera[:, 2] > 0).all(), 'Projected rectangle behind camera')
    q = camera @ K.T
    return q[:, :2]/q[:, 2:]


def polygon_gap(a, b):
    """XY edge clearance of convex rectangles; overlapping rectangles return zero."""
    a, b = np.asarray(a), np.asarray(b)
    separated = False
    for polygon in (a, b):
        for edge in np.roll(polygon, -1, axis=0)-polygon:
            axis = np.array([-edge[1], edge[0]])
            pa, pb = a @ axis, b @ axis
            separated |= pa.max() < pb.min() or pb.max() < pa.min()
    if not separated:
        return 0.
    distances = []
    for p, poly in [(p, b) for p in a] + [(p, a) for p in b]:
        for v, w in zip(poly, np.roll(poly, -1, axis=0)):
            t = np.clip((p-v) @ (w-v)/np.sum((w-v)**2), 0, 1)
            distances.append(np.linalg.norm(p-(v+t*(w-v))))
    return float(min(distances))


def sam3_selector(manifest, object_id, variant=None):
    """Convert a retained SAM3 runner manifest to the mask selector contract.

    Variant may be explicit (e.g. box_0) or the runner's selected candidate.
    This imports provenance; it does not mark a candidate visually reviewed.
    MeasurementSession subsequently checks its frame-image hash and mask raster.
    """
    path = Path(manifest).resolve(); report = read(path)
    matches = [o for o in report['objects'] if o['id'] == object_id]
    require(len(matches) == 1, 'SAM3 object ID missing or ambiguous')
    obj = matches[0]; chosen = variant or obj['selected_variant']
    variants = [v for v in obj['variants'] if v['variant'] == chosen]
    require(len(variants) == 1, 'SAM3 variant missing or ambiguous')
    mask = Path(variants[0]['mask'])
    if not mask.is_absolute():
        mask = path.parent/mask
    return dict(mask=str(mask), image_sha256=obj['image_sha256'],
                source_frame=obj['source_frame'], method='SAM3 '+chosen,
                manifest=str(path), manifest_sha256=digest(path), variant=chosen,
                review_status=report.get('status', 'unspecified'))


class MeasurementSession:
    """Load a raw/aligned Pi3X bundle once; reuse it for multiple requests."""
    def __init__(self, bundle):
        started = time.perf_counter()
        self.bundle = Path(bundle).resolve()
        self.manifest = read(self.bundle/'inputs.json')
        self.camera = read(self.bundle/'cameras.json')
        self.transform = rigid(self.camera['world_transform'], 'world_transform')
        self.ids = self.manifest['frame_indices']
        self.width, self.height = self.manifest['processed_size_wh']
        frames = self.camera['frames']
        require(len(set(self.ids)) == len(self.ids) and
                self.ids == [f['source_frame'] for f in frames], 'Frame identity mismatch')
        timestamps = np.asarray(self.manifest['timestamps_seconds'])
        require(np.isfinite(timestamps).all() and (np.diff(timestamps) > 0).all() and
                np.allclose(timestamps, [f['timestamp_seconds'] for f in frames]), 'Timestamp mismatch')
        self.poses = np.array([rigid(f['c2w'], 'camera') for f in frames])
        self.K = np.asarray([f['intrinsics'] for f in frames], dtype=float)
        require(self.K.shape == (len(self.ids), 3, 3) and np.isfinite(self.K).all() and
                (self.K[:, 0, 0] > 0).all() and (self.K[:, 1, 1] > 0).all() and
                np.allclose(self.K[:, 2], [0, 0, 1]), 'Invalid camera intrinsics')
        with np.load(self.bundle/'predictions.npz', allow_pickle=False) as z:
            self.points = z['points']; self.confidence = z['conf']; self.non_edge = z['non_edge']
            raw_poses = z['camera_poses']
        shape = (len(self.ids), self.height, self.width)
        require(self.points.shape == shape+(3,) and self.confidence.shape == shape+(1,) and
                self.non_edge.shape == shape, 'Prediction/processed image shape mismatch')
        require(np.allclose(self.poses, self.transform @ raw_poses, atol=1e-4),
                'Raw and exported camera basis differ')
        self.load_seconds = time.perf_counter()-started

    def measure(self, request, base_dir=None):
        """Return a JSON-compatible surface rectangle and measurement provenance.

        request: id, source_frame, selector (corners_uv/box_xyxy/mask),
        floor_reference, optional height_range_m, optional corners_uv for a mask/box.
        Pixel coordinates and mask raster must match the cached processed image.
        """
        started = time.perf_counter(); req = request
        name = req.get('id', '')
        require(isinstance(name, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_-]*', name), 'Invalid measurement ID')
        fid = req['source_frame']
        require(type(fid) is int and fid in self.ids, 'Source frame is not in bundle')
        require(isinstance(req.get('floor_reference'), str) and req['floor_reference'].strip(),
                'Explicit aligned floor_reference required for surface heights')
        row = self.ids.index(fid); selector = req['selector']
        modes = set(selector) & {'corners_uv', 'box_xyxy', 'mask'}
        require(len(modes) == 1, 'Choose exactly one selector: corners_uv, box_xyxy, mask')
        mode = next(iter(modes)); mask = np.zeros((self.height, self.width), dtype=bool)
        corners = req.get('corners_uv')
        mask_provenance = None
        if mode == 'corners_uv':
            require(corners is None, 'Specify corners only once')
            corners = selector['corners_uv']
        if corners is not None:
            corners = pixels(corners, self.width, self.height, 4)
            require(len(hull_xy(corners)) == 4, 'Four distinct convex corners required')
            # Require boundary order, preventing a self-crossing selector polygon.
            edges = np.roll(corners, -1, axis=0)-corners
            crosses = edges[:, 0]*np.roll(edges, -1, axis=0)[:, 1]-edges[:, 1]*np.roll(edges, -1, axis=0)[:, 0]
            require((crosses > 0).all() or (crosses < 0).all(), 'Corners must follow perimeter order')
        if mode == 'corners_uv':
            raster = Image.new('1', (self.width, self.height))
            ImageDraw.Draw(raster).polygon([tuple(p) for p in corners], fill=1)
            mask = np.array(raster, dtype=bool)
        elif mode == 'box_xyxy':
            box = np.asarray(selector['box_xyxy'])
            require(box.shape == (4,) and np.isfinite(box).all() and np.equal(box, np.round(box)).all(),
                    'Box needs four integer processed pixel edges')
            x0, y0, x1, y1 = box.astype(int)
            require(0 <= x0 < x1 <= self.width and 0 <= y0 < y1 <= self.height, 'Box outside processed image')
            mask[y0:y1, x0:x1] = True
        else:
            require(selector.get('image_sha256') and selector.get('method'),
                    'Mask requires image_sha256 and method for source provenance')
            require(selector.get('source_frame', fid) == fid, 'Mask source frame mismatch')
            image_path = self.bundle/'frames'/('%06d.jpg' % fid)
            require(digest(image_path) == selector['image_sha256'], 'Mask source image hash mismatch')
            path = Path(selector['mask'])
            if not path.is_absolute():
                path = Path(base_dir or '.')/path
            with Image.open(path) as im:
                require(im.size == (self.width, self.height) and im.mode in ('1', 'L'),
                        'Mask must be single-channel at processed resolution; no implicit resize')
                values = np.asarray(im)
            require(set(np.unique(values).tolist()).issubset({0, 1, 255}), 'Mask must be binary')
            mask = values > 0
            mask_provenance = dict(path=str(path.resolve()), sha256=digest(path),
                                   image_sha256=selector['image_sha256'], method=selector['method'])
            if 'manifest' in selector:
                require(digest(selector['manifest']) == selector.get('manifest_sha256'), 'SAM3 manifest changed')
                mask_provenance.update({key: selector[key] for key in
                                       ('manifest', 'manifest_sha256', 'variant', 'review_status')})
        require(mask.sum() >= 30, 'Selection too small')
        confidence_min = float(req.get('confidence_min', .6))
        threshold = float(req.get('plane_threshold_m', .025))
        min_fraction = float(req.get('min_inlier_fraction', .35))
        max_tilt = float(req.get('max_tilt_deg', 15))
        require(0 < confidence_min < 1 and math.isfinite(threshold) and threshold > 0 and
                0 < min_fraction <= 1 and 0 < max_tilt < 45, 'Invalid quality settings')
        raw = self.points[row]
        xyz = raw @ self.transform[:3, :3].T + self.transform[:3, 3]
        confidence = 1/(1+np.exp(-np.clip(self.confidence[row, ..., 0], -50, 50)))
        valid = mask & np.isfinite(xyz).all(-1) & self.non_edge[row].astype(bool) & (confidence >= confidence_min)
        if 'height_range_m' in req:
            band = np.asarray(req['height_range_m'], dtype=float)
            require(band.shape == (2,) and np.isfinite(band).all() and band[0] < band[1], 'Invalid height range')
            valid &= (xyz[..., 2] >= band[0]) & (xyz[..., 2] <= band[1])
        candidate = xyz[valid]
        plane, inliers = fit_plane(candidate, threshold, min_fraction, max_tilt)
        support = candidate[inliers]
        vv, uu = np.nonzero(valid)
        support_uv = np.column_stack([uu[inliers], vv[inliers]])
        # Pi3X point and camera predictions need not project to identical pixels.
        # Use the same camera-ray/plane construction for all selector boundaries.
        support_on_plane = ray_plane(support_uv, self.K[row], self.poses[row], plane)
        reprojection = np.linalg.norm(project(support, self.K[row], self.poses[row])-support_uv, axis=1)
        consistency = dict(point_camera_reprojection_p50_px=float(np.median(reprojection)),
                           point_camera_reprojection_p95_px=float(np.percentile(reprojection, 95)),
                           raw_point_extent_xy_m=rectangle_xy(support[:, :2])['size_xy_m'])
        warnings = ['Predicted metric scale; no physical accuracy calibration.',
                    'Plane residual is consistency, not a dimension accuracy estimate.']
        if corners is not None:
            boundary = ray_plane(corners, self.K[row], self.poses[row], plane)
            rect = rectangle_xy(boundary[:, :2])
            basis = 'corner_defined_rectangle_estimate'
            warnings.append('Rectangle assumes selected corners describe the intended surface; hidden corners remain inferred.')
        else:
            rect = rectangle_xy(support_on_plane[:, :2]); boundary = None
            basis = 'observed_surface_extent'
            warnings.append('Visible inlier extent only; not full furniture dimensions. Occlusion/cropping can shorten it; residual outliers can enlarge it.')
        center = np.asarray(rect['center_xy_m']); n = np.asarray(plane['normal'])
        z = float(-(center @ n[:2]+plane['offset_m'])/n[2])
        foot = np.asarray(rect['corners_xy_m'])
        surface_xyz = np.c_[foot, -(foot @ n[:2]+plane['offset_m'])/n[2]]
        if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
            warnings.append('Selection touches image edge; surface may be cropped.')
        counts = dict(selected_pixels=int(mask.sum()), reliable_pixels=int(valid.sum()), plane_pixels=int(inliers.sum()))
        result = dict(id=name, source_frame=fid, timestamp_seconds=self.manifest['timestamps_seconds'][row],
                      selector_mode=mode, measurement_basis=basis, floor_reference=req['floor_reference'],
                      boundary_note=req.get('boundary_note', 'Caller selected visible/inferred boundaries; not independently certified.'),
                      plane=plane, rectangle=rect, surface_height_m=z, counts=counts,
                      geometry_consistency=consistency,
                      footprint_method='Image boundary rays intersect the fitted Pi3X plane in the aligned camera basis.',
                      corner_xyz_m=None if boundary is None else boundary.tolist(),
                      rectangle_projected_uv=project(surface_xyz, self.K[row], self.poses[row]).tolist(),
                      input_corners_uv=None if corners is None else corners.tolist(),
                      mask_provenance=mask_provenance, warnings=warnings,
                      # A numeric adapter output, explicitly scoped to the measured surface.
                      authoring_surface=dict(center_xyz_m=[*center.tolist(), z], size_xy_m=rect['size_xy_m'],
                                             yaw_deg=rect['yaw_deg'], basis=basis,
                                             scope='Horizontal surface only; no furniture thickness, full body height or facing inferred.'),
                      elapsed_seconds=time.perf_counter()-started)
        return result

    def overlay(self, result, request, target):
        image_path = self.bundle/'frames'/('%06d.jpg' % result['source_frame'])
        with Image.open(image_path) as source:
            image = source.convert('RGB')
        require(image.size == (self.width, self.height), 'Source overlay raster mismatch')
        draw = ImageDraw.Draw(image)
        selector = request['selector']
        if 'box_xyxy' in selector:
            draw.rectangle(selector['box_xyxy'], outline='cyan', width=2)
        q = [tuple(p) for p in result['rectangle_projected_uv']]
        draw.line(q+[q[0]], fill='yellow', width=2)
        for i, p in enumerate(result['input_corners_uv'] or []):
            u, v = p; draw.ellipse((u-3, v-3, u+3, v+3), fill='red')
            draw.text((u+4, v+3), str(i), fill='red')
        header = Image.new('RGB', (self.width, self.height+48), '#17202a')
        header.paste(image, (0, 48)); draw = ImageDraw.Draw(header)
        sx, sy = result['rectangle']['size_xy_m']
        draw.text((8, 6), '%s | %s | %.2f x %.2f m | surface z %.2f m' %
                  (result['id'], result['selector_mode'], sx, sy, result['surface_height_m']), fill='white')
        draw.text((8, 25), result['measurement_basis']+' | uncalibrated Pi3X', fill='white')
        header.save(target)


def evaluate(bundle, config, out, base_dir=None):
    require(config.get('schema_version') == 1, 'Expected schema_version 1')
    requests = config['objects']; names = [q['id'] for q in requests]
    require(requests and len(names) == len(set(names)), 'Empty or duplicate object IDs')
    session = MeasurementSession(bundle); out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    results = []; failures = []
    for request in requests:
        try:
            result = session.measure(request, base_dir)
            session.overlay(result, request, out/(result['id']+'.png'))
            results.append(result)
        except (ValueError, KeyError, OSError, TypeError) as error:
            failures.append(dict(id=request.get('id'), error=str(error)))
    by_id = {r['id']: r for r in results}; gaps = []
    for a, b in config.get('clearances', []):
        require(a in names and b in names and a != b, 'Unknown/duplicate clearance endpoint')
        if a in by_id and b in by_id:
            gaps.append(dict(objects=[a, b], surface_edge_clearance_xy_m=polygon_gap(
                by_id[a]['rectangle']['corners_xy_m'], by_id[b]['rectangle']['corners_xy_m']),
                scope='Selected surface rectangles; excludes chair backs, people and hidden furniture extents.'))
    report = dict(schema_version=1, status='completed' if not failures else 'partial',
                  scale='uncalibrated Pi3X predicted metres', physical_accuracy_validated=False,
                  bundle=str(session.bundle), source_sha256=session.manifest.get('source_sha256'),
                  inputs_sha256=digest(session.bundle/'inputs.json'), cameras_sha256=digest(session.bundle/'cameras.json'),
                  code_sha256=digest(__file__), job_id=runtime.run_id(),
                  processed_size_wh=[session.width, session.height], world_transform=session.transform.tolist(),
                  load_seconds=session.load_seconds, objects=results, failures=failures, clearances=gaps)
    write(out/'report.json', report); write(out/'request.json', config)
    write(out/'authoring_surfaces.json', dict(schema_version=1, bundle=report['bundle'],
          scale=report['scale'], objects={r['id']: r['authoring_surface'] for r in results}))
    lines = ['# Furniture surface measurements', '', 'Scale: uncalibrated Pi3X prediction. Physical accuracy unverified.', '',
             '| ID | Input | XY size (m) | Surface Z (m) | Interpretation |', '| --- | --- | --- | --- | --- |']
    for r in results:
        x, y = r['rectangle']['size_xy_m']
        lines.append('| [%s](%s.png) | %s | %.3f x %.3f | %.3f | %s |' %
                     (r['id'], r['id'], r['selector_mode'], x, y, r['surface_height_m'], r['measurement_basis']))
    lines += ['', 'Yellow: fitted rectangle. Red: supplied corners. Cyan: selection box.', '',
              'Region-only results enclose visible plane inliers, not hidden/full furniture bounds.',
              'Corner results assume the selected boundary and a rectangular horizontal surface.', '',
              '[Numeric report](report.json) | [Authoring parameters](authoring_surfaces.json) | [Request](request.json)', '']
    if failures:
        lines += ['## Rejected requests', ''] + ['- %s: %s' % (f['id'], f['error']) for f in failures]
    (out/'MEASUREMENTS.md').write_text('\n'.join(lines)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(args.bundle, read(args.config), args.out, args.config.resolve().parent)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, 'furniture: %s\n' % error)
    print('%s: %d measurements, %d rejected; %s' %
          (report['status'], len(report['objects']), len(report['failures']), args.out/'MEASUREMENTS.md'))
    if report['failures']:
        parser.exit(2)


if __name__ == '__main__':
    main()
