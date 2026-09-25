"""Project complete-object silhouettes onto existing, matched inspection views."""
import argparse
import colorsys
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .object_report import write_report
from .semantic import digest


def object_color(identity):
    """Deterministic identity color; labels also distinguish similar hues."""
    key = hashlib.sha256(identity.encode()).digest()
    hue = int.from_bytes(key[:4], 'big') / 2**32
    rgb = colorsys.hsv_to_rgb(hue, .65 + key[4] / 255 * .25, .85 + key[5] / 255 * .15)
    return [round(x * 255) for x in rgb]


def clip_plane(triangles, axis, bound, sign):
    """Clip triangles against sign * (coordinate - bound) <= 0, without caps."""
    if not len(triangles):
        return triangles
    distance = sign * (triangles[..., axis] - bound)
    inside = distance <= 0
    count = inside.sum(axis=1)
    result = [triangles[count == 3]]
    for n in (1, 2):
        subset = triangles[count == n]
        if not len(subset):
            continue
        d = distance[count == n]
        # Rotate the isolated inside/outside vertex to the beginning.
        first = np.argmax(inside[count == n] if n == 1 else ~inside[count == n], axis=1)
        order = (first[:, None] + np.arange(3)) % 3
        t = subset[np.arange(len(subset))[:, None], order]
        d = d[np.arange(len(subset))[:, None], order]
        ab = t[:, 0] + (t[:, 1] - t[:, 0]) * (d[:, 0] / (d[:, 0] - d[:, 1]))[:, None]
        ac = t[:, 0] + (t[:, 2] - t[:, 0]) * (d[:, 0] / (d[:, 0] - d[:, 2]))[:, None]
        if n == 1:
            result.append(np.stack([t[:, 0], ab, ac], axis=1))
        else:
            result.extend([np.stack([ab, t[:, 1], t[:, 2]], axis=1),
                           np.stack([ab, t[:, 2], ac], axis=1)])
    return np.concatenate(result)


def clipped(triangles, crop):
    for axis, (low, high) in enumerate(crop):
        triangles = clip_plane(triangles, axis, low, -1)
        triangles = clip_plane(triangles, axis, high, 1)
    return triangles


def camera_rays(view, width, height):
    """Match Blender's pixel-center sampling, with rays in camera coordinates."""
    y, x = np.mgrid[:height, :width]
    settings = view['settings']
    pose = np.asarray(view['camera_matrix_world'], float) @ np.diag([1, -1, -1, 1])
    if 'source_record' in settings:
        k = np.asarray(settings['source_record']['intrinsics'], float)
        directions = np.stack([x + .5, y + .5, np.ones_like(x)], axis=-1) @ np.linalg.inv(k).T
        origins = np.zeros_like(directions)
    else:
        if width != height:
            raise ValueError('Existing orthographic inspection panels must be square')
        scale = settings['ortho_scale']
        origins = np.stack([(x + .5 - width / 2) * scale / width,
                            (y + .5 - height / 2) * scale / width, np.zeros_like(x)], axis=-1)
        directions = np.zeros_like(origins); directions[..., 2] = 1
    # Match inspection camera clip_start=.1 and clip_end=2000.
    origins = origins + directions * .1
    return np.concatenate([origins, directions], axis=-1).astype(np.float32), pose


def silhouette(triangles, view, width, height, threads=4):
    """First hit within one object's clipped geometry; other objects cannot hide it."""
    import open3d as o3d
    triangles = clipped(triangles, view['settings']['crop_xyz_m'])
    rays, pose = camera_rays(view, width, height)
    local = (triangles - pose[:3, 3]) @ pose[:3, :3]
    local = clip_plane(clip_plane(local, 2, .1, -1), 2, 2000, 1)
    if not len(local):
        return np.zeros((height, width), bool)
    mesh = local.reshape(-1, 3).astype(np.float32)
    scene = o3d.t.geometry.RaycastingScene(nthreads=threads)
    scene.add_triangles(o3d.core.Tensor(mesh), o3d.core.Tensor(np.arange(len(mesh), dtype=np.uint32).reshape(-1, 3)))
    result = scene.cast_rays(o3d.core.Tensor(rays), nthreads=threads)
    return np.isfinite(result['t_hit'].numpy())


def contours(mask, epsilon=1.):
    """External silhouettes only: omit internal parts and simplify subpixel noise."""
    import cv2
    raw, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in raw:
        if cv2.contourArea(contour) < 3:
            continue
        points = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(points) >= 3:
            result.append((points + .5).tolist())
    return result


def run(geometry, metadata, inspection, out, threads=4):
    start = time.monotonic()
    geometry, metadata, inspection, out = map(Path, (geometry, metadata, inspection, out))
    exported = json.loads(metadata.read_text())
    base = json.loads((inspection / 'inspection.json').read_text())
    if exported['geometry_sha256'] != digest(geometry):
        raise ValueError('Exported geometry fingerprint changed')
    if exported['source_scene_sha256'] != base['source_scene_sha256']:
        raise ValueError('Export and inspection use different saved scenes')
    if exported['cameras_sha256'] != base['cameras_sha256']:
        raise ValueError('Export and inspection camera provenance differs')
    if exported['frame'] != base['config'].get('model_frame', 1) or exported['excluded_objects'] != base['config'].get('exclude_objects', []):
        raise ValueError('Export and inspection frame/exclusions differ')
    if not np.allclose(exported['world_transform'], base['world_transform'], atol=1e-6, rtol=0):
        raise ValueError('Export and inspection world basis differs')
    if threads < 1:
        raise ValueError('threads must be positive')
    with np.load(geometry) as data:
        vertices, faces, face_ids = data['vertices'], data['faces'], data['face_object_id']
    transform = np.asarray(base['config']['model_to_world'])
    vertices = vertices @ transform[:3, :3].T + transform[:3, 3]
    groups = exported['object_groups']
    if len(groups) != len(exported['object_names']):
        raise ValueError('One explicit object group required per exported component')
    objects = {}
    for index, group in enumerate(groups):
        identity = group['id']
        if identity not in objects:
            objects[identity] = dict(group, color=object_color(identity), components=[])
        elif objects[identity]['root_name'] != group['root_name']:
            raise ValueError('Different roots share an instance_id: ' + identity)
        objects[identity]['components'].append(index)
    out.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'source_inspection': str(inspection.resolve()),
              'source_scene': exported['source_scene'], 'source_scene_sha256': exported['source_scene_sha256'],
              'input_hashes': {'geometry': digest(geometry), 'metadata': digest(metadata), 'inspection': digest(inspection/'inspection.json')},
              'objects': sorted(objects.values(), key=lambda x: x['id']), 'views': {},
              'policy': 'Independent per-object X-ray silhouettes of evaluated triangles, common camera and crop; internal edges and holes omitted.',
              'limits': ['Colors identify authored objects, not detected reference-video instances.',
                         'Objects may be occluded in reality; outlines deliberately ignore other objects and reference depth.',
                         'Contours simplified by 1 pixel; disconnected regions below 3 square pixels omitted.',
                         'Similar hues remain possible; IDs, labels and solo selection disambiguate them.',
                         'No geometry edits, new registration, source segmentation or source-fidelity acceptance.']}
    prepared = {key: vertices[faces[np.isin(face_ids, obj['components'])]] for key, obj in objects.items()}
    for name, view in base['views'].items():
        with Image.open(inspection / f'{name}_reference.png') as image:
            image = image.convert('RGB'); width, height = image.size
        result = dict(settings=view['settings'], camera_matrix_world=view['camera_matrix_world'],
                      size=[width, height], objects={})
        for key, triangles in prepared.items():
            mask = silhouette(triangles, view, width, height, threads)
            paths = contours(mask)
            result['objects'][key] = {'paths': paths, 'mask_pixels': int(mask.sum())}
        report['views'][name] = result
        draw = ImageDraw.Draw(image)
        for key, obj in objects.items():
            if not obj['semantic_class'].startswith('furniture/'):
                continue
            for path in result['objects'][key]['paths']:
                draw.line([tuple(p) for p in path + path[:1]], fill=tuple(obj['color']), width=2)
        image.save(out / f'{name}_furniture.png')
    report['seconds'] = time.monotonic() - start
    (out / 'objects.json').write_text(json.dumps(report, indent=2))
    write_report(out, report, inspection)
    from .overview import write_overviews
    from .overlay import write_report as write_inspection_report
    write_overviews(out, report, inspection)
    # Inspection may be immutable evidence from an earlier completed stage.
    # Publish the combined report beside new outlines, never overwrite its input.
    write_inspection_report(inspection, base, overview_dir=out, report_path=out/'comparison.html')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('geometry', 'metadata', 'inspection', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    report = run(**vars(args))
    print(json.dumps({'objects': len(report['objects']), 'views': len(report['views']), 'seconds': report['seconds']}))
