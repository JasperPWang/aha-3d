"""Production TSDF core and source-linked visible context for Pi3X references.

Display arrays are embedded in layers.npz so snapshots and hash-bound layout
reviews carry the complete representation. Measurements use separate source
triangles. Algorithms derive from the validated 2026-09-12 geometry study.
"""
import numpy as np
from scipy.ndimage import binary_dilation


def human_exclusion_mask(person, radius):
    """Dilate each processed-raster mask by a Euclidean pixel radius, never in time."""
    if isinstance(radius, bool) or not isinstance(radius, (int, np.integer)) or radius < 0:
        raise ValueError('Human mask radius must be a nonnegative integer')
    person = np.asarray(person, dtype=bool)
    if person.ndim != 3:
        raise ValueError('Human masks must have shape (frames, height, width)')
    if radius == 0:
        return person.copy()
    y, x = np.ogrid[-radius:radius+1, -radius:radius+1]
    disk = x*x + y*y <= radius*radius
    return binary_dilation(person, structure=disk[None], iterations=1)


def rigid(value):
    m = np.asarray(value, dtype=np.float64)
    if (m.shape != (4, 4) or not np.isfinite(m).all()
            or not np.allclose(m[3], [0, 0, 0, 1])
            or not np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-4)
            or np.linalg.det(m[:3, :3]) < .999):
        raise ValueError('Expected a proper rigid world/camera transform')
    return m


def validate_cameras(camera, ids, predicted_poses, intrinsics, transform, image_shape):
    poses = np.array([rigid(row['c2w']) for row in camera['frames']])
    if [row['source_frame'] for row in camera['frames']] != ids.tolist():
        raise ValueError('Camera frames/order differ from Pi3X bundle')
    if not np.allclose(poses, transform @ predicted_poses, atol=1e-4):
        raise ValueError('Camera poses differ from dense Pi3X coordinate basis')
    k = np.asarray(intrinsics, float)
    if (k.shape != (len(ids), 3, 3) or not np.isfinite(k).all()
            or np.any(k[:, (0, 1), (0, 1)] <= 0)
            or not np.allclose(k[:, 2], [0, 0, 1])
            or not np.allclose(k[:, (0, 1), (1, 0)], 0)):
        raise ValueError('Expected finite positive, unskewed pinhole intrinsics')
    if not np.allclose(k, [row['intrinsics'] for row in camera['frames']], atol=1e-4):
        raise ValueError('Camera intrinsics differ from Pi3X bundle')
    h, w = image_shape
    if camera['processed_size_wh'] != [w, h]:
        raise ValueError('Camera image size differs from Pi3X raster')
    return poses, k


def rays(k, pose, height, width):
    y, x = np.mgrid[:height, :width]
    uv = np.stack([x, y, np.ones_like(x)], -1)
    directions = uv @ np.linalg.inv(k).T @ pose[:3, :3].T
    return np.concatenate([np.broadcast_to(pose[:3, 3], directions.shape), directions], -1).astype(np.float32)


def context_triangles(points, depth, mask):
    """Native image adjacency with range-relative discontinuity protection."""
    h, w = mask.shape
    index = np.arange(h*w).reshape(h, w)
    a, b, c, d = index[:-1, :-1], index[:-1, 1:], index[1:, :-1], index[1:, 1:]
    faces = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3),
                            np.stack([b, d, c], -1).reshape(-1, 3)])
    good = mask.ravel()[faces].all(1)
    # Filter validity first, before numeric operations on unknown coordinates.
    faces = faces[good]
    z = depth.ravel()[faces]
    good = (z.max(1)-z.min(1)) <= np.maximum(.03, .08*z.min(1))
    p = points.reshape(-1, 3)
    lengths = np.stack([np.linalg.norm(p[faces[:, i]]-p[faces[:, j]], axis=1)
                        for i, j in ((0, 1), (1, 2), (2, 0))], -1)
    good &= lengths.max(1) <= np.minimum(.75, np.maximum(.04, 5*lengths.min(1)))
    faces = faces[good]
    used, inverse = np.unique(faces, return_inverse=True)
    return used, inverse.reshape(-1, 3)


def build_display(points, rgb, local, confidence, non_edge, layer, ids, camera,
                  predicted_poses, intrinsics, transform, voxel=.03, fusion_confidence=.1,
                  human_mask_radius=3):
    try:
        import open3d as o3d
    except ImportError as error:
        raise RuntimeError('TSDF references require Open3D; use the configured --mesh-python runtime. '
                           'Use --mesh-method grid only for an explicit legacy reconstruction.') from error
    if not np.isfinite(voxel) or voxel <= 0 or not np.isfinite(fusion_confidence) or not 0 <= fusion_confidence <= 1:
        raise ValueError('Invalid voxel size or fusion confidence')
    n, h, w, _ = points.shape
    poses, k = validate_cameras(camera, ids, predicted_poses, intrinsics, transform, (h, w))
    depth = local[..., 2]
    finite_depth = np.isfinite(points).all(-1) & np.isfinite(local).all(-1) & (depth > 0)
    background = finite_depth & (layer != 1)
    human_exclusion = human_exclusion_mask(layer == 1, human_mask_radius)
    # Match upstream example_mm.py: confidence is sigmoid(raw conf), strict >.
    # Keep raw background for provenance, but never reintroduce rejected pixels
    # through context triangles or fallback points after fusion.
    confidence_valid = np.isfinite(confidence) & (confidence > fusion_confidence)
    context_eligible = background & confidence_valid & ~human_exclusion
    fusion = finite_depth & (layer == 0) & confidence_valid & non_edge & ~human_exclusion
    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel, sdf_trunc=4*voxel,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8, depth_sampling_stride=2)
    # Predicted units already include the metric factor; never use millimetres
    # or an RGB-D sensor's default 3 m range cutoff.
    depth_max = float(depth[finite_depth].max())+1 if finite_depth.any() else 1.
    for i in range(n):
        if not fusion[i].any():
            continue
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(rgb[i])),
            o3d.geometry.Image(np.where(fusion[i], depth[i], 0).astype(np.float32)),
            depth_scale=1., depth_trunc=depth_max, convert_rgb_to_intensity=False)
        intrinsic = o3d.camera.PinholeCameraIntrinsic(w, h, k[i, 0, 0], k[i, 1, 1], k[i, 0, 2], k[i, 1, 2])
        volume.integrate(rgbd, intrinsic, np.linalg.inv(poses[i]))
    core = volume.extract_triangle_mesh()
    core_v = np.asarray(core.vertices).astype(np.float32)
    core_c = np.uint8(np.clip(np.asarray(core.vertex_colors)*255, 0, 255).round())
    core_f = np.asarray(core.triangles).astype(np.int32)
    scene = o3d.t.geometry.RaycastingScene(nthreads=8)
    if len(core_f):
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(core))
    vs, cs, fs = [core_v], [core_c], [core_f]
    semantic_faces = [np.zeros(len(core_f), np.uint8)]
    roles = [np.zeros(len(core_f), np.uint8)]
    source = [np.full(len(core_v), -1, np.int64)]
    fallback, residual_counts = [], []
    offset = len(core_v)
    for i in range(n):
        if len(core_f):
            rendered = scene.cast_rays(o3d.core.Tensor(rays(k[i], poses[i], h, w)))['t_hit'].numpy()
        else:
            rendered = np.full((h, w), np.inf)
        missing = ~np.isfinite(rendered) | (np.abs(rendered-depth[i]) > np.maximum(.04, .015*depth[i]))
        uncertain = np.isin(layer[i], [2, 3, 5])
        residual = context_eligible[i] & binary_dilation(missing | uncertain, iterations=1)
        used, faces = context_triangles(points[i], depth[i], residual)
        residual_counts.append(int(residual.sum()))
        vs.append(points[i].reshape(-1, 3)[used]); cs.append(rgb[i].reshape(-1, 3)[used])
        fs.append(faces+offset); roles.append(np.ones(len(faces), np.uint8))
        vertex_labels = layer[i].ravel()[used]
        labels = np.zeros(len(faces), np.uint8)
        for label in (3, 2, 5, 1):
            labels[(vertex_labels[faces] == label).any(1)] = label
        semantic_faces.append(labels)
        source.append(used.astype(np.int64)+i*h*w)
        supported = np.zeros(h*w, bool); supported[used] = True
        fallback.append(np.flatnonzero(residual.ravel() & ~supported).astype(np.int64)+i*h*w)
        offset += len(used)
    arrays = dict(display_vertices=np.concatenate(vs).astype(np.float32),
                  display_colors=np.concatenate(cs).astype(np.uint8),
                  display_faces=np.concatenate(fs).astype(np.int32),
                  display_face_layer=np.concatenate(semantic_faces), display_face_role=np.concatenate(roles),
                  display_source_flat_indices=np.concatenate(source),
                  context_point_indices=np.concatenate(fallback), background_valid=background.ravel(),
                  finite_depth=finite_depth.ravel(), fusion_eligible=fusion.ravel(),
                  context_eligible=context_eligible.ravel(), human_exclusion=human_exclusion.ravel())
    meta = dict(method='tsdf-context', voxel_size_predicted_m=voxel, sdf_truncation_predicted_m=4*voxel,
                fusion_confidence_min=fusion_confidence, fusion_weight='uniform accepted observations',
                confidence_space='sigmoid of raw Pi3X conf logits', confidence_comparison='>',
                context_confidence_min=fusion_confidence,
                human_mask_radius_pixels=human_mask_radius,
                human_mask_dilation='Per-frame Euclidean disk in processed depth-image pixels; zero disables expansion',
                human_pixels_per_frame=(layer == 1).sum(axis=(1, 2)).tolist(),
                human_exclusion_pixels_per_frame=human_exclusion.sum(axis=(1, 2)).tolist(),
                fusion_pixels_per_frame=fusion.sum(axis=(1, 2)).tolist(),
                context_confidence_rejected_per_frame=(background & ~confidence_valid).sum(axis=(1, 2)).tolist(),
                core_vertices=len(core_v), core_faces=len(core_f),
                display_vertices=len(arrays['display_vertices']), display_faces=len(arrays['display_faces']),
                context_faces=int((arrays['display_face_role'] == 1).sum()),
                background_observations=int(background.sum()), context_fallback_points=len(arrays['context_point_indices']),
                processed_frame_indices=ids.tolist(), residual_pixels_per_frame=residual_counts,
                depth_scale=1., depth_max_predicted_m=depth_max, open3d_version=o3d.__version__,
                roles={'0': 'fused static core; no exact source pixel', '1': 'uncertain source context; not measurement geometry'},
                visibility_default='core plus confidence-filtered non-person context; glass/mirror/unknown remain separately labeled',
                residual_rule='missing source-camera ray or Z disagreement > max(0.04 m, 0.015 Z), plus uncertain materials; one-pixel overlap',
                measurement_policy='Use original retained static source triangles and measurement_valid, not display arrays')
    return arrays, meta


def write_background(path, vertices, colors, confidence, layer, frame_ids, shape, background_valid):
    """Stream every finite positive-depth non-person observation, with provenance."""
    n, h, w = shape
    selected = np.flatnonzero(background_valid)
    dtype = np.dtype([('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'),
                      ('confidence', '<f4'), ('source_frame', '<i4'), ('pixel_y', '<i2'), ('pixel_x', '<i2'), ('semantic_layer', 'u1')])
    with path.open('wb') as f:
        f.write(('ply\nformat binary_little_endian 1.0\ncomment Uncalibrated Pi3X reference; all finite positive-depth non-person samples\n'
                 f'element vertex {len(selected)}\nproperty float x\nproperty float y\nproperty float z\n'
                 'property uchar red\nproperty uchar green\nproperty uchar blue\nproperty float confidence\n'
                 'property int source_frame\nproperty short pixel_y\nproperty short pixel_x\nproperty uchar semantic_layer\nend_header\n').encode())
        for start in range(0, len(selected), 250000):
            index = selected[start:start+250000]
            data = np.empty(len(index), dtype)
            for axis, key in enumerate(('x', 'y', 'z')): data[key] = vertices[index, axis]
            for axis, key in enumerate(('red', 'green', 'blue')): data[key] = colors[index, axis]
            data['confidence'] = confidence[index]; data['semantic_layer'] = layer[index]
            data['source_frame'] = frame_ids[index//(h*w)]
            data['pixel_y'] = index//w % h; data['pixel_x'] = index % w
            data.tofile(f)
