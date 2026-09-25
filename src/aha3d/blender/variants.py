"""Deterministic scene variants; importable without bpy for recipe validation.

Version 1 supports independent model and material operations. Geometry replacements
retain the semantic root transform/ID. Static objects get independent object trees
with shared mesh data; material assignment uses OBJECT slots to avoid mesh bleed.
"""
import copy
import json
import math
import random
from pathlib import Path

from aha3d.assets import resolve_item
from aha3d.io import signature
from aha3d.orientation import normalize_orientation, canonical_rotation, canonical_orientation


def _keys(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(label + ' has unknown fields: ' + ', '.join(sorted(unknown)))


def _selector(value):
    _keys(value, ('instance_ids', 'semantic_class'), 'selector')
    if len(value) != 1:
        raise ValueError('selector requires exactly one of instance_ids or semantic_class')
    if 'instance_ids' in value:
        ids = value['instance_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i for i in ids):
            raise ValueError('instance_ids requires a nonempty list of strings')
        if len(ids) != len(set(ids)):
            raise ValueError('instance_ids contains duplicates')
    elif not isinstance(value['semantic_class'], str) or not value['semantic_class'].strip('/'):
        raise ValueError('semantic_class requires a slash-delimited class')


def validate_recipe(recipe):
    _keys(recipe, ('schema_version', 'seed', 'models', 'materials', 'clear_material_override'), 'recipe')
    if type(recipe.get('schema_version')) is not int or recipe['schema_version'] != 1:
        raise ValueError('recipe.schema_version must be 1')
    if isinstance(recipe.get('seed', 0), bool) or not isinstance(recipe.get('seed', 0), int):
        raise ValueError('seed must be an integer')
    if not isinstance(recipe.get('clear_material_override', False), bool):
        raise ValueError('clear_material_override must be boolean')
    if not recipe.get('models') and not recipe.get('materials') and not recipe.get('clear_material_override'):
        raise ValueError('Recipe has no operations')
    for kind in ('models', 'materials'):
        if not isinstance(recipe.get(kind, []), list):
            raise ValueError(kind + ' must be a list')
        for op in recipe.get(kind, []):
            extra = ('fit',) if kind == 'models' else ('surface_role', 'parameters')
            _keys(op, ('selector', 'asset_id', 'asset_ids', 'allow_no_matches') + extra, kind + ' operation')
            if ('asset_id' in op) == ('asset_ids' in op):
                raise ValueError('Operation requires exactly one of asset_id or asset_ids')
            choices = [op['asset_id']] if 'asset_id' in op else op['asset_ids']
            if not isinstance(choices, list) or not choices or any(not isinstance(i, str) or not i for i in choices):
                raise ValueError('Asset choices require nonempty registered ID strings')
            if len(choices) != len(set(choices)):
                raise ValueError('Asset choices contain duplicates')
            if not isinstance(op.get('allow_no_matches', False), bool):
                raise ValueError('allow_no_matches must be boolean')
            if kind == 'models' or 'selector' in op:
                _selector(op.get('selector'))
            if kind == 'models':
                if op.get('fit') not in ('native', 'uniform_footprint'):
                    raise ValueError('Model fit must explicitly be native or uniform_footprint')
            else:
                if not isinstance(op.get('surface_role'), str) or not op['surface_role']:
                    raise ValueError('Material operation requires surface_role')
                params = op.get('parameters', {})
                _keys(params, ('color', 'roughness'), 'material parameters')
                if 'roughness' in params and (isinstance(params['roughness'], bool) or
                        not isinstance(params['roughness'], (int, float)) or not 0 <= params['roughness'] <= 1):
                    raise ValueError('roughness must be in [0, 1]')
                if 'color' in params:
                    color = params['color']
                    if (not isinstance(color, list) or len(color) not in (3, 4) or
                            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in color)):
                        raise ValueError('color must contain 3 or 4 linear RGBA values in [0, 1]')
    return copy.deepcopy(recipe)


def class_matches(actual, requested):
    requested = requested.strip('/')
    return actual == requested or actual.startswith(requested + '/')


def _selected(selector, all_roots, allow_none=False):
    if 'instance_ids' in selector:
        by_id = {root['instance_id']: root for root in all_roots}
        missing = sorted(set(selector['instance_ids']) - set(by_id))
        if missing and not allow_none:
            raise ValueError('Unknown instance IDs: ' + ', '.join(missing))
        return [by_id[i] for i in sorted(selector['instance_ids']) if i in by_id]
    return [root for root in all_roots if class_matches(root.get('semantic_class', ''), selector['semantic_class'])]


def _objects(root):
    from .semantics import descendants
    return [root] + descendants(root)


def _bounds(root):
    """Evaluated bounds in root coordinates, including legacy collection instances."""
    import bpy
    from mathutils import Matrix, Vector
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    inverse = root.matrix_world.inverted_safe()
    points = []

    def visit(obj, world, seen):
        if obj.type in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META'):
            evaluated = obj.evaluated_get(graph)
            points.extend(inverse @ world @ Vector(corner) for corner in evaluated.bound_box)
        col = obj.instance_collection if obj.instance_type == 'COLLECTION' else None
        if col and col.name not in seen:
            offset = Matrix.Translation(-col.instance_offset)
            for source in col.all_objects:
                visit(source, world @ offset @ source.matrix_world, seen | {col.name})

    for obj in _objects(root):
        visit(obj, obj.matrix_world, set())
    if not points:
        raise ValueError('No renderable geometry under ' + root.name)
    return ([min(point[i] for point in points) for i in range(3)],
            [max(point[i] for point in points) for i in range(3)])


def _assert_replaceable(root):
    import bpy
    from .semantics import descendants
    if root.type != 'EMPTY' or root.instance_type != 'NONE':
        raise ValueError(root.name + ': tag_root must provide an Empty replacement slot')
    objects = _objects(root)
    for obj in objects:
        if obj != root and obj.get('instance_id'):
            raise ValueError(root.name + ': contains nested semantic roots; replace those instances separately')
        if any(obj.get(key) for key in ('active_contact', 'contact_locked', 'motion_contact')):
            raise ValueError(root.name + ': active contact requires a reviewed motion/contact update')
        ad = obj.animation_data
        # Cabinet joint drivers are safe only for a static, closed source cabinet.
        if ad and (ad.action or ad.nla_tracks):
            raise ValueError(root.name + ': animated replacement is unsupported')
        if ad and ad.drivers and not obj.get('joint_id'):
            raise ValueError(root.name + ': non-joint drivers make replacement unsafe')
        if obj.get('joint_id') and abs(float(obj.get('open_amount', obj.get('Open', 0)))) > 1e-6:
            raise ValueError(root.name + ': close cabinet joints before replacement')
        if obj.constraints or any(mod.type == 'ARMATURE' for mod in obj.modifiers):
            raise ValueError(root.name + ': constrained/deformed replacement is unsupported')
    removed = set(descendants(root))

    def points_to_removed(value):
        if isinstance(value, bpy.types.ID):
            return value in removed
        if hasattr(value, 'items'):
            try:
                items = value.items()
            except TypeError:  # RNA structs can expose items() without IDProperty support.
                return False
            return any(points_to_removed(item) for _, item in items)
        if isinstance(value, (list, tuple)):
            return any(points_to_removed(item) for item in value)
        return False

    def pointer_dependency(block):
        if block is None:
            return False
        return any(points_to_removed(getattr(block, prop.identifier, None))
                   for prop in block.bl_rna.properties
                   if prop.type == 'POINTER' and prop.identifier != 'rna_type')

    for other in bpy.context.scene.objects:
        if other in objects:
            continue
        if points_to_removed(dict(other.items())) or (other.data and points_to_removed(dict(other.data.items()))):
            raise ValueError(root.name + ': an external custom object reference targets its geometry')
        for modifier in other.modifiers:
            if pointer_dependency(modifier):
                raise ValueError(root.name + ': an external modifier targets its geometry')
        if pointer_dependency(other.rigid_body_constraint):
            raise ValueError(root.name + ': an external rigid body constraint targets its geometry')
        for constraint in other.constraints:
            if pointer_dependency(constraint) or any(pointer_dependency(target) for target in getattr(constraint, 'targets', [])):
                raise ValueError(root.name + ': another object constraint targets its geometry')
        if other.animation_data:
            for curve in other.animation_data.drivers:
                for variable in curve.driver.variables:
                    if any(target.id in removed for target in variable.targets):
                        raise ValueError(root.name + ': an external driver targets its geometry')
    visited = set()

    def check_nodes(tree):
        if tree is None or tree in visited:
            return
        visited.add(tree)
        for node in tree.nodes:
            if pointer_dependency(node):
                raise ValueError(root.name + ': an external material node targets its geometry')
            if node.type == 'GROUP':
                check_nodes(node.node_tree)

    external_materials = {slot.material for obj in bpy.context.scene.objects if obj not in removed
                          for slot in obj.material_slots if slot.material}
    for material in external_materials:
        check_nodes(material.node_tree if material.use_nodes else None)


def _asset_info(card):
    return {key: card[key] for key in ('id', 'library_id', 'library', 'library_sha256', 'manifest_sha256', 'datablock', 'orientation') if key in card}


def _prepare(recipe, project_root=None):
    import bpy
    from .semantics import roots, surface_slots
    from .orientation import get_orientation, facing_report, _placement
    recipe = validate_recipe(recipe)
    all_roots = roots()
    rng = random.Random(recipe.get('seed', 0))
    cache, models, materials = {}, [], []

    def get_asset(identity, kind):
        key = (identity, kind)
        if key not in cache:
            card = resolve_item(identity, root=project_root, expected_kind=kind)
            if kind == 'collection':
                normalize_orientation(card.get('orientation'), require_trusted=True)
            with bpy.data.libraries.load(card['library'], link=False) as (source, dest):
                available = source.collections if kind == 'collection' else source.materials
                if card['datablock'] not in available:
                    raise ValueError('Registered datablock missing from library: ' + identity)
            cache[key] = card
        return cache[key]

    affected = set()
    for op in recipe.get('models', []):
        candidates = [get_asset(identity, 'collection') for identity in op.get('asset_ids', [op.get('asset_id')])]
        matched = _selected(op['selector'], all_roots, op.get('allow_no_matches', False))
        if not matched and not op.get('allow_no_matches', False):
            raise ValueError('Model selector matched no semantic roots')
        for root in matched:
            if root in affected:
                raise ValueError('Multiple model operations select ' + root['instance_id'])
            _assert_replaceable(root)
            source_orientation = get_orientation(root, require_trusted=True)
            _placement(root)
            if source_orientation['up_axis'] != 'Z' or source_orientation['front_axis'] not in ('-Y', None):
                raise ValueError(root.name + ': replacement slot must use canonical -Y/Z coordinates; migrate its root explicitly')
            before_facing = facing_report(root)
            if before_facing['status'] == 'fail':
                raise ValueError(root.name + ': current facing violates its stored target; correct placement before replacement')
            card = rng.choice(candidates)
            target_orientation = normalize_orientation(card['orientation'], require_trusted=True)
            if source_orientation['symmetry'] != target_orientation['symmetry']:
                raise ValueError(root.name + ': replacement changes directional symmetry; review the slot facing explicitly')
            for field in ('origin', 'semantic_front'):
                if source_orientation[field] != target_orientation[field]:
                    raise ValueError(root.name + ': replacement changes orientation ' + field + '; supply an explicit reviewed anchor/frame adaptation')
            if not (class_matches(card['category'], root['semantic_class']) or
                    class_matches(root['semantic_class'], card['category'])):
                raise ValueError('Incompatible category {} for {}'.format(card['category'], root['semantic_class']))
            if card['manifest_item'].get('articulation') or card['manifest_item'].get('import_mode') == 'articulated':
                matrix = root.matrix_world.to_3x3()
                columns = [matrix.col[i] for i in range(3)]
                lengths = [column.length for column in columns]
                if (min(lengths) <= 0 or max(lengths) - min(lengths) > 1e-5 or
                        matrix.determinant() <= 0 or any(abs(columns[i].dot(columns[j])) > 1e-5
                        for i, j in ((0, 1), (0, 2), (1, 2)))):
                    raise ValueError(root.name + ': articulated replacement requires a positive uniform transform without shear')
            bounds = _bounds(root)
            dims = card.get('dimensions_m')
            if not dims or len(dims) != 3 or any(not math.isfinite(v) or v <= 0 for v in dims):
                raise ValueError('Registered collection requires valid dimensions_m: ' + card['id'])
            rotation = canonical_rotation(target_orientation)
            dims = [sum(abs(rotation[i][j]) * dims[j] for j in range(3)) for i in range(3)]
            factor = 1.
            if op['fit'] == 'uniform_footprint':
                factor = min((bounds[1][i] - bounds[0][i]) / dims[i] for i in (0, 1))
                if not math.isfinite(factor) or factor <= 0:
                    raise ValueError('Target footprint cannot define a uniform fit')
            models.append({'root': root, 'card': card, 'fit': op['fit'], 'scale': factor, 'before_bounds': bounds})
            affected.add(root)
    deleted = {obj for root in affected for obj in _objects(root)[1:]}
    assigned_slots = set()
    for op in recipe.get('materials', []):
        candidates = [get_asset(identity, 'material') for identity in op.get('asset_ids', [op.get('asset_id')])]
        selected = None
        if 'selector' in op:
            selected = {obj for root in _selected(op['selector'], all_roots, op.get('allow_no_matches', False)) for obj in _objects(root)}
        count = 0
        for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
            if selected is not None and obj not in selected:
                continue
            slots = [slot for slot, role in surface_slots(obj).items() if role == op['surface_role']]
            if not slots:
                continue
            if obj in deleted:
                raise ValueError('Material operation targets replaced geometry; apply it in a second recipe to the saved result')
            if not hasattr(obj.data, 'materials') or obj.library or obj.data.library:
                raise ValueError('Surface must have local editable material slots: ' + obj.name)
            if any(slot >= max(1, len(obj.material_slots)) for slot in slots):
                raise ValueError('Stale surface slot metadata: ' + obj.name)
            for slot in slots:
                if (obj, slot) in assigned_slots:
                    raise ValueError('Multiple operations select surface slot: ' + obj.name)
                assigned_slots.add((obj, slot))
            materials.append({'object': obj, 'slots': slots, 'role': op['surface_role'],
                              'card': rng.choice(candidates), 'parameters': op.get('parameters', {})})
            count += len(slots)
        if not count and not op.get('allow_no_matches', False):
            raise ValueError('Material role matched no surfaces: ' + op['surface_role'])
    report = {'schema_version': 1, 'status': 'preflight_passed', 'recipe': recipe,
              'recipe_sha256': signature(recipe), 'seed': recipe.get('seed', 0),
              'assets': [_asset_info(cache[key]) for key in sorted(cache)],
              'models': [{'instance_id': op['root']['instance_id'], 'asset_id': op['card']['id'],
                          'fit': op['fit'], 'uniform_scale': op['scale'],
                          'before_bounds_local': op['before_bounds']} for op in models],
              'materials': [{'object': op['object'].name, 'slots': op['slots'], 'surface_role': op['role'],
                             'asset_id': op['card']['id'], 'parameters': op['parameters']} for op in materials],
              'affected_dependents': [root['instance_id'] for root in all_roots
                                      if root.get('support_id') in {obj['instance_id'] for obj in affected}],
              'clear_material_override': recipe.get('clear_material_override', False),
              'limitations': ['Support checks use local horizontal planes and bounds; no collision or occlusion test.',
                              'Color and roughness parameters explicitly replace the corresponding shader input, including links.',
                              'Texture scale and direction are preserved from each asset; generic parameter remapping is unsupported.']}
    return recipe, models, materials, report


def plan_variant(recipe, project_root=None):
    """Read-only matching, compatibility and asset-hash preflight; no scene mutation."""
    return _prepare(recipe, project_root)[3]


def _import_raw_geometry(card):
    import bpy
    from mathutils import Matrix
    item = card['manifest_item']
    if item.get('articulation') or item.get('import_mode') == 'articulated':
        from .articulated import import_articulated
        root = import_articulated(card['library'], card['datablock'], asset_id=card['id'])
        # This whole imported tree is replaceable content below our stable slot.
        for key in ('instance_id', 'semantic_class', 'asset_id', 'support_id', 'articulated_root'):
            if key in root:
                del root[key]
        return root
    with bpy.data.libraries.load(card['library'], link=False) as (source, dest):
        dest.collections = [card['datablock']]
    col = dest.collections[0]
    for source in col.all_objects:
        if source.animation_data or source.constraints:
            raise ValueError('Static collection contains rig dependencies; register as articulated: ' + card['id'])
    root = bpy.data.objects.new(card['datablock'] + ' geometry', None)
    bpy.context.scene.collection.objects.link(root)
    copies = {}
    for source in col.all_objects:
        obj = source.copy()
        for key in ('instance_id', 'semantic_class', 'asset_id', 'support_id'):
            if key in obj:
                del obj[key]
        bpy.context.scene.collection.objects.link(obj)
        copies[source] = obj
    for source, obj in copies.items():
        if source.parent in copies:
            obj.parent = copies[source.parent]
        else:
            obj.parent = root
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = Matrix.Translation(-col.instance_offset) @ source.matrix_world
    return root


def _import_geometry(card):
    from mathutils import Matrix
    from .orientation import tag_orientation
    orientation = normalize_orientation(card.get('orientation'), require_trusted=True)
    root = _import_raw_geometry(card)
    root.matrix_basis = Matrix(canonical_rotation(orientation)).to_4x4() @ root.matrix_basis
    # The geometry root still owns source-frame children; its parent slot is canonical.
    tag_orientation(root, orientation)
    return root


def _new_material(card, parameters):
    import bpy
    with bpy.data.libraries.load(card['library'], link=False) as (source, dest):
        dest.materials = [card['datablock']]
    material = dest.materials[0]
    # Appending is local; a distinct material for each selected object prevents bleed.
    material = material.copy()
    if parameters:
        shaders = [node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'] if material.use_nodes else []
        if len(shaders) != 1:
            raise ValueError('Parameter override requires exactly one Principled shader: ' + card['id'])
        for key, socket_name in (('color', 'Base Color'), ('roughness', 'Roughness')):
            if key not in parameters:
                continue
            socket = shaders[0].inputs[socket_name]
            for link in list(socket.links):
                material.node_tree.links.remove(link)
            value = parameters[key]
            socket.default_value = value + [1.] if key == 'color' and len(value) == 3 else value
    material['asset_id'] = card['id']
    material['variant_parameters'] = json.dumps(parameters, sort_keys=True)
    return material



def _capability_metadata(geometry, card):
    """Metadata promoted onto the stable slot, in that slot's coordinates."""
    import bpy
    from mathutils import Vector
    bpy.context.view_layer.update()
    result = {'asset_articulated': bool(card['manifest_item'].get('articulation') or
                                      card['manifest_item'].get('import_mode') == 'articulated'),
              'asset_import_mode': card['manifest_item'].get('import_mode', 'static')}
    orientation = canonical_orientation(card['orientation'])
    result['asset_orientation_json'] = json.dumps(orientation, sort_keys=True)
    result['asset_up_axis'] = orientation['up_axis']
    result['asset_origin'] = orientation['origin']
    if orientation['front_axis'] is not None:
        result['asset_front_axis'] = orientation['front_axis']
    for key in ('cabinet_layout_json', 'cabinet_legacy_layout', 'joint_ids_json',
                'articulation_schema_version'):
        if key in geometry:
            result[key] = geometry[key]
    if geometry.get('support_plane'):
        plane = json.loads(geometry['support_plane'])
        matrix = geometry.matrix_basis
        points = [matrix @ Vector((x, y, plane['z'])) for x in (plane['xmin'], plane['xmax'])
                  for y in (plane['ymin'], plane['ymax'])]
        if max(point.z for point in points) - min(point.z for point in points) > 1e-5:
            raise ValueError('Imported support plane is not horizontal in its semantic slot')
        result['support_plane'] = json.dumps(dict(xmin=min(p.x for p in points), xmax=max(p.x for p in points),
            ymin=min(p.y for p in points), ymax=max(p.y for p in points), z=sum(p.z for p in points) / 4))
    return result


def _set_capabilities(root, metadata):
    # Clear model-owned fields before applying replacement metadata. Placement,
    # identity and the support_id relationship belong to the scene and stay.
    for key in ('support_plane', 'cabinet_layout_json', 'cabinet_legacy_layout', 'joint_ids_json',
                'articulation_schema_version', 'asset_origin', 'asset_front_axis',
                'asset_articulated', 'asset_import_mode', 'asset_orientation_json', 'asset_up_axis'):
        if key in root:
            del root[key]
    for key, value in metadata.items():
        root[key] = value


def place_asset(asset_id, location=(0, 0, 0), rotation=None, scale=1, instance_id=None, project_root=None, *, facing_target=None, facing_direction=None):
    """Place a registered collection at a tagged slot; scale is positive and uniform."""
    import bpy
    from .semantics import tag_root
    from .orientation import _target, _direction, place_root
    if sum(value is not None for value in (rotation, facing_target, facing_direction)) > 1:
        raise ValueError('Choose only one rotation, facing_target or facing_direction')
    if facing_direction is not None:
        _direction(facing_direction)
    if rotation is not None and (isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation)):
        raise ValueError('rotation must be finite degrees')
    if not isinstance(location, (list, tuple)) or len(location) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in location):
        raise ValueError('location must contain three finite coordinates')
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip() or
            any(obj.get('instance_id') == instance_id for obj in bpy.context.scene.objects)):
        raise ValueError('instance_id must be nonempty and unique')
    if facing_target is not None:
        bpy.context.view_layer.update()
        point, _ = _target(facing_target)
        if math.hypot(point.x-location[0], point.y-location[1]) < 1e-8:
            raise ValueError('Facing target has the same horizontal position as the asset')
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('place_asset scale must be a positive uniform scalar')
    card = resolve_item(asset_id, root=project_root, expected_kind='collection')
    orientation = normalize_orientation(card.get('orientation'), require_trusted=True)
    if (facing_target is not None or facing_direction is not None) and orientation['symmetry'] != 'none':
        raise ValueError('Asset has no unique front; facing intent is not applicable')
    geometry = _import_geometry(card)
    root = bpy.data.objects.new(card['datablock'] + ' slot', None)
    bpy.context.scene.collection.objects.link(root)
    geometry.parent = root
    root.location = location
    root.rotation_euler.z = math.radians(rotation or 0)
    root.scale = (scale,) * 3
    tag_root(root, card['category'], instance_id=instance_id, asset_id=asset_id)
    _set_capabilities(root, _capability_metadata(geometry, card))
    if facing_target is not None or facing_direction is not None:
        place_root(root, facing_target=facing_target, facing_direction=facing_direction)
    return root


def _support_report(root, all_roots):
    from mathutils import Vector
    identity = root.get('support_id')
    if not identity:
        return None
    support = next((obj for obj in all_roots if obj['instance_id'] == identity), None)
    if support is None or not support.get('support_plane'):
        return {'support_id': identity, 'status': 'unverified', 'reason': 'Missing support root or explicit support_plane'}
    plane = json.loads(support['support_plane'])
    low, high = _bounds(root)
    transform = support.matrix_world.inverted_safe() @ root.matrix_world
    corners = [transform @ Vector((x, y, z)) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    gap = min(p.z for p in corners) - plane['z']
    inside = all(plane['xmin'] <= p.x <= plane['xmax'] and plane['ymin'] <= p.y <= plane['ymax'] for p in corners)
    return {'support_id': identity, 'status': 'bounds_checked', 'gap_m_local': gap, 'inside_bounds': inside,
            'passes_tolerance': inside and abs(gap) <= .01}


def apply_variant(recipe, project_root=None):
    """Preflight every operation, stage imports, then replace; returns provenance report.

    Save to a distinct .blend after success. This does not save or alter source files.
    """
    import bpy
    from mathutils import Matrix
    from .semantics import descendants, roots
    recipe, models, materials, report = _prepare(recipe, project_root)
    staged = []
    try:
        for op in models:
            geometry = _import_geometry(op['card'])
            staged.append(geometry)
            geometry.scale *= op['scale']
            op['geometry'] = geometry
            op['capabilities'] = _capability_metadata(geometry, op['card'])
        for op in materials:
            op['material'] = _new_material(op['card'], op['parameters'])
    except Exception:
        for root in staged:
            for obj in reversed([root] + descendants(root)):
                bpy.data.objects.remove(obj, do_unlink=True)
        raise
    for op, item in zip(models, report['models']):
        root = op['root']
        world = root.matrix_world.copy()
        for obj in reversed(descendants(root)):
            bpy.data.objects.remove(obj, do_unlink=True)
        geometry = op['geometry']
        geometry.parent = root
        geometry.matrix_parent_inverse = Matrix.Identity(4)
        _set_capabilities(root, op['capabilities'])
        root['asset_id'] = op['card']['id']
        root['variant_fit'] = op['fit']
        root['variant_uniform_scale'] = op['scale']
        root.matrix_world = world
        item['matrix_world_preserved'] = [list(row) for row in world]
    for op in materials:
        obj = op['object']
        if not obj.material_slots:
            # Adding a slot alters mesh data; make single-user first in that case.
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.data.materials.append(op['material'])
        for index in op['slots']:
            obj.material_slots[index].link = 'OBJECT'
            obj.material_slots[index].material = op['material']
    if recipe.get('clear_material_override'):
        for layer in bpy.context.scene.view_layers:
            layer.material_override = None
    bpy.context.view_layer.update()
    all_roots = roots()
    for op, item in zip(models, report['models']):
        item['after_bounds_local'] = _bounds(op['root'])
        item['support_check'] = _support_report(op['root'], all_roots)
        from .orientation import facing_report
        item['facing_check'] = facing_report(op['root'])
    by_id = {root['instance_id']: root for root in all_roots}
    report['dependent_support_checks'] = [{'instance_id': identity,
        'support_check': _support_report(by_id[identity], all_roots)}
        for identity in report['affected_dependents']]
    report['status'] = 'applied'
    bpy.context.scene['variant_provenance'] = json.dumps(report, sort_keys=True)
    return report
