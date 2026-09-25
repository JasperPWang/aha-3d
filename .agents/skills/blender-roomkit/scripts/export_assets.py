"""Extract furniture roots and procedural materials from an existing .blend.
blender -b source.blend --python export_assets.py -- --config selection.json --out library
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomkit as rk
from aha3d.orientation import canonical_orientation, canonical_rotation
from aha3d.blender.articulated import _trusted_export_orientation

def main():
    original_scene = bpy.context.window.scene
    original_frame = original_scene.frame_current
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--config', required=True)
        parser.add_argument('--out', required=True)
        parser.add_argument('--previews', action='store_true')
        parser.add_argument('--articulated', action='store_true',
                            help='Export one complete native articulated hierarchy, retaining drivers')
        args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        output = Path(args.out).resolve()
        if args.articulated:
            from aha3d.blender.articulated import export_articulated
            if len(config.get('furniture', [])) != 1:
                raise ValueError('Articulated export selects exactly one complete asset root')
            if args.previews:
                raise ValueError('Use the cabinet demo for articulated open/closed previews')
            item = config['furniture'][0]
            source = bpy.data.objects.get(item['root'])
            if source is None:
                raise ValueError('Missing source root: ' + item['root'])
            report = export_articulated(source, output, asset_name=item['name'], orientation=item.get('orientation'))
            print('ARTICULATED_ASSET_COMPLETE', json.dumps(report), flush=True)
            raise SystemExit(0)
        if (output / 'manifest.json').exists() or (output / 'roomkit_furniture_materials.blend').exists():
            raise ValueError('Choose a new asset version/output directory')
        # Validate every source before creating outputs or changing the source frame.
        source_orientations = []
        for item in config['furniture']:
            source = bpy.data.objects.get(item['root'])
            if source is None:
                raise ValueError('Missing source root: ' + item['root'])
            source_orientations.append(_trusted_export_orientation(source, item.get('orientation')))
        output.mkdir(parents=True, exist_ok=True)
        scene = bpy.context.scene
        scene.frame_set(config.get('source_frame', 1))
        dg = bpy.context.evaluated_depsgraph_get()
        catalogs, assets, material_map, image_map = {}, [], {}, {}


        def mark(block, catalog, description, tags):
            catalog_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'blender-roomkit/'+catalog))
            catalogs[catalog] = catalog_id
            block.asset_mark()
            block.asset_data.author = 'RoomKit'
            block.asset_data.description = description
            block.asset_data.catalog_id = catalog_id
            for tag in ['RoomKit', *tags]:
                block.asset_data.tags.new(tag)
            block.use_fake_user = True


        def material_copy(source):
            if source is None:
                return None
            if source.name in material_map:
                return material_map[source.name]
            result = source.copy()
            result.name = 'RK | '+source.name.split(' | ', 1)[-1]
            # Geometry Position is intentional for world-aligned plaster/flooring.
            for node in result.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    source_image = node.image
                    if source_image not in image_map:
                        copied_image = source_image.copy()
                        if copied_image.source != 'GENERATED' and not copied_image.packed_file:
                            copied_image.filepath = bpy.path.abspath(source_image.filepath, library=source_image.library)
                            copied_image.pack()
                        image_map[source_image] = copied_image
                    node.image = image_map[source_image]
                if node.type == 'TEX_COORD' and node.object:
                    raise ValueError('Material uses an external coordinate object: '+source.name)
            material_map[source.name] = result
            return result


        sources = [m for m in bpy.data.materials
                   if m.users and m.name.startswith(config.get('material_prefix', 'M'))]
        for source in sources:
            mat = material_copy(source)
            category = config.get('material_catalogs', {}).get(source.name.split(' | ')[0], 'Other')
            description = 'Procedural PBR material; editable nodes; no external texture files.'
            if any(n.type == 'NEW_GEOMETRY' for n in mat.node_tree.nodes):
                description += ' Uses world Position: pattern stays aligned to world axes.'
            mark(mat, 'RoomKit/Materials/'+category, description, ['material', 'procedural', category.lower()])

        for item, source_orientation in zip(config['furniture'], source_orientations):
            source_root = bpy.data.objects.get(item['root'])
            if source_root is None:
                raise ValueError('Missing source root: '+item['root'])
            col = bpy.data.collections.new(item['name'])
            root = bpy.data.objects.new(item['name']+' | placement root', None)
            col.objects.link(root)
            orientation = canonical_orientation(source_orientation)
            rotation = Matrix(canonical_rotation(source_orientation)).to_4x4()
            inverse = source_root.matrix_world.inverted()
            made = []
            original = [source_root, *source_root.children_recursive]
            for source_obj in original:
                if source_obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT'}:
                    continue
                evaluated = source_obj.evaluated_get(dg)
                mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=dg)
                obj = bpy.data.objects.new(source_obj.name, mesh)
                col.objects.link(obj)
                obj.matrix_world = rotation @ inverse @ evaluated.matrix_world
                for i, mat in enumerate(list(mesh.materials)):
                    mesh.materials[i] = material_copy(mat)
                made.append(obj)
            if not made:
                raise ValueError('No exportable geometry under '+item['root'])
            # Mesh vertices give exact placement bounds without requiring scene linkage.
            points = [obj.matrix_world @ vertex.co for obj in made for vertex in obj.data.vertices]
            low = Vector([min(p[k] for p in points) for k in range(3)])
            high = Vector([max(p[k] for p in points) for k in range(3)])
            # Mount/source origins are explicit declarations and remain at the source
            # root point. Only static floor_center assets use canonical geometry bounds.
            origin = (Vector(((low.x+high.x)/2, (low.y+high.y)/2, low.z))
                      if orientation['origin'] == 'floor_center' else Vector((0, 0, 0)))
            for obj in made:
                obj.matrix_world = Matrix.Translation(-origin) @ obj.matrix_world
                rk.parent_keep_world(obj, root)
            mark(col, 'RoomKit/Furniture/'+item['catalog'], item['description'], ['furniture', item['catalog'].lower()])
            col['roomkit_units'] = 'metres'
            col['roomkit_forward'] = orientation['front_axis'] or 'none'
            col['roomkit_origin'] = orientation['origin']
            col['asset_orientation_json'] = json.dumps(orientation, sort_keys=True)
            root['asset_orientation_json'] = json.dumps(orientation, sort_keys=True)
            assets.append({'name':col.name, 'source_root':source_root.name, 'parts':len(made),
                           'vertices':sum(len(o.data.vertices) for o in made),
                           'dimensions_m':list(high-low), 'description':item['description'],
                           'catalog_id':col.asset_data.catalog_id, 'articulation':False,
                           'import_mode':'collection', 'orientation':orientation,
                           'source_orientation':source_orientation,
                           'bounds_min_m':list(low-origin), 'bounds_max_m':list(high-origin),
                           'origin_normalization':('rotated geometry bounds floor center'
                               if orientation['origin'] == 'floor_center' else 'declared root retained')})

        asset_collections = [bpy.data.collections[a['name']] for a in assets]
        materials = list(material_map.values())
        for mat in materials:
            if mat.asset_data is None:
                mark(mat, 'RoomKit/Materials/Other', 'Editable material from extracted furniture.', ['material'])
        catalog_text = '# Blender Asset Catalog Definition File\nVERSION 1\n\n'
        catalog_text += '\n'.join(f'{uid}:{path}:{path.replace("/", " - ")}' for path,uid in sorted(catalogs.items()))+'\n'
        (output/'blender_assets.cats.txt').write_text(catalog_text, encoding='utf-8')

        if args.previews:
            # Use a separate staging scene. Source objects and original .blend stay untouched.
            stage = bpy.data.scenes.new('RoomKit preview stage')
            bpy.context.window.scene = stage
            stage.world = bpy.data.worlds.new('RoomKit preview world')
            stage.world.use_nodes = True
            stage.world.node_tree.nodes.clear()
            background = stage.world.node_tree.nodes.new('ShaderNodeBackground')
            background.inputs[0].default_value = (.3,.3,.3,1)
            background.inputs[1].default_value = .5
            world_output = stage.world.node_tree.nodes.new('ShaderNodeOutputWorld')
            stage.world.node_tree.links.new(background.outputs[0], world_output.inputs['Surface'])
            rk.configure_render(stage, 'material', samples=16)
            stage.render.resolution_x = stage.render.resolution_y = 384
            stage.render.resolution_percentage = 100
            stage.render.film_transparent = False
            camera_data = bpy.data.cameras.new('Preview camera')
            camera = bpy.data.objects.new('Preview camera', camera_data)
            stage.collection.objects.link(camera)
            stage.camera = camera
            camera_data.type = 'ORTHO'
            camera_data.lens = 50
            ground = rk.box('Preview floor', (0,0,-.06), (200,200,.1), edge=0)
            neutral = bpy.data.materials.new('Preview neutral')
            neutral.diffuse_color = (.5,.5,.5,1)
            ground.data.materials.append(neutral)
            rk.area_light('Key', (2,-4,6), (0,0,.6), 1000, 5)
            rk.area_light('Fill', (-4,-1,3), (0,0,.6), 650, 4)
            rk.area_light('Rim', (1,4,5), (0,0,.6), 1000, 3)
            preview_dir = output/'previews'
            preview_dir.mkdir(exist_ok=True)

            def take(block, name, target, extent):
                camera.location = Vector(target) + Vector((1.05,-1.55,.9))*extent
                camera.rotation_euler = (Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
                camera_data.ortho_scale = extent*1.32
                path = preview_dir/(name+'.png')
                stage.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
                with bpy.context.temp_override(id=block):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=str(path))

            for i, (col, item) in enumerate(zip(asset_collections, assets), 1):
                instance = bpy.data.objects.new('Furniture preview instance', None)
                stage.collection.objects.link(instance)
                instance.instance_type = 'COLLECTION'
                instance.instance_collection = col
                d = item['dimensions_m']
                take(col, f'furniture_{i:02d}', (0,0,d[2]*.5), max(d)*1.05)
                bpy.data.objects.remove(instance, do_unlink=True)
                print('ASSET_PREVIEW', col.name, flush=True)
            bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=.46, location=(0,0,.5))
            sphere = bpy.context.object
            for face in sphere.data.polygons:
                face.use_smooth = True
            for i, mat in enumerate(materials, 1):
                sphere.data.materials.clear()
                sphere.data.materials.append(mat)
                take(mat, f'material_{i:02d}', (0,0,.47), 1.05)
                print('MATERIAL_PREVIEW', mat.name, flush=True)

        library = output/'roomkit_furniture_materials.blend'
        bpy.data.libraries.write(str(library), set(asset_collections+materials), path_remap='RELATIVE', fake_user=True, compress=True)
        manifest = {'version':1, 'blender_version':bpy.app.version_string, 'library':library.name,
                    'furniture':assets, 'materials':[{'name':m.name,'source_name':old,
                                  'catalog_id':m.asset_data.catalog_id,
                                  'world_coordinates':any(n.type=='NEW_GEOMETRY' for n in m.node_tree.nodes)}
                                 for old,m in material_map.items()],
                    'origin':(assets[0]['orientation']['origin'] if assets and
                        all(a['orientation']['origin'] == assets[0]['orientation']['origin'] for a in assets) else 'per_asset'),
                    'forward':('-Y' if assets and all(a['orientation']['front_axis'] == '-Y' for a in assets) else None),
                    'units':'metres',
                    'geometry':'Separate editable mesh parts; modifiers baked; no room animation/drivers retained.'}
        if not config.get('register_materials', True):
            manifest['material_dependencies'] = manifest['materials']
            manifest['materials'] = []
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('ASSET_LIBRARY_COMPLETE', str(library), len(assets), 'furniture', len(materials), 'materials', flush=True)
    finally:
        bpy.context.window.scene = original_scene
        if original_scene.frame_current != original_frame:
            original_scene.frame_set(original_frame)


if __name__ == '__main__':
    main()
