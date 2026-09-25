"""Run inside background Blender; inspect saved native joint evaluation."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender.cabinets import build_cabinet
from aha3d.blender.semantics import descendants


def close(actual, expected, label, tolerance=2e-5):
    if abs(actual - expected) > tolerance:
        raise AssertionError('{}: {} != {}'.format(label, actual, expected))


def set_open(controls, value):
    for ctrl in controls:
        ctrl['open_amount'] = value
        ctrl.update_tag()
    bpy.context.view_layer.update()


def evaluated_joint(root, ctrl):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return (root.evaluated_get(depsgraph).matrix_world.inverted()
            @ ctrl.evaluated_get(depsgraph).matrix_world)


def check_joint(root, ctrl, amount):
    matrix = evaluated_joint(root, ctrl)
    expected = Vector(ctrl['joint_closed_location'])
    if ctrl['joint_type'] == 'slider':
        expected.y += amount * ctrl['joint_limit']
        angle = 0.
    else:
        angle = amount * ctrl['joint_limit']
    for i in range(3):
        close(matrix.translation[i], expected[i], ctrl.name + ' placement')
    close(matrix.to_euler().z, angle, ctrl.name + ' hinge angle')
    return {'location': list(matrix.translation), 'angle_z': matrix.to_euler().z}


def contains_point(obj, world_point):
    p = obj.matrix_world.inverted() @ world_point
    return all(min(v[i] for v in obj.bound_box) + 1e-5 < p[i]
               < max(v[i] for v in obj.bound_box) - 1e-5 for i in range(3))


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    variants = []
    for i, preset in enumerate(('default', 'three_drawers', 'mixed', 'open_shelving')):
        root, controls = build_cabinet(preset, location=(i * 2., 1.1, .2),
            size=(1.6, .65, 1.45), layout=preset, instance_id='check-' + preset)
        root.rotation_euler.z = math.radians(27 if i % 2 == 0 else -19)
        bpy.context.view_layer.update()
        expected_count = {'default': 3, 'three_drawers': 3, 'mixed': 4, 'open_shelving': 0}[preset]
        assert len(controls) == expected_count, (preset, len(controls))
        assert len({c['joint_id'] for c in controls}) == len(controls)
        assert json.loads(root['support_plane'])['z'] == 1.45
        assert root['semantics_schema_version'] == 1
        assert root['semantic_class'] == 'furniture/storage/cabinets'
        children = descendants(root)
        assert all(o in children for c in controls for o in c.children)
        assert all(c.parent == root for c in controls)
        assert all(o.get('surface_role') for o in children if o.type == 'MESH')
        assert all(min(o.dimensions) > 0 for o in children if o.type == 'MESH')
        for c in controls:
            assert 'Open' not in c
            assert c['roomkit_open_property'] == 'open_amount'
            assert all(fc.driver.is_simple_expression for fc in c.animation_data.drivers)
            if c['joint_type'] == 'slider':
                moving = list(c.children)
                bottom = next(o for o in moving if o.get('cabinet_part') == 'drawer_bottom')
                # There must be usable empty air above the bottom, surrounded by moving walls.
                point = bottom.matrix_world @ Vector((0, 0, bottom.dimensions.z / 2 + .025))
                assert not any(contains_point(o, point) for o in moving), 'Drawer cavity is solid'
                assert len([o for o in moving if o.get('cabinet_part') == 'drawer_side']) == 2
                assert len([o for o in moving if o.get('cabinet_part') == 'drawer_back']) == 1
        samples = []
        for value in (0., .5, 1., .5, 0., -.5, 1.5, 0.):
            set_open(controls, value)
            amount = min(1., max(0., value))
            samples.append({'requested': value, 'evaluated': [check_joint(root, c, amount) for c in controls]})
        variants.append({'preset': preset, 'root': root.name, 'controls': [c.name for c in controls],
                         'samples': samples, 'part_count': len(children)})

    # A valid body with invalid late sections must not leave a half-built cabinet.
    before = (len(bpy.data.objects), len(bpy.data.collections), len(bpy.data.meshes))
    invalid = {'columns': [{'sections': [{'front': 'door_left'},
                                        {'front': 'drawers', 'drawer_count': 50}]}]}
    try:
        build_cabinet('invalid', layout=invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid layout accepted')
    assert before == (len(bpy.data.objects), len(bpy.data.collections), len(bpy.data.meshes))

    # Independent copies keep separate controllers and apply motion in local axes.
    first = bpy.data.objects[variants[0]['controls'][0]]
    other_root, others = build_cabinet('duplicate layout', location=(-2, 0, 0),
                                      layout='default', instance_id='independent-default')
    set_open([first], .7)
    check_joint(other_root, others[0], 0.)

    # Native keyframes and drivers must survive save/reopen and an open/close cycle.
    keyed_names = [name for variant in variants for name in variant['controls']]
    for name in keyed_names:
        ctrl = bpy.data.objects[name]
        for frame, value in ((1, 0.), (13, .5), (25, 1.), (37, 0.)):
            ctrl['open_amount'] = value
            ctrl.keyframe_insert(data_path='["open_amount"]', frame=frame)
    bpy.context.scene.frame_end = 37
    bpy.context.scene.frame_set(13)
    scene_path = output / 'cabinets_native.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
    bpy.ops.wm.open_mainfile(filepath=str(scene_path))
    for frame, amount in ((1, 0.), (13, .5), (25, 1.), (37, 0.)):
        bpy.context.scene.frame_set(frame)
        for variant in variants:
            root = bpy.data.objects[variant['root']]
            for name in variant['controls']:
                ctrl = bpy.data.objects[name]
                check_joint(root, ctrl, amount)
                assert all(fc.driver.is_valid for fc in ctrl.animation_data.drivers)
    bpy.context.scene.frame_set(13)
    report = {'status': 'passed', 'variants': variants,
              'saved_scene': str(scene_path), 'saved_reopen_native_animation': True,
              'invalid_layout_no_mutation': True, 'independent_instances': True,
              'visual_review': 'not performed by this validator',
              'limits': ['No general obstacle or person-contact collision checks.']}
    (output / 'cabinets_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'variants': len(variants), 'out': str(output)}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    run(args.out)
