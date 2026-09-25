"""Meaningful Blender checks. Invoke background Blender with --python-exit-code 1.

Optional -- --out /claimed/checks.json saves the validation summary.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from aha3d.assets import resolve, resolve_item
from aha3d.orientation import authored_orientation
from aha3d.blender.orientation import tag_orientation
from aha3d.blender.roomkit import box, import_collection
from aha3d.blender.semantics import descendants, export_semantics, tag_root, tag_surface, tag_support
from aha3d.blender.variants import apply_variant, plan_variant, place_asset


def rejects(fn, phrase):
    try:
        fn()
    except ValueError as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError('Expected failure containing: ' + phrase)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path)
    parser.add_argument('--articulated-id', help='Exercise registered articulated placement/replacement when supplied')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    checks = []
    # Newly authored transforms must survive immediate collection-instance wrapping.
    legacy = import_collection(resolve('roomkit-v1', root=PROJECT), 'RK Chair - Walnut Lounge',
                               location=(2, 3, 0), rotation=37, scale=1.2)
    bpy.context.view_layer.update()
    expected = legacy.matrix_world.copy()
    root = tag_root(legacy, 'furniture/seating/chairs', instance_id='chair-legacy')
    # This raw legacy import still uses the source asset frame; do not assign a
    # canonical front until its geometry has actually been normalized.
    tag_orientation(root, resolve_item('roomkit-v1/chair-walnut-lounge', root=PROJECT)['orientation'])
    bpy.context.view_layer.update()
    assert root != legacy and legacy.parent == root
    assert (root.matrix_world.translation - Vector((2, 3, 0))).length < 1e-6
    assert all(abs(root.matrix_world[i][j] - expected[i][j]) < 1e-6 for i in range(4) for j in range(4))
    checks.append('legacy instance wrapping preserves placement')
    chair_a = place_asset('roomkit-v1/chair-walnut-lounge', location=(-2, 0, 0), instance_id='chair-a', project_root=PROJECT)
    chair_b = place_asset('roomkit-v1/chair-walnut-lounge', location=(2, 0, 0), instance_id='chair-b', project_root=PROJECT)
    mesh_a = next(obj for obj in descendants(chair_a) if obj.type == 'MESH')
    mesh_b = next(obj for obj in descendants(chair_b) if obj.type == 'MESH')
    # Explicitly share data, then override only one semantic surface.
    mesh_b.data = mesh_a.data
    before_material = mesh_b.material_slots[0].material
    tag_surface(mesh_a, 'seat_fabric', slot=0)
    tag_surface(mesh_b, 'seat_fabric', slot=0)
    material_recipe = {'schema_version': 1, 'materials': [{
        'selector': {'instance_ids': ['chair-a']}, 'surface_role': 'seat_fabric',
        'asset_id': 'roomkit-v1/warm-ivory-lime-plaster', 'parameters': {'roughness': .2}}]}
    material_report = apply_variant(material_recipe, PROJECT)
    assert mesh_a.material_slots[0].material != before_material
    assert mesh_b.material_slots[0].material == before_material
    assert mesh_a.material_slots[0].link == 'OBJECT'
    checks.append('selected material assignment isolates shared mesh instances')
    # Independent wall/floor slots on the same shared material remain separate.
    shared = bpy.data.materials.new('shared architectural material')
    wall = box('wall', (0, 5, 1), (5, .1, 2), shared)
    floor = box('floor', (0, 0, -.05), (5, 5, .1), shared)
    tag_surface(wall, 'wall_finish')
    tag_surface(floor, 'floor_finish')
    bpy.context.view_layer.material_override = shared
    apply_variant({'schema_version': 1, 'materials': [{'surface_role': 'wall_finish',
        'asset_id': 'roomkit-v1/warm-ivory-lime-plaster'}]}, PROJECT)
    assert floor.material_slots[0].material == shared
    assert bpy.context.view_layer.material_override == shared
    apply_variant({'schema_version': 1, 'clear_material_override': True}, PROJECT)
    assert bpy.context.view_layer.material_override is None
    checks.append('wall and floor roles independent; clay clear is explicit')
    # A later invalid selector must stop all changes, including earlier valid ops.
    recipe = {'schema_version': 1, 'seed': 91, 'models': [{'selector': {'instance_ids': ['chair-a']},
              'asset_id': 'roomkit-v1/chair-walnut-lounge', 'fit': 'uniform_footprint'}]}
    invalid = json.loads(json.dumps(recipe))
    invalid['models'].append(dict(invalid['models'][0], selector={'instance_ids': ['missing']}))
    old_geometry = set(obj.name for obj in descendants(chair_a))
    rejects(lambda: apply_variant(invalid, PROJECT), 'Unknown instance')
    assert old_geometry == set(obj.name for obj in descendants(chair_a))
    checks.append('all operation preflight precedes scene mutation')
    a_pose, b_pose = chair_a.matrix_world.copy(), chair_b.matrix_world.copy()
    untouched_b = set(obj.name for obj in descendants(chair_b))
    plan1, plan2 = plan_variant(recipe, PROJECT), plan_variant(recipe, PROJECT)
    assert plan1 == plan2
    report = apply_variant(recipe, PROJECT)
    assert not any(bpy.data.objects.get(name) for name in old_geometry)
    assert set(obj.name for obj in descendants(chair_b)) == untouched_b
    assert chair_a['instance_id'] == 'chair-a' and chair_a.matrix_world == a_pose
    assert chair_b.matrix_world == b_pose
    assert report['models'][0]['fit'] == 'uniform_footprint'
    checks.append('deterministic plan, old geometry removal and root pose preservation')
    mirror = floor.modifiers.new('dependent mirror', 'MIRROR')
    mirror.mirror_object = next(obj for obj in descendants(chair_a) if obj.type == 'MESH')
    rejects(lambda: apply_variant(recipe, PROJECT), 'external modifier')
    floor.modifiers.remove(mirror)
    checks.append('external modifier geometry dependency rejected before deletion')
    chair_b['active_contact'] = True
    blocked = {'schema_version': 1, 'models': [dict(recipe['models'][0], selector={'instance_ids': ['chair-b']})]}
    rejects(lambda: apply_variant(blocked, PROJECT), 'active contact')
    del chair_b['active_contact']
    chair_b.location.x = 2
    chair_b.keyframe_insert(data_path='location', frame=1)
    rejects(lambda: apply_variant(blocked, PROJECT), 'animated replacement')
    checks.append('active contact and animated replacements rejected')
    # Missing candidates never silently become usable registered assets.
    index = json.loads((PROJECT / 'assets/index.json').read_text())
    candidate = next(item['id'] for item in index['entries'] if item['status'] == 'needs_extraction')
    rejects(lambda: resolve_item(candidate, root=PROJECT), 'needs_extraction')
    table = tag_root(box('table', (0, 0, .7), (2, 2, .1)), 'furniture/tables', instance_id='table')
    tag_orientation(table, authored_orientation('generic', origin='source_root',
        evidence='Synthetic table slab authored in local XYZ; -Y is its explicit test front.'))
    tag_support(table, -1, 1, -1, 1, .05)
    semantics = export_semantics()
    assert semantics['schema_version'] == 1
    assert {'chair-a', 'chair-b', 'chair-legacy', 'table'} <= {item['instance_id'] for item in semantics['instances']}
    checks.append('semantic export and extraction status contract')
    if args.articulated_id:
        cabinet = place_asset(args.articulated_id, location=(5, 1, 0), rotation=20,
                              instance_id='cabinet-registered', project_root=PROJECT)
        assert cabinet.get('asset_articulated') and cabinet.get('support_plane')
        controls = [obj for obj in descendants(cabinet) if obj.get('joint_id')]
        assert controls and all(obj.animation_data and obj.animation_data.drivers for obj in controls)
        support = json.loads(cabinet['support_plane'])
        prop = tag_root(box('supported prop', (0, 0, 0), (.1, .1, .1)),
                        'props/decor', instance_id='supported-prop', support_id='cabinet-registered')
        tag_orientation(prop, authored_orientation('generic', origin='source_root',
            evidence='Synthetic test cube uses an explicit -Y reference face; no inferred facing intent.'))
        prop.location = cabinet.matrix_world @ Vector((0, 0, support['z'] + .05))
        bpy.context.view_layer.update()
        before_prop = prop.matrix_world.copy()
        before_cabinet = cabinet.matrix_world.copy()
        replacement = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['cabinet-registered']},
                         'asset_id': args.articulated_id, 'fit': 'native'}]}
        cabinet_report = apply_variant(replacement, PROJECT)
        assert cabinet.matrix_world == before_cabinet and prop.matrix_world == before_prop
        assert cabinet_report['affected_dependents'] == ['supported-prop']
        check = cabinet_report['dependent_support_checks'][0]['support_check']
        assert check['passes_tolerance'], check
        assert json.loads(cabinet['support_plane']) == support
        controls = [obj for obj in descendants(cabinet) if obj.get('joint_id')]
        assert controls and all(obj.animation_data and obj.animation_data.drivers for obj in controls)
        exported = export_semantics()
        assert set(exported['joints']['cabinet-registered']) == {ctrl['joint_id'] for ctrl in controls}
        assert all(record['property'] in ('Open', 'open_amount') and record['value'] == 0
                   for record in exported['joints']['cabinet-registered'].values())
        json.dumps(exported, allow_nan=False)
        cabinet.scale.x = 2
        bpy.context.view_layer.update()
        rejects(lambda: plan_variant(replacement, PROJECT), 'positive uniform transform')
        checks.append('registered articulated placement/replacement preserves rigs and dependent props; scaled rig rejection')
    result = {'passed': True, 'checks': checks, 'checks_count': len(checks), 'variant_report': report}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
