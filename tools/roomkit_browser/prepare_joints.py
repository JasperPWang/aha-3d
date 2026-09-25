"""Add explicitly reviewed hinges/sliders to a distinct saved Blender scene.

Run with Blender --python-exit-code 1 --python prepare_joints.py --
--source input.blend --recipe recipe.json --out output.blend.
Recipes enumerate root, id, parts, pivot, axis and angle_degrees (or travel_m).
Optional replacements enumerate solid objects to remove and exact shell boxes
(name, root, material, center, size). No membership is inferred from names.
The recipe must record the source size and mtime_ns. Validation compares retained
world geometry and all source camera samples, without computing file hashes.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from aha3d.blender import roomkit as rk


def identity(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def geometry(scene):
    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in scene.objects:
        if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT') or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            result[obj.name] = np.asarray([evaluated.matrix_world @ v.co for v in mesh.vertices])
        finally:
            evaluated.to_mesh_clear()
    return result


def cameras(scene):
    result = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        cam = scene.camera
        result.append((frame, cam.name, list(cam.matrix_world), cam.data.lens,
                       cam.data.shift_x, cam.data.shift_y, cam.data.sensor_width,
                       cam.data.sensor_height, cam.data.sensor_fit))
    return repr(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'recipe', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.source.resolve() == args.out.resolve() or args.out.exists():
        raise ValueError('Output must be a distinct new scene')
    recipe = json.loads(args.recipe.read_text())
    source_identity = identity(args.source)
    if source_identity != recipe['source_identity']:
        raise ValueError('Source size/mtime differs from reviewed recipe')
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene = bpy.context.scene
    timing = (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base)
    original_cameras = cameras(scene)
    frames = sorted({scene.frame_start, (scene.frame_start + scene.frame_end) // 2, scene.frame_end})
    before = {}
    for frame in frames:
        scene.frame_set(frame)
        before[frame] = geometry(scene)
    scene.frame_set(scene.frame_start)
    removed = set()
    for replacement in recipe.get('replacements', []):
        for name in replacement['remove']:
            if name in removed:
                raise ValueError('Duplicate replacement: ' + name)
            removed.add(name)
            bpy.data.objects.remove(scene.objects[name], do_unlink=True)
        for box in replacement['boxes']:
            if box['name'] in scene.objects:
                raise ValueError('Duplicate shell name: ' + box['name'])
            root = scene.objects[box['root']]
            obj = rk.box(box['name'], box['center'], box['size'],
                         bpy.data.materials[box['material']], edge=box.get('bevel', .003))
            rk.parent_keep_world(obj, root)
    used = set()
    controls = []
    for joint in recipe['joints']:
        root = scene.objects[joint['root']]
        if not root.get('instance_id'):
            raise ValueError('Joint root requires a semantic instance_id')
        parts = [scene.objects[name] for name in joint['parts']]
        for part in parts:
            if part.name in used or part not in root.children_recursive:
                raise ValueError('Duplicate or foreign joint member: ' + part.name)
            used.add(part.name)
        ctrl = rk.rig_parts(parts, joint['pivot'], joint['id'], axis=joint.get('axis', 'Z'),
                            angle_degrees=joint.get('angle_degrees', 90), travel_m=joint.get('travel_m'))
        rk.parent_keep_world(ctrl, root)
        ctrl['joint_id'] = joint['id']
        ctrl['joint_type'] = 'slider' if 'travel_m' in joint else 'hinge'
        ctrl['roomkit_open_property'] = 'Open'
        controls.append(ctrl.name)
    maximum = 0.
    for frame in frames:
        scene.frame_set(frame)
        after = geometry(scene)
        for name, vertices in before[frame].items():
            if name in removed:
                continue
            delta = float(np.max(np.abs(vertices - after[name]))) if vertices.size else 0.
            maximum = max(maximum, delta)
    if maximum > 2e-5:
        raise ValueError('Retained closed geometry moved: ' + str(maximum))
    assert cameras(scene) == original_cameras, 'Source camera changed'
    assert timing == (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base)
    scene.frame_set(scene.frame_start)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
    # Reopen the actual deliverable and validate independent native motion.
    bpy.ops.wm.open_mainfile(filepath=str(args.out.resolve()))
    scene = bpy.context.scene
    poses = []
    for name in controls:
        ctrl = scene.objects[name]
        closed = ctrl.matrix_world.copy()
        samples = []
        for value in (.25, .5, .75, 1.):
            ctrl['Open'] = value
            ctrl.update_tag()
            bpy.context.view_layer.update()
            actual = ctrl.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
            distance = (actual.translation - closed.translation).length
            angle = closed.to_quaternion().rotation_difference(actual.to_quaternion()).angle
            assert max(distance, angle) > 1e-5, name
            samples.append({'value': value, 'distance': distance, 'angle': angle})
            assert all(scene.objects[other]['Open'] == 0 for other in controls if other != name)
        ctrl['Open'] = 0.
        ctrl.update_tag()
        bpy.context.view_layer.update()
        poses.append({'name': name, 'samples': samples})
    assert identity(args.source) == source_identity, 'Source changed during authoring'
    report = {'passed': True, 'source': str(args.source.resolve()), 'source_identity': source_identity,
              'output': str(args.out.resolve()), 'recipe': str(args.recipe.resolve()),
              'joints': poses, 'replaced_solids': sorted(removed), 'sampled_frames': frames,
              'retained_world_vertex_max_error_m': maximum, 'camera_samples_unchanged': timing[1]-timing[0]+1,
              'source_timing': list(timing), 'source_unchanged': True}
    args.out.with_suffix('.validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'joints': len(poses), 'maximum_error_m': maximum}))


if __name__ == '__main__':
    main()
