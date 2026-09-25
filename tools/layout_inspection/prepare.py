"""Build TSDF + visible-context references with separate source measurement data."""
import argparse
import json
from pathlib import Path
import numpy as np
try:
    from .semantic import DEFAULT_PROMPTS, LAYERS, digest, validate_cache
    from .reference_geometry import human_exclusion_mask
except ImportError:
    from semantic import DEFAULT_PROMPTS, LAYERS, digest, validate_cache
    from reference_geometry import human_exclusion_mask


def classify(masks, known, geometry_valid):
    layer = np.full(geometry_valid.shape, LAYERS['semantic_unknown'], np.uint8)
    layer[np.broadcast_to(known[:, None, None], layer.shape)] = LAYERS['static']
    for name in ('mirror', 'glass', 'person'):
        layer[masks[name]] = LAYERS[name]
    # Quality remains separate; no class evidence is erased by invalid geometry.
    return layer


def triangulate(layer, valid, max_edge, vertices):
    n, h, w = layer.shape
    grid = np.arange(n*h*w).reshape(n,h,w)
    a,b,c,d = (grid[:,:-1,:-1], grid[:,:-1,1:], grid[:,1:,:-1], grid[:,1:,1:])
    faces = np.concatenate([np.stack([a,b,c], -1).reshape(-1,3), np.stack([b,d,c], -1).reshape(-1,3)])
    good = valid.ravel()[faces].all(1)
    for i,j in ((0,1),(1,2),(2,0)):
        good &= np.linalg.norm(vertices[faces[:,i]]-vertices[faces[:,j]], axis=1) <= max_edge
    faces = faces[good]
    labels = layer.ravel()[faces]
    face_layer = np.zeros(len(faces), np.uint8)
    # Mixed static/uncertain triangles are uncertain; people never leak to static.
    for key in ('mirror','glass','semantic_unknown','person'):
        face_layer[(labels == LAYERS[key]).any(1)] = LAYERS[key]
    return faces, face_layer


def require_full_coverage(ids, requested, known=None):
    """Display camera selections must never reduce reference surface coverage."""
    if requested is not None and list(requested) != ids.tolist():
        raise ValueError('Reference meshing requires all cached frames in order; omit --frames. Select display views in source_frames instead.')
    if known is not None and not known.all():
        raise ValueError('Semantic cache must cover all cached frames; rerun semantic without --frames before meshing.')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--cameras', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--semantic-cache', type=Path)
    p.add_argument('--frames', type=int, nargs='+', help='Compatibility only: must list every cached frame in order; default all')
    p.add_argument('--confidence', type=float, default=.5)
    p.add_argument('--max-edge', type=float, default=.15, help='Maximum triangle edge in predicted metres')
    p.add_argument('--mesh-method', choices=('tsdf-context', 'grid'), default='tsdf-context')
    p.add_argument('--fusion-confidence', type=float, default=.1,
                   help='Require sigmoid(raw Pi3X conf) > threshold for fusion and visible context')
    p.add_argument('--voxel-size', type=float, default=.03, help='TSDF voxel edge in predicted metres')
    p.add_argument('--human-mask-radius', type=int, default=3,
                   help='Per-frame human exclusion disk radius in processed-image pixels; 0 disables expansion')
    return p


def build(a):
    if a.human_mask_radius < 0:
        raise ValueError('Human mask radius must be a nonnegative integer')
    if not np.isfinite([a.confidence, a.max_edge, a.fusion_confidence, a.voxel_size]).all() or not 0 <= a.confidence <= 1 or a.max_edge <= 0 or not 0 <= a.fusion_confidence <= 1 or a.voxel_size <= 0:
        raise ValueError('Invalid confidence, max-edge or voxel size')
    with np.load(a.bundle/'inputs.npz', allow_pickle=False) as z:
        rgb, ids = z['rgb'], z['frame_indices']
    with np.load(a.bundle/'predictions.npz', allow_pickle=False) as z:
        points, conf, edge = z['points'], z['conf'], z['non_edge']
        if a.mesh_method == 'tsdf-context':
            local, predicted_poses, intrinsics = z['local_points'], z['camera_poses'], z['intrinsics']
            if local.shape != points.shape:
                raise ValueError('Pi3X local point shape mismatch')
    if points.shape != rgb.shape or conf.shape != (*points.shape[:-1],1) or edge.shape != points.shape[:-1]:
        raise ValueError('Pi3X dense array shape mismatch')
    if len(set(ids.tolist())) != len(ids):
        raise ValueError('Duplicate Pi3X frame IDs')
    require_full_coverage(ids, a.frames)
    camera = json.loads(a.cameras.read_text())
    transform = np.asarray(camera['world_transform'], float)
    if transform.shape != (4,4) or not np.isfinite(transform).all() or not np.allclose(transform[3], [0,0,0,1]) or not np.allclose(transform[:3,:3].T @ transform[:3,:3], np.eye(3), atol=1e-4) or np.linalg.det(transform[:3,:3]) < .999:
        raise ValueError('world_transform must be proper rigid; scale belongs in separate calibration')
    masks = {k: np.zeros(points.shape[:-1], bool) for k in DEFAULT_PROMPTS}
    known = np.zeros(len(ids), bool)
    semantic_meta = None
    if a.semantic_cache:
        masks, known, semantic_meta = validate_cache(a.semantic_cache, a.bundle, ids, points.shape[1:3])
        require_full_coverage(ids, a.frames, known)
    confidence = 1 / (1 + np.exp(-np.clip(conf[...,0], -50,50)))
    confidence[~np.isfinite(conf[...,0])] = np.nan
    finite = np.isfinite(points).all(-1) & np.isfinite(conf[...,0])
    valid = finite & (confidence >= a.confidence) & edge.astype(bool)
    if a.mesh_method == 'tsdf-context':
        valid &= np.isfinite(local).all(-1) & (local[...,2] > 0)
    layer = classify(masks, known, valid)
    human_exclusion = human_exclusion_mask(masks['person'], a.human_mask_radius)
    vertices = points.reshape(-1,3) @ transform[:3,:3].T + transform[:3,3]
    # Preserve original semantic labels and observations, but exclude the guard
    # band from source surfaces as well as fused/context geometry.
    guard_band = human_exclusion & ~masks['person']
    faces, face_layer = triangulate(layer, valid & ~guard_band, a.max_edge, vertices)
    n,h,w = valid.shape
    frame_slot,y,x = np.indices((n,h,w))
    a.out.mkdir(parents=True, exist_ok=False)
    extra = dict(measurement_valid=(valid & (layer == LAYERS['static']) & ~human_exclusion).ravel(),
                 human_exclusion=human_exclusion.ravel())
    representation = dict(method='grid', processed_frame_indices=ids.tolist(),
                          human_mask_radius_pixels=a.human_mask_radius)
    if a.mesh_method == 'tsdf-context':
        try:
            from .reference_geometry import build_display, write_background
        except ImportError:
            from reference_geometry import build_display, write_background
        display, representation = build_display(vertices.reshape(points.shape).astype(np.float32), rgb,
            local, confidence, edge.astype(bool), layer, ids, camera, predicted_poses, intrinsics, transform,
            voxel=a.voxel_size, fusion_confidence=a.fusion_confidence,
            human_mask_radius=a.human_mask_radius)
        extra.update(display)
        write_background(a.out/'background_all_finite.ply', vertices, rgb.reshape(-1,3), confidence.ravel(),
                         layer.ravel(), ids, (n,h,w), display['background_valid'])
        representation['background_ply'] = 'background_all_finite.ply'
        representation['background_ply_sha256'] = digest(a.out/'background_all_finite.ply')
        representation['implementation_sha256'] = digest(Path(__file__).with_name('reference_geometry.py'))
    np.savez_compressed(a.out/'layers.npz', vertices=vertices.astype(np.float32), colors=rgb.reshape(-1,3).astype(np.uint8), faces=faces.astype(np.int32), layer=layer.ravel(), face_layer=face_layer, geometry_valid=valid.ravel(), confidence=confidence.ravel().astype(np.float32), non_edge=edge.ravel().astype(bool), finite=finite.ravel(), semantic_known=np.repeat(known,h*w), frame_slot=frame_slot.ravel().astype(np.int16), source_frame=np.repeat(ids,h*w), pixel_yx=np.stack([y.ravel(),x.ravel()],-1).astype(np.int16), world_transform=transform, frame_indices=ids, **extra)
    meta = {'schema_version': 1, 'layers_sha256': digest(a.out/'layers.npz'), 'layers': LAYERS, 'bundle': str(a.bundle.resolve()), 'cameras': str(a.cameras.resolve()), 'cameras_sha256': digest(a.cameras), 'inputs_sha256': digest(a.bundle/'inputs.npz'), 'predictions_sha256': digest(a.bundle/'predictions.npz'), 'code_sha256': digest(__file__), 'semantic_cache': str(a.semantic_cache.resolve()) if a.semantic_cache else None, 'semantic_provenance': semantic_meta, 'confidence_min': a.confidence, 'max_triangle_edge_predicted_m': a.max_edge, 'world_transform': transform.tolist(), 'frame_indices': ids.tolist(), 'processed_shape_nhw': [n,h,w], 'vertex_counts': {k:int(((layer == v)&valid).sum()) for k,v in LAYERS.items()}, 'face_counts': {k:int((face_layer == v).sum()) for k,v in LAYERS.items()}, 'coordinate_status': 'Approximate predicted metres; no independent metric calibration', 'coverage': 'Unobserved space is unknown, never free; holes are not filled', 'policy': 'Vertices retain exact RGB, source frame/pixel, semantics and independent quality. Faces require three geometrically valid vertices and edge limit. Missing semantic frames are unknown; static layer excludes people and uncertain materials. Select points using geometry_valid as well as layer. Semantic masks pending visual review.'}
    meta.update(schema_version=2, geometry_representation=representation,
        measurement_policy='Only retained static source triangles and measurement_valid; display geometry is not measurement support',
        display_storage='Embedded display_* arrays in layers.npz; primary hash binds core and context; background PLY is a recoverable convenience export')
    (a.out/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(a.out/'layers.npz', flush=True)
    return meta


def main():
    build(parser().parse_args())

if __name__ == '__main__':
    main()
