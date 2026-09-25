"""Portable browser light records; scene data is only read, never saved."""
import bpy
import re
from mathutils import Vector

FIXTURE = re.compile(r'lamp|chandelier|sconce|pendant|lantern|downlight|ceiling light|light fixture', re.I)
EMITTER = re.compile(r'bulb|shade|diffuser|flame|light panel', re.I)
DAYLIGHT = re.compile(r'daylight|window|softbox|fill|bounce|sun|sky', re.I)


def emission(mat):
    if not mat or not mat.use_nodes:
        return [0., 0., 0.], 0.
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            color = node.inputs.get('Emission Color') or node.inputs.get('Emission')
            strength = node.inputs.get('Emission Strength')
            return list(color.default_value[:3]) if color else [0., 0., 0.], float(strength.default_value) if strength else 0.
        if node.type == 'EMISSION':
            return list(node.inputs['Color'].default_value[:3]), float(node.inputs['Strength'].default_value)
    return [0., 0., 0.], 0.


def export_lighting(scene, payload, ancestor, closed, joint_names):
    """Native light units are retained; browser intensities are an artistic mapping.

    Only recognizable emitter parts acquire inferred lights. Bounds put the
    emitter inside its bulb/shade; source furniture transforms are untouched.
    """
    records, fixtures = [], []
    meshes = {m['name']: m for m in payload['meshes']}
    for obj in scene.objects:
        if obj.name not in meshes or obj.hide_render:
            continue
        owner = ancestor(obj, 'instance_id')
        context = obj.name + ' ' + (owner.name + ' ' + str(owner.get('semantic_class', '')) if owner else '')
        if FIXTURE.search(context) and EMITTER.search(obj.name):
            corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            center = sum(corners, Vector()) / 8
            fixtures.append((obj, owner, center, max((c-center).length for c in corners)))
    native = []
    graph = bpy.context.evaluated_depsgraph_get()
    for inst in graph.object_instances:
        obj = inst.object
        if obj.type != 'LIGHT' or obj.hide_render or any(c.hide_render for c in obj.original.users_collection):
            continue
        original = obj.original
        source = inst.parent.original if inst.is_instance and inst.parent else original
        owner = ancestor(source, 'instance_id')
        joint = ancestor(original, 'joint_id')
        transform = inst.matrix_world.copy()
        position = transform.translation.copy()
        nearest = min(fixtures, key=lambda f: (f[2]-position).length, default=None)
        # Bind an unparented authored lamp light to its nearby movable fixture.
        linked = nearest if nearest and (nearest[2]-position).length < max(.6, nearest[3]*1.5) and not DAYLIGHT.search(original.name) else None
        if owner is None and linked:
            owner = linked[1]
        if joint:
            transform = closed[joint.name].inverted() @ transform
        kind = obj.data.type
        artificial = bool(linked or FIXTURE.search(original.name)) and not DAYLIGHT.search(original.name)
        record = {'id': 'native-' + str(len(records)), 'name': original.name, 'type': kind,
                  'owner': owner.get('instance_id') if owner else None,
                  'joint': joint_names.get(joint.name) if joint else None,
                  'position': list(transform.translation),
                  'direction': list(transform.to_quaternion() @ Vector((0, 0, -1))),
                  'color': list(obj.data.color), 'energy': float(obj.data.energy),
                  'lamp': artificial, 'provenance': 'native Blender light',
                  'emitter_meshes': [f[0].name for f in fixtures if linked and f[1] == linked[1] and (f[2]-position).length < max(.6, f[3]*1.5)] if linked else []}
        if kind == 'SPOT':
            record.update(angle=float(obj.data.spot_size / 2), penumbra=float(obj.data.spot_blend))
        if kind == 'AREA':
            record.update(size=float(obj.data.size), size_y=float(getattr(obj.data, 'size_y', obj.data.size)))
        records.append(record)
        native.append((position, record))
    inferred = []
    for obj, owner, center, radius in fixtures:
        if any((p-center).length < max(.65, radius*1.5) and r['lamp'] for p, r in native):
            continue
        # A shade and bulb in the same fixture must not create two lights.
        if any((p-center).length < max(.3, radius) for p in inferred):
            continue
        joint = ancestor(obj, 'joint_id')
        local = closed[joint.name].inverted() @ center if joint else center
        records.append({'id': 'fixture-' + str(len(records)), 'name': obj.name,
                        'type': 'POINT', 'position': list(local), 'direction': [0, 0, -1],
                        'owner': owner.get('instance_id') if owner else None,
                        'joint': joint_names.get(joint.name) if joint else None,
                        'color': [1., .72, .42], 'energy': 12., 'lamp': True,
                        'provenance': 'inferred warm emitter at fixture bounds center',
                        'emitter_meshes': [f[0].name for f in fixtures if f[1] == owner and (f[2]-center).length < max(.3, radius)]})
        inferred.append(center)
    payload['lighting'] = {'version': 1, 'lights': records,
                           'notes': 'Native light transforms/colors retained. Intensities and inferred bulbs are browser approximations, not photometric calibration. Area lights use spot approximations.'}
