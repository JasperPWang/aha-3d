"""Thin visible model contours over exact native source RGB."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .reference_geometry import rays, rigid
from .semantic import digest


def boundaries(mask):
    """Mark only the foreground side of a binary image boundary."""
    result = np.zeros(mask.shape, bool)
    for axis in (0, 1):
        a = [slice(None), slice(None)]; b = a.copy()
        a[axis] = slice(None, -1); b[axis] = slice(1, None)
        a, b = tuple(a), tuple(b)
        change = mask[a] != mask[b]
        result[a] |= change & mask[a]
        result[b] |= change & mask[b]
    return result


def visible_edges(depth, absolute=.05, relative=.03):
    """First-hit silhouette/depth jumps, never mesh triangulation edges."""
    hit = np.isfinite(depth) & (depth > 0)
    edges = boundaries(hit)
    for axis in (0, 1):
        a = [slice(None), slice(None)]; b = a.copy()
        a[axis] = slice(None, -1); b[axis] = slice(1, None)
        a, b = tuple(a), tuple(b)
        both = hit[a] & hit[b]
        change = np.zeros(both.shape, bool)
        change[both] = np.abs(depth[a][both] - depth[b][both]) > np.maximum(
            absolute, relative * np.minimum(depth[a][both], depth[b][both]))
        # Keep the nearer side of a jump, so line pixels do not spill behind it.
        edges[a] |= change & (depth[a] < depth[b])
        edges[b] |= change & (depth[b] < depth[a])
    return edges


def run(geometry, metadata, cameras, inputs, out, frames, highlight=(),
        absolute=.05, relative=.03, threads=8, only_highlight=False, object_ids=()):
    if not np.isfinite([absolute, relative]).all() or min(absolute, relative) < 0:
        raise ValueError('Depth-jump thresholds must be finite and nonnegative')
    if threads < 1:
        raise ValueError('threads must be positive')
    if only_highlight and not (highlight or object_ids):
        raise ValueError('only-highlight requires at least one highlight term')
    started = time.perf_counter()
    import open3d as o3d
    geometry, metadata, cameras, inputs, out = map(Path, (geometry, metadata, cameras, inputs, out))
    meta = json.loads(metadata.read_text()); cam = json.loads(cameras.read_text())
    hashes = {name: digest(path) for name, path in (
        ('geometry', geometry), ('metadata', metadata), ('cameras', cameras), ('inputs', inputs))}
    for key in ('geometry', 'cameras', 'inputs'):
        if key + '_sha256' in meta and meta[key + '_sha256'] != hashes[key]:
            raise ValueError('Export provenance mismatch: ' + key)
    if not np.allclose(rigid(meta['world_transform']), rigid(cam['world_transform']), atol=1e-6, rtol=0):
        raise ValueError('Export and cameras use different reviewed world bases')
    names = meta['object_names']
    if isinstance(names, list):
        names = {str(i): name for i, name in enumerate(names)}
    if not isinstance(names, dict) or any(not isinstance(name, str) for name in names.values()):
        raise ValueError('object_names must map integer IDs to original mesh names')
    names = {int(key): value for key, value in names.items()}
    if any(key < 0 for key in names):
        raise ValueError('Object IDs must be nonnegative')
    groups = {term: [oid for oid, name in names.items() if term.casefold() in name.casefold()]
              for term in highlight}
    for identity in object_ids:
        matched = [index for index, group in enumerate(meta.get('object_groups', [])) if group['id'] == identity]
        if not matched:
            raise ValueError('Exact object ID absent from export: ' + identity)
        groups['id:' + identity] = matched
    unmatched = [term for term, matched in groups.items() if not matched]
    if unmatched:
        raise ValueError('Highlight terms matched no exported model names: ' + ', '.join(unmatched))
    with np.load(geometry, allow_pickle=False) as z:
        vertices, faces, face_ids = z['vertices'], z['faces'], z['face_object_id']
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all()
            or faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer)
            or face_ids.shape != (len(faces),) or not np.issubdtype(face_ids.dtype, np.integer)):
        raise ValueError('Invalid triangle export arrays')
    if len(faces) and (faces.min() < 0 or faces.max() >= len(vertices)):
        raise ValueError('Triangle vertex index out of range')
    if not set(np.unique(face_ids).tolist()).issubset(names):
        raise ValueError('Triangle object ID has no original mesh name')
    with np.load(inputs, allow_pickle=False) as z:
        rgb, ids, times = z['rgb'], z['frame_indices'], z['timestamps_seconds']
    if (rgb.ndim != 4 or rgb.shape[-1] != 3 or rgb.dtype != np.uint8
            or ids.shape != (len(rgb),) or not np.issubdtype(ids.dtype, np.integer)
            or times.shape != ids.shape or not np.isfinite(times).all()
            or len(ids) == 0 or np.any(np.diff(ids) <= 0) or np.any(np.diff(times) <= 0)):
        raise ValueError('Need uint8 native RGB and ordered frame IDs/timestamps')
    records = cam['frames']; n, h, w, _ = rgb.shape
    if (cam['processed_size_wh'] != [w, h]
            or [row['source_frame'] for row in records] != ids.tolist()
            or not np.allclose([row['timestamp_seconds'] for row in records], times, atol=1e-6, rtol=0)):
        raise ValueError('Camera and RGB frame, timestamp or native raster mismatch')
    if not frames or len(set(frames)) != len(frames) or not set(frames).issubset(ids.tolist()):
        raise ValueError('Select distinct native source frame IDs present in the cache')
    for row in records:
        rigid(row['c2w']); k = np.asarray(row['intrinsics'], float)
        if (k.shape != (3, 3) or not np.isfinite(k).all() or min(k[0, 0], k[1, 1]) <= 0
                or not np.allclose(k[2], [0, 0, 1]) or not np.allclose(k[(0, 1), (1, 0)], 0)):
            raise ValueError('Expected finite positive unskewed camera intrinsics')
    loaded = time.perf_counter()
    scene = o3d.t.geometry.RaycastingScene(nthreads=threads)
    if len(faces):
        scene.add_triangles(o3d.core.Tensor(vertices.astype(np.float32)),
                            o3d.core.Tensor(faces.astype(np.uint32)))
    built = time.perf_counter()
    out.mkdir(parents=True, exist_ok=False)
    palette = [(255, 168, 45), (255, 90, 190), (105, 245, 100), (235, 225, 70)]
    report = dict(schema_version=1, status='diagnostic only; visual review required',
        hashes=hashes, implementation_sha256=digest(__file__), export_metadata=meta,
        image_size_wh=[w, h], selected_source_frames=frames,
        only_highlight=only_highlight,
        depth_convention='Camera-Z from unnormalized camera-space rays with Z=1',
        edge_thresholds=dict(absolute_predicted_m=absolute, relative=relative),
        legend={'cyan': 'Visible model silhouette and depth discontinuity',
                'highlight': {term: {'color_rgb': palette[i % len(palette)],
                                    'matched_original_mesh_ids': matched}
                              for i, (term, matched) in enumerate(groups.items())}},
        limitations=['Source mesh names are authored components, not source-video object identities',
                     'No reference depth, segmentation, correctness score or automatic acceptance',
                     'Missing model hits have no contour evidence; untouched RGB is not accepted geometry',
                     'Source people, glass and reflections are not masked in this minimal visual check',
                     'Camera and metric scale are estimates; all exported model geometry remains an occluder'],
        timing_seconds={'load_validate_hash': loaded - started, 'structure_add': built - loaded}, views=[])
    sheet = Image.new('RGB', (2 * w, (h + 42) * len(frames)), (25, 28, 35))
    for i, frame in enumerate(frames):
        slot = ids.tolist().index(frame); row = records[slot]; tick = time.perf_counter()
        depth = np.full((h, w), np.inf, np.float32)
        object_id = np.full((h, w), -1, np.int64)
        if len(faces):
            result = scene.cast_rays(o3d.core.Tensor(rays(np.asarray(row['intrinsics']),
                rigid(row['c2w']), h, w)), nthreads=threads)
            depth = result['t_hit'].numpy(); hit = np.isfinite(depth) & (depth > 0)
            object_id[hit] = face_ids[result['primitive_ids'].numpy()[hit]]
        queried = time.perf_counter(); edges = visible_edges(depth, absolute, relative)
        pixels = rgb[slot].copy()
        if not only_highlight:
            pixels[edges] = [30, 205, 245]
        for j, matched in enumerate(groups.values()):
            mask = np.isin(object_id, matched)
            pixels[boundaries(mask) | (edges & mask)] = palette[j % len(palette)]
        name = f'source_{frame:06d}'
        Image.fromarray(rgb[slot]).save(out / (name + '_source.png'))
        Image.fromarray(pixels).save(out / (name + '_overlay.png'))
        panel = Image.new('RGB', (2 * w, h + 42), (25, 28, 35))
        panel.paste(Image.fromarray(rgb[slot]), (0, 42)); panel.paste(Image.fromarray(pixels), (w, 42))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 6), f'SOURCE {frame} | {times[slot]:.3f}s | native {w}x{h}', fill='white')
        title = 'SOURCE + SELECTED VISIBLE CONTOURS' if only_highlight else 'SOURCE + VISIBLE MODEL CONTOURS | cyan: model'
        draw.text((w + 8, 6), title, fill='white')
        for j, term in enumerate(groups):
            draw.text((w + 8 + j * 160, 23), term, fill=tuple(palette[j % len(palette)]))
        panel.save(out / (name + '_comparison.jpg'), quality=95)
        sheet.paste(panel, (0, i * (h + 42)))
        np.savez_compressed(out / (name + '_visibility.npz'), depth_camera_z=depth,
                            object_id=object_id, visible_edge=edges)
        report['views'].append(dict(source_frame=frame, timestamp_seconds=float(times[slot]),
            c2w=row['c2w'], intrinsics=row['intrinsics'], hit_pixels=int((object_id >= 0).sum()),
            visible_mesh_ids=np.unique(object_id[object_id >= 0]).tolist(),
            query_seconds=queried - tick, compose_write_seconds=time.perf_counter() - queried))
    sheet.save(out / 'overview.jpg', quality=95)
    report['timing_seconds']['total'] = time.perf_counter() - started
    (out / 'inspection_report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('geometry', 'metadata', 'cameras', 'inputs', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--frames', required=True, help='Comma-separated exact cached source frame IDs')
    p.add_argument('--highlight', default='', help='Comma-separated case-insensitive model-name substrings')
    p.add_argument('--object-id', action='append', default=[], help='Exact authored instance ID; repeat for multiple objects')
    p.add_argument('--only-highlight', action='store_true', help='Draw selected contours only; all model geometry still occludes')
    p.add_argument('--absolute-jump', type=float, default=.05)
    p.add_argument('--relative-jump', type=float, default=.03)
    p.add_argument('--threads', type=int, default=8)
    a = p.parse_args()
    report = run(a.geometry, a.metadata, a.cameras, a.inputs, a.out,
                 [int(value.strip()) for value in a.frames.split(',')],
                 [value.strip() for value in a.highlight.split(',') if value.strip()],
                 a.absolute_jump, a.relative_jump, a.threads, a.only_highlight, a.object_id)
    print(json.dumps({'status': report['status'], 'views': len(report['views']),
                      'timing_seconds': report['timing_seconds']}))


if __name__ == '__main__':
    main()
