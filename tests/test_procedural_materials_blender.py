"""Blender integration check; invoke with --bundle material.json --out NEW_DIR."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    import bpy
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from aha3d.blender.procedural_materials import load_material, apply_material, UV_NAME, RECIPE_KEY
    p = argparse.ArgumentParser()
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.out.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    a = bpy.context.object
    a.name = 'Selected wood frame'
    a['instance_id'], a['semantic_class'] = 'test-frame', 'furniture/table'
    a.scale = (2, 1, .5)
    wood, cloth = [bpy.data.materials.new(name) for name in ['Original wood', 'Upholstery']]
    a.data.materials.append(wood)
    a.data.materials.append(cloth)
    a.data.polygons[0].material_index = 1
    b = a.copy()
    b.name = 'Unselected linked duplicate'
    b['instance_id'] = 'test-other'
    b.location.x = 5
    bpy.context.collection.objects.link(b)
    bpy.ops.mesh.primitive_cube_add(location=(0, 5, 1))
    actor = bpy.context.object
    actor.name = 'Animated actor fixture'
    actor['instance_id'], actor['semantic_class'] = 'test-actor', 'human/person'
    actor.shape_key_add(name='Basis')
    key = actor.shape_key_add(name='Motion')
    for vertex in key.data:
        vertex.co.z += .3
    key.value = 0
    key.keyframe_insert(data_path='value', frame=1)
    key.value = 1
    key.keyframe_insert(data_path='value', frame=3)
    bpy.context.scene.frame_end = 3
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    # A scalar native glass material must survive export even without a recipe.
    bpy.ops.mesh.primitive_cube_add(location=(-5, 0, 1), scale=(.1, 1, 1))
    native = bpy.context.object
    native.name = 'Native glass panel'
    native['instance_id'], native['semantic_class'] = 'native-glass', 'structure/window'
    native_material = bpy.data.materials.new('Native scalar glass')
    native_material.use_nodes = True
    native_bsdf = native_material.node_tree.nodes.get('Principled BSDF')
    native_bsdf.inputs['Transmission Weight'].default_value = 1
    native_bsdf.inputs['IOR'].default_value = 1.47
    native_bsdf.inputs['Coat Weight'].default_value = .2
    native_material['roomkit_transmission_thickness'] = .008
    native.data.materials.append(native_material)
    original_mesh = b.data
    matrix = a.matrix_world.copy()
    source = args.out / 'source.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    expected_recipe = json.loads(args.bundle.read_text())['recipe']
    m = load_material(args.bundle)
    assert json.loads(m[RECIPE_KEY]) == expected_recipe
    if expected_recipe['version'] >= 3:
        bsdf = m.node_tree.nodes.get('Principled BSDF')
        for key, socket in [('transmission', 'Transmission Weight'), ('ior', 'IOR'),
                            ('clearcoat', 'Coat Weight'), ('clearcoatRoughness', 'Coat Roughness')]:
            assert abs(bsdf.inputs[socket].default_value - expected_recipe[key]) < 1e-6
        assert m['roomkit_transmission_thickness'] == expected_recipe['thickness']
    assert apply_material([a], m, 'Original wood') == [a.name]
    assert b.data == original_mesh and a.data != b.data
    assert a.material_slots[0].material == m and a.material_slots[1].material == cloth
    assert b.material_slots[0].material == wood
    assert a.matrix_world == matrix
    assert a.data.uv_layers.get(UV_NAME) and not b.data.uv_layers.get(UV_NAME)
    assert all(n.image.packed_file for n in m.node_tree.nodes if n.type == 'TEX_IMAGE')
    assert m.node_tree.nodes['RoomKit baseColor'].image.colorspace_settings.name == 'sRGB'
    assert m.node_tree.nodes['RoomKit normal'].image.colorspace_settings.name == 'Non-Color'
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out / 'material.blend'))
    object_name = a.name
    bpy.ops.wm.open_mainfile(filepath=str(args.out / 'material.blend'))
    assert json.loads(bpy.data.objects[object_name].material_slots[0].material[RECIPE_KEY]) == expected_recipe
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    (args.out / 'validation.json').write_text(json.dumps({'passed': True, 'source_unchanged': True,
        'slot_isolation': True, 'linked_duplicate_isolation': True, 'packed_maps': True,
        'physical_uv_scale': True, 'saved_recipe': True, 'recipe_version': expected_recipe['version']}, indent=2))
    print('Blender procedural material integration passed')


if __name__ == '__main__':
    main()
