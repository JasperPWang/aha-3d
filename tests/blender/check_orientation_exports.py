"""Orientation export regression. Run background Blender with -- --out NEW_DIR."""
import argparse
import json
import math
import runpy
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from aha3d.orientation import canonical_rotation
from aha3d.blender.articulated import export_articulated, import_articulated
from aha3d.blender.roomkit import box, cabinet


STATIC_EXPORTER = PROJECT / '.agents/skills/blender-roomkit/scripts/export_assets.py'


def orientation(front='X', up='Z', origin='floor_center', symmetry='none', status='authored'):
    return {'schema_version': 1, 'front_axis': None if symmetry == 'continuous_z' else front,
            'up_axis': up, 'symmetry': symmetry, 'origin': origin,
            'semantic_front': 'none' if symmetry == 'continuous_z' else 'generic',
            'status': status, 'evidence': 'Synthetic fixture: front marker and upright geometry authored explicitly.'}


def refresh():
    for obj in bpy.context.scene.objects:
        obj.update_tag()
    bpy.context.view_layer.update()


def evaluated(obj):
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()


def assert_matrix(actual, expected, label):
    error = max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4))
    assert error < 2e-5, (label, error, actual, expected)


def rejects(fn, phrase):
    try:
        fn()
    except ValueError as error:
        assert phrase.lower() in str(error).lower(), (phrase, str(error))
    else:
        raise AssertionError('Expected rejection: ' + phrase)


def static_export(output, items, source_frame=1):
    config_path = output.parent / (output.name + '.selection.json')
    config_path.write_text(json.dumps({'source_frame': source_frame, 'furniture': items,
                                     'material_prefix': '__fixture_no_materials__'}, indent=2))
    previous = sys.argv
    try:
        sys.argv = [str(STATIC_EXPORTER), '--', '--config', str(config_path), '--out', str(output)]
        runpy.run_path(str(STATIC_EXPORTER), run_name='__main__')
    finally:
        sys.argv = previous
    return json.loads((output / 'manifest.json').read_text())


def append_static(library, name):
    with bpy.data.libraries.load(str(library), link=False) as (source, target):
        target.collections = [name]
    col = target.collections[0]
    bpy.context.scene.collection.children.link(col)
    refresh()
    return col


def mesh_points(collection):
    return [obj.matrix_world @ vertex.co for obj in collection.all_objects if obj.type == 'MESH'
            for vertex in obj.data.vertices]


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source = bpy.data.objects.new('Asymmetric fixture source root', None)
    bpy.context.scene.collection.objects.link(source)
    for label, point, dimensions in [('Body', (0, 0, .8), (.8, 1.2, 1.6)),
                                     ('FrontMarker', (1.0, 0, .8), (.2, .3, .2)),
                                     ('TopMarker', (0, 0, 1.8), (.2, .2, .2))]:
        part = box('OrientationFixture ' + label, point, dimensions, edge=0)
        part.parent = source
    source.location = (5, -2, .7)
    source.rotation_euler.z = .37
    bpy.context.scene.frame_set(9)
    refresh()
    source_objects = [source] + list(source.children_recursive)
    before = {obj.name: evaluated(obj) for obj in source_objects}
    missing = {'root': source.name, 'name': 'Missing orientation', 'catalog': 'Test', 'description': 'Test fixture'}
    rejects(lambda: static_export(output / 'missing-static', [missing]), 'orientation')
    assert not (output / 'missing-static').exists()
    source['roomkit_forward'] = '-Y'
    rejects(lambda: static_export(output / 'legacy-claim-static', [missing]), 'orientation')
    unknown = dict(missing, orientation=orientation(status='declared'))
    rejects(lambda: static_export(output / 'untrusted-static', [unknown]), 'orientation')
    items = [dict(missing, name='Floor centered +X fixture', orientation=orientation()),
             dict(missing, name='Mount root +X fixture', orientation=orientation(origin='mount_center')),
             dict(missing, name='Source root +X fixture', orientation=orientation(origin='source_root'))]
    manifest = static_export(output / 'static', items)
    assert bpy.context.scene.frame_current == 9
    for obj in source_objects:
        assert_matrix(evaluated(obj), before[obj.name], 'Static exporter preserves source transforms')
    for item in manifest['furniture']:
        assert item['orientation']['front_axis'] == '-Y'
        assert item['orientation']['up_axis'] == 'Z'
        assert item['source_orientation']['front_axis'] == 'X'
        assert item['orientation']['status'] == 'authored'
        col = append_static(output / 'static' / manifest['library'], item['name'])
        marker = next(obj for obj in col.all_objects if obj.name.startswith('OrientationFixture FrontMarker'))
        body = next(obj for obj in col.all_objects if obj.name.startswith('OrientationFixture Body'))
        delta = marker.matrix_world.translation - body.matrix_world.translation
        assert delta.y < -.9 and abs(delta.x) < 1e-5 and abs(delta.z) < 1e-5, delta
        points = mesh_points(col)
        low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
        high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
        if item['orientation']['origin'] == 'floor_center':
            assert abs(low.z) < 1e-5 and abs(low.x + high.x) < 1e-5 and abs(low.y + high.y) < 1e-5
        else:
            expected = Matrix(canonical_rotation(item['source_orientation'])) @ Vector((1, 0, .8))
            assert (marker.matrix_world.translation - expected).length < 1e-5
    # Continuous rotation symmetry has an up direction but no claimed front.
    sym_root = bpy.data.objects.new('Symmetric fixture', None)
    bpy.context.scene.collection.objects.link(sym_root)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=.2, depth=.6, location=(0, 0, .3))
    bpy.context.object.parent = sym_root
    sym_root['asset_orientation_json'] = json.dumps(orientation(front=None, symmetry='continuous_z'))
    sym_item = dict(missing, root=sym_root.name, name='Nondirectional fixture')
    symmetric = static_export(output / 'symmetric', [sym_item])
    assert symmetric['forward'] is None
    assert symmetric['furniture'][0]['orientation']['front_axis'] is None
    assert symmetric['furniture'][0]['orientation']['symmetry'] == 'continuous_z'
    # Missing/declared orientation must also stop articulated exports.
    cabinet_root, controls = cabinet('Orientation cabinet', location=(4, 2, .3))
    cabinet_root.rotation_euler.z = -.23
    if 'asset_orientation_json' in cabinet_root:
        del cabinet_root['asset_orientation_json']
    rejects(lambda: export_articulated(cabinet_root, output / 'missing-rig'), 'orientation')
    rejects(lambda: export_articulated(cabinet_root, output / 'untrusted-rig', orientation=orientation(status='declared')), 'orientation')
    # Rotate the whole source-local geometry +90 degrees: its semantic front is
    # now +X. A distinct external placement/rotation tests frame separation.
    source_rotation = Matrix.Rotation(math.pi / 2, 4, 'Z')
    base = bpy.data.objects.new('Original rig frame', None)
    bpy.context.scene.collection.objects.link(base)
    base.parent = cabinet_root
    for child in list(cabinet_root.children):
        if child != base:
            local = child.matrix_local.copy()
            child.parent = base
            child.matrix_parent_inverse = Matrix.Identity(4)
            child.matrix_basis = local
    base.matrix_basis = source_rotation
    source_data = orientation(front='X', origin='floor_center')
    source_data['semantic_front'] = 'door'
    cabinet_root['asset_orientation_json'] = json.dumps(source_data)
    cabinet_root['asset_root'] = True
    for ctrl in controls:
        ctrl['Open'] = .6
    refresh()
    rig_objects = [cabinet_root] + list(cabinet_root.children_recursive)
    open_before = {obj.name: evaluated(obj) for obj in rig_objects}
    bases = {ctrl['joint_id']: ctrl.matrix_basis.copy() for ctrl in controls}
    rig_manifest = export_articulated(cabinet_root, output / 'rig', asset_name='Oriented Cabinet')
    for obj in rig_objects:
        assert_matrix(evaluated(obj), open_before[obj.name], 'Articulated source remains open and unchanged')
    for ctrl in controls:
        ctrl['Open'] = 0.
    refresh()
    inverse = cabinet_root.matrix_world.inverted()
    canonical = Matrix(canonical_rotation(source_data)).to_4x4()
    expected_closed = {obj.name: canonical @ inverse @ evaluated(obj) for obj in rig_objects}
    closed_bases = {ctrl['joint_id']: ctrl.matrix_basis.copy() for ctrl in controls}
    library = output / 'rig' / rig_manifest['library']
    bpy.ops.wm.read_factory_settings(use_empty=True)
    placed = import_articulated(library, rig_manifest['furniture'][0]['name'], location=(2, -4, .2), rotation=31,
                               instance_id='oriented-cabinet')
    refresh()
    own = [placed] + list(placed.children_recursive)
    assert sum(bool(obj.get('articulated_root')) for obj in own) == 1
    assert sum(bool(obj.get('asset_root')) for obj in own) == 1
    assert sum(bool(obj.get('instance_id')) for obj in own) == 1
    assert (placed.matrix_world.translation - Vector((2, -4, .2))).length < 1e-5
    own_inverse = placed.matrix_world.inverted()
    imported_controls = []
    for obj in placed.children_recursive:
        if obj.get('asset_source_object'):
            assert_matrix(own_inverse @ evaluated(obj), expected_closed[obj['asset_source_object']],
                          'Canonical closed geometry matches rotated source frame')
        if obj.get('joint_id'):
            imported_controls.append(obj)
            assert_matrix(obj.matrix_basis, closed_bases[obj['joint_id']], 'Joint local closed basis retained')
    assert len(imported_controls) == 3
    first = imported_controls[0]
    closed = evaluated(first)
    first['Open'] = 1.
    refresh()
    assert max(abs(evaluated(first)[i][j] - closed[i][j]) for i in range(4) for j in range(4)) > .1
    opened = evaluated(first)
    first['Open'] = 0.
    refresh()
    assert_matrix(evaluated(first), closed, 'Canonical cabinet still closes exactly')
    first['Open'] = 1.
    refresh()
    saved = output / 'canonical_articulated.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    identity = first['joint_id']
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    first = next(obj for obj in bpy.context.scene.objects if obj.get('joint_id') == identity)
    assert_matrix(evaluated(first), opened, 'Canonical rig reopens with native controls')
    result = {'status': 'passed', 'checks': ['trusted orientation required for both exporters',
        'explicit +X static source mapped to -Y', 'static floor/mount/source origins respected',
        'nondirectional symmetry has no fabricated front', 'original sources preserved',
        'articulated wrapper preserves native joint locals', 'single semantic/articulated root',
        'declared articulated origin preserved', 'closed/open control survives save/reopen']}
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print('ORIENTATION_EXPORT_CHECK_PASSED ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    run(Path(args.out).resolve())
