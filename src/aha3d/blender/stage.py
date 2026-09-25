"""Generic assembly, saved-scene verification and resumable rendering in Blender."""
import argparse
from fractions import Fraction
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from aha3d.blender.body import camera_matrices, export_tracking, import_cache, project, track_active_mask
from aha3d.io import digest, read, signature, write
from aha3d.pipeline.runner import artifact


def gpu(scene):
    scene.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'OPTIX'
    selected = [d.name for d in prefs.devices if d.use]
    if not selected:
        raise RuntimeError('No allocated OptiX device available')
    scene.cycles.device = 'GPU'
    scene.render.use_persistent_data = True
    return selected


def mesh_arrays(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        co = np.empty((len(mesh.vertices), 3), np.float32)
        mesh.vertices.foreach_get('co', co.ravel())
        mesh.calc_loop_triangles()
        faces = np.array([t.vertices[:] for t in mesh.loop_triangles], np.int32)
        ids = np.arange(len(co), dtype=np.int32)
        if 'vertex_id' in mesh.attributes:
            mesh.attributes['vertex_id'].data.foreach_get('value', ids)
        return co, faces, np.array(evaluated.matrix_world), ids
    finally:
        evaluated.to_mesh_clear()


def sample_frames(recipe):
    timing = recipe['timing']
    selected = recipe['validation'].get('sample_frames')
    if selected == 'all':
        return list(range(timing['start'], timing['end'] + 1))
    return selected or sorted(set(np.linspace(timing['start'], timing['end'], min(5, timing['frames']), dtype=int).tolist()))


def camera_export(scene, out, recipe):
    matrices, intrinsics = [], []
    timing = recipe['timing']
    for frame in range(timing['start'], timing['end'] + 1):
        scene.frame_set(frame)
        K, rt, width, height, near, far = camera_matrices(scene, bpy.context.evaluated_depsgraph_get())
        if not np.isfinite(K).all() or not np.allclose(rt[:3, :3] @ rt[:3, :3].T, np.eye(3), atol=1e-5):
            raise ValueError('Invalid camera calibration')
        matrices.append(rt); intrinsics.append(K)
    np.savez_compressed(out / 'camera.npz', K=np.array(intrinsics), world_to_camera=np.array(matrices),
        camera_to_world=np.linalg.inv(np.array(matrices)), frames=np.arange(timing['start'], timing['end'] + 1),
        time_seconds=np.arange(timing['frames']) / float(Fraction(timing['fps'])), image_size=[width, height])


def checks(scene, body, data, recipe, out, save_samples=True):
    chosen = sample_frames(recipe)
    positions, camera_samples, collisions, floor, fractions = [], [], [], [], []
    max_cache_error = 0.
    activity = track_active_mask(data.get('track_active'), len(data['vertices'])) if data is not None else None
    sampled_active = []
    for frame in chosen:
        scene.frame_set(frame); dg = bpy.context.evaluated_depsgraph_get()
        K, rt, width, height, near, far = camera_matrices(scene, dg)
        if save_samples:
            camera_samples.append(rt)
        if body is None:
            continue
        index = frame - recipe['timing']['start']
        active = bool(activity[index]) if activity is not None else not body.hide_render
        if activity is not None and body.hide_render == active:
            raise ValueError('Body lifecycle visibility differs from cache')
        sampled_active.append(active)
        if not active:
            if save_samples:
                positions.append(np.full((len(body.data.vertices),3),np.nan))
            continue
        local, faces, matrix, ids = mesh_arrays(body, dg)
        world = local @ matrix[:3, :3].T + matrix[:3, 3]
        if not np.isfinite(world).all():
            raise ValueError('Nonfinite animated body')
        if data is not None:
            index = frame - recipe['timing']['start']
            if not np.array_equal(faces, data['faces']) or not np.array_equal(ids, data['vertex_ids']):
                raise ValueError('Saved body topology/IDs differ from its cache')
            max_cache_error = max(max_cache_error, float(np.abs(local - data['vertices'][index]).max()))
        if save_samples:
            positions.append(world)
        floor.append(float(world[:, 2].min()))
        uv, depth = project(world, K, rt)
        valid = (depth >= near) & (depth <= far) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
        fractions.append(float(valid.mean()))
        if recipe['validation']['collisions'] == 'off':
            continue
        low, high = world.min(0), world.max(0)
        body_tree = None
        for instance in dg.object_instances:
            other = instance.object
            if other.type != 'MESH' or other.original == body or other.hide_render:
                continue
            if instance.is_instance and instance.parent and instance.parent.hide_render:
                continue
            if any(c.hide_render for c in other.original.users_collection):
                continue
            transform = np.array(instance.matrix_world)
            corners = np.asarray(other.bound_box) @ transform[:3, :3].T + transform[:3, 3]
            lo, hi = corners.min(0), corners.max(0)
            if not (np.all(hi >= low) and np.all(lo <= high)):
                continue
            mesh = other.to_mesh()
            try:
                co = np.array([v.co[:] for v in mesh.vertices]) @ transform[:3, :3].T + transform[:3, 3]
                polygons = [list(p.vertices) for p in mesh.polygons]
                if not polygons:
                    continue
                if body_tree is None:
                    body_tree = BVHTree.FromPolygons(world.tolist(), faces.tolist(), all_triangles=True)
                hits = body_tree.overlap(BVHTree.FromPolygons(co.tolist(), polygons))
                if hits:
                    collisions.append({'frame': frame, 'object': other.name, 'triangle_pairs': len(hits)})
            finally:
                other.to_mesh_clear()
    if max_cache_error > 1e-5:
        raise ValueError(f'Body/cache mismatch: {max_cache_error} m')
    report = {'frames': recipe['timing']['frames'], 'fps': recipe['timing']['fps'], 'sampled_frames': chosen,
        'body_object': body.name if body else None, 'cache_maximum_error_m': max_cache_error,
        'furniture_intersections': collisions, 'floor_min_z_range_m': [min(floor), max(floor)] if floor else None,
        'minimum_body_in_frame_fraction': min(fractions) if fractions else None,
        'active_sampled_frames': [int(f) for f, ok in zip(chosen, sampled_active) if ok],
        'inactive_sampled_frames': [int(f) for f, ok in zip(chosen, sampled_active) if not ok],
        'limits': 'Integer sampled-frame triangle intersections, no inter-frame/self-collision check. Frustum flags do not test occlusion.'}
    write(out / 'scene_validation.json', report)
    if collisions and recipe['validation']['collisions'] == 'error':
        raise ValueError('Body intersects room geometry; see scene_validation.json')
    if fractions and min(fractions) < recipe['validation'].get('minimum_in_frame', 0):
        raise ValueError('Body falls outside configured framing threshold')
    if floor and min(floor) < recipe['validation'].get('floor_min', -float('inf')):
        raise ValueError('Body falls below configured floor threshold')
    if save_samples:
        extras = {'track_active': np.asarray(sampled_active,bool)} if sampled_active and not all(sampled_active) else {}
        np.savez_compressed(out / 'verification_samples.npz', frames=chosen, world=np.array(positions), camera=np.array(camera_samples), **extras)
    return report


def assemble(run, recipe):
    scene = bpy.context.scene
    timing, rendering, config = recipe['timing'], recipe['render'], recipe['body']
    original_engine = scene.render.engine
    if bpy.data.libraries or any(image.source == 'FILE' and image.filepath and not image.packed_file for image in bpy.data.images):
        raise ValueError('Source must localize linked libraries and pack file textures before preparation')
    out = run / 'stages/assemble'; out.mkdir(parents=True, exist_ok=True)
    target_fps = float(Fraction(timing['fps']))
    current_fps = scene.render.fps / scene.render.fps_base
    animated = any(o.animation_data and o.animation_data.action for o in scene.objects)
    if animated and abs(current_fps - target_fps) > 1e-4:
        raise ValueError('Existing animated source timing differs from recipe; provide an explicitly retimed source')
    scene.render.fps = max(1, round(target_fps)); scene.render.fps_base = scene.render.fps / target_fps
    scene.frame_start, scene.frame_end = timing['start'], timing['end']
    scene.frame_set(timing['start'])
    for name in recipe['assembly'].get('hide_collections', []):
        matches = [c for c in bpy.data.collections if c.name.startswith(name)]
        if not matches:
            raise ValueError(f'Missing collection: {name}')
        for collection in matches:
            collection.hide_render = True
    if recipe['assembly'].get('close_cabinets'):
        for obj in scene.objects:
            if obj.name.startswith(('CTRL |', 'CABINET MASTER')):
                if obj.animation_data:
                    obj.animation_data.action = None
                for prop in ('Demo', 'Open all', 'Open', 'Auto open', 'Stool clearance'):
                    if prop in obj:
                        obj[prop] = 0.
    camera = recipe['assembly'].get('camera')
    if camera:
        cam = bpy.data.objects.new('Pipeline camera', bpy.data.cameras.new('Pipeline camera'))
        scene.collection.objects.link(cam)
        cam.location = camera['location']
        cam.rotation_euler = (Vector(camera['target']) - cam.location).to_track_quat('-Z', 'Y').to_euler()
        cam.data.lens = camera['lens']; cam.data.clip_start = .05; cam.data.clip_end = 150
        scene.camera = cam
        for marker in scene.timeline_markers:
            if marker.camera:
                marker.camera = cam
    if scene.camera is None:
        raise ValueError('Source needs an active camera or an explicit camera recipe')
    body_name = config.get('object_name', 'Person_001_Body')
    body = bpy.data.objects.get(body_name)
    data = None
    cache_path = artifact(run, recipe, 'body')
    if cache_path.exists():
        with np.load(cache_path, allow_pickle=False) as src:
            data = {k: src[k] for k in src.files}
        if len(data['vertices']) != timing['frames']:
            raise ValueError('Body cache frame count differs from recipe')
        if abs(float(data['fps']) - target_fps) > 1e-4 and config.get('cache_timing') != 'match_scene_frames':
            raise ValueError('Cache timing differs; resample rotations before skinning or explicitly adopt already-baked scene timing')
        data['fps'] = np.float64(target_fps); data['time_seconds'] = np.arange(timing['frames']) / target_fps
    if config['mode'] != 'keep':
        for obj in list(scene.objects):
            if obj.name.startswith('Person_001'):
                bpy.data.objects.remove(obj, do_unlink=True)
        for collection in list(bpy.data.collections):
            if collection.name.startswith('Person_001'):
                bpy.data.collections.remove(collection)
        if data is None:
            raise ValueError('New body requires a skinned cache')
        if config.get('ground_clearance') is not None:
            correction = config['ground_clearance'] - data['vertices'][:, :, 2].min(axis=1)
            data['vertices'][:, :, 2] += correction[:, None]
            data['joints'][:, :, 2] += correction[:, None]
            data['vertical_ground_correction_m'] = correction
        np.savez_compressed(out / 'body_cache.npz', **data)
        offset = np.array(config.get('offset', [0, 0, 0]), dtype=float)
        if config.get('anchor') == 'first_pelvis_xy':
            angle = np.radians(config.get('yaw', 0)); x, y = data['joints'][0, 0, :2]
            offset[:2] -= [np.cos(angle) * x - np.sin(angle) * y, np.sin(angle) * x + np.cos(angle) * y]
        body, data = import_cache(out / 'body_cache.npz', start=timing['start'], offset=offset.tolist(), yaw=config.get('yaw', 0))
        scene.frame_start, scene.frame_end = timing['start'], timing['end']
    from aha3d.blender.rendering import configure_render
    renderer = configure_render(scene, rendering['mode'], rendering['samples'], rendering.get('engine', 'auto'))
    devices = renderer['gpu_devices']
    scene.cycles.seed = rendering['seed']
    scene.render.resolution_x, scene.render.resolution_y = rendering['width'], rendering['height']
    scene.render.resolution_percentage = 100
    scene.render.use_border = False; scene.render.use_motion_blur = False
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'; scene.render.film_transparent = False
    for field in ('view_transform', 'look', 'exposure'):
        if field in rendering:
            setattr(scene.view_settings, field, rendering[field])
    if body is not None and data is None:
        verts = []
        for frame in range(timing['start'], timing['end'] + 1):
            scene.frame_set(frame)
            co, faces, matrix, ids = mesh_arrays(body, bpy.context.evaluated_depsgraph_get())
            verts.append(co)
        data = {'vertices': np.array(verts), 'faces': faces, 'vertex_ids': ids,
                'joints': np.empty((timing['frames'], 0, 3)), 'joint_names': np.array([], dtype='U1'),
                'fps': np.float64(target_fps), 'time_seconds': np.arange(timing['frames']) / target_fps}
        body['cache_path'] = str(run / 'inputs/source.blend')
        body['person_id'] = int(body.get('person_id', 1))
    if body is not None and data is not None:
        np.savez_compressed(out / 'body_cache.npz', **data)
    checks(scene, body, data, recipe, out)
    if body is not None:
        export_tracking(body, data, out / 'tracks.npz', timing['start'])
    camera_export(scene, out, recipe)
    # Deliverable source dependencies must be contained in the saved copy.
    if any(lib for lib in bpy.data.libraries):
        raise ValueError('Source contains linked libraries; localize an authorized source copy before running')
    bpy.ops.file.pack_all()
    scene.frame_set(timing['start']); scene.render.filepath = str(run / 'stages/render/frames/frame_')
    scene['indoor_recipe'] = recipe['id']; scene['indoor_run'] = run.name
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'scene.blend'))
    write(out / 'assembly.json', {'gpu_devices': devices, 'materials_preserved': True,
        'source_engine': original_engine, 'render_engine': scene.render.engine, 'renderer': renderer,
        'color_management': {field: getattr(scene.view_settings, field) for field in ('view_transform', 'look', 'exposure')},
        'body_joints': len(data['joint_names']) if data is not None else None})


def verify(run, recipe):
    scene = bpy.context.scene; timing = recipe['timing']
    body = bpy.data.objects.get(recipe['body'].get('object_name', 'Person_001_Body'))
    with np.load(run / 'stages/assemble/verification_samples.npz', allow_pickle=False) as expected:
        # NpzFile does not cache members: indexing it in the frame loop repeatedly
        # decompresses the complete camera/vertex arrays, even for one frame.
        frames = expected['frames']
        cameras = expected['camera'] if len(frames) else None
        worlds = expected['world'] if body is not None and len(frames) else None
        activity = expected['track_active'] if 'track_active' in expected.files else None
    worst, camera_error = 0., 0.
    for i, frame in enumerate(frames):
        scene.frame_set(int(frame)); dg = bpy.context.evaluated_depsgraph_get()
        K, rt, *_ = camera_matrices(scene, dg)
        camera_error = max(camera_error, float(np.abs(rt - cameras[i]).max()))
        if body is not None:
            if activity is not None:
                if body.hide_render == bool(activity[i]) or body.hide_viewport == bool(activity[i]):
                    raise ValueError('Saved lifecycle visibility differs from assembled animation')
                if not activity[i]:
                    continue
            co, faces, transform, ids = mesh_arrays(body, dg)
            world = co @ transform[:3, :3].T + transform[:3, 3]
            worst = max(worst, float(np.abs(world - worlds[i]).max()))
    if worst > 1e-5 or camera_error > 1e-5:
        raise ValueError('Saved animation differs from assembled animation')
    if scene.frame_start != timing['start'] or scene.frame_end != timing['end'] or abs(scene.render.fps / scene.render.fps_base - float(Fraction(timing['fps']))) > 1e-4:
        raise ValueError('Saved scene timing mismatch')
    if bpy.data.libraries or any(image.source == 'FILE' and image.filepath and not image.packed_file for image in bpy.data.images):
        raise ValueError('Saved scene has external library/texture dependencies')
    if body is not None and (body.data.shape_keys is None or any(m.type == 'ARMATURE' for m in body.modifiers)):
        raise ValueError('Delivered body must use baked playback')
    write(run / 'stages/verify/validation.json', {'reopen_pass': True, 'maximum_vertex_error_m': worst,
          'maximum_camera_error': camera_error, 'frames': timing['frames'], 'fps': timing['fps'], 'self_contained_playback': True})


def render(run, recipe, budget):
    from aha3d.blender.rendering import configure_render
    scene = bpy.context.scene
    # Reopened scenes already carry mode, overrides and color management. Only
    # reconfigure the saved engine's process-local devices and sampling here.
    renderer = configure_render(scene, 'preserve', recipe['render']['samples'])
    out = run / 'stages/render'; folder = out / 'frames'; folder.mkdir(parents=True, exist_ok=True)
    receipt_path = out / 'frames.json'
    receipt = read(receipt_path) if receipt_path.exists() else {}
    settings = signature({'source': digest(run / 'stages/assemble/scene.blend'), 'render': recipe['render'], 'renderer': renderer})
    if receipt and receipt['settings'] != settings:
        raise ValueError('Existing frames belong to another scene/render configuration')
    receipt = receipt or {'settings': settings, 'frames': {}}
    selected = recipe['render'].get('stills') if recipe['render']['kind'] == 'stills' else list(range(recipe['timing']['start'], recipe['timing']['end'] + 1))
    started = time.monotonic(); rendered = reused = 0
    for frame in selected:
        target = folder / f'frame_{frame:06d}.png'
        if target.is_file() and receipt['frames'].get(str(frame)) == digest(target):
            reused += 1
            continue
        if budget is not None and rendered >= budget:
            print('FRAME_BUDGET_REACHED', rendered, 'new frames;', reused, 'reused', flush=True)
            os._exit(75)
        temporary = folder / f'frame_{frame:06d}.partial.png'
        scene.frame_set(frame); scene.render.filepath = str(temporary)
        bpy.ops.render.render(write_still=True)
        temporary.replace(target)
        receipt['frames'][str(frame)] = digest(target); write(receipt_path, receipt)
        rendered += 1
        if rendered % 15 == 0:
            print('RENDER_PROGRESS', frame, '/', selected[-1], flush=True)
    for temporary in folder.glob('*.partial.png'):
        temporary.unlink()
    write(out / 'validation.json', {'complete': True, 'frames': len(selected), 'new_frames': rendered,
          'reused_frames': reused, 'seconds': time.monotonic() - started, 'fps': recipe['timing']['fps'], 'renderer': renderer})


def main():
    p = argparse.ArgumentParser(); p.add_argument('--run', required=True, type=Path)
    p.add_argument('--stage', choices=['assemble', 'verify', 'render'], required=True); p.add_argument('--frame-budget', type=int)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    recipe = read(args.run / 'snapshot/recipe.json')
    if args.stage == 'assemble':
        assemble(args.run, recipe)
    elif args.stage == 'verify':
        verify(args.run, recipe)
    else:
        render(args.run, recipe, args.frame_budget)


if __name__ == '__main__':
    main()
