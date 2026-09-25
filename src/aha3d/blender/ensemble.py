"""Separate room, assemble declared people, and verify every baked person/camera."""
import argparse
from fractions import Fraction
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import bpy
import numpy as np
from mathutils import Matrix

from aha3d.blender.body import camera_matrices, import_cache, linear_keys
from aha3d.blender.stage import checks, gpu
from aha3d.config import path
from aha3d.io import digest, read, write
from aha3d.workflow.people import place_cache, validate_config
from aha3d.workflow.preflight import camera_report, pixel_aspect_pair


def bake_camera(scene, cache, t, size):
    with np.load(cache, allow_pickle=False) as z:
        poses, K = z['c2w'], z['K']
        if len(poses) != t['frames'] or len(K) != t['frames'] or not np.array_equal(z['image_size'], size):
            raise ValueError('Camera sample count or raster differs from ensemble')
        if not np.isfinite(poses).all() or not np.isfinite(K).all():
            raise ValueError('Nonfinite camera cache')
        if not np.allclose(np.diff(z['time_seconds']), 1 / float(Fraction(t['fps'])), atol=1e-7):
            raise ValueError('Camera cache cadence differs from ensemble')
    if not np.allclose(K[:, 0, 1], 0) or not np.allclose(K[:, 1, 0], 0):
        raise ValueError('Blender perspective camera cannot represent skew')
    cam = bpy.data.objects.new('Workflow reference camera', bpy.data.cameras.new('Workflow reference camera'))
    scene.collection.objects.link(cam); scene.camera = cam
    cam.rotation_mode = 'QUATERNION'; cam.data.sensor_fit = 'HORIZONTAL'; cam.data.sensor_width = 36
    cam.data.clip_start = .035; cam.data.clip_end = 150
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100; scene.render.use_border = False
    aspect = float(np.median(K[:, 0, 0] / K[:, 1, 1]))
    # Each axis is clamped to [1,200]; y=ratio silently failed for ratios below 1.
    scene.render.pixel_aspect_x, scene.render.pixel_aspect_y = pixel_aspect_pair(aspect)
    aspect = scene.render.pixel_aspect_y / scene.render.pixel_aspect_x
    width, height = size
    previous = None
    for frame, pose, k in zip(range(t['start'], t['end'] + 1), poses, K):
        mat = Matrix((pose @ np.diag([1, -1, -1, 1])).tolist())
        quat = mat.to_quaternion()
        if previous is not None and previous.dot(quat) < 0:
            quat.negate()
        previous = quat.copy()
        cam.location = mat.translation; cam.rotation_quaternion = quat
        cam.keyframe_insert('location', frame=frame); cam.keyframe_insert('rotation_quaternion', frame=frame)
        cam.data.lens = k[0, 0] * 36 / width
        cam.data.shift_x = (width / 2 - k[0, 2]) / width
        cam.data.shift_y = (k[1, 2] - height / 2) * aspect / width
        for prop in ('lens', 'shift_x', 'shift_y'):
            cam.data.keyframe_insert(prop, frame=frame)
    linear_keys(cam); linear_keys(cam.data)
    for marker in scene.timeline_markers:
        if marker.camera:
            marker.camera = cam
    return aspect


def camera_check(scene, cache, t, size, policy):
    with np.load(cache, allow_pickle=False) as z:
        poses, intrinsics = z['c2w'], z['K']
    if len(poses) != t['frames']:
        raise ValueError('Camera count changed')
    pose_error = intrinsic_error = 0.
    for i, frame in enumerate(range(t['start'], t['end'] + 1)):
        scene.frame_set(frame)
        k, rt, width, height, *_ = camera_matrices(scene, bpy.context.evaluated_depsgraph_get())
        if [width, height] != size or not np.isfinite(k).all() or not np.isfinite(rt).all():
            raise ValueError('Invalid evaluated camera or output raster')
        pose_error = max(pose_error, float(np.abs(np.linalg.inv(rt)-poses[i]).max()))
        intrinsic_error = max(intrinsic_error, float(np.abs(k-intrinsics[i]).max()))
    result = dict(frames_checked=t['frames'], maximum_c2w_element_error=pose_error,
        maximum_K_element_error_px=intrinsic_error, pixel_aspect_policy='fixed median fx/fy; keyed lens and shifts',
        pixel_aspect_xy=[scene.render.pixel_aspect_x, scene.render.pixel_aspect_y])
    if pose_error > policy.get('camera_pose_tolerance', 1e-4) or intrinsic_error > policy.get('intrinsics_tolerance_px', 2.):
        raise ValueError(f'Camera representation exceeds configured tolerance: {result}')
    return result


def remove_people(people):
    declared = {p['id'] for p in people}
    existing = {int(o['person_id']) for o in bpy.data.objects if 'person_id' in o}
    if existing - declared:
        raise ValueError(f'Unlisted people in source: {existing-declared}; declare them before room extraction')
    for person in people:
        prefix = f"Person_{person['id']:03d}"
        for obj in list(bpy.data.objects):
            if obj.name.startswith(prefix + '_'):
                bpy.data.objects.remove(obj, do_unlink=True)
        for col in list(bpy.data.collections):
            if col.name == prefix:
                bpy.data.collections.remove(col)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True); p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--stage', choices=['room', 'assemble', 'verify'], required=True)
    p.add_argument('--assembly', type=Path, help='Assembly output directory for saved-scene verification')
    p.add_argument('--preview', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    cfg = read(a.config); t = validate_config(cfg); scene = bpy.context.scene
    if not bpy.data.filepath or bpy.data.libraries:
        raise ValueError('Open a saved source with localized libraries')
    if any(im.source == 'FILE' and im.filepath and not im.packed_file for im in bpy.data.images):
        raise ValueError('Pack file textures in source first')
    source = Path(bpy.data.filepath)
    if abs(scene.render.fps / scene.render.fps_base - float(Fraction(t['fps']))) > 1e-4:
        raise ValueError('Source timing differs; explicitly retime existing animation first')
    policy = {'collisions': 'report', 'sample_frames': 'all', **cfg.get('validation', {})}
    camera = path(a.root, cfg['camera']) if cfg.get('camera') else None
    preflight = None
    if camera:
        with np.load(camera, allow_pickle=False) as data:
            preflight = camera_report(data, t, cfg['image_size'], policy.get('intrinsics_tolerance_px', 2.))
        if preflight['status'] != 'passed':
            raise ValueError(f'Camera preflight needs review before scene mutation: {preflight}')
    a.out.mkdir(parents=True, exist_ok=False)
    report = dict(schema_version=1, stage=a.stage, source=str(source), source_sha256=digest(source),
        config=cfg, config_sha256=digest(a.config), code_sha256=digest(__file__), timing=t, people={}, camera=None)
    report['camera_preflight'] = preflight
    if a.stage == 'verify':
        if not a.assembly:
            p.error('--assembly is required for verify')
        assembly = read(a.assembly / 'assembly.json')
        if assembly['config_sha256'] != digest(a.config):
            raise ValueError('Verification config differs from assembly')
        if scene.frame_start != t['start'] or scene.frame_end != t['end']:
            raise ValueError('Saved timeline differs')
        actual = [int(o['person_id']) for o in scene.objects if 'person_id' in o]
        if len(actual) != len(cfg['people']) or set(actual) != {p['id'] for p in cfg['people']}:
            raise ValueError('Saved person inventory differs')
        if camera and digest(camera) != assembly['camera']['input_sha256']:
            raise ValueError('Camera cache changed after assembly')
        for person in cfg['people']:
            name = f"Person_{person['id']:03d}_Body"; body = bpy.data.objects.get(name)
            if body is None or body.type != 'MESH':
                raise ValueError(f'Missing baked body mesh: {name}')
            recorded = assembly['people'][str(person['id'])]; cache = a.assembly / recorded['cache']
            if digest(cache) != recorded['cache_sha256']:
                raise ValueError('Placed body cache changed after assembly')
            with np.load(cache, allow_pickle=False) as z:
                data = {k: z[k] for k in z.files}
            folder = a.out / f"person_{person['id']:03d}"; folder.mkdir()
            report['people'][str(person['id'])] = checks(scene, body, data, {'timing': t, 'validation': policy}, folder)
            error = 0.
            for frame in report['people'][str(person['id'])]['sampled_frames']:
                scene.frame_set(frame)
                evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
                error = max(error, float(np.abs(np.asarray(evaluated.matrix_world)-recorded['matrix_world']).max()))
            if error > 1e-5:
                raise ValueError('Saved whole-body placement changed')
            report['people'][str(person['id'])]['placement_matrix_max_error'] = error
    else:
        remove_people(cfg['people'])
        scene.frame_start, scene.frame_end = t['start'], t['end']
        scene.render.resolution_x, scene.render.resolution_y = cfg['image_size']
        scene.render.resolution_percentage = 100
        if camera:
            bake_camera(scene, camera, t, cfg['image_size'])
        if a.stage == 'assemble':
            for person in cfg['people']:
                original = path(a.root, person['cache'])
                with np.load(original, allow_pickle=False) as z:
                    data, matrix = place_cache({k: z[k] for k in z.files}, person, t)
                cache = a.out / f"person_{person['id']:03d}.npz"
                np.savez_compressed(cache, **data)
                body, _ = import_cache(cache, person['id'], t['start'], matrix[:3, 3], person.get('yaw', 0))
                body['role'] = person['label']; body['motion_provenance'] = 'Generated approximate action; no identity fitting or post-generation pose/facing edits'
                report['people'][str(person['id'])] = dict(label=person['label'], object=body.name,
                    input_cache=str(original), input_sha256=digest(original), cache=cache.name,
                    cache_sha256=digest(cache), matrix_world=matrix.tolist(), scale=person.get('scale', 1),
                    ground_z=person.get('ground_z'), z_offset=person.get('z_offset', 0.))
    if camera:
        report['camera'] = camera_check(scene, camera, t, cfg['image_size'], policy)
        report['camera']['input_sha256'] = digest(camera)
    report['no_linked_libraries'] = not bool(bpy.data.libraries)
    report['status'] = 'passed'; scene.frame_set(t['start'])
    if a.stage != 'verify':
        bpy.ops.wm.save_as_mainfile(filepath=str(a.out / 'scene.blend'))
    write(a.out / ('assembly.json' if a.stage == 'assemble' else a.stage + '.json'), report)
    if a.preview:
        from aha3d.blender.rendering import configure_render
        renderer = configure_render(scene, 'preserve', 8, 'eevee')
        preview = a.out / 'previews'; preview.mkdir()
        for frame in cfg.get('preview_frames', [t['start'], t['end']]):
            scene.frame_set(frame); scene.render.filepath = str(preview / f'frame_{frame:06d}.png')
            bpy.ops.render.render(write_still=True)
        write(preview / 'render.json', {'renderer': renderer, 'frames': cfg.get('preview_frames', [t['start'], t['end']])})


if __name__ == '__main__':
    main()
