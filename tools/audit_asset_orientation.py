"""Render raw registered asset orientation and isolated saved-scene faucets.

Run in background Blender. Never executes scene builders, applies
placement helpers, or saves over an input. All image/report writes go to --out.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def digest(path):
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def serial(value):
    if hasattr(value, 'to_list'):
        return value.to_list()
    if hasattr(value, 'to_dict'):
        return {k: serial(v) for k, v in value.to_dict().items()}
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


def geometry(objects):
    dg = bpy.context.evaluated_depsgraph_get()
    records, all_points = [], []
    for obj in objects:
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT'}:
            continue
        evaluated = obj.evaluated_get(dg)
        mesh = evaluated.to_mesh()
        points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        if not points:
            evaluated.to_mesh_clear()
            continue
        low = Vector(tuple(min(p[k] for p in points) for k in range(3)))
        high = Vector(tuple(max(p[k] for p in points) for k in range(3)))
        dominant = max(mesh.polygons, key=lambda p: p.area, default=None)
        surface_axis = None if dominant is None else (
            evaluated.matrix_world.to_3x3().inverted().transposed() @ dominant.normal).normalized()
        records.append({'name': obj.name, 'type': obj.type, 'vertices': len(points),
                        'center': list((low + high) / 2), 'bounds_min': list(low),
                        'bounds_max': list(high), 'matrix_world': [list(row) for row in evaluated.matrix_world],
                        'parent': obj.parent.name if obj.parent else None,
                        'largest_face_normal': list(surface_axis) if surface_axis is not None else None,
                        'largest_face_area': dominant.area if dominant is not None else None,
                        'properties': {k: serial(v) for k, v in obj.items()}})
        all_points.extend(points)
        evaluated.to_mesh_clear()
    if not all_points:
        raise ValueError('No evaluated geometry to audit')
    low = Vector(tuple(min(p[k] for p in all_points) for k in range(3)))
    high = Vector(tuple(max(p[k] for p in all_points) for k in range(3)))
    return records, low, high


def landmark_mean(records, pattern):
    selected = [record for record in records if re.search(pattern, record['name'], re.I)]
    if not selected:
        raise ValueError('No geometry matched landmark expression: ' + pattern)
    center = sum((Vector(record['center']) for record in selected), Vector()) / len(selected)
    return center, [record['name'] for record in selected]


def horizontal(vector):
    result = Vector((vector[0], vector[1], 0))
    if result.length < 1e-6:
        raise ValueError('Horizontal orientation is undefined')
    return result.normalized()


def material(name, color, emission=False):
    mat = bpy.data.materials.new('Audit ' + name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = .8
    if emission:
        mat.node_tree.nodes.remove(bsdf)
        shader = mat.node_tree.nodes.new('ShaderNodeEmission')
        shader.inputs['Color'].default_value = (*color, 1)
        shader.inputs['Strength'].default_value = 1.
        output = mat.node_tree.nodes.get('Material Output')
        mat.node_tree.links.new(shader.outputs['Emission'], output.inputs['Surface'])
    return mat


def tube(scene, name, points, radius, mat):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for vertex, position in zip(spline.points, points):
        vertex.co = (*position, 1.)
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    data.materials.append(mat)
    return obj


def setup_render(scene, low, high, samples, resolution):
    from aha3d.blender.stage import gpu
    gpu(scene)
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('Audit World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.7, .7, .7, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .45
    scene.view_layers[0].material_override = None
    extent = max(high - low)
    for name, offset, power in [('Key', (2, -3, 5), 300), ('Fill', (-3, -1, 3), 170), ('Rim', (1, 3, 4), 220)]:
        data = bpy.data.lights.new('Audit ' + name, 'AREA')
        data.energy = power * max(extent, .4) ** 2
        data.shape = 'DISK'
        data.size = extent * 3
        obj = bpy.data.objects.new('Audit ' + name, data)
        scene.collection.objects.link(obj)
        obj.location = Vector(offset) * extent
        obj.rotation_euler = (Vector((0, 0, extent / 3)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data = bpy.data.cameras.new('Audit Camera')
    camera = bpy.data.objects.new('Audit Camera', camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = 'ORTHO'
    camera_data.clip_start = .001
    camera_data.clip_end = 1000
    scene.camera = camera
    return camera, extent


def overlays(scene, camera, extent, label, view, inferred, symmetric=False):
    """Use camera-facing annotations in image margins, outside the model area."""
    objects = []
    scale = camera.data.ortho_scale
    basis = camera.rotation_euler.to_matrix()
    origin = camera.location + basis @ Vector((0, 0, -extent * 2))
    def position(x, y):
        return origin + basis @ Vector((x * scale, y * scale, 0))
    colors = {name: material(name, color, True) for name, color in [
        ('ink', (.035, .045, .065)), ('X', (.65, .05, .05)),
        ('Y', (.03, .36, .07)), ('Z', (.04, .13, .7)), ('front', (.62, .04, .52))]}
    def text(label, x, y, color='ink', size=.017):
        data = bpy.data.curves.new('Audit label', 'FONT')
        data.body = label
        data.size = scale * size
        data.align_x = 'LEFT'
        obj = bpy.data.objects.new('Audit label ' + label, data)
        scene.collection.objects.link(obj)
        obj.location = position(x, y)
        obj.rotation_euler = camera.rotation_euler
        data.materials.append(colors[color])
        objects.append(obj)
    def arrow(start, end, color):
        p, q = Vector(start), Vector(end)
        d = (q-p).normalized()
        side = Vector((-d.y, d.x))
        wing = q - d * .018
        for points in [(p, q), (wing + side*.010, q, wing-side*.010)]:
            objects.append(tube(scene, 'Audit arrow', [position(*point) for point in points], scale*.0015, colors[color]))
    text(label, -.46, .445, size=.020)
    text(view + ' | raw local axes; zero placement yaw', -.46, .412, size=.016)
    text('Local axes', -.455, -.255, size=.017)
    center = Vector((-.365, -.355))
    inverse = basis.inverted()
    for axis, vector in [('X', Vector((1,0,0))), ('Y', Vector((0,1,0))), ('Z', Vector((0,0,1)))]:
        projected = inverse @ vector
        direction = Vector((projected.x, projected.y))
        if direction.length < .01:
            text('+Z toward camera', -.455, -.465, 'Z', .014)
        else:
            direction.normalize()
            end = center + direction * .10
            arrow(center, end, axis)
            text('+' + axis, end.x + .006, end.y + .006, axis, .020)
    if symmetric:
        text('Rotational symmetry:', .14, -.315, size=.017)
        text('no unique horizontal front', .14, -.345, size=.016)
    else:
        text('Source front', .18, -.28, 'front', .018)
        projected = inverse @ Vector(inferred)
        direction = Vector((projected.x, projected.y)).normalized()
        start = Vector((.30, -.385))
        arrow(start, start + direction * .09, 'front')
    return objects


def render_views(scene, objects, low, high, row, output, args):
    # A neutral material makes geometric direction legible independently of texture.
    neutral = material('geometry', (.55, .61, .65))
    for obj in objects:
        if obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT'}:
            obj.data = obj.data.copy()
            obj.data.materials.clear()
            obj.data.materials.append(neutral)
            for poly in getattr(obj.data, 'polygons', []):
                poly.material_index = 0
    camera, extent = setup_render(scene, low, high, args.samples, args.resolution)
    camera.data.ortho_scale = extent * 2.15
    center = (low + high) / 2
    views = []
    for view, offset in [('top', Vector((0, 0, 4))), ('oblique', Vector((2.3, -3.4, 2.7)))]:
        camera.location = center + offset * extent
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        labels = overlays(scene, camera, extent, row['id'], view,
                          row.get('likely_front_local', [0, -1, 0]), row.get('symmetric', False))
        scene.render.filepath = str(output / (view + '.png'))
        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=True)
        views.append(scene.render.filepath)
        for obj in labels:
            bpy.data.objects.remove(obj, do_unlink=True)
    return views


def audit_model(item, out, args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    path = ROOT / item['library']
    actual_hash = digest(path)
    if actual_hash != item['sha256']:
        raise ValueError('Pinned library hash changed: ' + str(path))
    with bpy.data.libraries.load(str(path), link=False) as (source, destination):
        if item['collection'] not in source.collections:
            raise ValueError('Missing collection: ' + item['collection'])
        destination.collections = [item['collection']]
    collection = destination.collections[0]
    bpy.context.scene.collection.children.link(collection)
    objects = list(collection.all_objects)
    bpy.context.scene.frame_set(1)
    for obj in objects:
        for prop in ('Open', 'open_amount'):
            if prop in obj:
                obj[prop] = 0.
                obj.update_tag()
    bpy.context.view_layer.update()
    records, low, high = geometry(objects)
    row = dict(item)
    row.update(library_sha256_verified=actual_hash, placement_rotation_degrees=0,
               collection_properties={k: serial(v) for k, v in collection.items()},
               root_objects=[{'name': o.name, 'matrix_world': [list(r) for r in o.matrix_world],
                              'properties': {k: serial(v) for k, v in o.items()}}
                             for o in objects if o.parent is None],
               parts=records, bounds_min=list(low), bounds_max=list(high),
               support_bottom_z=low.z, horizontal_bounds_center=list((low+high)/2)[:2],
               visual_review='pending')
    if item.get('symmetric'):
        row['front_status'] = 'No intrinsic front: rotationally symmetric source geometry'
    else:
        front, front_names = landmark_mean(records, item['front_landmarks'])
        back, back_names = landmark_mean(records, item['back_landmarks'])
        direction = horizontal(front - back)
        method = 'back-to-seat landmark centers'
        if item.get('front_method') == 'panel_normals':
            # A cupboard with one wide door and several narrow drawers must not
            # acquire a false sideways heading from unequal object counts.
            normals = []
            for record in records:
                if record['name'] not in front_names:
                    continue
                axis = Vector(record['largest_face_normal'])
                if axis.dot(front - back) < 0:
                    axis = -axis
                normals.append(axis * record['largest_face_area'])
            direction = horizontal(sum(normals, Vector()))
            method = 'area-weighted largest front-panel face normals, signed away from back'
        dot = direction.dot(horizontal(item['declared_front']))
        row.update(likely_front_local=list(direction), declared_front_dot=dot,
                   landmark_front_names=front_names, landmark_back_names=back_names,
                   landmark_front_center=list(front), landmark_back_center=list(back),
                   front_inference_method=method,
                   front_status='consistent by named geometry' if dot > .95 else 'mismatch by named geometry')
    row['previews'] = render_views(bpy.context.scene, objects, low, high, row, out, args)
    row['source_unchanged_after_render'] = digest(path) == actual_hash
    return row


def audit_faucet(item, out, args):
    path = ROOT / item['source_blend']
    actual_hash = digest(path)
    if actual_hash != item['sha256']:
        raise ValueError('Pinned faucet source changed: ' + str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    curve = bpy.data.objects[item['curve']]
    if curve.type != 'CURVE' or len(curve.data.splines) != 1:
        raise ValueError('Expected one explicit faucet centerline')
    spline = curve.data.splines[0]
    points = [p.co.copy() for p in spline.bezier_points] if spline.type == 'BEZIER' else [Vector(p.co[:3]) for p in spline.points]
    world = curve.matrix_world.copy()
    world_points = [world @ p for p in points]
    mount, outlet = world_points[0], world_points[-1]
    facing_world = horizontal(outlet - mount)
    rotation = world.to_3x3().normalized()
    preview_transform = rotation.inverted().to_4x4() @ Matrix.Translation(-mount)
    local_front = horizontal(rotation.inverted() @ facing_world)
    mount_error = (mount - Vector(item['expected_mount_world'])).length
    if mount_error > .003 or facing_world.dot(Vector(item['expected_front_world'])) < .99:
        raise ValueError('Saved faucet placement differs from reviewed source hypothesis')
    selected = []
    for name in item['parts']:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise ValueError('Missing required faucet part: ' + name)
        for part in [obj, *obj.children_recursive]:
            if part not in selected:
                selected.append(part)
    discovered = [o.name for o in bpy.context.scene.objects if re.search(r'faucet|\btap\b|spout', o.name, re.I)]
    extras = sorted(set(discovered) - {o.name for o in selected})
    if extras:
        raise ValueError('Unreviewed additional faucet-named pieces: ' + ', '.join(extras))
    source_parts, _, _ = geometry(selected)
    stage = bpy.data.scenes.new('Isolated faucet audit')
    copied = []
    dg = bpy.context.evaluated_depsgraph_get()
    for source in selected:
        if source.type not in {'MESH', 'CURVE', 'SURFACE'}:
            continue
        evaluated = source.evaluated_get(dg)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=dg)
        obj = bpy.data.objects.new(source.name + ' | isolated copy', mesh)
        stage.collection.objects.link(obj)
        obj.matrix_world = preview_transform @ evaluated.matrix_world
        copied.append(obj)
    bpy.context.window.scene = stage
    bpy.context.view_layer.update()
    records, low, high = geometry(copied)
    row = dict(item)
    row.update(source_sha256_verified=actual_hash, source_parts=source_parts,
               discovered_faucet_parts=discovered, parts=records,
               source_object_matrix_world=[list(r) for r in world],
               source_object_origin_world=list(world.translation),
               mount_world=list(mount), mount_hypothesis_error_m=mount_error,
               outlet_world=list(outlet), centerline_world=[list(p) for p in world_points],
               likely_front_world=list(facing_world), likely_front_local=list(local_front),
               outlet_last_segment_direction_world=list((world_points[-1]-world_points[-2]).normalized()),
               front_definition='Horizontal mount-to-spout projection; separate from outlet/downward flow direction',
               preview_origin='reviewed mounting point, Z-up with source-root local horizontal axes',
               preview_transform_from_source_world=[list(r) for r in preview_transform],
               bounds_min=list(low), bounds_max=list(high), visual_review='pending')
    row['previews'] = render_views(stage, copied, low, high, row, out, args)
    row['source_unchanged_after_render'] = digest(path) == actual_hash
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'configs/orientation_audit.json'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--samples', type=int, default=24)
    parser.add_argument('--resolution', type=int, default=1000)
    parser.add_argument('--only', nargs='*', help='Exact item IDs to run')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    config = json.loads(Path(args.config).read_text())
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'config': str(Path(args.config).resolve()),
              'config_sha256': digest(args.config), 'script_sha256': digest(__file__),
              'items': [], 'visual_review': 'pending',
              'inference_limit': 'Named geometry provides front hypotheses; rendered pictures require inspection.'}
    for key, runner in [('models', audit_model), ('faucets', audit_faucet)]:
        for item in config[key]:
            if args.only and item['id'] not in args.only:
                continue
            item_out = out / item['id'].replace('/', '__')
            item_out.mkdir(exist_ok=True)
            row = runner(item, item_out, args)
            (item_out / 'audit.json').write_text(json.dumps(row, indent=2) + '\n')
            report['items'].append(row)
            (out / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'audited': item['id'], 'front': row.get('front_status', row.get('likely_front_world'))}), flush=True)
    report['execution_status'] = 'complete; visual review pending'
    (out / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
