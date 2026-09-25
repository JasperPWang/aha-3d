"""Reusable Blender helpers. Distances are metres; furniture faces local -Y."""
import csv
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector


def collection(name):
    result = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(result)
    return result


def box(name, location, dimensions, material=None, target=None, edge=.008,
        *, surface_role=None, semantic_class=None, instance_id=None,
        asset_id=None, support_id=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if target:
        for col in list(obj.users_collection):
            col.objects.unlink(obj)
        target.objects.link(obj)
    if material:
        obj.data.materials.append(material)
    if edge:
        modifier = obj.modifiers.new('Edge radius', 'BEVEL')
        modifier.width = edge
        modifier.segments = 3
        obj.modifiers.new('Face normals', 'WEIGHTED_NORMAL')
    if surface_role is not None:
        from .semantics import tag_surface
        tag_surface(obj, surface_role)
    if semantic_class is not None:
        from .semantics import tag_root
        return tag_root(obj, semantic_class, instance_id, asset_id, support_id)
    return obj


def import_collection(library, name, location=(0, 0, 0), rotation=None, scale=1,
                      *, semantic_class=None, instance_id=None, asset_id=None,
                      support_id=None, orientation=None, facing_target=None):
    """Low-level collection placement retains source coordinates; place_asset canonicalizes.

    Registered item reviews or explicit declarations describe the actual front.
    Raw unregistered collections remain unverified, never implicitly -Y.
    """
    from aha3d.assets import collection_orientation
    from aha3d.orientation import normalize_orientation, unknown_orientation
    from .orientation import tag_orientation, face_towards, _target
    if rotation is not None and facing_target is not None:
        raise ValueError('Choose either rotation or facing_target, not both')
    if rotation is not None and (isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation)):
        raise ValueError('rotation must be finite degrees')
    if len(location) != 3 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in location):
        raise ValueError('location must contain three finite coordinates')
    if facing_target is not None:
        bpy.context.view_layer.update()
        point, _ = _target(facing_target)
        if math.hypot(point.x-location[0], point.y-location[1]) < 1e-8:
            raise ValueError('Facing target has the same horizontal position as the asset')
        scales = [scale] * 3 if isinstance(scale, (float, int)) else list(scale)
        if (len(scales) != 3 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0 for v in scales)
                or max(scales)-min(scales) > 1e-8):
            raise ValueError('Facing requires a positive uniform scale')
    if semantic_class is not None and instance_id is not None and any(o.get('instance_id') == instance_id for o in bpy.context.scene.objects):
        raise ValueError('Duplicate instance_id: ' + str(instance_id))
    library = Path(library).resolve()
    metadata = orientation if orientation is not None else collection_orientation(library, name)
    key = str(library) + '::' + name
    col = next((c for c in bpy.data.collections if c.get('roomkit_import_key') == key), None)
    if col is None:
        with bpy.data.libraries.load(str(library), link=False) as (source, dest):
            if name not in source.collections:
                raise ValueError('Missing asset collection: ' + name)
            dest.collections = [name]
        col = dest.collections[0]
        col['roomkit_import_key'] = key
    if metadata is None:
        metadata = json.loads(col['asset_orientation_json']) if col.get('asset_orientation_json') else unknown_orientation()
    metadata = normalize_orientation(metadata, require_trusted=facing_target is not None)
    if facing_target is not None and (metadata['front_axis'] is None or metadata['up_axis'] != 'Z'):
        raise ValueError('Facing requires an upright directional asset; use place_asset to normalize source axes')
    obj = bpy.data.objects.new(name + ' instance', None)
    bpy.context.scene.collection.objects.link(obj)
    obj.instance_type = 'COLLECTION'
    obj.instance_collection = col
    obj.location = location
    obj.rotation_euler.z = math.radians(rotation or 0)
    obj.scale = (scale,) * 3 if isinstance(scale, (int, float)) else scale
    tag_orientation(obj, metadata)
    if semantic_class is not None:
        from .semantics import tag_root
        obj = tag_root(obj, semantic_class, instance_id, asset_id, support_id)
    if facing_target is not None:
        face_towards(obj, facing_target)
    return obj


def place_asset(asset_id, location=(0, 0, 0), rotation=None, scale=1,
                instance_id=None, project_root=None, *, facing_target=None, facing_direction=None):
    """Place a registered item with stable semantics and a replaceable root."""
    from .variants import place_asset as place
    return place(asset_id, location=location, rotation=rotation, scale=scale,
                 instance_id=instance_id, project_root=project_root, facing_target=facing_target,
                 facing_direction=facing_direction)


def place_root(root, location=None, **kwargs):
    """Place a generated/custom root using an explicit world facing intent."""
    from .orientation import place_root as place
    return place(root, location, **kwargs)


def face_towards(root, target, **kwargs):
    """Orient a verified asset toward a stable semantic object or world point."""
    from .orientation import face_towards as face
    return face(root, target, **kwargs)


def parent_keep_world(obj, parent):
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world


def rig_parts(parts, pivot, name, axis='Z', angle_degrees=90, travel_m=None):
    """Create a local-axis hinge or slider. Parts must be actual objects, not instances."""
    if not parts:
        raise ValueError('A rig requires moving parts')
    ctrl = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(ctrl)
    ctrl.location = pivot
    ctrl.empty_display_type = 'ARROWS'
    ctrl.empty_display_size = .12
    ctrl['Open'] = 0.
    ctrl.id_properties_ui('Open').update(min=0., max=1., description='0 closed, 1 fully open')
    bpy.context.view_layer.update()
    for obj in parts:
        parent_keep_world(obj, ctrl)
    index = 'XYZ'.index(axis.upper())
    path = 'rotation_euler' if travel_m is None else 'location'
    offset = 0. if travel_m is None else float(pivot[index])
    factor = math.radians(angle_degrees) if travel_m is None else float(travel_m)
    driver = ctrl.driver_add(path, index).driver
    variable = driver.variables.new()
    variable.name = 'opening'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id = ctrl
    variable.targets[0].data_path = '["Open"]'
    driver.expression = f'{offset!r}+({factor!r})*min(1,max(0,opening))'
    return ctrl


def smoother(value):
    u = max(0., min(1., value))
    return u**3 * (10 + u * (-15 + 6 * u))


def fcurves(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if not action:
        return []
    if hasattr(action, 'layers'):
        return [fc for layer in action.layers for strip in layer.strips
                for bag in strip.channelbags for fc in bag.fcurves]
    return list(action.fcurves)


def clear_keyed_paths(obj, paths):
    """Remove only replaced animation channels; preserve drivers and other channels."""
    if not obj.animation_data or not obj.animation_data.action:
        return
    if obj.animation_data.action.users > 1:
        obj.animation_data.action = obj.animation_data.action.copy()
    action = obj.animation_data.action
    containers = [bag.fcurves for layer in action.layers for strip in layer.strips
                  for bag in strip.channelbags] if hasattr(action, 'layers') else [action.fcurves]
    for container in containers:
        for fc in list(container):
            if fc.data_path in paths:
                container.remove(fc)


def animate_property(obj, prop, poses, frames, fps, frame_start=1):
    """Sample continuous quintic easing between [seconds, value] poses at output FPS."""
    if prop == 'Open' and obj.get('roomkit_open_property') == 'open_amount':
        prop = 'open_amount'
    if prop not in obj:
        raise ValueError(f'{obj.name} has no property {prop}')
    if len(poses) < 2 or any(b[0] <= a[0] for a, b in zip(poses, poses[1:])):
        raise ValueError('Pose times must strictly increase')
    path = '[' + json.dumps(prop) + ']'
    clear_keyed_paths(obj, {path})
    values = []
    for index in range(frames):
        t = index / fps
        value = poses[0][1] if t <= poses[0][0] else poses[-1][1]
        for a, b in zip(poses, poses[1:]):
            if a[0] <= t <= b[0]:
                value = a[1] + (b[1] - a[1]) * smoother((t-a[0])/(b[0]-a[0]))
                break
        obj[prop] = float(value)
        obj.keyframe_insert(data_path=path, frame=frame_start+index)
        values.append(float(value))
    for fc in fcurves(obj):
        if fc.data_path == path:
            for key in fc.keyframe_points:
                key.interpolation = 'LINEAR'
    return values


def cabinet_controls(root):
    """Discover native controls under one cabinet or semantic placement root."""
    controls = [obj for obj in [root, *root.children_recursive] if obj.get('joint_id')]
    identities = [obj['joint_id'] for obj in controls]
    if len(identities) != len(set(identities)):
        raise ValueError('Duplicate joint_id under ' + root.name)
    return sorted(controls, key=lambda obj: obj['joint_id'])


def set_open(root, amount, joint_ids=None):
    """Set all or selected cabinet joints without scene-specific hinge code."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or not 0 <= amount <= 1:
        raise ValueError('Opening amount must be finite and in [0, 1]')
    controls = cabinet_controls(root)
    if joint_ids is not None:
        requested = set(joint_ids)
        unknown = requested - {obj['joint_id'] for obj in controls}
        if unknown:
            raise ValueError('Unknown joints: ' + ', '.join(sorted(unknown)))
        controls = [obj for obj in controls if obj['joint_id'] in requested]
    if not controls:
        raise ValueError('No operable joints selected under ' + root.name)
    for obj in controls:
        prop = obj.get('roomkit_open_property', 'open_amount' if 'open_amount' in obj else 'Open')
        obj[prop] = float(amount)
        obj.update_tag()
    bpy.context.view_layer.update()
    return controls


def animate_open(root, joint_id, poses, frames, fps, frame_start=1):
    """Animate a joint by its stable local ID; retain native driver behavior."""
    controls = {obj['joint_id']: obj for obj in cabinet_controls(root)}
    if joint_id not in controls:
        raise ValueError('Unknown joint: ' + joint_id)
    if any(len(pose) != 2 or not math.isfinite(pose[1]) or not 0 <= pose[1] <= 1 for pose in poses):
        raise ValueError('Opening poses require amounts in [0, 1]')
    obj = controls[joint_id]
    prop = obj.get('roomkit_open_property', 'open_amount' if 'open_amount' in obj else 'Open')
    return animate_property(obj, prop, poses, frames, fps, frame_start)


def camera_path(points, look_start, look_end, seconds=5, fps=24, lens=21,
                sensor_width=36, ramp_seconds=.55, name='RoomKit Camera'):
    frames = round(seconds * fps)
    if frames < 2 or len(points) != 4:
        raise ValueError('Need four cubic Bezier points and at least two frames')
    duration = (frames-1) / fps
    ramp = min(max(ramp_seconds, 0.), duration/2)
    cp = np.asarray(points, dtype=float)
    def bezier(u):
        return (1-u)**3*cp[0] + 3*(1-u)**2*u*cp[1] + 3*(1-u)*u*u*cp[2] + u**3*cp[3]
    dense_u = np.linspace(0, 1, 6001)
    dense = np.array([bezier(u) for u in dense_u])
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
    if lengths[-1] <= 1e-6:
        raise ValueError('Camera path has zero length')
    def progress(t):
        def start_area(v):
            return .5*v - ramp*math.sin(math.pi*v/ramp)/(2*math.pi)
        if ramp == 0:
            return t/duration
        if t < ramp:
            return start_area(t)/(duration-ramp)
        if t > duration-ramp:
            return 1-start_area(duration-t)/(duration-ramp)
        return (t-ramp/2)/(duration-ramp)
    data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(cam)
    data.lens = lens
    data.sensor_width = sensor_width
    data.sensor_fit = 'HORIZONTAL'
    cam.rotation_mode = 'QUATERNION'
    q0 = (Vector(look_start)-Vector(points[0])).to_track_quat('-Z', 'Y')
    q1 = (Vector(look_end)-Vector(points[-1])).to_track_quat('-Z', 'Y')
    if q0.dot(q1) < 0:
        q1.negate()
    for i in range(frames):
        t = i/fps
        u = float(np.interp(progress(t)*lengths[-1], lengths, dense_u))
        cam.location = bezier(u)
        cam.rotation_quaternion = q0.slerp(q1, smoother(t/duration))
        cam.keyframe_insert(data_path='location', frame=i+1)
        cam.keyframe_insert(data_path='rotation_quaternion', frame=i+1)
    for fc in fcurves(cam):
        for key in fc.keyframe_points:
            key.interpolation = 'LINEAR'
    scene = bpy.context.scene
    scene.camera = cam
    scene.frame_start, scene.frame_end = 1, frames
    scene.render.fps, scene.render.fps_base = fps, 1.
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.
    return cam


def export_camera(scene, output):
    """Perspective calibration: square pixels, horizontal sensor fit, zero camera shift."""
    cam = scene.camera
    if (cam.data.type != 'PERSP' or cam.data.sensor_fit != 'HORIZONTAL'
            or abs(cam.data.shift_x)+abs(cam.data.shift_y) > 1e-8
            or scene.render.pixel_aspect_x != scene.render.pixel_aspect_y):
        raise ValueError('Calibration requires horizontal perspective camera, square pixels, zero shift')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    width = round(scene.render.resolution_x * scene.render.resolution_percentage / 100)
    height = round(scene.render.resolution_y * scene.render.resolution_percentage / 100)
    focal = width * cam.data.lens / cam.data.sensor_width
    K = np.array([[focal, 0, width/2], [0, focal, height/2], [0, 0, 1]])
    transforms, rows = [], []
    axes = Matrix.Diagonal((1, -1, -1, 1))
    fps = scene.render.fps / scene.render.fps_base
    original_frame = scene.frame_current
    for frame in range(scene.frame_start, scene.frame_end+1):
        scene.frame_set(frame)
        transform = np.array(cam.matrix_world @ axes)
        transforms.append(transform)
        rows.append([frame, (frame-scene.frame_start)/fps, *cam.matrix_world.translation])
    scene.frame_set(original_frame)
    np.savez_compressed(output/'camera_matrices_opencv.npz', K=K,
                        camera_to_world=np.array(transforms), world_to_camera=np.linalg.inv(transforms),
                        frame=[r[0] for r in rows], time_s=[r[1] for r in rows])
    with (output/'camera_trajectory.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['frame', 'time_s', 'x', 'y', 'z'])
        writer.writerows(rows)


def configure_render(scene, mode='clay', samples=32, engine='auto', *, cycles_device='GPU'):
    from .rendering import configure_render as configure
    return configure(scene, mode, samples, engine, cycles_device=cycles_device)


def area_light(name, position, target, energy=700, size=4):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy, data.shape, data.size = energy, 'DISK', size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z', 'Y').to_euler()
    return obj


def cabinet(name, location=(0,0,0), size=(1.2,.55,1.1), material=None, interior=None,
            *, layout=None, instance_id=None, facing_target=None, facing_direction=None):
    """Create an operable cabinet; a layout selects configurable compartments.

    Omitting layout retains the original geometry and writable Open controls.
    New layout controls use open_amount. Both paths return (root, controls).
    """
    if facing_target is not None and facing_direction is not None:
        raise ValueError('Choose one facing_target or facing_direction')
    if facing_direction is not None:
        from .orientation import _direction
        _direction(facing_direction)
    if facing_target is not None:
        from .orientation import _target
        delta = _target(facing_target)[0] - _target(location)[0]
        if math.hypot(delta.x, delta.y) < 1e-8:
            raise ValueError('Facing target has the same horizontal position as the cabinet')
    if layout is not None:
        from .cabinets import build_cabinet
        root, controls = build_cabinet(name, location=location, size=size, material=material,
                                      interior=interior, layout=layout, instance_id=instance_id)
        if facing_target is not None or facing_direction is not None:
            place_root(root, facing_target=facing_target, facing_direction=facing_direction)
        return root, controls
    root, controls = _legacy_cabinet(name, location, size, material, interior)
    from .semantics import tag_root
    tag_root(root, 'furniture/storage/cabinets', instance_id,
             'generator/roomkit-cabinet')
    root['cabinet_legacy_layout'] = True
    from aha3d.orientation import authored_orientation
    from .orientation import tag_orientation
    tag_orientation(root, authored_orientation('door', evidence='src/aha3d/blender/roomkit.py:_legacy_cabinet; doors at negative Y'))
    for control, joint_id in zip(controls, ('door_left', 'door_right', 'drawer')):
        control['joint_id'] = joint_id
        control['joint_type'] = 'slide' if joint_id == 'drawer' else 'hinge'
        control['roomkit_open_property'] = 'Open'
    if facing_target is not None or facing_direction is not None:
        place_root(root, facing_target=facing_target, facing_direction=facing_direction)
    return root, controls


def _legacy_cabinet(name, location=(0,0,0), size=(1.2,.55,1.1), material=None, interior=None):
    """Hollow two-door cabinet plus open-top drawer. Front -Y, local floor Z=0."""
    width, depth, height = size
    if min(size) < .2:
        raise ValueError('Cabinet dimensions must exceed 0.2 m')
    before = set(bpy.data.objects)
    target = collection(name)
    thick = .024
    def part(label, position, dimensions, mat=material):
        return box(name+' | '+label,position,dimensions,mat,target,.004)
    for sign in [-1,1]:
        part('side',(sign*(width-thick)/2,0,height/2),(thick,depth,height))
    for z in [thick/2,height-thick/2]:
        part('horizontal',(0,0,z),(width-2*thick,depth,thick))
    part('back',(0,(depth-thick)/2,height/2),(width-2*thick,thick,height-2*thick))
    part('shelf',(0,.015,height*.40),(width-2*thick,depth-.06,thick),interior)
    part('drawer separator',(0,0,height*.76),(width-2*thick,depth-.04,thick),interior)
    controls=[]
    for sign in [-1,1]:
        x=sign*width/4
        panel=part('door',(x,-depth/2-.014,height*.38),(width/2-.018,.026,height*.71))
        handle=part('handle',(sign*.055,-depth/2-.048,height*.54),(.016,.03,.11),interior)
        ctrl=rig_parts([panel,handle],(sign*(width/2-.008),-depth/2-.014,height*.38),
                       name+(' | Door L' if sign<0 else ' | Door R'),angle_degrees=sign*95)
        controls.append(ctrl)
    drawer_z=height*.88
    front=part('drawer front',(0,-depth/2-.015,drawer_z),(width-.035,.026,height*.19))
    handle=part('drawer handle',(0,-depth/2-.05,drawer_z),(.23,.035,.016),interior)
    bottom_z=height*.79
    drawer=[front,handle,part('drawer bottom',(0,0,bottom_z),(width-.10,depth-.09,.02),interior)]
    for sign in [-1,1]:
        drawer.append(part('drawer side',(sign*(width/2-.06),0,bottom_z+height*.06),(.02,depth-.09,height*.12),interior))
    drawer.append(part('drawer back',(0,depth/2-.055,bottom_z+height*.06),(width-.10,.02,height*.12),interior))
    controls.append(rig_parts(drawer,(0,-depth/2,drawer_z),name+' | Drawer',axis='Y',travel_m=-depth*.60))
    root=bpy.data.objects.new(name+' | placement root',None)
    target.objects.link(root)
    for obj in set(bpy.data.objects)-before-{root}:
        if obj.parent is None:
            parent_keep_world(obj,root)
    root.location=location
    return root,controls
