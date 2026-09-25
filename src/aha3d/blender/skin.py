"""Use the user's installed SMPL-X Blender asset to skin a 24 fps AMASS motion."""
import argparse
import json
import sys
from pathlib import Path
import bpy
import addon_utils
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--motion', required=True, type=Path)
p.add_argument('--out', required=True, type=Path)
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
if not hasattr(bpy.context.window_manager, 'smplx_tool'):
    addon_utils.enable('bl_ext.user_default.smplx_blender_addon', default_set=False)
if not hasattr(bpy.context.window_manager, 'smplx_tool'):
    raise RuntimeError('Installed SMPL-X extension did not register')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
with np.load(a.motion, allow_pickle=False) as src:
    data = {k: src[k] for k in src.files}
wm = bpy.context.window_manager
wm.smplx_tool.smplx_version = 'locked_head'
wm.smplx_tool.smplx_uv = 'UV_2023'
result = bpy.ops.object.smplx_add_animation(filepath=str(a.motion), anim_format='AMASS',
    rest_position='SMPL-X', hand_reference='FLAT', keyframe_corrective_pose_weights=True,
    target_framerate=int(data['mocap_frame_rate']))
if 'FINISHED' not in result:
    raise RuntimeError(str(result))
obj = bpy.context.view_layer.objects.active
assert obj.type == 'MESH', obj.name
rig = obj.parent
scene = bpy.context.scene
scene.render.fps = int(data['mocap_frame_rate'])
actual_fps = float(data.get('output_fps', data['mocap_frame_rate']))
scene.render.fps_base = scene.render.fps / actual_fps
scene.frame_start, scene.frame_end = 1, len(data['trans'])
joint_names = data['joint_names'].tolist()
print('MOTION_JOINTS', joint_names, flush=True)
print('RIG_BONES', list(rig.pose.bones.keys()), flush=True)
verts, joints = [], []
for frame in range(1, scene.frame_end+1):
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(dg)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    co = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get('co', co.ravel())
    mat = np.array(evaluated.matrix_world)
    verts.append(co @ mat[:3, :3].T + mat[:3, 3])
    tris = np.array([tri.vertices[:] for tri in mesh.loop_triangles], dtype=np.int32)
    if frame == 1:
        faces = tris
    else:
        assert np.array_equal(faces, tris), 'Topology changed'
    evaluated.to_mesh_clear()
    rig_eval = rig.evaluated_get(dg)
    joints.append([list(rig_eval.matrix_world @ rig_eval.pose.bones[name].head) for name in joint_names])
    if frame % 24 == 0:
        print(f'Baked {frame}/{scene.frame_end}', flush=True)
verts, joints = np.array(verts, dtype=np.float32), np.array(joints, dtype=np.float32)
assert np.isfinite(verts).all()
a.out.parent.mkdir(parents=True, exist_ok=True)
np.savez_compressed(a.out, schema_version=np.int32(1), surface_model_type=np.array('smplx'),
    coordinate_system=np.array('Blender Z-up, +Y forward, meters'), fps=actual_fps,
    time_seconds=data['time_seconds'], vertices=verts, faces=faces, joints=joints,
    joint_names=data['joint_names'], vertex_ids=np.arange(verts.shape[1], dtype=np.int32),
    betas=data['betas'], mean_hands=data['mean_hands'], kimodo_to_blender=data['kimodo_to_blender'],
    local_rot_mats_kimodo=data['local_rot_mats_kimodo'], root_positions_kimodo=data['root_positions_kimodo'])
metadata = {'frames':len(verts), 'fps':actual_fps, 'vertices':verts.shape[1],
    'faces':len(faces), 'joints':len(joint_names), 'bbox_min':verts.min(axis=(0,1)).tolist(),
    'bbox_max':verts.max(axis=(0,1)).tolist(), 'pelvis_start':joints[0,0].tolist(),
    'pelvis_end':joints[-1,0].tolist(), 'min_z_range':[float(verts[:,:,2].min(axis=1).min()),float(verts[:,:,2].min(axis=1).max())],
    'max_joint_difference_vs_kimodo_m':float(np.linalg.norm(joints-data['joints_kimodo_zup'],axis=-1).max()),
    'method':'SMPL-X locked-head Blender asset; all 300 betas; pose correctives; neutral face; mean hands; body rotations resampled with SLERP before skinning'}
a.out.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(a.out.with_suffix('.blend')))
print(json.dumps(metadata, indent=2), flush=True)
