"""Exercise complete-object grouping in the actual Blender geometry exporter."""
import importlib.util
import json
from pathlib import Path
import sys
import bpy
from mathutils import Euler, Matrix

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('export_model',root/'tools/layout_inspection/export_model.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True,exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
room=bpy.data.objects.new('Room parent',None);bpy.context.scene.collection.objects.link(room)
for identity in ('chair-a','chair-b'):
    parent=bpy.data.objects.new(identity,None);bpy.context.scene.collection.objects.link(parent)
    parent['instance_id']=identity;parent['semantic_class']='furniture/seating/chair';parent.parent=room
    for part in ('seat','leg'):
        bpy.ops.mesh.primitive_cube_add();obj=bpy.context.object;obj.name=identity+' '+part;obj.parent=parent
bpy.ops.mesh.primitive_cube_add();untagged=bpy.context.object;untagged.name='untagged';untagged.parent=room
# Instance placement takes ownership over the referenced asset hierarchy.
assert module.object_group(untagged,bpy.data.objects['chair-b'])['id']=='chair-b'
cameras=out/'cameras.json';cameras.write_text(json.dumps({'world_transform':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}))
source=out/'source.blend';bpy.ops.wm.save_as_mainfile(filepath=str(source))
before=module.digest(source)
result=module.export(out/'export',cameras)
groups=[g['id'] for g in result['object_groups']]
assert groups.count('chair-a')==2 and groups.count('chair-b')==2
assert groups.count('unassigned:untagged')==1
assert before==module.digest(source)
projection_cases=[]
scene=bpy.context.scene
for kind in ('orthographic','perspective'):
    camera=bpy.data.cameras.new(kind);obj=bpy.data.objects.new(kind,camera);scene.collection.objects.link(obj)
    obj.matrix_world=Euler((.2,-.3,.5)).to_matrix().to_4x4();obj.location=(1,2,3)
    width,height=(96,96) if kind=='orthographic' else (96,64)
    settings={'crop_xyz_m':[[-10,10]]*3}
    if kind=='orthographic':
        camera.type='ORTHO';camera.ortho_scale=8;settings['ortho_scale']=8
        scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
    else:
        fx,fy,cx,cy=75,83,44,30;ratio=fx/fy
        settings['source_record']={'intrinsics':[[fx,0,cx],[0,fy,cy],[0,0,1]]}
        scene.render.pixel_aspect_x=max(1,1/ratio);scene.render.pixel_aspect_y=max(1,ratio)
        camera.type='PERSP';camera.sensor_fit='HORIZONTAL';camera.sensor_width=36
        camera.lens=fx*36/width;camera.shift_x=(width/2-cx)/width;camera.shift_y=(cy-height/2)*ratio/width
    bpy.context.view_layer.update()
    projection=obj.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=width,y=height,
                                        scale_x=scene.render.pixel_aspect_x,scale_y=scene.render.pixel_aspect_y)
    projection_cases.append({'view':{'settings':settings,'camera_matrix_world':[list(row) for row in obj.matrix_world]},
                             'size':[width,height],'projection_matrix':[list(row) for row in projection]})
(out/'validation.json').write_text(json.dumps({'passed':True,'component_groups':groups,'source_unchanged':True,
                                             'projection_cases':projection_cases},indent=2))
