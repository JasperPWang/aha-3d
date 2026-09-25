"""Orientation behavior checks in background Blender.

blender -b --python-exit-code 1 --python tests/blender/check_asset_orientation.py -- \
  --out /claimed/orientation-checks

The test authors small asymmetric +X/+Y fixtures with explicit front markers;
it does not infer real asset facing from footprints or assert visual provenance.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import unittest

import bpy
from mathutils import Matrix, Vector

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from aha3d.io import digest
from aha3d.blender.orientation import (
    face_towards, facing_report, get_orientation, tag_orientation, world_front)
from aha3d.blender.roomkit import box, import_collection
from aha3d.blender.semantics import descendants, export_semantics, tag_root
from aha3d.blender.variants import apply_variant, place_asset, plan_variant


def authored(front='-Y', semantic_front='seating', origin='floor_center', **updates):
    result = {'schema_version': 1, 'front_axis': front, 'up_axis': 'Z', 'symmetry': 'none',
              'origin': origin, 'semantic_front': semantic_front, 'status': 'authored',
              'evidence': 'Synthetic test geometry has explicit front and top markers.'}
    result.update(updates)
    return result


def make_root(identity, location=(0, 0, 0), orientation=None, category='furniture/seating/chairs'):
    root = bpy.data.objects.new(identity, None)
    bpy.context.scene.collection.objects.link(root)
    tag_root(root, category, instance_id=identity)
    root.location = location
    geometry = box(identity + ' asymmetric body', (0, -.05, .3), (.3, .5, .6), edge=0)
    geometry.parent = root
    if orientation is not None:
        tag_orientation(root, orientation)
    bpy.context.view_layer.update()
    return root


def scene_snapshot():
    bpy.context.view_layer.update()
    return {obj.name: {'matrix_world': [list(row) for row in obj.matrix_world],
                      'parent': obj.parent.name if obj.parent else None,
                      'instance_id': obj.get('instance_id'),
                      'orientation': obj.get('asset_orientation_json'),
                      'relation': obj.get('facing_target_json')}
            for obj in bpy.context.scene.objects}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def fixture_library(project):
    """Author a tiny private registered library with source frames known by construction."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    definitions = [
        ('chair-y', 'Y', 'seating', 'floor_center', 'furniture/seating/chairs', 'authored'),
        ('chair-x', 'X', 'seating', 'floor_center', 'furniture/seating/chairs', 'authored'),
        ('chair-spout', 'X', 'spout', 'floor_center', 'furniture/seating/chairs', 'authored'),
        ('faucet-x', 'X', 'spout', 'mount_center', 'fixtures/plumbing/faucets', 'authored'),
        ('faucet-y', 'Y', 'spout', 'mount_center', 'fixtures/plumbing/faucets', 'authored'),
        ('faucet-floor', 'X', 'spout', 'floor_center', 'fixtures/plumbing/faucets', 'authored'),
        ('symmetric-vase', None, 'none', 'floor_center', 'props/decor/vases', 'authored'),
        ('unreviewed-chair', 'Y', 'seating', 'floor_center', 'furniture/seating/chairs', 'declared')]
    items, cards, collections = [], [], []
    for name, front, semantic, origin, category, status in definitions:
        col = bpy.data.collections.new('TEST ' + name)
        bpy.context.scene.collection.children.link(col)
        root = bpy.data.objects.new(name + ' source root', None)
        col.objects.link(root)
        data = authored(front, semantic, origin, status=status,
                        symmetry='continuous_z' if front is None else 'none')
        tag_orientation(root, data)
        dims = (.7, .3, .8) if front == 'X' else (.3, .7, .8)
        geometry = box(name + ' body', (0, 0, .4), dims, edge=0)
        for previous in list(geometry.users_collection):
            previous.objects.unlink(geometry)
        col.objects.link(geometry)
        geometry.parent = root
        if front is not None:
            tip = bpy.data.objects.new(name + ' front marker', None)
            tip['orientation_probe'] = 'front'
            tip.location = (.3, 0, .4) if front == 'X' else (0, .3, .4)
            tip.parent = root
            col.objects.link(tip)
        top = bpy.data.objects.new(name + ' top marker', None)
        top['orientation_probe'] = 'top'
        top.location = (0, 0, .8)
        top.parent = root
        col.objects.link(top)
        item = {'name': col.name, 'dimensions_m': list(dims), 'parts': 1, 'orientation': data,
                'description': 'Private source-frame fixture with marked semantic front.', 'category': category}
        items.append(item)
        cards.append({'id': 'test-orientation/' + name, 'name': col.name, 'kind': 'collection',
            'status': 'registered', 'category': category, 'family_id': name,
            'source': {'path': 'assets/test/manifest.json', 'pointer': '/furniture/' + str(len(items)-1)},
            'library_id': 'test-orientation', 'library_path': 'assets/test/fixtures.blend',
            'datablock': col.name, 'dimensions_m': list(dims), 'units': 'metres',
            'origin': origin, 'forward': front, 'orientation': data})
        collections.append(col)
    bpy.context.view_layer.update()
    binary = project / 'assets/test/fixtures.blend'
    binary.parent.mkdir(parents=True, exist_ok=True)
    bpy.data.libraries.write(str(binary), set(collections), fake_user=True)
    checksum = digest(binary)
    for card in cards:
        card['library_sha256'] = checksum
    write_json(project / 'assets/test/manifest.json', {'version': 1, 'units': 'metres',
        'origin': 'per_item', 'forward': 'per_item', 'geometry': 'Synthetic independent test geometry.',
        'furniture': items, 'materials': []})
    write_json(project / 'assets/registry.json', {'schema_version': 1, 'assets': {'test-orientation': {
        'path': 'assets/test/fixtures.blend', 'metadata': 'assets/test/manifest.json', 'sha256': checksum,
        'units': 'metres', 'world_up': 'Z', 'forward': 'per_item'}}})
    write_json(project / 'assets/catalog_sources.json', {'schema_version': 1, 'source_groups': [], 'library_annotations': {}})
    write_json(project / 'assets/orientation_reviews.json', {'schema_version': 1, 'reviews': {}})
    fingerprints = {name: digest(project / name) for name in ('assets/registry.json',
                    'assets/catalog_sources.json', 'assets/test/manifest.json', 'assets/orientation_reviews.json')}
    write_json(project / 'assets/index.json', {'schema_version': 1, 'input_sha256': fingerprints, 'entries': cards})
    return {'library': str(binary), 'sha256': checksum, 'items': [card['id'] for card in cards]}


class OrientationBlenderTests(unittest.TestCase):
    output = None
    fixture_root = None
    fixture_provenance = None

    @classmethod
    def setUpClass(cls):
        cls.fixture_root = cls.output / 'private_project'
        cls.fixture_provenance = fixture_library(cls.fixture_root)

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def assertVectorClose(self, actual, expected, tolerance=2e-5):
        self.assertLess((Vector(actual) - Vector(expected)).length, tolerance, (actual, expected))

    def assertMatrixClose(self, actual, expected, tolerance=2e-5):
        for left, right in zip(actual, expected):
            self.assertVectorClose(left, right, tolerance)

    def assertRejectedUnchanged(self, function):
        before = scene_snapshot()
        with self.assertRaises(ValueError):
            function()
        self.assertEqual(scene_snapshot(), before)

    def place(self, name, **kwargs):
        return place_asset('test-orientation/' + name, project_root=self.fixture_root, **kwargs)

    def assertFrontMarker(self, root, direction):
        bpy.context.view_layer.update()
        marker = next(obj for obj in descendants(root) if obj.get('orientation_probe') == 'front')
        delta = marker.matrix_world.translation - root.matrix_world.translation
        delta.z = 0
        self.assertVectorClose(delta.normalized(), direction)
        self.assertVectorClose(world_front(root), direction)
        top = next(obj for obj in descendants(root) if obj.get('orientation_probe') == 'top')
        self.assertGreater(top.matrix_world.translation.z, root.matrix_world.translation.z)

    def test_chairs_face_target_from_all_sides_and_keep_position_scale(self):
        table = make_root('table', category='furniture/tables')
        for i, location in enumerate(((2, 0, 0), (-2, 0, 0), (0, 2, 0), (0, -2, 0), (2, 2, 0))):
            root = make_root('chair-' + str(i), location, authored())
            root.scale = (1.4,) * 3
            bpy.context.view_layer.update()
            before = root.matrix_world.copy()
            report = face_towards(root, table)
            self.assertEqual(report['status'], 'pass')
            expected = -Vector(location)
            expected.z = 0
            self.assertVectorClose(world_front(root), expected.normalized())
            self.assertVectorClose(root.matrix_world.translation, before.translation)
            self.assertVectorClose(root.matrix_world.to_scale(), before.to_scale())
            self.assertVectorClose(root.matrix_world.to_3x3().col[2].normalized(), (0, 0, 1))
            saved = json.loads(root['facing_target_json'])
            self.assertEqual(saved['instance_id'], 'table')
            self.assertEqual(facing_report(root)['status'], 'pass')

    def test_clockwise_and_counterclockwise_yaw(self):
        root = make_root('yaw', orientation=authored())
        face_towards(root, (1, 0, 0))
        self.assertVectorClose(world_front(root), (1, 0, 0))
        self.assertAlmostEqual(math.degrees(root.rotation_euler.z), 90., places=4)
        face_towards(root, (-1, 0, 0))
        self.assertVectorClose(world_front(root), (-1, 0, 0))
        # Matrix orientation is invariant to equivalent +/-360 degree Euler choices.
        self.assertVectorClose(root.matrix_world.to_3x3() @ Vector((1, 0, 0)), (0, -1, 0))

    def test_rotated_uniform_parent_preserves_world_mount_and_sibling(self):
        parent = bpy.data.objects.new('rotated parent', None)
        bpy.context.scene.collection.objects.link(parent)
        parent.location = (4, -3, .8)
        parent.rotation_euler.z = .61
        parent.scale = (1.7,) * 3
        faucet = make_root('faucet', (1, .2, .4), authored('X', 'spout', 'mount_center'),
                           category='fixtures/plumbing/faucets')
        faucet.parent = parent
        sibling = make_root('sibling', (3, 2, 0), authored())
        sibling.parent = parent
        bpy.context.view_layer.update()
        before, sibling_before, parent_before = faucet.matrix_world.copy(), sibling.matrix_world.copy(), parent.matrix_world.copy()
        target = before.translation + Vector((2, -3, -1))
        face_towards(faucet, target)
        self.assertVectorClose(faucet.matrix_world.translation, before.translation)
        self.assertVectorClose(faucet.matrix_world.to_scale(), before.to_scale())
        self.assertMatrixClose(parent.matrix_world, parent_before)
        self.assertMatrixClose(sibling.matrix_world, sibling_before)
        self.assertVectorClose(world_front(faucet), Vector((2, -3, 0)).normalized())
        self.assertEqual(get_orientation(faucet)['origin'], 'mount_center')

    def test_invalid_transform_animation_and_constraints_rejected_atomically(self):
        cases = ('reflection', 'nonuniform', 'shear', 'tilt', 'animation', 'constraint', 'parent_animation', 'compensated_parent')
        for case in cases:
            with self.subTest(case=case):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                root = make_root('invalid-' + case, orientation=authored())
                if case == 'reflection':
                    root.scale.x = -1
                elif case == 'nonuniform':
                    root.scale.x = 2
                elif case == 'shear':
                    root.matrix_world = Matrix(((1, .3, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
                elif case == 'tilt':
                    root.rotation_euler.x = .1
                elif case == 'animation':
                    root.keyframe_insert(data_path='location', frame=1)
                elif case == 'constraint':
                    root.constraints.new('LIMIT_LOCATION')
                else:
                    parent = bpy.data.objects.new('parent', None)
                    bpy.context.scene.collection.objects.link(parent)
                    root.parent = parent
                    if case == 'parent_animation':
                        parent.keyframe_insert(data_path='location', frame=1)
                    else:
                        parent.scale.x = 2
                        root.scale.x = .5
                bpy.context.view_layer.update()
                self.assertRejectedUnchanged(lambda: face_towards(root, (1, 1, 0)))

    def test_unknown_symmetric_no_target_and_invalid_targets(self):
        unknown = make_root('unknown')
        self.assertEqual(facing_report(unknown)['status'], 'unverified')
        self.assertRejectedUnchanged(lambda: face_towards(unknown, (1, 0, 0)))
        symmetric = make_root('vase', orientation=authored(None, 'none', symmetry='continuous_z'), category='props/decor/vases')
        self.assertIsNone(world_front(symmetric))
        self.assertEqual(facing_report(symmetric)['status'], 'not_applicable')
        self.assertRejectedUnchanged(lambda: face_towards(symmetric, (1, 0, 0)))
        directional = make_root('directional', orientation=authored())
        self.assertEqual(facing_report(directional)['status'], 'no_target')
        for target in ((0, 0, 3), (float('nan'), 1, 0), (True, 1, 0), (1, 2)):
            with self.subTest(target=target):
                self.assertRejectedUnchanged(lambda: face_towards(directional, target))
        untagged = bpy.data.objects.new('untagged target', None)
        bpy.context.scene.collection.objects.link(untagged)
        untagged.location.x = 3
        self.assertRejectedUnchanged(lambda: face_towards(directional, untagged))
        target = make_root('target', (2, 3, 0), authored())
        duplicate = target.copy()
        bpy.context.scene.collection.objects.link(duplicate)
        self.assertRejectedUnchanged(lambda: face_towards(directional, target))
        bpy.data.objects.remove(duplicate, do_unlink=True)
        target.parent = directional
        self.assertRejectedUnchanged(lambda: face_towards(directional, target))
        target.parent = None
        face_towards(directional, target)
        bpy.data.objects.remove(target, do_unlink=True)
        self.assertRejectedUnchanged(lambda: facing_report(directional))

    def test_reports_detect_wrong_facing_and_preserve_record_false(self):
        root = make_root('directional', orientation=authored())
        face_towards(root, (0, -3, 0), tolerance_degrees=3)
        relation = root['facing_target_json']
        self.assertEqual(facing_report(root, (0, 3, 0))['status'], 'fail')
        self.assertAlmostEqual(facing_report(root, (0, 3, 0))['error_degrees'], 180., places=4)
        face_towards(root, (3, 0, 0), record=False)
        self.assertEqual(root['facing_target_json'], relation)
        self.assertEqual(facing_report(root)['status'], 'fail')
        for tolerance in (-1, 181, float('nan'), True):
            self.assertRejectedUnchanged(lambda: face_towards(root, (1, 1, 0), tolerance_degrees=tolerance))

    def test_registered_source_frames_normalize_geometry_without_editing_library(self):
        original_hash = digest(self.fixture_provenance['library'])
        for name in ('chair-y', 'chair-x', 'faucet-x', 'faucet-y'):
            with self.subTest(name=name):
                root = self.place(name, location=(2, -3, 1.1), instance_id=name)
                self.assertFrontMarker(root, (0, -1, 0))
                self.assertEqual(get_orientation(root, require_trusted=True)['front_axis'], '-Y')
                before_vertices = [tuple(v.co) for obj in descendants(root) if obj.type == 'MESH' for v in obj.data.vertices]
                before_location = root.matrix_world.translation.copy()
                face_towards(root, (5, -3, 1.1))
                self.assertFrontMarker(root, (1, 0, 0))
                self.assertVectorClose(root.matrix_world.translation, before_location)
                after_vertices = [tuple(v.co) for obj in descendants(root) if obj.type == 'MESH' for v in obj.data.vertices]
                self.assertEqual(before_vertices, after_vertices)
        self.assertEqual(digest(self.fixture_provenance['library']), original_hash)

    def test_place_target_conflicts_and_untrusted_assets_do_not_add_objects(self):
        target = make_root('basin', (3, 0, 1), category='fixtures/plumbing/basins')
        self.assertRejectedUnchanged(lambda: self.place('faucet-x', rotation=0, facing_target=target))
        self.assertRejectedUnchanged(lambda: self.place('unreviewed-chair', facing_target=target))
        faucet = self.place('faucet-x', location=(0, 0, 1), facing_target=target, instance_id='mounted-faucet')
        self.assertFrontMarker(faucet, (1, 0, 0))
        self.assertVectorClose(faucet.matrix_world.translation, (0, 0, 1))
        self.assertEqual(get_orientation(faucet)['origin'], 'mount_center')
        untouched = self.place('faucet-x', location=(2, 3, 1), rotation=32, instance_id='other-faucet')
        before = untouched.matrix_world.copy()
        face_towards(faucet, (0, -3, 1))
        self.assertMatrixClose(untouched.matrix_world, before)

    def test_low_level_import_retains_source_frame_and_preflights_targets(self):
        library = self.fixture_provenance['library']
        target = make_root('target', (2, 0, 0), category='fixtures/plumbing/basins')
        raw = import_collection(library, 'TEST chair-y', orientation=authored('Y'),
                                semantic_class='furniture/seating/chairs', instance_id='raw-source-frame')
        self.assertEqual(get_orientation(raw)['front_axis'], 'Y')
        self.assertVectorClose(world_front(raw), (0, 1, 0))
        face_towards(raw, target)
        self.assertVectorClose(world_front(raw), (1, 0, 0))
        untagged = bpy.data.objects.new('untagged target', None)
        bpy.context.scene.collection.objects.link(untagged)
        untagged.location.x = 4
        self.assertRejectedUnchanged(lambda: import_collection(library, 'TEST chair-y',
            orientation=authored('Y'), facing_target=untagged))
        self.assertRejectedUnchanged(lambda: import_collection(library, 'TEST chair-y',
            orientation=authored('Y'), location=(2, 0, 0), facing_target=target))
        self.assertRejectedUnchanged(lambda: import_collection(library, 'TEST chair-y',
            orientation=authored('Y'), scale=(2, 1, 1), facing_target=target))

    def test_replacement_rejects_incompatible_origin_and_noncanonical_source(self):
        faucet = self.place('faucet-x', location=(0, 0, 1), instance_id='mount')
        recipe = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['mount']},
            'asset_id': 'test-orientation/faucet-floor', 'fit': 'native'}]}
        self.assertRejectedUnchanged(lambda: apply_variant(recipe, self.fixture_root))
        tag_orientation(faucet, authored('X', 'spout', 'mount_center'))
        recipe['models'][0]['asset_id'] = 'test-orientation/faucet-y'
        self.assertRejectedUnchanged(lambda: apply_variant(recipe, self.fixture_root))
        vase = make_root('directional-vase', orientation=authored(semantic_front='generic'), category='props/decor/vases')
        symmetric = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['directional-vase']},
            'asset_id': 'test-orientation/symmetric-vase', 'fit': 'native'}]}
        self.assertRejectedUnchanged(lambda: apply_variant(symmetric, self.fixture_root))

        chair = self.place('chair-y', instance_id='seating-chair')
        incompatible_semantics = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['seating-chair']},
            'asset_id': 'test-orientation/chair-spout', 'fit': 'native'}]}
        self.assertRejectedUnchanged(lambda: apply_variant(incompatible_semantics, self.fixture_root))

    def test_footprint_fit_uses_canonical_dimensions_without_guessing_front(self):
        chair = self.place('chair-y', instance_id='fitted-chair')
        face_towards(chair, (3, 0, 0))
        before = chair.matrix_world.copy()
        recipe = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['fitted-chair']},
            'asset_id': 'test-orientation/chair-x', 'fit': 'uniform_footprint'}]}
        plan = plan_variant(recipe, self.fixture_root)
        # Raw X-source width/depth are reversed; both normalized fixtures are
        # .3 x .7. A fit against raw dimensions would incorrectly shrink to3/7.
        self.assertAlmostEqual(plan['models'][0]['uniform_scale'], 1., places=5)
        report = apply_variant(recipe, self.fixture_root)
        self.assertAlmostEqual(report['models'][0]['uniform_scale'], 1., places=5)
        self.assertMatrixClose(chair.matrix_world, before)
        self.assertFrontMarker(chair, (1, 0, 0))
        self.assertEqual(facing_report(chair)['status'], 'pass')

    def test_saved_target_relation_survives_replacement_and_reopen(self):
        basin = make_root('basin', (2, 2, 1), category='fixtures/plumbing/basins')
        faucet = self.place('faucet-x', location=(2, -1, 1), facing_target=basin, instance_id='mounted-faucet')
        before_matrix = faucet.matrix_world.copy()
        before_relation = faucet['facing_target_json']
        recipe = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['mounted-faucet']},
                  'asset_id': 'test-orientation/faucet-y', 'fit': 'native'}]}
        snapshot = scene_snapshot()
        first_plan, second_plan = plan_variant(recipe, self.fixture_root), plan_variant(recipe, self.fixture_root)
        self.assertEqual(first_plan, second_plan)
        self.assertEqual(scene_snapshot(), snapshot)
        report = apply_variant(recipe, self.fixture_root)
        self.assertEqual(report['status'], 'applied')
        self.assertEqual(faucet['facing_target_json'], before_relation)
        self.assertMatrixClose(faucet.matrix_world, before_matrix)
        self.assertFrontMarker(faucet, (0, 1, 0))
        self.assertEqual(facing_report(faucet)['status'], 'pass')
        output = self.output / 'saved_relation.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(output))
        bpy.ops.wm.open_mainfile(filepath=str(output))
        reopened = next(obj for obj in bpy.context.scene.objects if obj.get('instance_id') == 'mounted-faucet')
        self.assertEqual(reopened['facing_target_json'], before_relation)
        self.assertFrontMarker(reopened, (0, 1, 0))
        self.assertEqual(facing_report(reopened)['status'], 'pass')
        exported = export_semantics()
        json.dumps(exported, allow_nan=False)
        write_json(self.output / 'saved_relation.semantics.json', exported)

    def test_replacement_requires_trusted_source_and_asset_before_deletion(self):
        source = make_root('legacy-chair', orientation=authored(status='declared'))
        recipe = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['legacy-chair']},
                  'asset_id': 'test-orientation/chair-y', 'fit': 'native'}]}
        self.assertRejectedUnchanged(lambda: apply_variant(recipe, self.fixture_root))
        tag_orientation(source, authored())
        bad_asset = copy.deepcopy(recipe)
        bad_asset['models'][0]['asset_id'] = 'test-orientation/unreviewed-chair'
        self.assertRejectedUnchanged(lambda: apply_variant(bad_asset, self.fixture_root))
        # A first valid operation must not run when a later root is unresolved.
        second = make_root('unresolved-second')
        mixed = copy.deepcopy(recipe)
        mixed['models'].append({'selector': {'instance_ids': ['unresolved-second']},
                               'asset_id': 'test-orientation/chair-x', 'fit': 'native'})
        self.assertRejectedUnchanged(lambda: apply_variant(mixed, self.fixture_root))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    args.out.mkdir(parents=True, exist_ok=True)
    OrientationBlenderTests.output = args.out
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OrientationBlenderTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    write_json(args.out / 'report.json', {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
               'failures': [str(case) for case, trace in result.failures],
               'errors': [str(case) for case, trace in result.errors],
               'fixture': OrientationBlenderTests.fixture_provenance,
               'blender_version': bpy.app.version_string})
    if not result.wasSuccessful():
        raise RuntimeError('Orientation behavior tests failed; see report and Blender log')


if __name__ == '__main__':
    main()
