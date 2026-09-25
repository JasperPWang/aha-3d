import bpy, pathlib, sys
output=pathlib.Path(sys.argv[sys.argv.index('--')+1])
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
def box(name,loc,scale,color,root=None,role=None):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.scale=scale
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True;m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*color,1);o.data.materials.append(m);bpy.context.view_layer.update()
 if root:
  matrix=o.matrix_world.copy();o.parent=root;o.matrix_world=matrix
 if role:o['surface_role']=role
 return o
root=bpy.data.objects.new('Architecture',None);bpy.context.scene.collection.objects.link(root);root['instance_id']='room';root['semantic_class']='architecture/room'
box('Floor',(0,0,-.1),(6,5,.2),(.5,.45,.38),root,'floor')
box('Back wall',(0,2.5,1.5),(6,.15,3),(.65,.25,.18),root,'wall')
box('Side wall',(-3,0,1.5),(.15,5,3),(.7,.7,.65),root,'wall')
lamp=bpy.data.objects.new('Table lamp',None);bpy.context.scene.collection.objects.link(lamp);lamp['instance_id']='lamp';lamp['semantic_class']='lighting/table_lamps'
box('Lamp stem',(-1,1,.6),(.08,.08,1.2),(.2,.2,.2),lamp)
box('Lamp shade',(-1,1,1.3),(.5,.5,.35),(.9,.8,.6),lamp)
native=bpy.data.lights.new('Table lamp bulb light','POINT');native.energy=10;native.color=(1,.7,.4)
light=bpy.data.objects.new('Table lamp bulb light',native);bpy.context.scene.collection.objects.link(light);light.location=(-1,1,1.3)
lamp2=bpy.data.objects.new('Floor lamp',None);bpy.context.scene.collection.objects.link(lamp2);lamp2['instance_id']='lamp-2';lamp2['semantic_class']='lighting/floor_lamps'
box('Floor lamp stem',(2,1,.8),(.08,.08,1.6),(.2,.2,.2),lamp2)
box('Floor lamp shade',(2,1,1.7),(.4,.4,.3),(.9,.8,.6),lamp2)
chair=bpy.data.objects.new('Movable stool',None);bpy.context.scene.collection.objects.link(chair);chair['instance_id']='stool';chair['semantic_class']='furniture/stools'
box('Stool',(1,0,.4),(.6,.6,.8),(.2,.4,.6),chair)
bpy.ops.object.camera_add(location=(8,-10,8));bpy.context.scene.camera=bpy.context.object;bpy.context.object.rotation_euler=(Vector((0,0,1))-bpy.context.object.location).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.frame_end=1
bpy.ops.wm.save_as_mainfile(filepath=str(output.resolve()))
