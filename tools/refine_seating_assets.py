"""Deterministic chair support audit and reviewed repairs, run in background Blender.

Source libraries/scenes are immutable. Geometry-contact graphs report geometric
support paths, not structural engineering/load capacity. Visible back/seat gaps
are not classified as defects when another supported part makes real contact.
"""
import argparse
import hashlib
import json
import math
import runpy
import shutil
import sys
from collections import deque
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from aha3d.assets import resolve_item
from aha3d.blender.roomkit import place_asset, box, parent_keep_world
from aha3d.blender.semantics import adopt_group, tag_root
from aha3d.blender.orientation import tag_orientation

ASSETS = ('dining-chair-v1/chair-open-frame-dining', 'roomkit-v1/chair-walnut-lounge', 'scene/g0064/accent-chair')
ACCENT_SOURCE = PROJECT / 'runs/living_room_piano_g0064/full_20260909/delivery/piano_room_animated.blend'
CONTACT_TOLERANCE = .0005
REFINEMENTS = {
    ASSETS[1]: ('RK Chair - Walnut Lounge Supported', 'chair-walnut-lounge-supported'),
    ASSETS[2]: ('RK Chair - Accent Supported', 'chair-accent-supported'),
}


def digest(path):
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def refreshed():
    for obj in bpy.context.scene.objects:
        obj.update_tag()
    bpy.context.view_layer.update()
    return bpy.context.evaluated_depsgraph_get()


def load_source(identity):
    if identity != 'scene/g0064/accent-chair':
        card = resolve_item(identity, root=PROJECT, expected_kind='collection')
        root = place_asset(identity, instance_id='quality-' + identity.replace('/', '-'), project_root=PROJECT)
        provenance = {'asset_id': identity, 'library': card['library'], 'library_sha256': card['library_sha256'],
                      'datablock': card['datablock'], 'orientation': card['orientation']}
    else:
        with bpy.data.libraries.load(str(ACCENT_SOURCE), link=False) as (source, target):
            names = ['Small accent chair seat', 'Small accent chair back', 'Accent chair leg',
                     'Accent chair leg.001', 'Accent chair leg.002', 'Accent chair leg.003']
            missing = set(names) - set(source.objects)
            if missing:
                raise ValueError('Missing first accent-chair parts: ' + str(sorted(missing)))
            # Blender replaces the assigned list entries with datablocks on exit.
            # Keep source names as a separate immutable provenance value.
            target.objects = list(names)
        parts = target.objects
        for obj in parts:
            bpy.context.scene.collection.objects.link(obj)
        refreshed()
        # Saved scene geometry remains unchanged; authored source dimensions/front
        # and selected exact part names establish this source extraction boundary.
        points = [obj.matrix_world @ Vector(corner) for obj in parts for corner in obj.bound_box]
        low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
        high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
        origin = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
        root = adopt_group(parts, 'furniture/seating/chairs', 'quality-accent-chair',
                           placement_matrix=Matrix.Translation(origin))
        root.location = (0, 0, 0)
        orientation = {'schema_version': 1, 'front_axis': '-Y', 'up_axis': 'Z', 'symmetry': 'none',
                       'origin': 'floor_center', 'semantic_front': 'seating', 'status': 'reviewed',
                       'evidence': 'Saved g0064 accent parts; source builder places back at seat +Y; structural audit in runs/seating_quality/20260910.'}
        tag_orientation(root, orientation)
        provenance = {'asset_id': identity, 'source_scene': str(ACCENT_SOURCE), 'source_sha256': digest(ACCENT_SOURCE),
                      'parts': names, 'original_floor_center': list(origin), 'orientation': orientation,
                      'source_builder': 'scenes/living_room_piano_g0064/blender/build_room.py:101-104'}
    refreshed()
    return root, provenance


def geometry(root):
    graph = refreshed()
    inverse = root.matrix_world.inverted()
    result = []
    for obj in [root] + list(root.children_recursive):
        if obj.type != 'MESH':
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        points = [inverse @ evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        triangles = [tuple(tri.vertices) for tri in mesh.loop_triangles]
        edges = {}
        for triangle in triangles:
            for a, b in zip(triangle, triangle[1:] + triangle[:1]):
                edge = tuple(sorted((a, b)))
                edges[edge] = edges.get(edge, 0) + 1
        closed_surface = bool(edges) and all(count == 2 for count in edges.values())
        low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
        high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
        tree = BVHTree.FromPolygons(points, triangles, all_triangles=True, epsilon=1e-7)
        # Dense mesh vertices plus triangle centroids bound nearest surface gaps.
        samples = points + [(points[a] + points[b] + points[c]) / 3 for a, b, c in triangles]
        result.append({'object': obj, 'points': points, 'samples': samples, 'bvh': tree,
                       'low': low, 'high': high, 'vertices': len(points), 'triangles': len(triangles),
                       'closed_surface': closed_surface})
        evaluated.to_mesh_clear()
    return result


def point_inside(point, part):
    """Odd-even rays on a closed surface; majority guards ray/triangle edge hits."""
    if not part['closed_surface'] or any(point[i] <= part['low'][i] or point[i] >= part['high'][i] for i in range(3)):
        return False
    votes = 0
    for direction in (Vector((1, .371, .123)).normalized(), Vector((.213, 1, .479)).normalized(),
                      Vector((.337, .173, 1)).normalized()):
        origin, crossings = point.copy(), 0
        for _ in range(128):
            hit = part['bvh'].ray_cast(origin, direction)
            if hit[0] is None:
                break
            crossings += 1
            origin = hit[0] + direction * 1e-6
        votes += crossings % 2
    return votes >= 2


def contained_vertex(a, b):
    for point in a['points'][::max(1, len(a['points']) // 32)]:
        if point_inside(point, b):
            return list(point)
    return None


def audit(root):
    geometries = geometry(root)
    low = Vector(tuple(min(part['low'][i] for part in geometries) for i in range(3)))
    high = Vector(tuple(max(part['high'][i] for part in geometries) for i in range(3)))
    contacts, pairs = {}, []
    for part in geometries:
        contacts[part['object'].name] = []
    for index, a in enumerate(geometries):
        for b in geometries[index + 1:]:
            separation = Vector(tuple(max(0., a['low'][i] - b['high'][i], b['low'][i] - a['high'][i]) for i in range(3)))
            lower = separation.length
            overlaps = len(a['bvh'].overlap(b['bvh'])) if lower < 1e-6 else 0
            contained = None
            if not overlaps and lower < 1e-7:
                contained = contained_vertex(a, b)
                if contained is None:
                    contained = contained_vertex(b, a)
            closest = float('inf')
            if not overlaps and lower < .12:
                for first, second in ((a, b), (b, a)):
                    for point in first['samples']:
                        hit = second['bvh'].find_nearest(point)
                        if hit[0] is not None:
                            closest = min(closest, hit[3])
            contact = bool(overlaps) or contained is not None or closest <= CONTACT_TOLERANCE
            a_name, b_name = a['object'].name, b['object'].name
            record = {'a': a_name, 'b': b_name, 'bounds_gap_lower_m': lower,
                      'intersecting_triangle_pairs': overlaps, 'contained_vertex': contained,
                      'sampled_surface_gap_upper_m': 0. if overlaps else closest if math.isfinite(closest) else None,
                      'contact': contact}
            pairs.append(record)
            if contact:
                contacts[a_name].append(b_name)
                contacts[b_name].append(a_name)
    ground = [part['object'].name for part in geometries if part['low'].z <= low.z + CONTACT_TOLERANCE]
    parent = {name: None for name in ground}
    queue = deque(ground)
    while queue:
        name = queue.popleft()
        for adjacent in contacts[name]:
            if adjacent not in parent:
                parent[adjacent] = name
                queue.append(adjacent)
    parts = []
    for part in geometries:
        name = part['object'].name
        path, cursor = [], name
        while cursor is not None and cursor in parent:
            path.append(cursor)
            cursor = parent[cursor]
        parts.append({'name': name, 'bounds_min': list(part['low']), 'bounds_max': list(part['high']),
                      'vertices': part['vertices'], 'triangles': part['triangles'], 'closed_surface': part['closed_surface'],
                      'contacts': contacts[name], 'ground_support_path': path if name in parent else None,
                      'materials': [slot.material.name if slot.material else None for slot in part['object'].material_slots]})
    return {'bounds_min': list(low), 'bounds_max': list(high), 'dimensions_m': list(high - low),
            'contact_tolerance_m': CONTACT_TOLERANCE, 'parts': parts, 'pairs': pairs, 'ground_parts': ground,
            'unsupported_parts': [part['name'] for part in parts if part['ground_support_path'] is None],
            'method': 'Evaluated triangle intersection, closed-surface volume containment, or dense vertex/triangle-centroid surface distance <= tolerance; graph paths to lowest feet.',
            'limitations': 'Contact graph is geometric, not load-bearing certification. Sampled surface distance is an upper bound; bounds separation is a lower bound. Tangencies below 0.5 mm count as contact and are flagged for constructive review.'}


def mat(name, color, roughness=.7):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    return material


def views(root, output, report, samples=24, resolution=900):
    from aha3d.blender.stage import gpu
    scene = bpy.context.scene
    gpu(scene)
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('Seating review studio')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.48, .5, .54, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .35
    low, high = Vector(report['bounds_min']), Vector(report['bounds_max'])
    extent = max(high - low)
    center = (low + high) / 2
    studio = []
    for label, delta, power in [('key', (2, -3, 4), 500), ('fill', (-3, -1, 2), 300), ('rim', (1, 3, 4), 650)]:
        data = bpy.data.lights.new('Seating ' + label, 'AREA')
        data.energy = power * extent ** 2
        data.shape = 'DISK'
        data.size = extent * 2
        obj = bpy.data.objects.new('Seating ' + label, data)
        scene.collection.objects.link(obj)
        obj.location = center + Vector(delta) * extent
        obj.rotation_euler = (center - obj.location).to_track_quat('-Z', 'Y').to_euler()
        studio.append(obj)
    data = bpy.data.cameras.new('Seating audit camera')
    camera = bpy.data.objects.new('Seating audit camera', data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    data.type = 'ORTHO'
    studio.append(camera)
    clay = mat('Structural clay', (.65, .68, .72))
    output.mkdir(parents=True, exist_ok=True)
    for label, direction, mode in [('front_material', (1.25, -1.8, 1.1), 'material'),
                                    ('rear_material', (1.1, 1.8, .7), 'material'),
                                    ('side_clay', (2.5, .05, .06), 'clay'),
                                    ('rear_clay', (-1.1, 1.8, .45), 'clay')]:
        camera.location = center + Vector(direction).normalized() * extent * 4
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        data.ortho_scale = extent * 1.35
        scene.view_layers[0].material_override = clay if mode == 'clay' else None
        scene.render.filepath = str(output / (label + '.png'))
        bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override = None
    # Save a browsable audit scene before removing temporary studio objects.
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'inspection.blend'))
    for obj in studio:
        bpy.data.objects.remove(obj, do_unlink=True)


def run_audit(output, samples, resolution, assets=ASSETS, reuse_views=None):
    output.mkdir(parents=True, exist_ok=False)
    summary = []
    for identity in assets:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        root, provenance = load_source(identity)
        item_out = output / identity.replace('/', '__')
        item_out.mkdir()
        report = audit(root)
        report['provenance'] = provenance
        (item_out / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
        old_views = reuse_views / identity.replace('/', '__') if reuse_views else None
        if old_views and all((old_views / (name + '.png')).is_file() for name in
                             ('front_material', 'rear_material', 'side_clay', 'rear_clay')):
            report['reused_views'] = str(old_views.resolve())
            (item_out / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
        else:
            views(root, item_out, report, samples, resolution)
        summary.append({'asset_id': identity, 'unsupported_parts': report['unsupported_parts'],
                        'audit': str(item_out / 'audit.json')})
        print('SEATING_AUDIT_ITEM ' + json.dumps(summary[-1]), flush=True)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('SEATING_AUDIT_COMPLETE ' + str(output), flush=True)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def material_signature(material):
    """Procedural node graph/parameters, independent of copied datablock names."""
    if material is None:
        return None
    result = {'diffuse': list(material.diffuse_color), 'use_nodes': material.use_nodes}
    if material.use_nodes:
        nodes = []
        for node in material.node_tree.nodes:
            inputs = []
            for socket in node.inputs:
                if not hasattr(socket, 'default_value'):
                    continue
                value = socket.default_value
                if isinstance(value, (str, int, float, bool)) or value is None:
                    inputs.append((socket.identifier, value))
                elif not isinstance(value, bpy.types.ID):
                    inputs.append((socket.identifier, list(value)))
            nodes.append((node.name, node.bl_idname, inputs))
        result['nodes'] = sorted(nodes)
        result['links'] = sorted((link.from_node.name, link.from_socket.identifier,
                                  link.to_node.name, link.to_socket.identifier)
                                 for link in material.node_tree.links)
    return result


def portable_snapshot(root):
    return [{'points': part['points'], 'vertices': part['vertices'], 'triangles': part['triangles'],
             'low': part['low'], 'high': part['high'],
             'materials': [material_signature(slot.material) for slot in part['object'].material_slots]}
            for part in geometry(root)]


def verify_snapshot(root, expected):
    remaining = portable_snapshot(root)
    maximum_error = 0.
    for original in expected:
        matching = [part for part in remaining if part['vertices'] == original['vertices']
                    and part['triangles'] == original['triangles']
                    and (part['low'] - original['low']).length < 2e-5
                    and (part['high'] - original['high']).length < 2e-5]
        if len(matching) != 1:
            raise AssertionError('Export lost unique per-part geometry identity')
        actual = matching[0]
        remaining.remove(actual)
        if actual['materials'] != original['materials']:
            raise AssertionError('Export altered per-part material node graph or parameters')
        for first, second in ((original, actual), (actual, original)):
            tree = KDTree(len(first['points']))
            for index, point in enumerate(first['points']):
                tree.insert(point, index)
            tree.balance()
            maximum_error = max(maximum_error, max(tree.find(point)[2] for point in second['points']))
    if remaining or maximum_error > 2e-5:
        raise AssertionError('Export changed per-part evaluated vertex coordinates')
    return maximum_error


def baked_copy(root):
    """Freeze evaluated source meshes before deterministic root-local edits."""
    graph = refreshed()
    for obj in root.children_recursive:
        if obj.type != 'MESH':
            continue
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(graph), depsgraph=graph)
        obj.modifiers.clear()
        obj.data = mesh


def root_transform(obj, root, transform):
    matrix = obj.matrix_world.inverted() @ root.matrix_world @ transform @ root.matrix_world.inverted() @ obj.matrix_world
    obj.data.transform(matrix)
    obj.data.update()


def refine(root, identity, before):
    baked_copy(root)
    objects = {obj.name: obj for obj in root.children_recursive if obj.type == 'MESH'}
    if identity == ASSETS[1]:
        wood = next(obj.active_material for obj in objects.values() if 'rear post' in obj.name)
        added = []
        # Both rails already meet rear posts. Slats bridge them and enter the
        # back cushion, providing a direct rear support route independent of arms.
        for side, x in [('left', -.22), ('right', .22)]:
            obj = box('Lounge rear support slat ' + side, (x, .36, .674),
                      (.052, .12, .58), wood, edge=.004)
            parent_keep_world(obj, root)
            added.append(obj.name)
        moved = []
        for obj in objects.values():
            if 'lumbar pillow' in obj.name:
                root_transform(obj, root, Matrix.Translation((0, 0, -.018)))
                moved.append(obj.name)
        return {'classification': 'support-quality refinement', 'added_parts': added,
                'lumbar_translation_m': [0, 0, -.018], 'moved_parts': moved,
                'rationale': 'Original back has arm support. Add direct rear rail-to-cushion support; close the measured 6.59132 mm lumbar-to-seat gap.'}
    if identity == ASSETS[2]:
        back = objects['Small accent chair back']
        bounds = next(part for part in before['parts'] if part['name'] == back.name)
        top, bottom = bounds['bounds_max'][2], bounds['bounds_min'][2]
        stretch = Matrix.Identity(4)
        stretch[2][2] = (top - bottom + .012) / (top - bottom)
        stretch[2][3] = top * (1 - stretch[2][2])
        root_transform(back, root, stretch)
        rear_legs = []
        for part in before['parts']:
            if part['name'].startswith('Accent chair leg') and part['bounds_min'][1] > 0:
                obj = objects[part['name']]
                low, old_top = part['bounds_min'][2], part['bounds_max'][2]
                transform = Matrix.Identity(4)
                transform[2][2] = (.72 - low) / (old_top - low)
                transform[2][3] = low * (1 - transform[2][2])
                root_transform(obj, root, transform)
                rear_legs.append(obj.name)
        return {'classification': 'tangent-joint reinforcement', 'back_bottom_extension_m': .012,
                'rear_posts_extended_to_m': .72, 'extended_parts': rear_legs,
                'rationale': 'Original beveled back and seat only tangent; retain top and footprint while adding overlap and continuous internal rear posts.'}
    raise ValueError('No reviewed refinement for ' + identity)


def verify_refinement(identity, before, after):
    if after['unsupported_parts']:
        raise AssertionError('Unsupported geometry: ' + str(after['unsupported_parts']))
    if max(abs(a - b) for a, b in zip(before['dimensions_m'], after['dimensions_m'])) > 2e-5:
        raise AssertionError('Refinement changed outer dimensions')
    if abs(after['bounds_min'][2]) > 2e-5:
        raise AssertionError('Refinement moved floor origin')
    contacts = {part['name']: part['contacts'] for part in after['parts']}
    if identity == ASSETS[1]:
        lumbar = next(name for name in contacts if name.startswith('Lounge chair A lumbar pillow'))
        if not any(name.startswith('Lounge chair A cushion.') for name in contacts[lumbar]):
            raise AssertionError('Lumbar still has no seat contact')
        for name in contacts:
            if name.startswith('Lounge rear support slat'):
                if not any('back cushion' in neighbor for neighbor in contacts[name]):
                    raise AssertionError('Rear slat misses cushion')
                if sum('back cross rail' in neighbor for neighbor in contacts[name]) != 2:
                    raise AssertionError('Rear slat must intersect both existing rails')
    else:
        back = 'Small accent chair back'
        if sum(name.startswith('Accent chair leg') for name in contacts[back]) != 2:
            raise AssertionError('Accent back lacks continuous rear-post contact')
        pair = next(pair for pair in after['pairs'] if {pair['a'], pair['b']} == {back, 'Small accent chair seat'})
        if not pair['intersecting_triangle_pairs']:
            raise AssertionError('Accent back-seat seam remains tangent')


def build_candidates(output, samples, resolution):
    output.mkdir(parents=True, exist_ok=False)
    summary = []
    for identity, (name, slug) in REFINEMENTS.items():
        bpy.ops.wm.read_factory_settings(use_empty=True)
        root, provenance = load_source(identity)
        before = audit(root)
        change = refine(root, identity, before)
        refreshed()
        after = audit(root)
        verify_refinement(identity, before, after)
        root.name = name + ' | source root'
        tag_root(root, 'furniture/seating/chairs', 'template-' + slug,
                 asset_id='seating-refined-v1/' + slug, support_id='floor')
        root['source_asset_id'] = identity
        item_out = output / slug
        item_out.mkdir()
        collection = bpy.data.collections.new('Seating candidate ' + slug)
        bpy.context.scene.collection.children.link(collection)
        for obj in [root, *root.children_recursive]:
            if obj.name not in collection.objects:
                collection.objects.link(obj)
        candidate = item_out / 'candidate.blend'
        bpy.data.libraries.write(str(candidate), {collection}, fake_user=True, compress=True)
        record = {'asset_id': 'seating-refined-v1/' + slug, 'name': name, 'root': root.name,
                  'candidate_collection': collection.name, 'candidate_library': str(candidate),
                  'candidate_sha256': digest(candidate), 'provenance': provenance, 'change': change,
                  'before': before, 'after': after}
        write_json(item_out / 'comparison.json', record)
        views(root, item_out, after, samples, resolution)
        summary.append({key: record[key] for key in ('asset_id', 'name', 'root', 'candidate_collection',
                                                    'candidate_library', 'candidate_sha256', 'provenance', 'change')})
        print('SEATING_CANDIDATE ' + json.dumps(summary[-1]), flush=True)
    write_json(output / 'summary.json', summary)
    print('SEATING_BUILD_COMPLETE ' + str(output), flush=True)


def export_candidates(candidates, output, library_output):
    """Use verified static export, then add semantic root metadata to a new library."""
    output.mkdir(parents=True, exist_ok=False)
    if library_output.exists():
        raise ValueError('Immutable asset output already exists: ' + str(library_output))
    records = json.loads((candidates / 'summary.json').read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    snapshots = {}
    for item in records:
        if digest(item['candidate_library']) != item['candidate_sha256']:
            raise ValueError('Candidate changed since inspection: ' + item['asset_id'])
        with bpy.data.libraries.load(item['candidate_library'], link=False) as (source, target):
            target.collections = [item['candidate_collection']]
        bpy.context.scene.collection.children.link(target.collections[0])
        candidate_root = bpy.data.objects[item['root']]
        snapshots[item['asset_id']] = portable_snapshot(candidate_root)
    refreshed()
    config = {'material_prefix': '__NO_STANDALONE_MATERIALS__', 'register_materials': False,
              'furniture': [{'root': item['root'], 'name': item['name'], 'catalog': 'Seating',
                             'description': item['change']['rationale']} for item in records]}
    config_path = output / 'selection.json'
    write_json(config_path, config)
    staging = output / 'export_staging'
    argv = sys.argv[:]
    try:
        sys.argv = ['export_assets.py', '--', '--config', str(config_path), '--out', str(staging)]
        runpy.run_path(str(PROJECT / '.agents/skills/blender-roomkit/scripts/export_assets.py'), run_name='__main__')
    finally:
        sys.argv = argv
    manifest = json.loads((staging / 'manifest.json').read_text())
    collections = []
    for item, exported in zip(records, manifest['furniture']):
        collection = bpy.data.collections[exported['name']]
        root = next(obj for obj in collection.objects if obj.parent is None)
        tag_root(root, 'furniture/seating/chairs', 'library-' + item['asset_id'].split('/')[1],
                 asset_id=item['asset_id'], support_id='floor')
        root['source_asset_id'] = item['provenance']['asset_id']
        exported.update({'semantic_class': 'furniture/seating/chairs', 'provenance': item['provenance'],
                         'refinement': item['change'], 'candidate_sha256': item['candidate_sha256']})
        for obj in collection.objects:
            for slot in obj.material_slots:
                if slot.material and slot.material.asset_data:
                    slot.material.asset_clear()
        collections.append(collection)
    library_output.mkdir(parents=True)
    library = library_output / manifest['library']
    bpy.data.libraries.write(str(library), set(collections), fake_user=True, compress=True, path_remap='RELATIVE')
    shutil.copyfile(staging / 'blender_assets.cats.txt', library_output / 'blender_assets.cats.txt')
    manifest['library_id'] = 'seating-refined-v1'
    manifest['library_sha256'] = digest(library)
    manifest['validation_scope'] = 'Geometric contact paths, preserved outer dimensions/materials/orientation; no engineering strength certification.'
    manifest['builder'] = {'path': str(Path(__file__).relative_to(PROJECT)), 'sha256': digest(__file__)}
    write_json(library_output / 'manifest.json', manifest)
    # Factory reset proves no live source or candidate dependency. All geometry
    # checks are repeated on the final, metadata-complete portable library.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(library), link=False) as (source, target):
        target.collections = [item['name'] for item in records]
    final_checks = []
    for collection, item in zip(target.collections, records):
        bpy.context.scene.collection.children.link(collection)
        root = next(obj for obj in collection.objects if obj.parent is None)
        comparison = json.loads((candidates / item['asset_id'].split('/')[1] / 'comparison.json').read_text())
        after = audit(root)
        # Static exporter may suffix part names while source objects coexist;
        # dimensional/contact totals prove geometry preservation independently.
        expected = comparison['after']
        if after['unsupported_parts'] or len(after['parts']) != len(expected['parts']):
            raise AssertionError('Reopened export lost supported geometry')
        if max(abs(a-b) for a,b in zip(after['dimensions_m'], expected['dimensions_m'])) > 2e-5:
            raise AssertionError('Export changed dimensions')
        if sum(part['vertices'] for part in after['parts']) != sum(part['vertices'] for part in expected['parts']):
            raise AssertionError('Export changed evaluated vertex count')
        if root.get('asset_id') != item['asset_id'] or not root.get('instance_id') or root.get('semantic_class') != 'furniture/seating/chairs':
            raise AssertionError('Incomplete semantic root')
        if any(obj.library for obj in collection.all_objects):
            raise AssertionError('Live linked source remained')
        error = verify_snapshot(root, snapshots[item['asset_id']])
        final_checks.append({'asset_id': item['asset_id'], 'reopened_audit': after,
                             'maximum_vertex_error_m': error, 'material_graphs_and_parameters_unchanged': True,
                             'root_metadata': {key: root.get(key) for key in ('instance_id', 'semantic_class', 'asset_id', 'support_id', 'asset_orientation_json')}})
    for item in records:
        source = item['provenance']
        path = source.get('library') or source['source_scene']
        expected_hash = source.get('library_sha256') or source['source_sha256']
        if digest(path) != expected_hash:
            raise AssertionError('Original source changed during refinement')
    write_json(output / 'verification.json', {'library': str(library), 'sha256': manifest['library_sha256'],
               'checks': final_checks, 'source_hashes_unchanged': True})
    print('SEATING_EXPORT_COMPLETE ' + str(library), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['audit', 'build', 'export'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--asset', action='append', choices=ASSETS, help='Audit only selected identities')
    parser.add_argument('--reuse-views', type=Path, help='Existing identical-source audit views; new geometry checks still run')
    parser.add_argument('--candidates', type=Path, help='Reviewed build output for export phase')
    parser.add_argument('--library-out', type=Path, help='New immutable library directory for export phase')
    parser.add_argument('--samples', type=int, default=24)
    parser.add_argument('--resolution', type=int, default=900)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if args.phase == 'audit':
        run_audit(args.out.resolve(), args.samples, args.resolution, args.asset or ASSETS, args.reuse_views)
    elif args.phase == 'build':
        build_candidates(args.out.resolve(), args.samples, args.resolution)
    else:
        if not args.candidates or not args.library_out:
            parser.error('export needs --candidates and --library-out')
        export_candidates(args.candidates.resolve(), args.out.resolve(), args.library_out.resolve())


if __name__ == '__main__':
    main()
