"""Conservative in-memory discovery for saved Blender scenes; never saves source."""
import re
import bpy


def ancestor(obj, key):
    while obj:
        if obj.get(key):
            return obj
        obj = obj.parent


def discover(scene):
    report = {'inferred_roots': [], 'inferred_joints': [], 'warnings': []}
    used = {o.get('instance_id') for o in scene.objects if o.get('instance_id')}

    def tag(obj, category, movable):
        if not obj.get('instance_id'):
            base = re.sub(r'[^a-z0-9]+', '-', obj.name.lower()).strip('-') or 'object'
            identity, index = base, 2
            while identity in used:
                identity = f'{base}-{index}'; index += 1
            used.add(identity)
            obj['instance_id'] = identity
            obj['semantic_class'] = category
            obj['asset_id'] = 'source-scene/' + obj.name
            report['inferred_roots'].append({'object': obj.name, 'id': identity, 'category': category})
        obj['browser_movable'] = movable
        return obj

    # Existing semantic metadata wins. Legacy complete furniture empties are a
    # conservative fallback; loose mesh names never establish a complete object.
    for obj in list(scene.objects):
        if obj.type == 'EMPTY' and not ancestor(obj, 'instance_id') and re.search(r'\b(sofa|chair|stool|table|bench|bed)\b', obj.name, re.I) and obj.children:
            if not any(ancestor(p, 'instance_id') for p in obj.children_recursive):
                tag(obj, 'furniture/inferred', True)
    animated = []
    for obj in list(scene.objects):
        if obj.type != 'MESH' or obj.hide_render:
            continue
        keys = obj.data.shape_keys
        deforming = bool(keys and keys.animation_data) or any(m.type == 'ARMATURE' and m.object and m.object.animation_data for m in obj.modifiers)
        if deforming:
            root = ancestor(obj, 'instance_id')
            if root is None:
                # A dedicated per-mesh root avoids absorbing unrelated siblings.
                root = bpy.data.objects.new('Animated | ' + obj.name, None)
                scene.collection.objects.link(root)
                root.parent = obj.parent
                bpy.context.view_layer.update()
                world = obj.matrix_world.copy(); obj.parent = root; obj.matrix_world = world
            tag(root, 'animation/baked-mesh', False)
            animated.append(obj.name)
    for obj in scene.objects:
        for key in ('Demo', 'Open all', 'Auto open'):
            if key in obj:
                obj[key] = 0.; obj.update_tag()
    controllers = [o for o in scene.objects if 'Open' in o and o.children and not o.get('joint_id')]
    for obj in controllers:
        obj['Open'] = 0.; obj.update_tag()
    bpy.context.view_layer.update()
    for obj in controllers:
        closed = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
        obj['Open'] = 1.; obj.update_tag(); bpy.context.view_layer.update()
        opened = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
        obj['Open'] = 0.; obj.update_tag(); bpy.context.view_layer.update()
        angle = closed.to_quaternion().rotation_difference(opened.to_quaternion()).angle
        travel = (closed.translation-opened.translation).length
        if angle < 1e-5 and travel < 1e-5:
            report['warnings'].append('Unresolved Open controller: ' + obj.name); continue
        if not ancestor(obj.parent, 'instance_id'):
            root = bpy.data.objects.new('Fitted | ' + obj.name, None); scene.collection.objects.link(root)
            tag(root, 'furniture/cabinet-parts', False)
            world = obj.matrix_world.copy(); obj.parent = root; obj.matrix_world = world
        obj['joint_id'] = obj.name
        obj['joint_type'] = 'hinge' if angle > 1e-5 else 'slider'
        obj['roomkit_open_property'] = 'Open'
        report['inferred_joints'].append(obj.name)
    # Existing animation owners must not be draggable, including tagged actors.
    for name in animated:
        ancestor(scene.objects[name], 'instance_id')['browser_movable'] = False
    report['animated_meshes'] = animated
    report['static_unowned'] = [o.name for o in scene.objects if o.type in ('MESH', 'CURVE', 'FONT', 'SURFACE') and not ancestor(o, 'instance_id') and not o.hide_render]
    report['warnings'].append('Unowned geometry stays static; inference does not prove semantic completeness. Baked motion is not source-person ground truth.')
    return {'animated_meshes': animated, 'title': scene.name + ' / interactive demo',
            'description': 'Saved Blender scene. Hold to grab; bounding-box drag limits. Baked motion does not replan around furniture.',
            'motion_description': 'Existing baked scene animation; source timing preserved.',
            'cutaway_collections': [c.name for c in bpy.data.collections if re.search(r'ceiling|roof|exposed.*beams', c.name, re.I)],
            'cutaway_objects': [o.name for o in scene.objects if re.search(r'\b(ceiling|roof)\b', o.name, re.I)],
            'discovery': report}


def auto_views(meshes, joints):
    import numpy as np
    from mathutils import Matrix, Quaternion, Vector
    joint_poses = {j["id"]: j["closed"] for j in joints}
    lows, highs = [], []
    for m in meshes:
        if m.get('cutaway'):
            continue
        points = np.asarray(m['positions']).reshape(-1, 3)
        transform = np.asarray(m['matrix']).reshape(4, 4).T
        if m.get('joint'):
            pose = joint_poses[m['joint']]
            x, y, z, w = pose['quaternion']
            parent = Matrix.LocRotScale(Vector(pose['position']), Quaternion((w, x, y, z)), Vector(pose['scale']))
            transform = np.asarray(parent) @ transform
        points = points @ transform[:3, :3].T + transform[:3, 3]
        lows.append(points.min(axis=0)); highs.append(points.max(axis=0))
    if not lows:
        raise ValueError('No visible geometry to frame')
    lo, hi = np.min(lows, axis=0), np.max(highs, axis=0)
    center = (lo+hi)/2; extent = max(float(np.linalg.norm(hi-lo)), 1.)
    views = {'orbit': {'position': (center+np.array([.75,-1.,.7])*extent).tolist(), 'target': center.tolist(), 'fov': 50},
            'plan': {'position': (center+np.array([0.,0.,1.5])*extent).tolist(), 'target': center.tolist(), 'fov': 50}}

    camera = bpy.context.scene.camera
    if camera and camera.data.type == 'PERSP':
        position = camera.matrix_world.translation
        forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
        fov = min(90., max(25., camera.data.angle_y * 180 / 3.141592653589793))
        toward_center = Vector(center.tolist()) - position
        # Tall walls can put the room center above a useful authored human view.
        # Retain that camera when every currently visible animated mesh center
        # is inside its cone, even if the architectural center is outside it.
        actor_directions = []
        for obj in bpy.context.scene.objects:
            if obj.type != 'MESH' or obj.hide_render:
                continue
            keys = obj.data.shape_keys
            if not (bool(keys and keys.animation_data) or any(
                    m.type == 'ARMATURE' and m.object and m.object.animation_data for m in obj.modifiers)):
                continue
            center_local = sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8
            actor_directions.append(obj.matrix_world @ center_local - position)
        cone = float(np.cos(np.deg2rad(fov / 2)))
        actors_in_view = bool(actor_directions) and all(
            direction.length > 1e-6 and forward.dot(direction.normalized()) >= cone
            for direction in actor_directions)
        # Walkthroughs may start facing a near wall or away from the room.
        # Keep the overview unless the room center is inside the source view cone.
        if (toward_center.length > 1e-6 and forward.dot(toward_center.normalized()) >= cone) or actors_in_view:
            views['orbit'] = {'position': list(position), 'target': list(position + forward * extent * .3), 'fov': fov}
    return views
