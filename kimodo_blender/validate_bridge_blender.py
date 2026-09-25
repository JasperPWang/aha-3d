"""Integration checks using an analytic tetrahedron, NOT a generated human."""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from import_body_blender import import_cache, export_tracking

out = ROOT / 'validation'
out.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
camera_data = bpy.data.cameras.new('ValidationCamera')
camera = bpy.data.objects.new('ValidationCamera', camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera.location = (3, -6, 3)
camera.rotation_euler = (Vector((0.5, 0, 1.)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera_data.lens = 35
camera_data.shift_x = .07
camera_data.shift_y = -.04
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = 1.2
scene.render.pixel_aspect_y = 1
times = np.arange(120) / 24
base = np.array([[0., 0., 0.], [.2, 0., 0.], [0., .2, 0.], [0., 0., .7]], dtype=np.float32)
verts = np.repeat(base[None], len(times), axis=0)
verts[:, :, 0] += times[:, None] * .2
verts[:, 3, 2] += np.sin(times * 2) * .1
faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int32)
cache = out / 'analytic_fixture.npz'
np.savez(cache, schema_version=1, fps=24., vertices=verts, faces=faces, joints=verts[:, :1],
    vertex_ids=np.arange(4), joint_names=np.array(['test_point']), surface_model_type='TEST_TETRAHEDRON', time_seconds=times)
body, data = import_cache(cache, person_id=7, offset=(.2, .4, .7), yaw=37)
tracks_path = out / 'analytic_tracks.npz'
export_tracking(body, data, tracks_path)
world = np.array(body.matrix_world)
expected = verts @ world[:3, :3].T + world[:3, 3]
with np.load(tracks_path) as tracks:
    vertex_error = float(np.abs(tracks['vertices_world'] - expected).max())
    assert vertex_error < 2e-6, vertex_error
    max_projection_error = 0.
    for t in [0, 31, 75, 119]:
        scene.frame_set(t + 1)
        for v in range(4):
            ndc = world_to_camera_view(scene, camera, Vector(expected[t, v]))
            uv = np.array([ndc.x * 960, (1 - ndc.y) * 540])
            max_projection_error = max(max_projection_error, float(np.abs(uv - tracks['vertices_uv'][t, v]).max()))
    assert max_projection_error < .002, max_projection_error
    assert np.array_equal(tracks['vertex_ids'], np.arange(4))
    assert tracks['vertices_uv'].shape == (120, 4, 2)
blend = out / 'analytic_fixture.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.open_mainfile(filepath=str(blend))
body = bpy.data.objects['Person_007_Body']
roundtrip_error = 0.
for t in [0, 31, 75, 119]:
    bpy.context.scene.frame_set(t + 1)
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    actual = np.array([ev.matrix_world @ v.co for v in mesh.vertices])
    ev.to_mesh_clear()
    roundtrip_error = max(roundtrip_error, float(np.abs(actual - expected[t]).max()))
assert roundtrip_error < 2e-6, roundtrip_error
report = dict(status='passed', fixture='analytic tetrahedron, not a human or Kimodo inference',
    blender=bpy.app.version_string, frames=120, fps=24, vertex_world_max_error_m=vertex_error,
    projection_max_error_px=max_projection_error, saved_reopened_max_error_m=roundtrip_error,
    tests=['120 animated mesh frames', 'placement rotation/translation', 'stable vertex IDs',
           'camera shift and nonsquare pixels', 'projection versus Blender utility', 'save/reopen without handlers'],
    not_tested=['Kimodo inference', 'SMPL-X skin without licensed model file', 'occlusion'])
(out / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
