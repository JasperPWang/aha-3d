"""Author reviewed, explicit interaction metadata into a distinct Blender file.

Recipes enumerate exact members and seating types; names do not authorize
implicit grouping. Source geometry/animation are checked at three native frames.
"""
import argparse,hashlib,json,sys,math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix,Vector


def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--recipe',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);assert a.source.resolve()!=a.out.resolve();assert not a.out.exists()
 recipe=json.loads(a.recipe.read_text());source_hash=hashlib.sha256(a.source.read_bytes()).hexdigest()
 if source_hash!=recipe['source_sha256']:raise ValueError('Recipe source fingerprint changed')
 bpy.ops.wm.open_mainfile(filepath=str(a.source));scene=bpy.context.scene
 def geometry():
  result={}
  for frame in sorted(set([scene.frame_start,(scene.frame_start+scene.frame_end)//2,scene.frame_end])):
   scene.frame_set(frame);dg=bpy.context.evaluated_depsgraph_get()
   for o in scene.objects:
    if o.type!='MESH' or o.hide_render:continue
    e=o.evaluated_get(dg);m=e.to_mesh()
    try:result[(frame,o.name)]=np.asarray([e.matrix_world@v.co for v in m.vertices],dtype=np.float32)
    finally:e.to_mesh_clear()
  return result
 before=geometry();scene.frame_set(scene.frame_start);used=set()
 def keep_parent(o,parent):
  world=o.matrix_world.copy();o.parent=parent;o.matrix_world=world
 for g in recipe['groups']:
  if g.get('root'):
   root=scene.objects[g['root']]
  else:
   root=bpy.data.objects.new(g['name'],None);scene.collection.objects.link(root)
  root['instance_id']=root.get('instance_id',g['id']);root['semantic_class']=g['class'];root['browser_movable']=g.get('movable',True)
  for name in g.get('objects',[]):
   if name in used:raise ValueError('Duplicate recipe member '+name)
   used.add(name);keep_parent(scene.objects[name],root)
  for key,value in g.get('properties',{}).items():root[key]=value
 bpy.context.view_layer.update();frames=[]
 for entry in recipe.get('chairs',[]):
  root=scene.objects[entry['root']]
  if entry.get('retain_frame'):continue
  children=list(root.children);parts=[o for o in root.children_recursive if o.type=='MESH' and not o.hide_render]
  points=np.asarray([o.matrix_world@Vector(p) for o in parts for p in o.bound_box])
  yaw=entry['yaw'];c,s=math.cos(yaw),math.sin(yaw);rot=np.array([[c,-s,0],[s,c,0],[0,0,1]])
  local=points@rot;center=(local.min(0)+local.max(0))/2;center[2]=entry.get('floor_z',0);position=rot@center
  worlds={o.name:o.matrix_world.copy() for o in children};mat=Matrix(rot.tolist()).to_4x4();mat.translation=Vector(position)
  root.matrix_world=mat
  for o in children:o.matrix_world=worlds[o.name]
  root['semantic_class']='furniture/seating/chairs';root['browser_movable']=True
  root['browser_seating_type']=entry['seating_type'];root['browser_source_model_id']=entry['source_model_id']
  root['asset_orientation_json']=json.dumps(dict(schema_version=1,front_axis='-Y',up_axis='Z',origin='floor_center',symmetry='none',semantic_front='seating',status='authored',evidence='Explicit interaction recipe '+str(a.recipe)+'; '+entry['evidence']))
  frames.append(dict(root=root.name,position=list(position),yaw=yaw,**{k:entry[k] for k in ('seating_type','source_model_id','evidence')}))
 bpy.context.view_layer.update();after=geometry();assert before.keys()==after.keys()
 maximum=max(float(np.max(np.abs(before[k]-after[k]))) for k in before if before[k].size)
 if maximum>2e-5:raise ValueError('Metadata authoring moved native geometry: '+str(maximum))
 scene.frame_set(scene.frame_start);a.out.parent.mkdir(parents=True,exist_ok=True)
 bpy.ops.wm.save_as_mainfile(filepath=str(a.out))
 assert hashlib.sha256(a.source.read_bytes()).hexdigest()==source_hash
 (a.out.parent/'metadata-validation.json').write_text(json.dumps(dict(passed=True,source=str(a.source),source_sha256=source_hash,recipe=str(a.recipe),maximum_world_vertex_error_m=maximum,sampled_frames=sorted(set(k[0] for k in before)),objects_checked=len(before),chairs=frames,groups=recipe['groups']),indent=2))
 print('METADATA_VALIDATED',a.out,maximum)

if __name__=='__main__':main()
