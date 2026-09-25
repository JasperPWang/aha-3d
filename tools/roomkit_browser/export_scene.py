"""Export an evaluated RoomKit fixture to the standalone browser viewer.

Run in background Blender. Source files are never saved.
Supports rigid, independently parented hinge/slider joints, not deforming rigs.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import math
import re

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy
from mathutils import Matrix


def ancestor(obj, key):
    while obj is not None:
        if obj.get(key):
            return obj
        obj = obj.parent
    return None


def matrix(m):
    return [float(m[r][c]) for c in range(4) for r in range(4)]


def pose(m):
    p, q, s = m.decompose()
    return {'position': list(p), 'quaternion': [q.x, q.y, q.z, q.w], 'scale': list(s)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--no-sha', action='store_true', help='Use source size/mtime correspondence without SHA-256 checks')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--bake-indirect', action='store_true', help='Bake a static-room indirect lightmap and diffuse probe with Cycles')
    parser.add_argument('--tabletop', action='store_true', help='Enable tabletop physics and registered seeded variants')
    parser.add_argument('--chairs', action='store_true', help='Enable constrained native-size chair replacements')
    parser.add_argument('--auto', action='store_true', help='Discover metadata, baked actors, legacy joints and framing')
    parser.add_argument('--config', type=Path, help='Explicit reviewed object groups and animated mesh names')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.out.exists():
        raise FileExistsError(args.out)
    source_stat = args.source.stat()
    source_identity = (source_stat.st_size, source_stat.st_mtime_ns)
    source_hash = None if args.no_sha else hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    scene = bpy.context.scene
    scene.frame_set(scene.frame_start)
    config = json.loads(args.config.read_text()) if args.config else {}
    if args.auto:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from auto_scene import discover, auto_views
        inferred = discover(scene)
        inferred.update(config)
        config = inferred
        if scene.name == 'Scene' and not args.config:
            config['title'] = args.source.stem.replace('_', ' ').capitalize() + ' / interactive demo'
    scene.frame_set(scene.frame_start)
    # Metadata migration in memory only; exact membership is authored in config.
    claimed = set()
    for group in config.get('groups', []):
        root = bpy.data.objects.new('Browser group | ' + group['id'], None)
        scene.collection.objects.link(root)
        root['instance_id'], root['semantic_class'] = group['id'], group['class']
        root['asset_id'] = group.get('asset_id', 'existing-scene/' + group['id'])
        root['browser_movable'] = group.get('movable', True)
        if group.get('support_id'):
            root['support_id'] = group['support_id']
        for name in group['objects']:
            if name in claimed:
                raise ValueError('Duplicate explicit group member: ' + name)
            claimed.add(name)
            obj = scene.objects[name]
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world
    for name, values in config.get('properties', {}).items():
        for key, value in values.items():
            scene.objects[name][key] = value
        scene.objects[name].update_tag()
    for record in config.get('joints', []):
        ctrl = scene.objects[record['object']]
        ctrl['joint_id'], ctrl['joint_type'] = record['id'], record['type']
        ctrl['roomkit_open_property'] = record.get('property', 'Open')
    bpy.context.view_layer.update()
    tabletop = None
    chairs = None
    if args.chairs:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from chair_export import prepare as prepare_chairs, finish as finish_chairs
        chairs = prepare_chairs(scene)
    if args.tabletop:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from tabletop_export import prepare, finish
        tabletop = prepare(scene)
    animated_names = set(config.get('animated_meshes', []))
    controllers = [o for o in scene.objects if o.get('joint_id')]
    roots = [o for o in scene.objects if o.get('instance_id')]
    assert len({o['instance_id'] for o in roots}) == len(roots), 'Duplicate instance IDs'
    joints, by_name = [], {}
    for ctrl in controllers:
        owner = ancestor(ctrl.parent, 'instance_id')
        if owner is None or ancestor(ctrl.parent, 'joint_id') is not None:
            raise ValueError('Missing owner or nested joint: ' + ctrl.name)
        # Older authored cabinet assets use slide for the same rigid slider.
        # Normalize only in memory; sampled native-pose checks below still apply.
        if ctrl.get('joint_type') == 'slide':
            ctrl['joint_type'] = 'slider'
        if ctrl.get('joint_type') not in ('hinge', 'slider'):
            raise ValueError('Unsupported joint: ' + ctrl.name)
        key = owner['instance_id'] + '/' + ctrl['joint_id']
        if key in by_name.values():
            raise ValueError('Duplicate joint: ' + key)
        by_name[ctrl.name] = key
        prop = ctrl['roomkit_open_property']
        ctrl[prop] = 0.0
        ctrl.update_tag()
    bpy.context.view_layer.update()
    closed = {o.name: o.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy() for o in controllers}
    for ctrl in controllers:
        ctrl[ctrl['roomkit_open_property']] = 1.0
        ctrl.update_tag()
    bpy.context.view_layer.update()
    opened = {o.name: o.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy() for o in controllers}
    max_error = 0.0
    for amount in (0., .25, .5, .75, 1.):
        for ctrl in controllers:
            ctrl[ctrl['roomkit_open_property']] = amount
            ctrl.update_tag()
        bpy.context.view_layer.update()
        for ctrl in controllers:
            actual = ctrl.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
            p0, q0, s0 = closed[ctrl.name].decompose()
            p1, q1, s1 = opened[ctrl.name].decompose()
            expected = Matrix.LocRotScale(p0.lerp(p1, amount), q0.slerp(q1, amount), s0.lerp(s1, amount))
            max_error = max(max_error, max(abs(actual[r][c] - expected[r][c]) for r in range(4) for c in range(4)))
    if max_error > 1e-5:
        raise ValueError('Joint interpolation differs from native Blender: ' + str(max_error))
    for ctrl in controllers:
        owner = ancestor(ctrl.parent, 'instance_id')
        joints.append({'id': by_name[ctrl.name], 'owner': owner['instance_id'], 'label': ctrl['joint_id'],
                       'type': ctrl['joint_type'], 'closed': pose(closed[ctrl.name]), 'open': pose(opened[ctrl.name])})
        ctrl[ctrl['roomkit_open_property']] = 0.0
        ctrl.update_tag()
    bpy.context.view_layer.update()
    meshes, materials = [], []
    material_ids = {}
    from material_export import material_uv_samples, linked_color
    uv_samples = material_uv_samples(bpy.context.scene.objects)

    def mat_id(mat):
        key = mat.name if mat else '__default'
        if key not in material_ids:
            color, roughness, metalness = (.5, .5, .5, 1), .65, 0.
            physical = None
            if mat:
                color = tuple(mat.diffuse_color)
                if mat.use_nodes:
                    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    if bsdf:
                        color = tuple(bsdf.inputs['Base Color'].default_value)
                        if bsdf.inputs['Base Color'].is_linked:
                            color = linked_color(bsdf.inputs['Base Color'], uv_samples.get(mat.name, ()), mat.diffuse_color)
                        roughness = bsdf.inputs['Roughness'].default_value
                        metalness = bsdf.inputs['Metallic'].default_value
                        transmission = float(bsdf.inputs['Transmission Weight'].default_value)
                        coat = float(bsdf.inputs['Coat Weight'].default_value)
                        if transmission > 0 or coat > 0:
                            physical = {'transmission': transmission, 'clearcoat': coat,
                                        'ior': float(bsdf.inputs['IOR'].default_value),
                                        'clearcoatRoughness': float(bsdf.inputs['Coat Roughness'].default_value),
                                        'thickness': float(mat.get('roomkit_transmission_thickness', .006))}
            from lighting_export import emission
            emissive, strength = emission(mat)
            if mat and mat.use_nodes:
                bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if bsdf and bsdf.inputs['Emission Color'].is_linked:
                    emissive = list(linked_color(bsdf.inputs['Emission Color'], uv_samples.get(mat.name, ()), (*emissive, 1))[:3])
            material_ids[key] = len(materials)
            materials.append({'name': key, 'color': list(color[:3]), 'roughness': roughness, 'metalness': metalness, 'emissive': emissive, 'emissive_intensity': strength})
            if physical is not None:
                materials[-1]['physical'] = physical
            if mat and mat.get('roomkit_procedural_material'):
                materials[-1]['procedural'] = json.loads(mat['roomkit_procedural_material'])
        return material_ids[key]

    graph = bpy.context.evaluated_depsgraph_get()
    for inst in graph.object_instances:
        obj = inst.object
        if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT') or obj.hide_render or any(c.hide_render for c in obj.original.users_collection) or obj.original.name in animated_names:
            continue
        original = obj.original
        # A collection instance's placement root belongs to the instancer.
        source = inst.parent.original if inst.is_instance and inst.parent else original
        owner = ancestor(source, 'instance_id')
        joint = ancestor(original, 'joint_id')
        if inst.is_instance and joint:
            raise ValueError('Instanced articulation requires independent import')
        local = inst.matrix_world.copy()
        if joint:
            local = closed[joint.name].inverted() @ local
        mesh = obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            positions, normals, groups = [], [], {}
            material_uv = []
            uv_layer = mesh.uv_layers.get('RoomKitMaterial')
            for tri in mesh.loop_triangles:
                material = obj.material_slots[tri.material_index].material if tri.material_index < len(obj.material_slots) else None
                mid = mat_id(material)
                indices = groups.setdefault(mid, [])
                for vi, li in zip(tri.vertices, tri.loops):
                    indices.append(len(positions) // 3)
                    positions.extend(mesh.vertices[vi].co)
                    normals.extend(mesh.corner_normals[li].vector)
                    if uv_layer:
                        material_uv.extend(uv_layer.data[li].uv)
            if positions:
                meshes.append({'name': original.name, 'owner': owner['instance_id'] if owner else None,
                               'joint': by_name.get(joint.name) if joint else None,
                               'surface': original.get('surface_role'), 'matrix': matrix(local),
                               'cutaway': original.name in config.get('cutaway_objects', []) or any(c.name in config.get('cutaway_collections', []) for c in original.users_collection),
                               'positions': positions, 'normals': normals,
                               'groups': [{'material': k, 'indices': v} for k, v in groups.items()]})
                if material_uv:
                    meshes[-1]['material_uv'] = material_uv
        finally:
            obj.to_mesh_clear()
    animation = None
    if animated_names:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from animation_export import export_actor
        actors = []
        for name in sorted(animated_names):
            obj = scene.objects[name]
            owner = ancestor(obj, 'instance_id')
            if owner is None:
                raise ValueError('Animated mesh requires an explicit semantic owner')
            mid = mat_id(obj.active_material)
            if config.get('actor_color'):
                mid = len(materials)
                materials.append({'name': 'Browser person highlight', 'color': config['actor_color'], 'roughness': .65, 'metalness': 0})
            body_mesh, actor, timing = export_actor(obj, mid, owner['instance_id'])
            meshes.append(body_mesh)
            actors.append(actor)
        animation = {**timing, 'actors': actors, 'description': config.get('motion_description', 'Existing baked motion')}
    objects = [{**{k: o.get(k) for k in ('instance_id', 'semantic_class', 'asset_id', 'support_id')},
                'movable': bool(o.get('browser_movable', True))} for o in roots]
    # Ground roots may name themselves as a support-plane label in Blender.
    # Browser support IDs become parenting edges, where that would be a cycle.
    self_supports = []
    for record in objects:
        if record['support_id'] == record['instance_id']:
            self_supports.append(record['instance_id'])
            record['support_id'] = None
    seen = {m['owner'] for m in meshes}
    if any(o['instance_id'] not in seen for o in objects):
        raise ValueError('An object lost all geometry during export')
    if any(not any(m['joint'] == j['id'] for m in meshes) for j in joints):
        raise ValueError('Joint has no moving geometry')
    final_stat = args.source.stat()
    assert (final_stat.st_size, final_stat.st_mtime_ns) == source_identity
    if not args.no_sha:
        assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    payload = {'schema_version': 1, 'title': 'RoomKit interaction lab', 'source': args.source.name,
               'source_sha256': source_hash, 'units': 'metres', 'world_up': 'Z',
               'objects': objects, 'joints': joints, 'meshes': meshes, 'materials': materials,
               'validation': {'native_joint_samples': 5, 'max_matrix_error': max_error, 'source_unchanged': True},
               'appearance': 'Evaluated source geometry; RoomKit generated PBR recipes retained. Other source shaders use simplified base colors.'}
    if args.no_sha:
        payload['source_correspondence'] = {'path': str(args.source.resolve()), 'size': source_identity[0], 'mtime_ns': source_identity[1], 'method': 'size_mtime; evaluated geometry and native joint checks'}
    from lighting_export import export_lighting
    if self_supports:
        payload['validation']['self_supports_normalized'] = self_supports
    export_lighting(scene, payload, ancestor, closed, by_name)
    if tabletop:
        finish(payload, tabletop)
        config['description'] = payload['description']
    if config:
        payload['title'] = config.get('title', payload['title'])
        payload['description'] = config.get('description', '')
        payload['views'] = config.get('views') or (auto_views(payload['meshes'], joints) if args.auto else None)
        payload['discovery'] = config.get('discovery')
        payload['animation'] = animation
        payload['config_sha256'] = hashlib.sha256(args.config.read_bytes()).hexdigest() if args.config and not args.no_sha else None
        payload['validation']['animated_frame_checks'] = 'Per-frame evaluated float32 positions, fixed topology and vertex samples'
    if chairs:
        print('Browser export: finishing chair metadata', flush=True)
        finish_chairs(payload, chairs)
        if args.auto and not config.get('views'):
            payload['views'] = auto_views(payload['meshes'], joints)
    if args.tabletop and not args.chairs:
        seating=[o for o in payload['objects'] if re.search('chair|stool',str(o.get('semantic_class','')),re.I)]
        payload['capability_note']='Tabletop objects support replacement and physics. Chair replacement is unavailable in this demo.'
        if seating and all('stool' in str(o.get('semantic_class','')).lower() for o in seating):
            payload['capability_note']='Tabletop objects support replacement and physics. Counter-height seating has no same-type replacement in the current library.'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print('Browser export: geometry and interactions complete', flush=True)
    if args.bake_indirect:
        from lighting_bake import bake_indirect
        bake_indirect(payload, args.out.parent)
    actors = (payload.get('animation') or {}).get('actors', [])
    # Keep large clips below JavaScript's single-string limit without resampling.
    if sum(len(a.get('positions_base64', '')) for a in actors) > 64 * 1024 * 1024:
        for index, actor in enumerate(actors):
            encoded = actor.pop('positions_base64')
            name = f'actor-{index:03d}.f32'
            with (args.out.parent / name).open('xb') as stream:
                for start in range(0, len(encoded), 4 * 1024 * 1024):
                    stream.write(base64.b64decode(encoded[start:start + 4 * 1024 * 1024], validate=True))
            actor['positions_file'] = name
    args.out.write_text(json.dumps(payload, separators=(',', ':'), allow_nan=False))
    print(json.dumps({'objects': len(payload['objects']), 'joints': len(joints), 'meshes': len(payload['meshes']), 'validation': payload['validation']}))


if __name__ == '__main__':
    main()
