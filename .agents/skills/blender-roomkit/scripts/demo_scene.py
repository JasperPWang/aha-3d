"""Build a fresh reuse demo and check asset independence, placement and actual rig motion."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
import roomkit as rk

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--library',default=str(Path(__file__).resolve().parents[1]/'assets/library/roomkit_furniture_materials.blend'))
ap.add_argument('--out',required=True)
args=ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
out=Path(args.out).resolve()
out.mkdir(parents=True,exist_ok=True)
library=Path(args.library).resolve()
manifest=json.loads((library.parent/'manifest.json').read_text())
bpy.ops.wm.read_factory_settings(use_empty=True)
s=bpy.context.scene
s.unit_settings.system='METRIC'
s.unit_settings.scale_length=1
with bpy.data.libraries.load(str(library),link=False) as (source,dest):
    dest.collections=source.collections
    dest.materials=source.materials
loaded_collections=dest.collections
loaded_materials=dest.materials
assert len(loaded_collections)==len(manifest['furniture'])
assert len(loaded_materials)==len(manifest['materials'])
qa={'library':str(library),'furniture_assets':len(loaded_collections),'material_assets':len(loaded_materials),'assets':[]}
for col in loaded_collections:
    col['roomkit_import_key']=str(library)+'::'+col.name
    s.collection.children.link(col)
    bpy.context.view_layer.update()
    assert col.asset_data and col.preview and col.preview.image_size[0]>0
    points=[]
    for obj in col.all_objects:
        assert obj.animation_data is None and len(obj.constraints)==0
        if obj.type=='MESH':
            points.extend(obj.matrix_world@v.co for v in obj.data.vertices)
    low=[min(v[i] for v in points) for i in range(3)]
    high=[max(v[i] for v in points) for i in range(3)]
    assert abs(low[2])<1e-5
    assert abs(low[0]+high[0])<1e-5 and abs(low[1]+high[1])<1e-5
    qa['assets'].append({'name':col.name,'bounds_min':low,'bounds_max':high,'floor_origin_pass':True,
                         'has_thumbnail':True,'external_animation_removed':True})
    s.collection.children.unlink(col)
for mat in loaded_materials:
    assert mat.asset_data and mat.preview and mat.preview.image_size[0]>0
assert not any(block.library for group in [bpy.data.objects,bpy.data.meshes,bpy.data.collections,
                                           bpy.data.materials,bpy.data.node_groups,bpy.data.images] for block in group)
assert not [im for im in bpy.data.images if im.source=='FILE' and not im.packed_file]

sofa=rk.import_collection(library,'RK Sofa - Linen Three Seat',(-1.2,1.05,0))
chair=rk.import_collection(library,'RK Chair - Walnut Lounge',(-2.1,-.65,0),rotation=-35)
chair2=rk.import_collection(library,'RK Chair - Walnut Lounge',(-.4,-.9,0),rotation=25)
stool=rk.import_collection(library,'RK Stool - Upholstered Counter',(2.6,.5,0),rotation=-25)
assert chair.instance_collection == chair2.instance_collection
qa['chair_instances_share_mesh_data']=True
mat=lambda phrase:next(m for m in loaded_materials if phrase in m.name)
rk.box('Floor',(0,0,-.06),(9,7,.12),mat('Natural oak floorboards'),edge=.015)
rk.box('Back wall',(0,2.5,1.55),(9,.12,3.1),mat('Warm ivory lime plaster'))
rk.box('Side wall',(-4.5,0,1.55),(.12,5,3.1),mat('Warm ivory lime plaster'))
cab,controls=rk.cabinet('Demo cabinet',(1.4,1.4,0),size=(1.3,.6,1.15),
                        material=mat('Warm white painted'),interior=mat('Walnut furniture'))
fps=24;frames=48
for ctrl in controls:
    rk.animate_property(ctrl,'Open',[[0,0],[1.8,.75]],frames,fps)
camera=rk.camera_path([[-3.2,-4.1,2.2],[-1.6,-4.4,2.25],[1.6,-4.4,2.1],[3.2,-3.9,2.0]],
                      look_start=[-.4,.6,.75],look_end=[.6,.9,.75],seconds=2,fps=fps,lens=29,ramp_seconds=.3)
s.render.resolution_x,s.render.resolution_y=960,540
s.world=bpy.data.worlds.new('Demo world')
s.world.use_nodes=True
s.world.node_tree.nodes.clear()
bg=s.world.node_tree.nodes.new('ShaderNodeBackground')
bg.inputs[0].default_value=(.55,.55,.55,1)
bg.inputs[1].default_value=.35
wo=s.world.node_tree.nodes.new('ShaderNodeOutputWorld')
s.world.node_tree.links.new(bg.outputs[0],wo.inputs['Surface'])
rk.area_light('Window light',(-1,-2,5),(0,0,.5),1300,5)
rk.area_light('Fill',(4,-1,3),(0,1,.7),900,4)

# Validate evaluated controller transforms across every frame, not only input key values.
samples={o.name:[] for o in controls}
camera_positions=[]
for f in range(1,frames+1):
    s.frame_set(f)
    dg=bpy.context.evaluated_depsgraph_get()
    for o in controls:
        ev=o.evaluated_get(dg)
        samples[o.name].append(ev.location.y if o==controls[-1] else ev.rotation_euler.z)
    camera_positions.append(list(camera.matrix_world.translation))
for name,values in samples.items():
    assert len(set(round(float(v),6) for v in values))>30
assert abs(abs(samples[controls[0].name][-1])-math.radians(95)*.75)<1e-5
assert abs(samples[controls[-1].name][-1]-samples[controls[-1].name][0]+.6*.6*.75)<1e-5
qa.update(actual_driver_motion_pass=True,intermediate_transform_counts={k:len(set(round(v,6) for v in vs)) for k,vs in samples.items()},
          no_linked_libraries=True,no_unpacked_file_textures=True,camera_frames=frames)
rk.configure_render(s,'material',samples=24)
s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'roomkit_reuse_demo.blend'))
rk.export_camera(s,out/'camera_data')
matrix=np.load(out/'camera_data/camera_matrices_opencv.npz')
assert np.allclose(matrix['camera_to_world']@matrix['world_to_camera'],np.eye(4),atol=1e-5)
qa['camera_matrices_pass']=True
(out/'reuse_validation.json').write_text(json.dumps(qa,indent=2),encoding='utf-8')
s.frame_set(40)
s.render.filepath=str(out/'reuse_demo.png')
bpy.ops.render.render(write_still=True)
print('REUSE_DEMO_COMPLETE',json.dumps(qa),flush=True)
