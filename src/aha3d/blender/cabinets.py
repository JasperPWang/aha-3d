"""Configurable cabinet construction using native Blender hierarchy and drivers."""
import json
import math

import bpy

from aha3d.cabinet_layout import cabinet_preset, normalize_layout
from .roomkit import box, collection, parent_keep_world, rig_parts
from .semantics import tag_root, tag_surface, tag_support


def build_cabinet(name, location=(0, 0, 0), size=(1.2, .55, 1.1),
                  material=None, interior=None, layout=None, instance_id=None):
    """Create a hollow, operable cabinet and return ``(root, controls)``.

    ``layout`` is a recipe mapping or preset name (default, three_drawers, mixed,
    open_shelving). All dimensions and partitions are checked before scene
    mutation. Local -Y is the front; root Z=0 is the cabinet's floor. ``size``
    describes the carcass; doors and handles protrude in front of it. Rotate or
    move only the returned root for placement. Controls are ordered by column,
    bottom-to-top section, and left/right door or bottom-to-top drawer.

    Each independent joint uses ``open_amount`` in [0, 1]; transformations use
    native clamped drivers and remain editable after save/reopen without this
    module. This generator does not test scene obstacles or human contacts.
    """
    plan = normalize_layout(layout, size)
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name must be a nonempty string')
    if (len(location) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                               or not math.isfinite(v) for v in location)):
        raise ValueError('location must have three finite coordinates')
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        raise ValueError('instance_id must be a nonempty string')
    if instance_id is not None and any(o.get('instance_id') == instance_id for o in bpy.data.objects):
        raise ValueError('Duplicate cabinet instance_id: ' + instance_id)
    target = collection(name)
    root = bpy.data.objects.new(name + ' | placement root', None)
    target.objects.link(root)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = .2
    tag_root(root, 'furniture/storage/cabinets', instance_id=instance_id,
             asset_id='generator/roomkit-cabinet')
    root['cabinet_layout_json'] = json.dumps(plan, sort_keys=True)
    root['asset_origin'] = 'carcass_floor_center'
    root['asset_front_axis'] = '-Y'
    from aha3d.orientation import authored_orientation
    from .orientation import tag_orientation
    tag_orientation(root, authored_orientation('door', evidence='src/aha3d/blender/cabinets.py: front panels at negative Y; carcass floor root'))
    root['articulation_schema_version'] = 1
    width, depth, height = plan['size_m']
    tag_support(root, -width / 2, width / 2, -depth / 2, depth / 2, height)
    thick, front, gap = plan['panel_thickness'], plan['front_thickness'], plan['gap']
    inner_y0, inner_y1 = -depth / 2 + gap, depth / 2 - thick
    inner_depth = inner_y1 - inner_y0
    inside_mat = material if interior is None else interior
    controls = []

    def part(label, position, dimensions, inside=False, role='cabinet_body'):
        mat = inside_mat if inside else material
        obj = box(name + ' | ' + label, position, dimensions, mat, target,
                  min(.004, min(dimensions) / 5))
        obj.parent = root
        obj['cabinet_part'] = role
        tag_surface(obj, 'handle_metal' if role == 'handle' else
                    'cabinet_interior' if inside else 'cabinet_finish')
        return obj

    def joint(parts, pivot, label, joint_id, angle=None, travel=None):
        ctrl = rig_parts(parts, pivot, name + ' | ' + label,
                         axis='Z' if travel is None else 'Y',
                         angle_degrees=0 if angle is None else angle, travel_m=travel)
        for col in list(ctrl.users_collection):
            col.objects.unlink(ctrl)
        target.objects.link(ctrl)
        parent_keep_world(ctrl, root)
        ctrl['open_amount'] = 0.
        ctrl.id_properties_ui('open_amount').update(min=0., max=1., soft_min=0., soft_max=1.,
                                                   description='0 closed, 1 fully open')
        for fc in ctrl.animation_data.drivers:
            for var in fc.driver.variables:
                for ref in var.targets:
                    if ref.id == ctrl and ref.data_path == '["Open"]':
                        ref.data_path = '["open_amount"]'
        del ctrl['Open']
        ctrl['joint_id'] = joint_id
        ctrl['joint_type'] = 'hinge' if travel is None else 'slider'
        ctrl['joint_axis'] = 'Z' if travel is None else 'Y'
        ctrl['joint_limit'] = math.radians(angle) if travel is None else travel
        ctrl['joint_limit_unit'] = 'radians' if travel is None else 'metres'
        ctrl['joint_closed_location'] = list(pivot)
        ctrl['joint_closed_rotation'] = [0., 0., 0.]
        ctrl['roomkit_open_property'] = 'open_amount'
        ctrl['cabinet_part'] = 'joint'
        controls.append(ctrl)
        return ctrl

    for sign in (-1, 1):
        part('side ' + ('left' if sign < 0 else 'right'),
             (sign * (width - thick) / 2, 0, height / 2), (thick, depth, height))
    for label, z in [('bottom', thick / 2), ('top', height - thick / 2)]:
        part(label, (0, 0, z), (width - 2 * thick, depth, thick))
    part('back', (0, (depth - thick) / 2, height / 2),
         (width - 2 * thick, thick, height - 2 * thick), True)

    for column in plan['columns']:
        ci, cx, cw = column['index'], column['x'], column['width']
        if ci:
            part('column divider ' + str(ci), (cx - cw / 2 - thick / 2,
                 (inner_y0 + inner_y1) / 2, height / 2),
                 (thick, inner_depth, height - 2 * thick), True, 'divider')
        for section in column['sections']:
            si, z0, sh = section['index'], section['bottom'], section['height']
            prefix = 'c{}s{}'.format(ci, si)
            if si:
                part(prefix + ' separator', (cx, (inner_y0 + inner_y1) / 2, z0 - thick / 2),
                     (cw, inner_depth, thick), True, 'separator')
            for shelf_index, p in enumerate(section['shelves']):
                part(prefix + ' shelf ' + str(shelf_index),
                     (cx, (inner_y0 + inner_y1) / 2, z0 + p * sh),
                     (cw, inner_depth, thick), True, 'shelf')
            # Split vertical pieces at each shelf, avoiding overlapping solids.
            edges = [z0] + [z0 + p * sh for p in section['shelves']] + [z0 + sh]
            for di, p in enumerate(section['dividers']):
                for band, (lo, hi) in enumerate(zip(edges, edges[1:])):
                    low = lo + (thick / 2 if band else 0)
                    high = hi - (thick / 2 if band < len(edges) - 2 else 0)
                    part(prefix + ' divider {} band {}'.format(di, band),
                         (cx - cw / 2 + p * cw, (inner_y0 + inner_y1) / 2, (low + high) / 2),
                         (thick, inner_depth, high - low), True, 'divider')
            kind = section['front']
            if kind in ('door_left', 'door_right', 'double_door'):
                signs = (-1, 1) if kind == 'double_door' else (-1,) if kind == 'door_left' else (1,)
                door_width = (cw - gap) / len(signs) - gap
                for sign in signs:
                    side = 'left' if sign < 0 else 'right'
                    pivot_x = cx + sign * (cw / 2 - gap / 2)
                    door_x = pivot_x - sign * door_width / 2
                    door_y = -depth / 2 - front / 2 - gap
                    door_z = z0 + sh / 2
                    panel = part(prefix + ' door ' + side, (door_x, door_y, door_z),
                                 (door_width, front, sh - gap), role='door')
                    handle_height = min(.11, (sh - gap) * .45)
                    handle_x = pivot_x - sign * (door_width - min(.045, door_width * .2))
                    handle = part(prefix + ' handle ' + side,
                                  (handle_x, door_y - front / 2 - .014, door_z),
                                  (.016, .028, handle_height), True, 'handle')
                    joint([panel, handle], (pivot_x, door_y, door_z), prefix + ' Door ' + side,
                          prefix + '.door.' + side, angle=sign * plan['door_angle_degrees'])
            elif kind == 'drawers':
                drawer_bottom = z0
                for di, dh in enumerate(section['drawer_heights']):
                    label = prefix + ' drawer ' + str(di)
                    body_thick = min(.016, thick)
                    bottom_thick = min(.014, thick)
                    drawer_width = cw - 2 * gap
                    body_front = -depth / 2 - gap
                    body_back = depth / 2 - thick - gap
                    body_depth = body_back - body_front
                    body_y = (body_front + body_back) / 2
                    box_bottom = drawer_bottom + gap
                    box_height = (dh - 2 * gap) * .8
                    wall_height = box_height - bottom_thick
                    drawer_z = drawer_bottom + dh / 2
                    front_y = -depth / 2 - front / 2 - gap
                    moving = [part(label + ' front', (cx, front_y, drawer_z),
                                   (cw - gap, front, dh - gap), role='drawer_front'),
                              part(label + ' handle', (cx, front_y - front / 2 - .014, drawer_z),
                                   (min(.23, cw * .55), .028, .016), True, 'handle'),
                              part(label + ' bottom', (cx, body_y, box_bottom + bottom_thick / 2),
                                   (drawer_width, body_depth, bottom_thick), True, 'drawer_bottom')]
                    for sign in (-1, 1):
                        moving.append(part(label + ' side ' + str(sign),
                            (cx + sign * (drawer_width - body_thick) / 2, body_y,
                             box_bottom + bottom_thick + wall_height / 2),
                            (body_thick, body_depth, wall_height), True, 'drawer_side'))
                    moving.append(part(label + ' back', (cx, body_back - body_thick / 2,
                        box_bottom + bottom_thick + wall_height / 2),
                        (drawer_width - 2 * body_thick, body_thick, wall_height), True, 'drawer_back'))
                    joint(moving, (cx, -depth / 2, drawer_z), label,
                          prefix + '.drawer.' + str(di),
                          travel=-body_depth * plan['drawer_travel_fraction'])
                    drawer_bottom += dh
    root['joint_ids_json'] = json.dumps([c['joint_id'] for c in controls])
    root.location = location
    bpy.context.view_layer.update()
    return root, controls
