"""Portable furniture rigs with independent native Blender controls.

Run in Blender. Unlike a collection instance, each import owns its object tree
and drivers. Geometry and materials may be shared between imported instances.
Source timeline keys are omitted on export so libraries always start closed.
"""
import hashlib
import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from aha3d.orientation import canonical_orientation, canonical_rotation, normalize_orientation


FORMAT_VERSION = 1
_CONTROL_PROPERTIES = ('open_amount', 'Open')
_CATALOG = 'RoomKit/Furniture/Cabinets'
_CATALOG_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, 'blender-roomkit/' + _CATALOG))


def _tree(root):
    return [root] + list(root.children_recursive)


def _id_values(value):
    if isinstance(value, bpy.types.ID):
        yield value
    elif hasattr(value, 'items'):
        for _, item in value.items():
            yield from _id_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _id_values(item)


def _pointer_items(block):
    """Writable RNA ID pointers on a modifier, constraint, or node."""
    for prop in block.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.type != 'POINTER':
            continue
        value = getattr(block, prop.identifier, None)
        if isinstance(value, bpy.types.ID):
            yield prop.identifier, value


def _walk_nodes(tree, seen=None):
    seen = set() if seen is None else seen
    if tree is None or tree in seen:
        return
    seen.add(tree)
    yield tree
    for node in tree.nodes:
        if node.type == 'GROUP' and node.node_tree:
            yield from _walk_nodes(node.node_tree, seen)


def _materials(objects):
    return set(slot.material for obj in objects for slot in obj.material_slots if slot.material)


def _validate(objects, root):
    owned = set(objects)

    def object_reference(value, context):
        if not isinstance(value, bpy.types.Object) or value not in owned:
            raise ValueError('Unsupported external dependency in {}: {}'.format(context, value.name))

    for obj in objects:
        if obj.type not in {'EMPTY', 'MESH'}:
            raise ValueError('Unsupported articulated object type: {} ({})'.format(obj.name, obj.type))
        if obj.instance_type != 'NONE' or obj.instance_collection:
            raise ValueError('Realize nested collection instances before export: ' + obj.name)
        if obj != root and obj.parent not in owned:
            raise ValueError('Hierarchy is not closed: ' + obj.name)
        if obj.parent_type != 'OBJECT':
            raise ValueError('Only object parenting is supported: ' + obj.name)
        if obj.data and (obj.data.animation_data or obj.data.shape_keys):
            raise ValueError('Animated mesh data and shape keys are unsupported: ' + obj.name)
        for value in _id_values(dict(obj.items())):
            object_reference(value, obj.name + ' custom properties')
        if obj.data:
            for value in _id_values(dict(obj.data.items())):
                raise ValueError('Object/data references in shared mesh properties are unsupported: ' + obj.name)
        for block in list(obj.modifiers) + list(obj.constraints):
            for prop, value in _pointer_items(block):
                object_reference(value, '{}.{}.{}'.format(obj.name, block.name, prop))
            # Multi-target constraints contain additional pointer records.
            for target in getattr(block, 'targets', []):
                for prop, value in _pointer_items(target):
                    object_reference(value, '{}.{}.{}'.format(obj.name, block.name, prop))
        animation = obj.animation_data
        if animation:
            for curve in animation.drivers:
                driver = curve.driver
                if driver.type == 'SCRIPTED' and not driver.is_simple_expression:
                    raise ValueError('Driver requires a Python namespace: ' + obj.name + ':' + curve.data_path)
                for variable in driver.variables:
                    if variable.type not in {'SINGLE_PROP', 'TRANSFORMS', 'ROTATION_DIFF', 'LOC_DIFF'}:
                        raise ValueError('Unsupported driver variable: ' + variable.type)
                    for target in variable.targets:
                        if target.id is None:
                            raise ValueError('Unbound driver target: ' + obj.name)
                        object_reference(target.id, obj.name + ' driver')
    if root.constraints:
        raise ValueError('Placement-root constraints must be baked or removed before export')
    if root.animation_data:
        for curve in root.animation_data.drivers:
            if not curve.data_path.startswith('["'):
                raise ValueError('Placement root cannot have transform drivers: ' + root.name)
    for mat in _materials(objects):
        if mat.animation_data:
            raise ValueError('Animated materials are unsupported: ' + mat.name)
        for value in _id_values(dict(mat.items())):
            raise ValueError('Object/data references in shared material properties are unsupported: ' + mat.name)
        for tree in _walk_nodes(mat.node_tree):
            if tree.animation_data:
                raise ValueError('Animated material node trees are unsupported: ' + tree.name)
            for node in tree.nodes:
                for prop, value in _pointer_items(node):
                    if isinstance(value, bpy.types.Object):
                        # Materials can be shared by independent instances only
                        # when their coordinates do not point at a rig object.
                        raise ValueError('Object-dependent material is unsupported: ' + mat.name + ':' + node.name)
                    if not isinstance(value, (bpy.types.Image, bpy.types.NodeTree)):
                        raise ValueError('Unsupported material dependency: ' + value.name)
                    if isinstance(value, bpy.types.Image) and value.source not in {'FILE', 'GENERATED', 'TILED'}:
                        raise ValueError('Unsupported external image sequence/movie: ' + value.name)


def _remapped_id(value, mapping):
    # Blender Object.copy already remaps self-references in some drivers.
    # Cross-object pointers still refer to source IDs and need our full map.
    if value in mapping:
        return mapping[value]
    if value in mapping.values():
        return value
    raise ValueError('Unexpected object dependency while copying: ' + value.name)


def _remap_custom_properties(block, mapping):
    for key, value in list(block.items()):
        if isinstance(value, bpy.types.ID):
            block[key] = _remapped_id(value, mapping)
        elif hasattr(value, 'items'):
            _remap_custom_properties(value, mapping)


def _copy_actions(obj, strip_timeline):
    animation = obj.animation_data
    if not animation:
        return
    if strip_timeline:
        animation.action = None
        for track in list(animation.nla_tracks):
            animation.nla_tracks.remove(track)
    else:
        actions = {}
        def own(action):
            if action not in actions:
                actions[action] = action.copy()
            return actions[action]
        if animation.action:
            animation.action = own(animation.action)
        for track in animation.nla_tracks:
            for strip in track.strips:
                if strip.type == 'CLIP' and strip.action:
                    strip.action = own(strip.action)
                elif strip.type == 'META':
                    raise ValueError('Nested NLA meta strips are unsupported')


def _clone_tree(objects, root, collection, strip_timeline=False):
    mapping = {}
    try:
        for obj in objects:
            clone = obj.copy()
            mapping[obj] = clone
            collection.objects.link(clone)
        for source, clone in mapping.items():
            clone.parent = mapping.get(source.parent)
            clone.matrix_parent_inverse = source.matrix_parent_inverse.copy()
            clone.matrix_basis = source.matrix_basis.copy()
            _copy_actions(clone, strip_timeline)
            _remap_custom_properties(clone, mapping)
            for block in list(clone.modifiers) + list(clone.constraints):
                for prop, value in _pointer_items(block):
                    setattr(block, prop, _remapped_id(value, mapping))
                for target in getattr(block, 'targets', []):
                    for prop, value in _pointer_items(target):
                        setattr(target, prop, _remapped_id(value, mapping))
            if clone.animation_data:
                for curve in clone.animation_data.drivers:
                    for variable in curve.driver.variables:
                        for target in variable.targets:
                            target.id = _remapped_id(target.id, mapping)
        clone_root = mapping[root]
        clone_root.parent = None
        clone_root.matrix_parent_inverse = Matrix.Identity(4)
        return clone_root, mapping
    except Exception:
        for obj in mapping.values():
            bpy.data.objects.remove(obj, do_unlink=True)
        raise


def _copy_export_data(mapping):
    """Own export data before packing images or remapping custom properties."""
    data_map, material_map, tree_map, image_map = {}, {}, {}, {}

    def own_image(source):
        if source not in image_map:
            clone = source.copy()
            image_map[source] = clone
            if clone.source != 'GENERATED' and not clone.packed_file:
                # Resolve relative paths while the source .blend is active.
                clone.filepath = bpy.path.abspath(source.filepath, library=source.library)
                clone.pack()
            if clone.source != 'GENERATED' and not clone.packed_file:
                raise ValueError('Failed to pack texture: ' + source.name)
        return image_map[source]

    def patch_nodes(tree):
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree:
                source = node.node_tree
                if source not in tree_map:
                    tree_map[source] = source.copy()
                    patch_nodes(tree_map[source])
                node.node_tree = tree_map[source]
            if getattr(node, 'image', None):
                node.image = own_image(node.image)

    def own_material(source):
        if source not in material_map:
            clone = source.copy()
            material_map[source] = clone
            _remap_custom_properties(clone, mapping)
            if clone.node_tree:
                patch_nodes(clone.node_tree)
        return material_map[source]

    for source, clone in mapping.items():
        if source.data:
            if source.data not in data_map:
                data_map[source.data] = source.data.copy()
                _remap_custom_properties(data_map[source.data], mapping)
            clone.data = data_map[source.data]
        for index, slot in enumerate(source.material_slots):
            if slot.material:
                clone.material_slots[index].material = own_material(slot.material)
    return list(material_map.values())


def _hash_file(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, bpy.types.ID):
        return {'object': value.name}
    if hasattr(value, 'items'):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [_json_value(item) for item in value]
    except TypeError:
        return str(value)


def _trusted_export_orientation(root, explicit=None):
    """Resolve per-root evidence; old global forward strings are not evidence."""
    data = explicit
    if data is None:
        value = root.get('asset_orientation_json')
        if value is None:
            raise ValueError('Missing trusted orientation for ' + root.name +
                ': author/review the local front/up axes and supply orientation=... '
                'or root["asset_orientation_json"]. Legacy roomkit_forward is not sufficient.')
        try:
            data = json.loads(value)
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid asset_orientation_json on ' + root.name) from error
    return normalize_orientation(data, require_trusted=True)


def _canonical_support_plane(value, rotation):
    plane = json.loads(value)
    corners = [rotation @ Vector((x, y, plane['z']))
               for x in (plane['xmin'], plane['xmax']) for y in (plane['ymin'], plane['ymax'])]
    if max(point.z for point in corners) - min(point.z for point in corners) > 1e-5:
        raise ValueError('Source support_plane is not horizontal after orientation canonicalization; '
                         'supply a correct support declaration in the canonical frame')
    return json.dumps({'xmin': min(point.x for point in corners), 'xmax': max(point.x for point in corners),
                       'ymin': min(point.y for point in corners), 'ymax': max(point.y for point in corners),
                       'z': sum(point.z for point in corners) / 4}, sort_keys=True)


def _orientation_wrapper(rig_root, collection, orientation):
    """Keep joint locals intact beneath a canonical placement root."""
    rotation = Matrix(canonical_rotation(orientation))
    outer = bpy.data.objects.new(rig_root.name + ' | canonical placement root', None)
    collection.objects.link(outer)
    # Promote scene identity and inventory metadata. Actual native controls stay
    # on the copied inner rig and keep their own driver targets.
    for key, value in rig_root.items():
        if key not in _CONTROL_PROPERTIES and key not in {'joint_id', 'joint_type'}:
            outer[key] = value
    if outer.get('support_plane'):
        outer['support_plane'] = _canonical_support_plane(outer['support_plane'], rotation)
    outer['asset_orientation_json'] = json.dumps(canonical_orientation(orientation), sort_keys=True)
    outer['source_orientation_json'] = json.dumps(orientation, sort_keys=True)
    outer['articulated_orientation_wrapper'] = True
    rig_root.parent = outer
    rig_root.matrix_parent_inverse = Matrix.Identity(4)
    rig_root.matrix_basis = rotation.to_4x4()
    for key in ('instance_id', 'semantic_class', 'asset_id', 'support_id', 'asset_root', 'articulated_root'):
        if key in rig_root:
            del rig_root[key]
    # The inner root's orientation now belongs to its local source frame. Keep
    # it only as provenance, so downstream code does not treat it as a second asset.
    if 'asset_orientation_json' in rig_root:
        del rig_root['asset_orientation_json']
    return outer


def export_articulated(root_object, output_directory, asset_name=None, orientation=None):
    """Export a new immutable library directory and return its manifest.

    Explicit authored/reviewed orientation (or root asset_orientation_json) is
    required. A wrapper maps source front/up to canonical -Y/Z without changing
    internal joint coordinates. Source world placement and scale are removed.
    Every origin mode preserves the declared root point for articulated assets:
    floor_center means the authored carcass/support origin, not protruding-handle
    or moving-pose bounds. Static floor_center exports instead recenter geometry.
    Source timeline animation is removed from copies, controls start at zero,
    and native drivers/constraints survive. The source scene is never saved or
    modified. Output directories must not exist, preventing version overwrite.
    """
    root = bpy.data.objects.get(root_object) if isinstance(root_object, str) else root_object
    if root is None:
        raise ValueError('Missing articulated root: ' + str(root_object))
    source_orientation = _trusted_export_orientation(root, orientation)
    orientation = canonical_orientation(source_orientation)
    output = Path(output_directory).resolve()
    if output.exists():
        raise FileExistsError('Keep asset versions immutable; output already exists: ' + str(output))
    objects = _tree(root)
    _validate(objects, root)
    if not any(obj.type == 'MESH' for obj in objects):
        raise ValueError('No mesh geometry under root: ' + root.name)
    name = asset_name or root.name.split(' | placement root')[0]
    original_scene = bpy.context.window.scene
    original_frame = original_scene.frame_current
    source_path = Path(bpy.data.filepath) if bpy.data.filepath else None
    source_transform = [list(row) for row in root.matrix_world]
    source_provenance = {'blend': str(source_path) if source_path else None,
                         'root': root.name, 'frame': original_frame,
                         'root_world_matrix': source_transform,
                         'saved_file_sha256': _hash_file(source_path) if source_path and source_path.is_file() else None,
                         'live_state_may_differ_from_saved_file': bool(bpy.data.is_dirty)}
    before = {key: set(getattr(bpy.data, key)) for key in
              ('objects', 'collections', 'meshes', 'materials', 'node_groups', 'images', 'actions')}
    stage = bpy.data.scenes.new('Articulated export staging')
    collection = bpy.data.collections.new(name)
    stage.collection.children.link(collection)
    temporary = None
    try:
        bpy.context.window.scene = stage
        clone_root, mapping = _clone_tree(objects, root, collection, strip_timeline=True)
        clone_root.matrix_basis = Matrix.Identity(4)
        rig_root = clone_root
        clone_root = _orientation_wrapper(rig_root, collection, source_orientation)
        clone_root['articulated_root'] = True
        clone_root['articulated_schema_version'] = FORMAT_VERSION
        clone_root['instance_id'] = 'asset-template'
        clone_root['semantic_class'] = root.get('semantic_class', 'cabinet')
        clone_root['asset_id'] = root.get('asset_id', '')
        clone_root['support_id'] = root.get('support_id', '')
        controls = []
        for source, clone in mapping.items():
            clone['asset_source_object'] = source.name
            for prop in _CONTROL_PROPERTIES:
                if prop in clone:
                    clone[prop] = 0.0
            if any(prop in clone for prop in _CONTROL_PROPERTIES):
                controls.append({'object': clone.name, 'joint_id': clone.get('joint_id', source.name),
                                 'joint_type': clone.get('joint_type', 'legacy'),
                                 'properties': [prop for prop in _CONTROL_PROPERTIES if prop in clone],
                                 'metadata': {key: _json_value(value) for key, value in clone.items()
                                              if key.startswith('joint_') or key in {'axis', 'limit_min', 'limit_max', 'closed_position'}}})
            clone.update_tag()
        materials = _copy_export_data(mapping)
        bpy.context.view_layer.update()
        stage.frame_set(1)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        points = [obj.evaluated_get(dg).matrix_world @ Vector(corner)
                  for obj in mapping.values() if obj.type == 'MESH'
                  for corner in obj.evaluated_get(dg).bound_box]
        low = Vector(tuple(min(point[k] for point in points) for k in range(3)))
        high = Vector(tuple(max(point[k] for point in points) for k in range(3)))
        collection['articulated_schema_version'] = FORMAT_VERSION
        collection['articulated_root_name'] = clone_root.name
        collection['roomkit_units'] = 'metres'
        collection['roomkit_forward'] = orientation['front_axis'] or 'none'
        collection['roomkit_origin'] = orientation['origin']
        collection['asset_orientation_json'] = json.dumps(orientation, sort_keys=True)
        collection.asset_mark()
        collection.asset_data.author = 'RoomKit'
        collection.asset_data.description = 'Editable cabinet with independent native door and drawer controls.'
        collection.asset_data.catalog_id = _CATALOG_ID
        for tag in ('RoomKit', 'cabinet', 'articulated'):
            collection.asset_data.tags.new(tag)
        library_name = 'articulated_furniture.blend'
        item = {'name': collection.name, 'source_root': root.name, 'root_object': clone_root.name,
                'parts': sum(obj.type == 'MESH' for obj in mapping.values()),
                'vertices': sum(len(obj.data.vertices) for obj in mapping.values() if obj.type == 'MESH'),
                'dimensions_m': list(high - low), 'bounds_min_m': list(low), 'bounds_max_m': list(high),
                'description': collection.asset_data.description, 'category': 'furniture/storage/cabinets',
                'semantic_class': clone_root['semantic_class'], 'articulation': True, 'import_mode': 'articulated',
                'orientation': orientation, 'source_orientation': source_orientation,
                'origin_normalization': 'declared root retained; no bounds recentering',
                'controls': controls, 'root_metadata': {key: _json_value(value) for key, value in clone_root.items()},
                'catalog_id': _CATALOG_ID}
        manifest = {'version': 1, 'articulated_schema_version': FORMAT_VERSION,
                    'blender_version': bpy.app.version_string, 'library': library_name,
                    'furniture': [item], 'materials': [],
                    'material_dependencies': [{'name': mat.name, 'source_name': mat.name,
                        'world_coordinates': any(node.type == 'NEW_GEOMETRY' for tree in _walk_nodes(mat.node_tree)
                                                  for node in tree.nodes)} for mat in materials],
                    'origin': orientation['origin'], 'forward': orientation['front_axis'], 'units': 'metres',
                    'geometry': 'Separate editable meshes; native hierarchy, modifiers, constraints and drivers retained.',
                    'timeline_animation': 'Source action and NLA keys removed; native drivers retained; controls closed.',
                    'source': source_provenance}
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '-staging-', dir=str(output.parent)))
        bpy.data.libraries.write(str(temporary / library_name), {collection}, path_remap='RELATIVE',
                                 fake_user=True, compress=True)
        manifest['library_sha256'] = _hash_file(temporary / library_name)
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (temporary / 'blender_assets.cats.txt').write_text(
            '# Blender Asset Catalog Definition File\nVERSION 1\n\n{}:{}:Cabinets\n'.format(_CATALOG_ID, _CATALOG),
            encoding='utf-8')
        # Atomic installation, without silently replacing an existing version.
        if output.exists():
            raise FileExistsError(str(output))
        temporary.rename(output)
        temporary = None
        return manifest
    finally:
        bpy.context.window.scene = original_scene
        bpy.data.scenes.remove(stage)
        # Remove only datablocks allocated by this synchronous export call.
        for key in ('objects', 'collections', 'meshes', 'materials', 'node_groups', 'images', 'actions'):
            datablocks = getattr(bpy.data, key)
            for block in set(datablocks) - before[key]:
                datablocks.remove(block, do_unlink=True)
        if temporary is not None:
            shutil.rmtree(str(temporary))


def import_articulated(library, collection_name, location=(0, 0, 0), rotation=0,
                       instance_id=None, asset_id=None):
    """Append an independent object rig. Z rotation is in degrees.

    Imported objects and actions are independent. Meshes/materials are shared
    between repeated calls; assign a material copy before a per-instance edit.
    The saved scene has no live link to the source library.
    """
    library = Path(library).resolve()
    identifier = instance_id or str(uuid.uuid4())
    if any(obj.get('instance_id') == identifier for obj in bpy.data.objects):
        raise ValueError('Duplicate instance_id: ' + identifier)
    key = str(library) + '::' + collection_name
    template = next((col for col in bpy.data.collections
                     if col.get('articulated_import_key') == key), None)
    if template is None:
        with bpy.data.libraries.load(str(library), link=False) as (source, dest):
            if collection_name not in source.collections:
                raise ValueError('Missing articulated collection: ' + collection_name)
            dest.collections = [collection_name]
        template = dest.collections[0]
        template['articulated_import_key'] = key
        template.use_fake_user = True
    if template.get('articulated_schema_version') != FORMAT_VERSION:
        raise ValueError('Not a supported articulated asset: ' + collection_name)
    roots = [obj for obj in template.all_objects if obj.get('articulated_root')]
    if len(roots) != 1:
        raise ValueError('Articulated asset must have exactly one placement root')
    source_root = roots[0]
    objects = _tree(source_root)
    if set(objects) != set(template.all_objects):
        raise ValueError('Articulated collection contains objects outside its root')
    _validate(objects, source_root)
    target = bpy.data.collections.new(collection_name + ' | ' + identifier)
    bpy.context.scene.collection.children.link(target)
    try:
        root, mapping = _clone_tree(objects, source_root, target)
        root.location = location
        root.rotation_mode = 'XYZ'
        root.rotation_euler = (0, 0, math.radians(rotation))
        root.scale = (1, 1, 1)
        root['instance_id'] = identifier
        root['asset_id'] = asset_id if asset_id is not None else source_root.get('asset_id', '')
        root['source_asset_library'] = str(library)
        root['source_asset_collection'] = collection_name
        for source, clone in mapping.items():
            if source != source_root and 'instance_id' in clone:
                clone['instance_id'] = identifier + '/' + str(clone.get('joint_id', source.name))
            clone.update_tag()
        bpy.context.view_layer.update()
        return root
    except Exception:
        for obj in list(target.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(target)
        raise
