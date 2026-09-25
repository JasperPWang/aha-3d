"""Offline Cycles indirect atlas + diffuse SH probe of fixed room geometry.

Builds a temporary scene from exported triangles; never edits/saves source data.
Movable objects, joints, people and switchable lamps cannot leave baked shadows.
"""
import base64
import json
import math
import os
import re
import bpy
import numpy as np
from mathutils import Matrix, Vector


def bake_indirect(payload, out):
    structural = lambda value: bool(re.match(r'^(architecture|structure)(/|$)|^(walls?|floors?|ceilings?|roofs?|windows?|doors?|stairs?|columns?|beams?)(/|$)', value or '', re.I))
    objects = {o['instance_id']: o for o in payload['objects']}
    fixed = {k for k, o in objects.items() if not o.get('movable', True) or structural(o.get('semantic_class'))}
    fixed.update(m['owner'] for m in payload['meshes'] if m['owner'] and structural(m.get('surface')))
    for key in list(fixed):
        seen = set()
        while key in objects and key not in seen:
            fixed.add(key); seen.add(key); key = objects[key].get('support_id')
    actors = {a['mesh_name'] for a in (payload.get('animation') or {}).get('actors', [])}
    selected = [m for m in payload['meshes'] if not m['joint'] and m['name'] not in actors and (not m['owner'] or m['owner'] in fixed)]
    if not selected:
        raise ValueError('No fixed room surfaces available for indirect bake')
    print('Lighting bake: fixed meshes', len(selected), flush=True)
    old_scene = bpy.context.window.scene
    scene = bpy.data.scenes.new('Browser indirect bake (temporary)')
    bpy.context.window.scene = scene
    scene.render.engine = 'CYCLES'
    device = os.environ.get('ROOMKIT_BAKE_DEVICE', 'CPU').upper()
    if device not in ('CPU', 'OPTIX', 'CUDA'):
        raise ValueError('ROOMKIT_BAKE_DEVICE must be CPU, OPTIX or CUDA')
    if device != 'CPU':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = device
        prefs.get_devices()
        for item in prefs.devices:
            item.use = item.type == device
        if not any(item.use for item in prefs.devices):
            raise RuntimeError('No allocated Cycles ' + device + ' device')
    scene.cycles.device = 'CPU' if device == 'CPU' else 'GPU'
    print('Lighting bake device:', device, flush=True)
    scene.cycles.samples = 256
    scene.cycles.use_denoising = True
    scene.cycles.seed = 13
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = int(os.environ.get('INDOOR_THREADS') or os.cpu_count() or 4)
    scene.world = bpy.data.worlds.new('Browser daylight')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.8, .88, 1., 1.)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .22
    sun = bpy.data.lights.new('Browser key', 'SUN'); sun.energy = 1.5; sun.angle = .08
    sun_obj = bpy.data.objects.new('Browser key', sun); scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = Vector((.45, .6, -1)).to_track_quat('-Z', 'Y').to_euler()
    image = bpy.data.images.new('Browser indirect atlas', width=1024, height=1024, float_buffer=True)
    image.colorspace_settings.name = 'Linear Rec.709'
    mats = []
    for record in payload['materials']:
        mat = bpy.data.materials.new('Bake ' + record['name']); mat.use_nodes = True
        shader = mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = (*record['color'], 1.)
        shader.inputs['Roughness'].default_value = 1.
        # The atlas is diffuse illumination; metallic specular is supplied by IBL.
        node = mat.node_tree.nodes.new('ShaderNodeTexImage'); node.image = image
        mat.node_tree.nodes.active = node; mats.append(mat)
    verts, faces, face_materials, mapping, unique = [], [], [], [], {}
    for mi, m in enumerate(selected):
        transform = Matrix(np.asarray(m['matrix']).reshape(4, 4).T.tolist())
        coords = np.asarray(m['positions']).reshape(-1, 3)
        remap = []
        for co in coords:
            v = transform @ Vector(co)
            key = tuple(round(float(x), 6) for x in v)
            if key not in unique:
                unique[key] = len(verts); verts.append(tuple(v))
            remap.append(unique[key])
        m['lightmap_uv'] = [0.] * (len(coords)*2)
        for group in m['groups']:
            indices = group['indices']
            for i in range(0, len(indices), 3):
                tri = indices[i:i+3]
                faces.append(tuple(remap[j] for j in tri)); face_materials.append(group['material']); mapping.append((mi, tri))
    print('Lighting bake: unwrap', len(faces), 'triangles', flush=True)
    mesh = bpy.data.meshes.new('Static room atlas'); mesh.from_pydata(verts, [], faces); mesh.update()
    obj = bpy.data.objects.new('Static room atlas', mesh); scene.collection.objects.link(obj)
    for mat in mats: mesh.materials.append(mat)
    for poly, mid in zip(mesh.polygons, face_materials): poly.material_index = mid
    bpy.context.view_layer.objects.active = obj; obj.select_set(True)
    from lightmap_uv import pack_planar_charts
    triangle_uvs, atlas = pack_planar_charts(verts, faces, [mi for mi, _ in mapping])
    resolution = atlas['resolution']
    image.scale(resolution, resolution)
    uv_layer = mesh.uv_layers.new(name='Browser lightmap')
    uv_layer.data.foreach_set('uv', np.asarray(triangle_uvs, dtype=np.float32).reshape(-1))
    print('Lighting bake: packed', atlas['charts'], 'charts at', resolution, flush=True)
    for poly, (mi, tri) in zip(mesh.polygons, mapping):
        for li, vi in zip(poly.loop_indices, tri):
            selected[mi]['lightmap_uv'][vi*2:vi*2+2] = list(mesh.uv_layers.active.data[li].uv)
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = True
    scene.render.bake.use_pass_color = False
    scene.render.bake.margin = 2  # Keep dilation inside each three-pixel chart gutter.
    print('Lighting bake: Cycles indirect atlas', flush=True)
    bpy.ops.object.bake(type='DIFFUSE')
    print('Lighting bake: atlas complete', flush=True)
    # Store linear float16 RGB: compact, self-contained, and no display transform.
    pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(resolution, resolution, 4)
    rgb = np.maximum(pixels[:, :, :3], 0).astype('<f2')
    if not np.isfinite(rgb).all() or float(rgb.max()) == 0:
        raise ValueError('Indirect atlas is empty or nonfinite')
    payload['lighting']['lightmap'] = {'width': resolution, 'height': resolution,
        'rgb_float16_base64': base64.b64encode(rgb.tobytes()).decode(), 'intensity': math.pi}
    # Capture a diffuse probe in world coordinates, at the overview target XY.
    points = np.asarray(verts)
    lo, hi = points.min(axis=0), points.max(axis=0)
    target = payload.get('views', {}).get('orbit', {}).get('target', ((lo+hi)/2).tolist())
    position = [float(target[0]), float(target[1]), float(lo[2] + min(1.4, max(.3, (hi[2]-lo[2])*.5)))]
    scene.cycles.samples = 64
    camera_data = bpy.data.cameras.new('Probe camera'); camera_data.lens = 16.; camera_data.sensor_width = 32.; camera_data.clip_start = .02
    camera = bpy.data.objects.new('Probe camera', camera_data); scene.collection.objects.link(camera); scene.camera = camera
    camera.location = position
    scene.render.resolution_x = scene.render.resolution_y = 32; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'; scene.render.image_settings.color_depth = '32'
    coefficients = np.zeros((9, 3), dtype=np.float64)
    total = 0.
    directions = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    for face, direction in enumerate(directions):
        camera.rotation_euler = Vector(direction).to_track_quat('-Z', 'Y').to_euler()
        path = out / ('probe-%d.exr' % face); scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        loaded = bpy.data.images.load(str(path), check_existing=False)
        colors = np.asarray(loaded.pixels[:]).reshape(32, 32, 4)[:, :, :3]
        rotation = camera.rotation_euler.to_matrix()
        for row in range(32):
            for col in range(32):
                u, v = 2*(col+.5)/32-1, 2*(row+.5)/32-1
                x,y,z = rotation @ Vector((u,v,-1)).normalized()
                sh = np.array([.282095,.488603*y,.488603*z,.488603*x,1.092548*x*y,1.092548*y*z,.315392*(3*z*z-1),1.092548*x*z,.546274*(x*x-y*y)])
                weight = 4 / (32*32*(1+u*u+v*v)**1.5)
                coefficients += sh[:,None] * colors[row,col] * weight; total += weight
        bpy.data.images.remove(loaded)
    coefficients *= 4*math.pi / total
    payload['lighting']['probe'] = {'position': position, 'coefficients': coefficients.tolist(),
        'scope': 'One room-wide diffuse probe; no spatial interpolation or lamp bounce'}
    report = {'method': 'Cycles diffuse indirect atlas and six-face radiance SH projection',
              'device':device, 'atlas_samples':256, 'probe_samples':64, 'atlas_size':resolution, 'atlas_charts':atlas['charts'], 'atlas_packing':{k:v for k,v in atlas.items() if k!='rectangles'}, 'static_meshes':len(selected), 'triangles':len(faces),
              'excluded':'Movable objects, joints, people, lamp emission and native source lights',
              'lighting':'Fixed browser daylight only; lamp direct light remains switchable',
              'probe':payload['lighting']['probe'], 'atlas_max':float(rgb.max()),
              'atlas_mean':float(rgb.mean()), 'source_saved':False}
    (out/'lighting-bake.json').write_text(json.dumps(report, indent=2))
    bpy.context.window.scene = old_scene
