"""Render fixed-topology caches in a neutral studio, preserving world heading."""
import json
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

request=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
out=Path(request['out']); (out/'frames').mkdir()
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
scene.render.engine='CYCLES'; scene.cycles.samples=8; scene.cycles.use_denoising=True
scene.render.use_persistent_data=True
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='OPTIX'; prefs.get_devices()
for d in prefs.devices: d.use=(d.type=='OPTIX')
if not any(d.use for d in prefs.devices): raise RuntimeError('No OPTIX GPU available')
scene.cycles.device='GPU'
scene.render.resolution_x=1280; scene.render.resolution_y=720; scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'; scene.render.film_transparent=False
scene.world.color=(.55,.55,.55)
scene.view_settings.view_transform='AgX'
scene.view_settings.exposure=-.7
bpy.ops.object.camera_add(location=(4,6,3.0))
cam=bpy.context.object; cam.rotation_euler=(Vector((0,0,1))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO'; cam.data.ortho_scale=5.4; scene.camera=cam
right=np.array(cam.rotation_euler.to_matrix() @ Vector((1,0,0)))
right[2]=0; right/=np.linalg.norm(right)

def material(name,color):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF'); bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=.65
    return m

bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.025))
bpy.context.object.data.materials.append(material('Floor',(.83,.86,.90)))
for loc,power,size in [((1,4,7),650,5),((-4,0,4),250,4)]:
    bpy.ops.object.light_add(type='AREA',location=loc)
    lamp=bpy.context.object; lamp.data.energy=power; lamp.data.shape='DISK'; lamp.data.size=size
    lamp.rotation_euler=(-lamp.location).to_track_quat('-Z','Y').to_euler()
bodies=[]
for i,path in enumerate(request['caches']):
    with np.load(path,allow_pickle=False) as data:
        verts=data['vertices'].copy(); faces=data['faces'].copy(); joints=data['joints'].copy()
    if len(verts)!=request['frames'] or not np.isfinite(verts).all(): raise ValueError('Invalid mesh cache')
    offset=right*((i-.5)*2.7 if len(request['caches'])==2 else 0)
    displayed=verts-joints[:,0,None,:]*np.array([1,1,0])+offset
    mesh=bpy.data.meshes.new(f'Body{i}'); mesh.from_pydata(displayed[0],[],faces); mesh.update()
    obj=bpy.data.objects.new(f'Body{i}',mesh); scene.collection.objects.link(obj)
    mesh.materials.append(material(f'Body{i}',(.16,.40,.57) if i==0 and len(request['caches'])==2 else (.70,.32,.13)))
    for poly in mesh.polygons: poly.use_smooth=True
    bodies.append((obj,displayed))
bpy.context.view_layer.update()
minimum_margin=1.
for frame in range(request['frames']):
    for obj,verts in bodies:
        obj.data.vertices.foreach_set('co',verts[frame].astype(np.float32).ravel()); obj.data.update()
        # Orthographic projected extrema are bounded by the world AABB corners.
        lo=verts[frame].min(axis=0); hi=verts[frame].max(axis=0)
        for x in (lo[0],hi[0]):
            for y in (lo[1],hi[1]):
                for z in (lo[2],hi[2]):
                    p=world_to_camera_view(scene,cam,Vector((x,y,z)))
                    minimum_margin=min(minimum_margin,p.x,1-p.x,p.y,1-p.y)
    scene.render.filepath=str(out/'frames'/f'{frame+1:04d}.png')
    bpy.ops.render.render(write_still=True)
    if frame%50==0: print('MESH_PREVIEW',frame+1,request['frames'],flush=True)
(out/'framing.json').write_text(json.dumps(dict(minimum_aabb_projection_margin=minimum_margin,
    note='Conservative full-body framing check; no collision or occlusion validation'),indent=2))
if minimum_margin<0: raise RuntimeError('Mesh framing overflow')
