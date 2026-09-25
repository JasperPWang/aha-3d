"""Render selected diagnostic frames in a frozen authored room (Blender Python)."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender.body import import_cache


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def mesh_world(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        points = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get('co', points)
        matrix = np.asarray(evaluated.matrix_world)
        return points.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
    finally:
        evaluated.to_mesh_clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--body', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    started = time.monotonic()
    config = json.loads(args.config.read_text())
    if config.get('schema_version') != 1:
        raise ValueError('Unsupported preview config')
    source = Path(bpy.data.filepath).resolve(strict=True)
    scene_sha = digest(source)
    if scene_sha != config['scene_sha256']:
        raise ValueError('Loaded room differs from frozen source scene')
    body_sha = digest(args.body)
    data = dict(np.load(args.body, allow_pickle=False))
    if str(data['source_actor_id']) != config['actor_id']:
        raise ValueError('Wrong source actor')
    count = len(data['vertices'])
    if count != config['frames'] or abs(float(data['fps']) - config['fps']) > 1e-6:
        raise ValueError('Body and frozen source timing differ')
    if float(data.get('body_scale', 1.)) != 1.:
        raise ValueError('Preview expects unchanged native body dimensions')
    selection = json.loads(args.selection.read_text())['selected_frames']
    frames = sorted({row['source_frame'] for row in selection})
    if not frames or any(type(f) is not int or not 0 <= f < count for f in frames):
        raise ValueError('Selection contains invalid source frames')
    scene = bpy.context.scene
    if any(o.name.startswith('Person_') for o in scene.objects):
        raise ValueError('Load the frozen room-only scene for inspection')
    scene.frame_set(1)
    static = {o.name: mesh_world(o) for o in scene.objects if o.type == 'MESH'}
    args.output.mkdir(parents=True, exist_ok=False)
    body, _ = import_cache(args.body, person_id=int(config['person_id']), start=1)
    body.data.materials[0].diffuse_color = (.12, .22, .32, 1.)
    for obj in scene.objects:
        if any(obj.name.startswith(prefix) for prefix in config.get('hide_prefixes', [])):
            obj.hide_render = True
        if any(obj.name.startswith(prefix) for prefix in config.get('show_prefixes', [])):
            obj.hide_render = False
    camera_config = config['camera']
    camera_data = bpy.data.cameras.new('Inspection overview')
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    camera.location = camera_config['position']
    camera.rotation_euler = (Vector(camera_config['target']) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.lens = camera_config['lens']
    camera_data.clip_start, camera_data.clip_end = .025, 100.
    scene.camera = camera
    scene.frame_start, scene.frame_end = 1, count
    scene.render.fps = max(1, int(round(config['fps'])))
    scene.render.fps_base = scene.render.fps / config['fps']
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.render_aa = '8'
    scene.view_settings.view_transform = 'Standard'
    scene.frame_set(1)
    saved = args.output / 'candidate.blend'
    body_name = body.name
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    scene = bpy.context.scene
    body = bpy.data.objects[body_name]
    static_error = max((float(np.abs(mesh_world(bpy.data.objects[name]) - vertices).max())
                        for name, vertices in static.items()), default=0.)
    if static_error > 2e-6:
        raise ValueError('Saved static scene geometry changed')
    active = data.get('track_active', np.ones(count, bool))
    maximum = 0.
    for frame in range(count):
        scene.frame_set(frame + 1)
        if bool(body.hide_render) != (not bool(active[frame])):
            raise ValueError('Saved track visibility differs from source lifecycle')
        if active[frame]:
            maximum = max(maximum, float(np.abs(mesh_world(body) - data['vertices'][frame]).max()))
    if maximum > 1e-5:
        raise ValueError('Saved body differs from candidate geometry')
    import gpu
    gpu.init()
    renderer = dict(renderer=gpu.platform.renderer_get(), vendor=gpu.platform.vendor_get(),
                    version=gpu.platform.version_get())
    if config.get('expected_renderer') and config['expected_renderer'].lower() not in renderer['renderer'].lower():
        raise ValueError('Selected graphics backend differs from preview configuration')
    views = []
    for frame in frames:
        scene.frame_set(frame + 1)
        image = args.output / f'room_{frame:06d}.png'
        scene.render.filepath = str(image)
        bpy.ops.render.render(write_still=True)
        views.append(dict(source_frame=frame, path=str(image.resolve()), sha256=digest(image),
                          body_sha256=body_sha, scene_sha256=scene_sha, relation='same_candidate',
                          body_hidden=bool(body.hide_render)))
    if digest(source) != scene_sha or digest(args.body) != body_sha:
        raise ValueError('Frozen scene or body changed during rendering')
    report = dict(schema_version=1, scene_sha256=scene_sha, body_sha256=body_sha,
                  config_sha256=digest(args.config), selection_sha256=digest(args.selection),
                  source_scene=str(source), body_cache=str(args.body.resolve()),
                  saved_scene=str(saved.resolve()), saved_scene_sha256=digest(saved), views=views,
                  frames=count, active_meshes_verified=int(active.sum()), all_visibility_verified=True,
                  max_vertex_error_m=maximum, static_meshes_verified=len(static),
                  static_max_vertex_error_m=static_error, elapsed_seconds=time.monotonic()-started,
                  renderer=renderer, renderer_source_sha256=digest(__file__),
                  scope='Selected diagnostic room views; full saved motion verified, no full video or physical acceptance.')
    (args.output / 'preview.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'views'}))


if __name__ == '__main__':
    main()
