"""Import mesh cache into Blender and optionally export camera point tracks.

blender -b room.blend --python import_body_blender.py -- --cache body.npz --out new.blend --tracking tracks.npz
Caches are baked with shape keys; no startup scripts, handlers, Torch or add-on required.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix


def linear_keys(id_block):
    action = id_block.animation_data.action
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = 'LINEAR'


def import_cache(path, person_id=1, start=1, offset=(0, 0, 0), yaw=0):
    with np.load(path, allow_pickle=False) as source:
        data = {key: source[key] for key in source.files}
    if int(data['schema_version']) != 1:
        raise ValueError('Unsupported cache schema')
    verts, faces = data['vertices'], data['faces']
    fps = float(data['fps'])
    if verts.ndim != 3 or verts.shape[-1] != 3 or len(verts) < 1 or not np.isfinite(verts).all():
        raise ValueError('Expected finite vertices [T,V,3]')
    if faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer) or faces.min() < 0 or faces.max() >= verts.shape[1]:
        raise ValueError('Invalid triangle faces')
    if not 1 <= person_id <= 32767:
        raise ValueError('person_id must be in [1,32767] for Blender object index')
    if len(np.unique(data['vertex_ids'])) != verts.shape[1]:
        raise ValueError('Vertex IDs must be unique and match the vertex count')
    scene = bpy.context.scene
    scene_fps = scene.render.fps / scene.render.fps_base
    # Existing room camera/cabinet timing must not be silently changed.
    if bpy.data.filepath and abs(scene_fps - fps) > 1e-6:
        raise ValueError(f'Room is {scene_fps} fps but body is {fps}; resample cache to the room fps first')
    if fps <= 0 or abs(round(fps) - fps) > 1e-6:
        raise ValueError('This importer currently requires integer cache fps')
    scene.render.fps, scene.render.fps_base = int(round(fps)), 1.0
    collection = bpy.data.collections.new(f'Person_{person_id:03d}')
    scene.collection.children.link(collection)
    placement = bpy.data.objects.new(f'Person_{person_id:03d}_Placement', None)
    collection.objects.link(placement)
    placement.location = offset
    placement.rotation_euler[2] = math.radians(yaw)
    mesh = bpy.data.meshes.new(f'Person_{person_id:03d}_SMPLX')
    mesh.from_pydata(verts[0].tolist(), [], faces.tolist())
    mesh.update()
    body = bpy.data.objects.new(f'Person_{person_id:03d}_Body', mesh)
    collection.objects.link(body)
    body.parent = placement
    body['person_id'] = person_id
    body['cache_path'] = str(Path(path).resolve())
    body['surface_model_type'] = str(data['surface_model_type'])
    body['tracking_note'] = 'Stable topology; camera in_frame flag does not test occlusion'
    body.pass_index = person_id
    ids = mesh.attributes.new('vertex_id', 'INT', 'POINT')
    ids.data.foreach_set('value', np.asarray(data['vertex_ids'], dtype=np.int32))
    for poly in mesh.polygons:
        poly.use_smooth = True
    mat = bpy.data.materials.new(f'Person_{person_id:03d}_Clay')
    mat.diffuse_color = (0.38, 0.58, 0.73, 1)
    body.data.materials.append(mat)
    body.shape_key_add(name='Basis')
    for t, frame_verts in enumerate(verts):
        key = body.shape_key_add(name=f'Frame_{start+t:05d}')
        key.data.foreach_set('co', np.ascontiguousarray(frame_verts, dtype=np.float32).ravel())
        for frame, value in ((start+t-1, 0.), (start+t, 1.), (start+t+1, 0.)):
            key.value = value
            key.keyframe_insert('value', frame=frame)
    linear_keys(mesh.shape_keys)
    scene.frame_start = min(scene.frame_start, start)
    scene.frame_end = max(scene.frame_end if bpy.data.filepath else 0, start + len(verts) - 1)
    scene.frame_set(start)
    bpy.context.view_layer.update()
    return body, data


def camera_matrices(scene, depsgraph):
    if scene.render.use_border:
        raise ValueError('Disable render border before exporting full-frame tracking')
    camera = scene.camera.evaluated_get(depsgraph)
    if camera.data.type != 'PERSP':
        raise ValueError('Tracking exporter currently supports perspective cameras only')
    width = int(scene.render.resolution_x * scene.render.resolution_percentage / 100)
    height = int(scene.render.resolution_y * scene.render.resolution_percentage / 100)
    p = np.array(camera.calc_matrix_camera(depsgraph, x=width, y=height,
        scale_x=scene.render.pixel_aspect_x, scale_y=scene.render.pixel_aspect_y))
    k = np.array([[p[0, 0]*width/2, 0, (1-p[0, 2])*width/2],
                  [0, p[1, 1]*height/2, (1+p[1, 2])*height/2], [0, 0, 1]])
    # OpenCV camera: +X right, +Y down, +Z forward.
    world_to_cv = np.diag([1., -1., -1., 1.]) @ np.array(camera.matrix_world.normalized().inverted())
    return k, world_to_cv, width, height, camera.data.clip_start, camera.data.clip_end


def project(points, k, rt):
    camera_points = points @ rt[:3, :3].T + rt[:3, 3]
    h = camera_points @ k.T
    pixels = np.full((len(points), 2), np.nan, dtype=np.float64)
    valid = np.abs(h[:, 2]) > 1e-10
    pixels[valid] = h[valid, :2] / h[valid, 2:3]
    return pixels, camera_points[:, 2]


def export_tracking(body, data, path, start=1):
    scene = bpy.context.scene
    if scene.camera is None:
        raise ValueError('Scene needs an active camera for camera point tracks')
    samples = {key: [] for key in ['vertices_world', 'joints_world', 'vertices_uv', 'joints_uv', 'vertices_depth', 'joints_depth', 'vertices_in_frame', 'joints_in_frame', 'K', 'world_to_camera_cv']}
    for t in range(len(data['vertices'])):
        scene.frame_set(start+t)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj = body.evaluated_get(depsgraph)
        mesh = obj.to_mesh()
        try:
            if len(mesh.vertices) != len(data['vertex_ids']):
                raise ValueError('A topology-changing modifier invalidated vertex correspondence')
            verts = np.empty(len(mesh.vertices)*3, dtype=np.float32)
            mesh.vertices.foreach_get('co', verts)
            world = np.array(obj.matrix_world)
            verts = verts.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
        finally:
            obj.to_mesh_clear()
        joints = data['joints'][t] @ world[:3, :3].T + world[:3, 3]
        k, rt, width, height, near, far = camera_matrices(scene, depsgraph)
        for prefix, points in [('vertices', verts), ('joints', joints)]:
            uv, depth = project(points, k, rt)
            in_frame = (depth >= near) & (depth <= far) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
            samples[prefix+'_world'].append(points)
            samples[prefix+'_uv'].append(uv)
            samples[prefix+'_depth'].append(depth)
            samples[prefix+'_in_frame'].append(in_frame)
        samples['K'].append(k)
        samples['world_to_camera_cv'].append(rt)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **{k: np.asarray(v) for k, v in samples.items()},
        person_id=np.int32(body['person_id']), vertex_ids=data['vertex_ids'], faces=data['faces'],
        joint_names=data['joint_names'], fps=data['fps'], time_seconds=data['time_seconds'],
        blender_frames=np.arange(start, start+len(data['vertices'])), image_size=np.array([width, height]))
    path.with_suffix('.json').write_text(json.dumps({
        'units': 'meters', 'world': 'Blender Z-up', 'camera': 'OpenCV +X right, +Y down, +Z forward',
        'pixels': 'top-left image boundary (0,0); pixel centers (i+0.5,j+0.5)',
        'in_frame': 'Frustum test only. Occlusion, self-occlusion, material transparency and lens distortion are NOT tested.',
        'source': str(Path(data.get('source', body['cache_path'])).resolve()),
        'frames': len(data['vertices']), 'person_id': body['person_id'],
        'accuracy': 'Exact baked mesh at integer sample frames. No manual deformation/retargeting is assumed.'
    }, indent=2), encoding='utf-8')
    scene.frame_set(start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--tracking', type=Path)
    parser.add_argument('--person-id', type=int, default=1)
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--offset', nargs=3, type=float, default=[0, 0, 0])
    parser.add_argument('--yaw', type=float, default=0)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if bpy.data.filepath and args.out.resolve() == Path(bpy.data.filepath).resolve():
        parser.error('Choose a new output .blend to preserve the source room')
    body, data = import_cache(args.cache, args.person_id, args.start, args.offset, args.yaw)
    if args.tracking:
        export_tracking(body, data, args.tracking, args.start)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
    print(f'Imported {len(data["vertices"])} mesh frames to {args.out}', flush=True)


if __name__ == '__main__':
    main()
