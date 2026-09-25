"""Reopen the real CLI demo output and validate retained placement and native controls."""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender.roomkit import cabinet_controls, set_open, animate_open
from aha3d.blender.semantics import roots, export_semantics


def matrix_error(a, b):
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))


def snapshot():
    bpy.context.view_layer.update()
    return {'roots': {obj['instance_id']: {'matrix': obj.matrix_world.copy(), 'asset_id': obj.get('asset_id')}
                      for obj in roots()},
            'camera': bpy.context.scene.camera.matrix_world.copy()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--variant', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    before = snapshot()
    bpy.ops.wm.open_mainfile(filepath=str(args.variant))
    after = snapshot()
    assert set(before['roots']) == set(after['roots']), 'Semantic identities changed'
    assert matrix_error(before['camera'], after['camera']) < 1e-7, 'Camera moved'
    for identity in before['roots']:
        assert matrix_error(before['roots'][identity]['matrix'], after['roots'][identity]['matrix']) < 1e-7, identity
    for identity in ('chair-1', 'chair-2'):
        assert after['roots'][identity]['asset_id'] == 'dining-chair-v1/chair-open-frame-dining'
    assert after['roots']['tabletop-vase']['asset_id'] == 'ceramic-vase-v1/vase-rounded-ceramic'
    report = json.loads(args.variant.with_suffix('.variant.json').read_text())
    prop_report = next(item for item in report['models'] if item['instance_id'] == 'tabletop-vase')
    assert prop_report['support_check']['passes_tolerance'], prop_report['support_check']
    all_roots = {obj['instance_id']: obj for obj in roots()}
    cabinet = all_roots['cabinet-mixed']
    controls = cabinet_controls(cabinet)
    assert len(controls) == 4
    untouched = cabinet_controls(all_roots['cabinet-default'])
    untouched_matrices = [obj.matrix_world.copy() for obj in untouched]
    closed = [obj.matrix_world.copy() for obj in controls]
    set_open(cabinet, 1)
    assert all(matrix_error(obj.matrix_world, old) > 1e-3 for obj, old in zip(controls, closed))
    assert all(matrix_error(obj.matrix_world, old) < 1e-7 for obj, old in zip(untouched, untouched_matrices))
    set_open(cabinet, 0)
    assert all(matrix_error(obj.matrix_world, old) < 1e-6 for obj, old in zip(controls, closed))
    chosen = controls[0]['joint_id']
    animate_open(cabinet, chosen, [[0, 0], [1, 1], [2, 0]], frames=72, fps=24)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base = 1, 72, 24, 1
    scene.frame_set(25)
    open_matrix = controls[0].matrix_world.copy()
    assert matrix_error(open_matrix, closed[0]) > 1e-3
    scene.frame_set(1)
    output = args.out / 'controls_animated.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    bpy.ops.wm.open_mainfile(filepath=str(output))
    cabinet = next(obj for obj in roots() if obj['instance_id'] == 'cabinet-mixed')
    target = next(obj for obj in cabinet_controls(cabinet) if obj['joint_id'] == chosen)
    bpy.context.scene.frame_set(25)
    assert matrix_error(target.matrix_world, open_matrix) < 1e-6, 'Native key/driver lost on reopen'
    bpy.context.scene.frame_set(49)
    assert matrix_error(target.matrix_world, closed[0]) < 1e-6, 'Native closing failed'
    assert not bpy.data.libraries, 'Unexpected linked library dependency'
    export_semantics(args.out / 'reopened_semantics.json')
    result = {'status': 'passed', 'source': str(args.source), 'variant': str(args.variant),
              'retained_semantic_roots': len(after['roots']), 'unchanged_camera': True,
              'model_replacements_checked': ['chair-1', 'chair-2', 'tabletop-vase'],
              'tabletop_support_check': prop_report['support_check'],
              'independent_cabinet_controls': True, 'native_animation_reopen': True,
              'animation_frames': 72, 'animation_fps': 24,
              'limits': 'Static support and native articulation checks; no scene-wide collision or human-contact certification'}
    (args.out / 'integration.json').write_text(json.dumps(result, indent=2) + '\n')
    print('ROOMKIT_INTEGRATION_PASSED', json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
