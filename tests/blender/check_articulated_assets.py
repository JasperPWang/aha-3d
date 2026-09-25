"""Blender regression: --python this_file -- --out NEW_DIR, writes only NEW_DIR."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from aha3d.blender.articulated import export_articulated, import_articulated
from aha3d.blender import roomkit as rk


def assert_close(actual, expected, message, tolerance=1e-5):
    if isinstance(actual, Matrix):
        error = max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4))
    else:
        error = abs(actual - expected)
    assert error < tolerance, (message, error, actual, expected)


def refresh():
    for obj in bpy.context.scene.objects:
        obj.update_tag()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def evaluated_matrix(obj):
    refresh()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()


def control(root, joint_id):
    return next(obj for obj in root.children_recursive if obj.get('joint_id') == joint_id)


def expect_rejection(fn, label):
    try:
        fn()
    except (ValueError, FileExistsError):
        return label
    raise AssertionError('Expected rejection: ' + label)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    material = bpy.data.materials.new('Test procedural finish')
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (.32, .17, .07, 1)
    image = bpy.data.images.new('Fixture external image', width=2, height=2)
    image.filepath_raw = str(output / 'fixture_texture.png')
    image.file_format = 'PNG'
    image.pixels = [.3, .2, .1, 1] * 4
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(str(output / 'fixture_texture.png'))
    image_node = material.node_tree.nodes.new('ShaderNodeTexImage')
    image_node.image = image
    material.node_tree.links.new(image_node.outputs['Color'], shader.inputs['Base Color'])
    root, controls = rk.cabinet('Portable fixture', location=(4, -3, .4), material=material)
    root.rotation_euler.z = math.radians(37)
    root['instance_id'] = 'source-cabinet'
    root['semantic_class'] = 'cabinet'
    root['asset_id'] = 'fixture/cabinet'
    root['support_id'] = 'floor-01'
    for index, ctrl in enumerate(controls):
        ctrl['joint_id'] = 'test-joint-' + str(index)
        ctrl['joint_type'] = 'slider' if 'Drawer' in ctrl.name else 'hinge'
    # Canonical open_amount and legacy Open are both supported by remapping.
    first = controls[0]
    first['open_amount'] = .65
    first.id_properties_ui('open_amount').update(min=0, max=1)
    for curve in first.animation_data.drivers:
        for variable in curve.driver.variables:
            variable.targets[0].data_path = '["open_amount"]'
    first.keyframe_insert(data_path='["open_amount"]', frame=1)
    first['open_amount'] = 1.0
    first.keyframe_insert(data_path='["open_amount"]', frame=12)
    controls[1]['Open'] = .3
    controls[2]['Open'] = .5
    bpy.context.scene.frame_set(1)
    refresh()
    root['main_controller'] = first
    source_objects = [root] + list(root.children_recursive)
    snapshot = {obj.name: evaluated_matrix(obj) for obj in source_objects}
    source_frame = bpy.context.scene.frame_current
    source_action = first.animation_data.action
    source_image = image
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'source.blend'))
    manifest = export_articulated(root, output / 'library', 'RK Portable Cabinet Test')
    assert manifest['furniture'][0]['articulation']
    assert manifest['source']['saved_file_sha256']
    assert bpy.context.scene.frame_current == source_frame
    assert first.animation_data.action == source_action
    assert not source_image.packed_file, 'Export must not pack source image in place'
    assert set(snapshot) == {obj.name for obj in bpy.data.objects}
    for obj in source_objects:
        assert_close(evaluated_matrix(obj), snapshot[obj.name], 'source scene preserved')
    rejected = []
    rejected.append(expect_rejection(lambda: export_articulated(root, output / 'library'), 'immutable_output'))
    foreign = bpy.data.objects.new('Foreign control', None)
    bpy.context.scene.collection.objects.link(foreign)
    driver_target = first.animation_data.drivers[0].driver.variables[0].targets[0]
    own_target = driver_target.id
    driver_target.id = foreign
    rejected.append(expect_rejection(lambda: export_articulated(root, output / 'bad_driver'), 'external_driver'))
    driver_target.id = own_target
    part = next(obj for obj in root.children_recursive if obj.type == 'MESH')
    constraint = part.constraints.new('COPY_LOCATION')
    constraint.target = foreign
    rejected.append(expect_rejection(lambda: export_articulated(root, output / 'bad_constraint'), 'external_constraint'))
    part.constraints.remove(constraint)
    modifier = part.modifiers.new('External mirror', 'MIRROR')
    modifier.mirror_object = foreign
    rejected.append(expect_rejection(lambda: export_articulated(root, output / 'bad_modifier'), 'external_modifier'))
    part.modifiers.remove(modifier)
    texture_coordinates = material.node_tree.nodes.new('ShaderNodeTexCoord')
    texture_coordinates.object = foreign
    rejected.append(expect_rejection(lambda: export_articulated(root, output / 'bad_material'), 'external_material_coordinate'))
    material.node_tree.nodes.remove(texture_coordinates)
    first.animation_data.action = None
    for ctrl in controls:
        ctrl['Open'] = 0.0
        if 'open_amount' in ctrl:
            ctrl['open_amount'] = 0.0
    refresh()
    source_inverse = root.matrix_world.inverted()
    source_closed = {obj.name: source_inverse @ evaluated_matrix(obj) for obj in source_objects}
    library = output / 'library' / manifest['library']
    collection_name = manifest['furniture'][0]['name']
    bpy.ops.wm.read_factory_settings(use_empty=True)
    (output / 'fixture_texture.png').rename(output / 'fixture_texture_hidden.png')
    a = import_articulated(library, collection_name, location=(1, 2, 0), rotation=20,
                           instance_id='cabinet-a', asset_id='test-v1/cabinet')
    b = import_articulated(library, collection_name, location=(-2, 1, 0), rotation=-15,
                           instance_id='cabinet-b')
    assert a != b and a['instance_id'] != b['instance_id']
    assert a['support_id'] == 'floor-01' and a['semantic_class'] == 'cabinet'
    assert a['asset_id'] == 'test-v1/cabinet'
    assert all(obj.library is None for obj in bpy.data.objects)
    assert all(image.packed_file for image in bpy.data.images if image.name.startswith('Fixture external image'))
    rejected.append(expect_rejection(lambda: import_articulated(library, collection_name,
                                    instance_id='cabinet-a'), 'duplicate_instance_id'))
    a_controls = [control(a, 'test-joint-' + str(i)) for i in range(3)]
    b_controls = [control(b, 'test-joint-' + str(i)) for i in range(3)]
    assert a['main_controller'] == a_controls[0]
    assert b['main_controller'] == b_controls[0]
    for rig, ctrls in ((a, a_controls), (b, b_controls)):
        owned = {rig} | set(rig.children_recursive)
        for obj in owned:
            if obj.animation_data:
                assert obj.animation_data.action is None, 'Source timeline must not override closed asset controls'
                for curve in obj.animation_data.drivers:
                    assert all(target.id in owned for variable in curve.driver.variables for target in variable.targets)
        for ctrl in ctrls:
            prop = 'open_amount' if 'open_amount' in ctrl else 'Open'
            assert_close(ctrl[prop], 0, 'import starts closed')
    before_a = {obj.name: evaluated_matrix(obj) for obj in a.children_recursive}
    before_b = {obj.name: evaluated_matrix(obj) for obj in b.children_recursive}
    a_controls[0]['open_amount'] = 1.0
    a_controls[1]['Open'] = .5
    a_controls[2]['Open'] = 1.0
    refresh()
    moved = sum(max(abs(evaluated_matrix(obj)[i][j] - before_a[obj.name][i][j])
                    for i in range(4) for j in range(4)) > .02 for obj in a.children_recursive)
    assert moved >= 5, ('Opening must visibly transform geometry', moved)
    for obj in b.children_recursive:
        assert_close(evaluated_matrix(obj), before_b[obj.name], 'second cabinet stays closed')
    assert_close(a.matrix_world.translation.x, 1, 'placement x')
    assert_close(a.matrix_world.translation.y, 2, 'placement y')
    assert_close(a.matrix_world.translation.z, 0, 'placement z')
    for obj in b.children_recursive:
        assert_close(b.matrix_world.inverted() @ evaluated_matrix(obj), source_closed[obj['asset_source_object']],
                     'root-relative closed transform')
    a_controls[0].keyframe_insert(data_path='["open_amount"]', frame=1)
    a_controls[0]['open_amount'] = .25
    a_controls[0].keyframe_insert(data_path='["open_amount"]', frame=12)
    bpy.context.scene.frame_set(12)
    expected = evaluated_matrix(a_controls[0])
    saved = output / 'two_independent_cabinets.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    hidden_library = library.with_suffix('.hidden')
    library.rename(hidden_library)
    try:
        bpy.ops.wm.open_mainfile(filepath=str(saved))
        a2 = next(obj for obj in bpy.context.scene.objects if obj.get('instance_id') == 'cabinet-a')
        b2 = next(obj for obj in bpy.context.scene.objects if obj.get('instance_id') == 'cabinet-b')
        assert_close(evaluated_matrix(control(a2, 'test-joint-0')), expected, 'saved animation remains functional')
        assert_close(control(b2, 'test-joint-0')['open_amount'], 0, 'independence survives reopen')
        assert all(obj.library is None for obj in bpy.data.objects)
    finally:
        hidden_library.rename(library)
    report = {'status': 'passed', 'moved_objects': moved, 'rejected_unsafe_cases': rejected,
              'checks': ['source scene preserved', 'packed texture without source mutation',
                         'rotated translated source rest frame preserved', 'closed canonical export',
                         'independent controls and internal custom pointers', 'local appended data',
                         'saved animation works without source library'],
              'manifest': str(output / 'library' / 'manifest.json'), 'saved_scene': str(saved)}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('ARTICULATED_ASSET_CHECK_PASSED ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    run(Path(args.out).resolve())
