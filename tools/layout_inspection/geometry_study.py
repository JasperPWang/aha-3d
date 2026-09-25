"""Reproducible Pi3X initial-reference experiment; never modifies source bundles.

Run with the configured Open3D meshing runtime. This is an opt-in
research exporter, not a replacement for prepare.py or its measurement contract.
All cached frames participate. Metrics measure prediction consistency, not GT.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from .semantic import digest, validate_cache


def rigid(matrix):
    m = np.asarray(matrix, dtype=np.float64)
    if (m.shape != (4, 4) or not np.isfinite(m).all()
            or not np.allclose(m[3], [0, 0, 0, 1])
            or not np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-4)
            or np.linalg.det(m[:3, :3]) < .999):
        raise ValueError('Expected a proper rigid transform; no scale in alignment')
    return m


def camera_rays(k, c2w, height, width, stride=1):
    """Unnormalized rays: ray parameter t equals camera Z, not radial distance."""
    y, x = np.mgrid[0:height:stride, 0:width:stride]
    uv1 = np.stack([x, y, np.ones_like(x)], -1)
    direction = uv1 @ np.linalg.inv(k).T @ c2w[:3, :3].T
    origin = np.broadcast_to(c2w[:3, 3], direction.shape)
    return np.concatenate([origin, direction], -1).astype(np.float32)


def grid_arrays(points, rgb, valid, depth, stride=1, adaptive=False, max_edge=.15):
    """Keep image adjacency; reject depth discontinuities, never bridge images."""
    pts, col, good, dep = [x[::stride, ::stride] for x in (points, rgb, valid, depth)]
    h, w = good.shape
    index = np.arange(h*w).reshape(h, w)
    a, b, c, d = index[:-1, :-1], index[:-1, 1:], index[1:, :-1], index[1:, 1:]
    faces = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3),
                            np.stack([b, d, c], -1).reshape(-1, 3)])
    keep = good.ravel()[faces].all(1)
    p = pts.reshape(-1, 3)
    z = dep.ravel()[faces]
    if adaptive:
        # Local footprint grows with range; the relative Z gate prevents curtains.
        keep &= (z.max(1)-z.min(1)) <= np.maximum(.03, .08*z.min(1))
        lengths = np.stack([np.linalg.norm(p[faces[:, i]]-p[faces[:, j]], axis=1)
                            for i, j in ((0, 1), (1, 2), (2, 0))], -1)
        # A local shape test, plus an explicit generous emergency edge bound.
        keep &= lengths.max(1) <= np.minimum(.75, np.maximum(.04, 5*lengths.min(1)))
    else:
        for i, j in ((0, 1), (1, 2), (2, 0)):
            keep &= np.linalg.norm(p[faces[:, i]]-p[faces[:, j]], axis=1) <= max_edge
    faces = faces[keep]
    used, inv = np.unique(faces, return_inverse=True)
    sy, sx = np.mgrid[0:points.shape[0]:stride, 0:points.shape[1]:stride]
    pixel = np.stack([sy.ravel()[used], sx.ravel()[used]], -1)
    return p[used], col.reshape(-1, 3)[used], inv.reshape(-1, 3), pixel


def make_mesh(vertices, colors, faces):
    import open3d as o3d
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),
                                 o3d.utility.Vector3iVector(faces))
    m.vertex_colors = o3d.utility.Vector3dVector(np.asarray(colors, float)/255)
    return m


def grids(data, valid, stride, adaptive=False):
    vs, cs, fs, ids = [], [], [], []
    count = 0
    for i in range(len(data['ids'])):
        v, c, f, pix = grid_arrays(data['points'][i], data['rgb'][i], valid[i],
                                   data['depth'][i], stride, adaptive)
        vs.append(v); cs.append(c); fs.append(f+count)
        ids.append(np.column_stack([np.full(len(pix), i), pix]))
        count += len(v)
    return make_mesh(np.concatenate(vs), np.concatenate(cs), np.concatenate(fs)), np.concatenate(ids)


def tsdf(data, valid, voxel=.04, slots=None):
    import open3d as o3d
    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel, sdf_trunc=4*voxel,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
        depth_sampling_stride=2)
    h, w = data['depth'].shape[1:]
    # Explicitly override Open3D's RGB-D sensor defaults (millimetres / 3 m).
    depth_max = float(np.max(data['depth'][data['finite']]))+1
    for i in (range(len(data['ids'])) if slots is None else slots):
        dep = np.where(valid[i], data['depth'][i], 0).astype(np.float32)
        color = o3d.geometry.Image(np.ascontiguousarray(data['rgb'][i]))
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            color, o3d.geometry.Image(dep), depth_scale=1., depth_trunc=depth_max,
            convert_rgb_to_intensity=False)
        k = data['k'][i]
        intrinsic = o3d.camera.PinholeCameraIntrinsic(w, h, k[0, 0], k[1, 1], k[0, 2], k[1, 2])
        volume.integrate(rgbd, intrinsic, np.linalg.inv(data['poses'][i]))
    return volume.extract_triangle_mesh()


def oriented_cloud(data, valid, voxel=.05):
    import open3d as o3d
    vertices, colors, normals = [], [], []
    for p, rgb, ok, pose in zip(data['points'], data['rgb'], valid, data['poses']):
        dx, dy = np.gradient(p, axis=1), np.gradient(p, axis=0)
        norm = np.cross(dx, dy)
        size = np.linalg.norm(norm, axis=-1)
        ok = ok & np.isfinite(norm).all(-1) & (size > 1e-8)
        norm /= np.maximum(size[..., None], 1e-8)
        norm[np.sum(norm*(pose[:3, 3]-p), -1) < 0] *= -1
        vertices.append(p[ok]); colors.append(rgb[ok]); normals.append(norm[ok])
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.concatenate(vertices))
    cloud.colors = o3d.utility.Vector3dVector(np.concatenate(colors)/255.)
    cloud.normals = o3d.utility.Vector3dVector(np.concatenate(normals))
    cloud = cloud.voxel_down_sample(voxel)
    norm = np.asarray(cloud.normals)
    cloud = cloud.select_by_index(np.flatnonzero(np.linalg.norm(norm, axis=-1) > .2))
    cloud.normalize_normals()
    return cloud


def voxel_surface(cloud, voxel=.08):
    """Boundary of cells containing samples. Empty cells remain unobserved.

    This produces a thick occupancy shell, not a signed distance reconstruction.
    Sparse integer keys avoid allocating a dense far-background bounding box.
    """
    p, color = np.asarray(cloud.points), np.asarray(cloud.colors)
    cells, first = np.unique(np.floor(p/voxel).astype(np.int64), axis=0, return_index=True)
    lookup = set(map(tuple, cells))
    vertices, colors, faces = [], [], []
    for axis in range(3):
        other = [x for x in range(3) if x != axis]
        for sign in (-1, 1):
            shift = np.eye(3, dtype=np.int64)[axis]*sign
            exposed = np.array([tuple(c+shift) not in lookup for c in cells])
            base = cells[exposed].astype(float)
            base[:, axis] += sign == 1
            corner = np.zeros((4, 3))
            corner[:, other] = [[0, 0], [1, 0], [1, 1], [0, 1]]
            v = ((base[:, None, :]+corner)*voxel).reshape(-1, 3)
            offset = sum(len(x) for x in vertices)
            f = np.arange(len(v)).reshape(-1, 4)
            faces.append(np.concatenate([f[:, [0, 1, 2]], f[:, [0, 2, 3]]])+offset)
            vertices.append(v); colors.append(np.repeat(color[first[exposed]]*255, 4, axis=0))
    return make_mesh(np.concatenate(vertices), np.concatenate(colors), np.concatenate(faces))


def scene_for(mesh):
    import open3d as o3d
    scene = o3d.t.geometry.RaycastingScene(nthreads=8)
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    return scene


def cast(scene, k, pose, h, w, stride):
    import open3d as o3d
    rays = camera_rays(k, pose, h, w, stride)
    result = scene.cast_rays(o3d.core.Tensor(rays))
    return {key: result[key].numpy() for key in ('t_hit', 'primitive_ids', 'primitive_uvs', 'primitive_normals')}


def shaded(mesh, result):
    hit = np.isfinite(result['t_hit'])
    image = np.full((*hit.shape, 3), [30, 34, 40], dtype=np.uint8)
    if not hit.any():
        return image
    face = np.asarray(mesh.triangles)[result['primitive_ids'][hit]]
    uv = result['primitive_uvs'][hit]
    weights = np.column_stack([1-uv.sum(-1), uv])
    colors = np.asarray(mesh.vertex_colors)
    if len(colors):
        col = (colors[face]*weights[..., None]).sum(1)
    else:
        col = np.full((len(face), 3), .75)
    normal = result['primitive_normals'][hit]
    light = np.array([.3, -.4, .85]); light /= np.linalg.norm(light)
    intensity = .65+.35*np.abs(normal@light)
    image[hit] = np.uint8(np.clip(col*intensity[:, None]*255, 0, 255))
    return image


def metric(depth, target, mask):
    hit = mask & np.isfinite(depth)
    delta = np.abs(depth-target)
    agree = hit & (delta <= np.maximum(.10, .05*target))
    return {'pixels': int(mask.sum()), 'hit': int(hit.sum()), 'agree': int(agree.sum()),
            'abs_error_sum': float(delta[hit].sum()),
            'coverage': float(hit.sum()/max(1, mask.sum())),
            'agreement_10cm_or_5pct': float(agree.sum()/max(1, mask.sum())),
            'mean_abs_depth_error_m_on_hits': float(delta[hit].mean()) if hit.any() else None}


def evaluate(mesh, data, out, name, display_slots):
    scene = scene_for(mesh)
    h, w = data['depth'].shape[1:]
    stats = {key: [] for key in ('static', 'far_static', 'context', 'glass_mirror', 'person')}
    previews = []
    for i in range(len(data['ids'])):
        result = cast(scene, data['k'][i], data['poses'][i], h, w, 2)
        target = data['depth'][i, ::2, ::2]
        masks = {'static': data['strict'][i], 'far_static': data['strict'][i] & data['far'][i],
                 'context': data['context'][i], 'glass_mirror': data['context'][i] & data['uncertain'][i],
                 'person': data['finite'][i] & data['person'][i]}
        for key, mask in masks.items():
            stats[key].append(metric(result['t_hit'], target, mask[::2, ::2]))
        if i in display_slots:
            im = Image.fromarray(shaded(mesh, result))
            im.save(out/f'{name}_frame_{data["ids"][i]:06d}.png')
            previews.append(im)
    combined = {}
    for key, rows in stats.items():
        n = sum(x['pixels'] for x in rows); hits = sum(x['hit'] for x in rows)
        combined[key] = {'pixels': n, 'coverage': sum(x['hit'] for x in rows)/max(n, 1),
                         'agreement_10cm_or_5pct': sum(x['agree'] for x in rows)/max(n, 1),
                         'mean_abs_depth_error_m_on_hits': sum(x['abs_error_sum'] for x in rows)/max(hits, 1)}
    del scene
    return combined, stats, previews


def load_data(bundle, cameras, semantic):
    with np.load(bundle/'inputs.npz', allow_pickle=False) as z:
        rgb, ids = z['rgb'], z['frame_indices']
    with np.load(bundle/'predictions.npz', allow_pickle=False) as z:
        points, local, logits, edge = z['points'], z['local_points'], z['conf'][..., 0], z['non_edge']
        predicted_poses, k = z['camera_poses'], z['intrinsics']
    camera = json.loads(cameras.read_text())
    transform = rigid(camera['world_transform'])
    records = camera['frames']
    if [r['source_frame'] for r in records] != ids.tolist():
        raise ValueError('Camera frame IDs/order differ from bundle')
    poses = np.array([rigid(r['c2w']) for r in records])
    if not np.allclose(poses, transform@predicted_poses, atol=1e-4):
        raise ValueError('Camera poses do not match dense point basis')
    if not np.allclose(k, [r['intrinsics'] for r in records], atol=1e-4):
        raise ValueError('Camera intrinsics differ from bundle')
    masks, known, _ = validate_cache(semantic, bundle, ids, rgb.shape[1:3])
    if not known.all():
        raise ValueError('Require semantic processing on every cached frame')
    if points.shape != rgb.shape or local.shape != rgb.shape or logits.shape != rgb.shape[:-1]:
        raise ValueError('Dense shape mismatch')
    finite = np.isfinite(points).all(-1) & np.isfinite(local).all(-1) & (local[..., 2] > 0)
    confidence = 1/(1+np.exp(-np.clip(logits, -50, 50)))
    points = (points@transform[:3, :3].T+transform[:3, 3]).astype(np.float32)
    uncertain = masks['glass'] | masks['mirror']
    static = ~masks['person'] & ~uncertain
    strict = finite & np.isfinite(logits) & static & (confidence >= .5) & edge
    relaxed = finite & np.isfinite(logits) & static & (confidence >= .1) & edge
    context = finite & ~masks['person']
    depth = local[..., 2].copy()
    threshold = np.quantile(depth[context], .75)
    # Diagnose the pinhole approximation before attributing fusion errors to TSDF.
    y, x = np.mgrid[:rgb.shape[1], :rgb.shape[2]]
    errors = []
    for p, intrinsic, ok in zip(local, k, finite):
        uv = p@intrinsic.T
        uv = uv[..., :2]/np.maximum(uv[..., 2:], 1e-8)
        errors.append(np.linalg.norm(uv-np.stack([x, y], -1), axis=-1)[ok][::32])
    return dict(rgb=rgb, ids=ids, points=points, depth=depth, k=k, poses=poses,
                finite=finite, confidence=confidence, edge=edge, person=masks['person'],
                uncertain=uncertain, static=static, strict=strict, relaxed=relaxed,
                context=context, far=depth >= threshold, far_threshold=float(threshold),
                pinhole_error_px_quantiles=np.quantile(np.concatenate(errors), [.5, .9, .99]).tolist())


def audit(data, out):
    stages = {'finite': data['finite'], 'confidence_05': data['finite'] & (data['confidence'] >= .5),
              'confidence_01': data['finite'] & (data['confidence'] >= .1),
              'confidence_05_edge': data['finite'] & (data['confidence'] >= .5) & data['edge'],
              'current_static_vertices': data['strict'], 'relaxed_static_vertices': data['relaxed'],
              'preserved_context': data['context']}
    groups = {'all': data['finite'], 'far_quartile': data['finite'] & data['far'],
              'glass_mirror': data['finite'] & data['uncertain'] & ~data['person']}
    counts = {g: {k: {'count': int((mask & group).sum()),
                      'fraction': float((mask & group).sum()/max(1, group.sum()))}
                  for k, mask in stages.items()} for g, group in groups.items()}
    # Native-grid face support, without allocating one giant multi-frame mesh.
    total, used_pixels = 0, 0
    for i in range(len(data['ids'])):
        v, c, f, _ = grid_arrays(data['points'][i], data['rgb'][i], data['strict'][i], data['depth'][i])
        total += len(f); used_pixels += len(v)
    result = dict(stages=counts, native_static_faces=total, native_static_used_vertices=used_pixels,
                  frame_indices=data['ids'].tolist(), far_definition='top depth quartile of finite non-person samples',
                  far_depth_threshold_m=data['far_threshold'], pinhole_error_px_p50_p90_p99=data['pinhole_error_px_quantiles'])
    (out/'filter_audit.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def contact_sheet(rows, names, out):
    width, height = rows[0][0].size
    canvas = Image.new('RGB', (3*width, len(rows)*(height+28)), 'white')
    draw = ImageDraw.Draw(canvas)
    for j, (row, name) in enumerate(zip(rows, names)):
        y = j*(height+28)
        draw.text((5, y+7), name, fill='black')
        for i, im in enumerate(row):
            canvas.paste(im, (i*width, y+28))
    canvas.save(out/'comparison.jpg', quality=92)


def run(a):
    import open3d as o3d
    started = time.perf_counter()
    a.out.mkdir(parents=True, exist_ok=False)
    d = load_data(a.bundle, a.cameras, a.semantic_cache)
    audit_result = audit(d, a.out)
    display = [0, len(d['ids'])//2, len(d['ids'])-1]
    rows = [[Image.fromarray(d['rgb'][i, ::2, ::2]) for i in display]]
    labels = ['Source RGB: early / middle / late; all cached frames used in reconstruction']
    report = {'schema_version': 1, 'status': 'running', 'open3d': o3d.__version__,
              'job_id': os.environ.get('INDOOR_RUN_ID'), 'bundle': str(a.bundle.resolve()),
              'cameras': str(a.cameras.resolve()), 'semantic_cache': str(a.semantic_cache.resolve()),
              'hashes': {str(p): digest(p) for p in (a.bundle/'inputs.npz', a.bundle/'predictions.npz', a.cameras,
                                                  a.semantic_cache/'masks.npz', Path(__file__))},
              'frame_indices': d['ids'].tolist(), 'grid_stride': a.grid_stride,
              'evaluation': 'All-view reprojection against cached Pi3X Z; not ground truth. '
                            'Confidence is not calibrated. Far is a depth quartile, not a semantic label. '
                            'Person coverage is not a contamination metric because background can be visible through removed people.',
              'audit': audit_result, 'methods': {}}
    def deliver(name, mesh, settings, provenance=None):
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()
        if not len(mesh.triangles):
            raise ValueError(f'{name}: empty mesh')
        if not np.isfinite(np.asarray(mesh.vertices)).all():
            raise ValueError(f'{name}: nonfinite vertices')
        path = a.out/f'{name}.ply'
        if not o3d.io.write_triangle_mesh(str(path), mesh, write_ascii=False):
            raise RuntimeError(f'Failed to write {path}')
        score, perframe, previews = evaluate(mesh, d, a.out, name, display)
        result = dict(vertices=len(mesh.vertices), faces=len(mesh.triangles), bytes=path.stat().st_size,
                      sha256=digest(path), settings=settings, scores=score, per_frame=perframe,
                      elapsed_since_start_s=time.perf_counter()-started)
        report['methods'][name] = result
        (a.out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        rows.append(previews); labels.append(name)
        contact_sheet(rows, labels, a.out)
        print(name, json.dumps({k: result[k] for k in ('vertices', 'faces')}), flush=True)
    for name, valid, adaptive in [
            ('grid_current', d['strict'], False),
            ('grid_conf01', d['relaxed'], False),
            ('grid_adaptive_static', d['finite'] & d['static'] & (d['confidence'] >= .1), True),
            ('grid_context', d['context'], True)]:
        t = time.perf_counter()
        mesh, provenance = grids(d, valid, a.grid_stride, adaptive)
        if name == 'grid_context':
            slot, y, x = provenance.T
            np.savez_compressed(a.out/'context_vertex_sources.npz', frame_slot=slot.astype(np.int16),
                source_frame=d['ids'][slot], pixel_yx=np.stack([y, x], -1).astype(np.int16),
                confidence=d['confidence'][slot, y, x], glass_mirror=d['uncertain'][slot, y, x],
                vertices=np.asarray(mesh.vertices).astype(np.float32))
        deliver(name, mesh, dict(grid_stride=a.grid_stride, adaptive=adaptive, build_s=time.perf_counter()-t))
        del mesh, provenance; gc.collect()
    for voxel in (.03, .06):
        t = time.perf_counter()
        mesh = tsdf(d, d['relaxed'], voxel)
        deliver(f'tsdf_{int(voxel*100):02d}cm', mesh,
                dict(voxel_m=voxel, truncation_m=4*voxel, confidence=.1, non_edge=True,
                     semantics='exclude person/glass/mirror', weighting='uniform accepted observations',
                     depth_scale=1, depth_max=float(d['depth'][d['finite']].max())+1,
                     build_s=time.perf_counter()-t))
        del mesh; gc.collect()
    t = time.perf_counter()
    cloud = oriented_cloud(d, d['relaxed'], .05)
    o3d.io.write_point_cloud(str(a.out/'static_surfel_samples.ply'), cloud)
    cloud_seconds = time.perf_counter()-t
    t = time.perf_counter()
    mesh = voxel_surface(cloud, .08)
    deliver('occupancy_08cm', mesh, dict(voxel_m=.08, cloud_voxel_m=.05,
            interpretation='boundary of observed cells; empty cells unknown', build_s=time.perf_counter()-t))
    del mesh; gc.collect()
    t = time.perf_counter()
    mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
        cloud, o3d.utility.DoubleVector([.075, .15, .30]))
    deliver('ball_pivoting', mesh, dict(radii_m=[.075, .15, .30], cloud_voxel_m=.05,
            cloud_points=len(cloud.points), cloud_build_s=cloud_seconds, build_s=time.perf_counter()-t))
    del mesh; gc.collect()
    t = time.perf_counter()
    mesh, density = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(cloud, depth=8, n_threads=8)
    # Do not hide the untrimmed completion; quantify and save it separately.
    vertices = np.asarray(mesh.vertices)
    distance, _ = cKDTree(np.asarray(cloud.points)).query(vertices, workers=8)
    trim = (np.asarray(density) < np.quantile(density, .02)) | (distance > .15)
    raw_faces = len(mesh.triangles)
    o3d.io.write_triangle_mesh(str(a.out/'poisson_untrimmed.ply'), mesh)
    mesh.remove_vertices_by_mask(trim)
    deliver('poisson_trimmed', mesh, dict(depth=8, cloud_voxel_m=.05, cloud_points=len(cloud.points),
            raw_faces=raw_faces, trim_vertices=int(trim.sum()), support_distance_m=.15, density_trim_quantile=.02,
            build_s=time.perf_counter()-t))
    del mesh, cloud; gc.collect()
    # Core + residual context: preserve finite background with its own provenance.
    # Surface distance only decides display duplication, never measurement trust.
    core = o3d.io.read_triangle_mesh(str(a.out/'tsdf_03cm.ply'))
    scene = scene_for(core)
    residual = d['context'].copy()
    for i, points in enumerate(d['points']):
        flat = points.reshape(-1, 3)
        distance = scene.compute_distance(o3d.core.Tensor(flat)).numpy().reshape(residual.shape[1:])
        residual[i] &= (distance > .06) | d['uncertain'][i]
    context, provenance = grids(d, residual, a.grid_stride, adaptive=True)
    o3d.io.write_triangle_mesh(str(a.out/'context_residual.ply'), context)
    slot, y, x = provenance.T
    np.savez_compressed(a.out/'residual_vertex_sources.npz', frame_slot=slot.astype(np.int16),
        source_frame=d['ids'][slot], pixel_yx=np.stack([y, x], -1).astype(np.int16),
        confidence=d['confidence'][slot, y, x], glass_mirror=d['uncertain'][slot, y, x],
        vertices=np.asarray(context.vertices).astype(np.float32))
    deliver('hybrid_reference', core+context, dict(core='tsdf_03cm.ply', context='context_residual.ply',
            context_confidence_cutoff=None, residual_surface_distance_m=.06,
            measurement_policy='Context is display reference only; use trusted source support for measurements'))
    report['status'] = 'complete; visual review recorded separately'
    report['total_seconds'] = time.perf_counter()-started
    (a.out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--cameras', type=Path, required=True)
    p.add_argument('--semantic-cache', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--grid-stride', type=int, default=1, choices=(1, 2, 4))
    a = p.parse_args()
    run(a)


if __name__ == '__main__':
    main()
