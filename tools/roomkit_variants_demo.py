"""Build, package and inspect the synthetic RoomKit semantic-asset demonstration.

Run with background Blender 5.2.1. Each phase writes only its claimed outputs.
No source scene is saved over. The demo is a functionality fixture, not a video
reconstruction or a measurement of a physical room.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def extract(out):
    sources = [
        ('chair', ROOT / 'scenes/open_plan_group_walk_g0055/blender/correction_20260910/room_corrected_v2.blend',
         'Dining near chair 1', 'RK Chair - Open Frame Dining', 'Seating/Chairs',
         'Existing source-specific dining chair with armrests and simplified slatted back; normalized for reuse.'),
        ('vase', ROOT / 'scenes/living_room_kitchen_g0025/blender/walkthrough_cabinet_animation/living_room_kitchen_operable_cabinets.blend',
         'Coffee table ceramic vase', 'RK Vase - Rounded Ceramic', 'Decor/Tabletop/Vases',
         'Existing rounded ceramic vase with open narrow neck; extracted without rebuilding the source room.')]
    reports = []
    for key, source, root_name, name, catalog, description in sources:
        destination = ROOT / 'assets/scene-extracted/v1' / key
        if (destination / 'manifest.json').exists():
            reports.append({'asset': key, 'status': 'existing immutable extraction', 'destination': str(destination)})
            continue
        before = digest(source)
        bpy.ops.wm.open_mainfile(filepath=str(source))
        config = {'source_frame': 1, 'material_prefix': '__only_selected_object_materials__',
                  'register_materials': False,
                  'furniture': [{'root': root_name, 'name': name, 'catalog': catalog,
                                 'description': description}]}
        selection = out / (key + '_selection.json')
        write(selection, config)
        previous = sys.argv
        try:
            sys.argv = ['export_assets.py', '--', '--config', str(selection), '--out', str(destination)]
            if os.environ.get('ROOMKIT_ASSET_PREVIEWS') == '1':
                sys.argv.append('--previews')
            runpy.run_path(str(ROOT / '.agents/skills/blender-roomkit/scripts/export_assets.py'), run_name='__main__')
        finally:
            sys.argv = previous
        assert digest(source) == before, 'Source scene changed during extraction'
        record = {'asset': key, 'source': str(source.relative_to(ROOT)), 'source_sha256': before,
                  'source_root': root_name, 'destination': str(destination.relative_to(ROOT)),
                  'status': 'extracted; import and visual validation pending'}
        write(destination / 'provenance.json', record)
        reports.append(record)
    write(out / 'extraction.json', reports)


def material(name, color, roughness=.55):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    mat.diffuse_color = (*color, 1)
    return mat


def build(out):
    from aha3d.blender.roomkit import box, cabinet, import_collection
    from aha3d.blender.semantics import tag_root, tag_support, tag_surface, export_semantics
    from aha3d.assets import resolve
    from aha3d.blender.articulated import export_articulated
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    ivory = material('Demo warm ivory', (.73, .69, .60))
    blue = material('Demo cabinet blue', (.075, .22, .28))
    oak = material('Demo light interior', (.52, .35, .20))
    floor = material('Demo pale floor', (.41, .43, .44))
    box('Floor', (0, 0, -.07), (10, 8, .14), floor, surface_role='floor_finish')
    box('Rear wall', (0, 3.1, 1.55), (10, .12, 3.1), ivory, surface_role='wall_finish')
    generated = []
    for index, (preset, x) in enumerate(zip(('default', 'three_drawers', 'mixed', 'open_shelving'), (-2.85, -.95, .95, 2.85))):
        root, controls = cabinet('Cabinet ' + preset, (x, 2.12, 0), (1.65, .65, 1.45),
                                 blue, oak, layout=preset, instance_id='cabinet-' + preset)
        generated.append((root, controls))
    library = resolve('roomkit-v1', root=ROOT)
    for i, x in enumerate((-1.25, 1.25), 1):
        import_collection(library, 'RK Chair - Walnut Lounge', (x, -.8, 0), rotation=0,
                          semantic_class='furniture/seating/chairs', instance_id='chair-' + str(i),
                          asset_id='roomkit-v1/chair-walnut-lounge')
    # A primitive support plinth exercises the existing box helper, not a new furniture asset.
    table = bpy.data.objects.new('Demo support plinth root', None)
    scene.collection.objects.link(table)
    tag_root(table, 'furniture/tables', 'support-plinth', 'generator/roomkit-box')
    for name, loc, size in [('top', (0, -.75, .52), (.8, .65, .08)),
                            ('base', (0, -.75, .24), (.36, .36, .48))]:
        part = box('Support plinth ' + name, loc, size, oak)
        part.parent = table
    tag_support(table, -.4, .4, -1.075, -.425, .56)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1, location=(0, -.75, .68))
    prop = bpy.context.object
    prop.name = 'Placeholder tabletop vase'
    prop.scale = (.11, .11, .12)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    prop.data.materials.append(ivory)
    prop = tag_root(prop, 'decor/tabletop/vases', 'tabletop-vase', 'demo/placeholder', 'support-plinth')
    # Placement root is at contact with the support; geometry remains in place.
    child = prop.children[0]
    world = child.matrix_world.copy()
    prop.location.z = .56
    bpy.context.view_layer.update()
    child.matrix_world = world
    scene.world = bpy.data.worlds.new('Demo world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.65, .72, .82, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .3
    for name, loc, energy, size in [('Key', (0, -3, 5), 1700, 6), ('Fill', (-4, 0, 3), 800, 4)]:
        data = bpy.data.lights.new(name, 'AREA')
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = loc
        obj.rotation_euler = (Vector((0, 1, .6)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
        data.energy, data.shape, data.size = energy, 'DISK', size
    data = bpy.data.cameras.new('Demo camera')
    camera = bpy.data.objects.new('Demo camera', data)
    scene.collection.objects.link(camera)
    camera.location = (5.9, -10.5, 6.4)
    camera.rotation_euler = (Vector((0, .8, .65)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    data.type, data.ortho_scale = 'ORTHO', 10
    scene.camera = camera
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1200, 780
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    scene.frame_start, scene.frame_end = 1, 1
    source = out / 'source.blend'
    if source.exists():
        raise ValueError('Demo source exists; choose a new output folder')
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    export_semantics(out / 'source_semantics.json')
    destination = ROOT / 'assets/cabinets/v1'
    if not (destination / 'manifest.json').exists():
        export_articulated(generated[2][0], destination, asset_name='RK Cabinet - Mixed Storage')
    write(out / 'build.json', {'source': str(source), 'source_sha256': digest(source),
                              'cabinet_controls': {r['instance_id']: len(c) for r, c in generated},
                              'scope': 'Synthetic reusable-asset functionality demonstration; no video reference'})


def render(out, source):
    from aha3d.blender.stage import gpu
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    gpu(scene)
    controls = [obj for obj in scene.objects if obj.get('joint_id')]
    original = {obj.name: obj.get(obj.get('roomkit_open_property', 'open_amount'), 0) for obj in controls}
    for state, amount in [('closed', 0.), ('open', 1.)]:
        for obj in controls:
            obj[obj.get('roomkit_open_property', 'open_amount')] = amount
            obj.update_tag()
        scene.frame_set(scene.frame_current)
        bpy.context.view_layer.update()
        scene.render.filepath = str(out / (source.stem + '_' + state + '.png'))
        bpy.ops.render.render(write_still=True)
    for obj in controls:
        obj[obj.get('roomkit_open_property', 'open_amount')] = original[obj.name]
    # Render-only state changes are not saved into the source scene.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['extract', 'build', 'render'], required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'runs/roomkit_variants_demo/20260910')
    parser.add_argument('--source', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.out.mkdir(parents=True, exist_ok=True)
    if args.phase == 'extract':
        extract(args.out)
    elif args.phase == 'build':
        build(args.out)
    else:
        render(args.out, args.source or args.out / 'source.blend')


if __name__ == '__main__':
    main()
