"""Build and reopen-validate a self-contained GVHMR/Pi3X Blender scene."""
import argparse,json,sys
from pathlib import Path
import bpy,numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from aha3d.blender.body import import_cache
from aha3d.blender.ensemble import bake_camera,camera_check
from aha3d.workflow.preflight import camera_report

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--verify',action='store_true');a=p.parse_args(sys.argv[sys.argv.index("--")+1:])
 r=a.run;data=np.load(r/'body_room.npz');n=len(data['vertices']);t=dict(frames=n,start=1,end=n,fps='30');scene=bpy.context.scene
 if a.verify:
  body=bpy.data.objects['Person_001_Body'];errors=[]
  for f in range(1,n+1):
   scene.frame_set(f);obj=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=obj.to_mesh();v=np.empty(data['vertices'].shape[1]*3,dtype='f4');mesh.vertices.foreach_get('co',v);obj.to_mesh_clear();errors.append(float(np.max(np.abs(v.reshape(-1,3)-data['vertices'][f-1]))))
  cam=camera_check(scene,r/'camera.npz',t,[1280,720],{})
  report=dict(frames=n,fps=scene.render.fps,maximum_vertex_error_m=max(errors),camera=cam,shape_keys=len(body.data.shape_keys.key_blocks),self_contained_baked_mesh=True)
  assert max(errors)<1e-5 and scene.frame_end==n and scene.render.fps==30
  (r/'blender_validation.json').write_text(json.dumps(report,indent=2)+'\n');print(report);return
 pre=camera_report(np.load(r/'camera.npz'),t,[1280,720]);(r/'camera_preflight.json').write_text(json.dumps(pre,indent=2)+'\n')
 if pre['status']!='passed':raise ValueError(pre)
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 scene.render.fps=30;scene.frame_start=1;scene.frame_end=n;scene.unit_settings.system='METRIC'
 z=np.load(r/'room_reference.npz');mesh=bpy.data.meshes.new('Pi3X source-colored reference mesh');mesh.from_pydata(z['vertices'].tolist(),[],z['faces'].tolist());mesh.update();room=bpy.data.objects.new('Room reference - approximate Pi3X surface',mesh);scene.collection.objects.link(room)
 color=mesh.color_attributes.new(name='Source RGB',type='FLOAT_COLOR',domain='POINT');color.data.foreach_set('color',np.c_[z['colors'],np.ones(len(z['colors']))].astype('f4').ravel())
 room['provenance']='Same reference video, Pi3X views 0/12/23; body bbox regions masked. Not a watertight authored room.'
 body,_=import_cache(r/'body_room.npz');body['motion_kind']='GVHMR monocular estimate; one global similarity; no contact refinement'
 attr=body.data.color_attributes.new(name='Body color',type='FLOAT_COLOR',domain='POINT');attr.data.foreach_set('color',np.tile([.08,.55,.95,1.],len(body.data.vertices)))
 bake_camera(scene,r/'camera.npz',t,[1280,720]);source_camera=scene.camera
 scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.light='STUDIO';scene.display.shading.color_type='VERTEX';scene.display.shading.show_shadows=False;scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH';scene.display.shading.background_type='WORLD';scene.world.color=(.08,.08,.08)
 scene['alignment_report']=str((r/'alignment.json').resolve());scene['source_video']='30_living_room_tv_presentation_g0027.mp4';scene['scale_note']='Predicted metres, no measured metric calibration';scene['floor_note']='Reviewed carpet plane is Z=0. No contact optimization.'
 # A static overview supports checking the room/body relationship.
 cam=bpy.data.objects.new('Room overview',bpy.data.cameras.new('Room overview'));scene.collection.objects.link(cam)
 path=data['joints'][:,0];target=np.median(path,axis=0);target[2]=.85
 first=np.load(r/'camera.npz')['c2w'][0,:3,3];cam.location=first+np.array([.7,-.3,.6]);cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=22
 scene.camera=source_camera;scene.frame_set(1)
 for area in bpy.context.screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.shading.color_type='VERTEX'
 a.out.parent.mkdir(parents=True,exist_ok=True);bpy.ops.wm.save_as_mainfile(filepath=str(a.out.resolve()))
 (r/'render_frames').mkdir(exist_ok=True);scene.render.resolution_percentage=50;scene.render.image_settings.file_format='PNG'
 for f in range(1,n+1):
  scene.frame_set(f);scene.render.filepath=str((r/'render_frames'/f'{f:04d}.png').resolve());bpy.ops.render.render(write_still=True)
 scene.camera=cam
 for f in [1,80,160,246]:
  scene.frame_set(f);scene.render.filepath=str((r/f'overview_{f:04d}.png').resolve());bpy.ops.render.render(write_still=True)
if __name__=='__main__':main()
