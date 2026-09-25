"""Background Blender lifecycle regression: saved visibility, export and collisions."""
from pathlib import Path
import argparse
import json
import sys
import unittest
import bpy
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from aha3d.blender.body import import_cache,export_tracking,linear_keys
from aha3d.blender import stage


class SavedLifecycle(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.out=OUT/self._testMethodName;self.out.mkdir(exist_ok=False)
        v=np.array([[0,0,1],[.1,0,1],[0,.1,1],[0,0,1.1]],np.float32)
        verts=np.repeat(v[None],4,axis=0);verts[2:,:,2]-=100
        self.data=dict(schema_version=np.array(1),vertices=verts,faces=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]],np.int32),vertex_ids=np.arange(4),
            joints=verts[:,:2],joint_names=np.array(['pelvis','head']),fps=np.array(30.),time_seconds=np.arange(4)/30,
            surface_model_type=np.array('Synthetic lifecycle fixture'),track_active=np.array([True,True,False,False]),source_frame_indices=np.arange(4))
        self.cache=self.out/'cache.npz';np.savez_compressed(self.cache,**self.data)
        scene=bpy.context.scene;camera=bpy.data.objects.new('Camera',bpy.data.cameras.new('Camera'));scene.collection.objects.link(camera)
        camera.location=(0,-3,1);camera.rotation_euler=(Vector((0,0,1))-camera.location).to_track_quat('-Z','Y').to_euler();scene.camera=camera
        scene.render.resolution_x=320;scene.render.resolution_y=240;scene.render.resolution_percentage=100

    def test_saved_constant_visibility_and_full_timeline_export(self):
        body,data=import_cache(self.cache)
        linear_keys(body) # Generic linearization must preserve discrete visibility.
        before=(len(bpy.app.handlers.frame_change_pre),len(bpy.app.handlers.frame_change_post))
        path=self.out/'saved.blend';bpy.ops.wm.save_as_mainfile(filepath=str(path));bpy.ops.wm.open_mainfile(filepath=str(path))
        body=bpy.data.objects['Person_001_Body'];scene=bpy.context.scene
        self.assertEqual((scene.frame_start,scene.frame_end),(1,4))
        for frame,sub,hidden in [(1,0,False),(2,.999,False),(3,0,True),(4,0,True)]:
            scene.frame_set(frame,subframe=sub);self.assertEqual(body.hide_render,hidden);self.assertEqual(body.hide_viewport,hidden)
        for layer in body.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        if curve.data_path in ('hide_render','hide_viewport'):
                            self.assertTrue(all(k.interpolation=='CONSTANT' for k in curve.keyframe_points))
        self.assertEqual(before,(len(bpy.app.handlers.frame_change_pre),len(bpy.app.handlers.frame_change_post)))
        export_tracking(body,data,self.out/'tracks.npz')
        with np.load(self.out/'tracks.npz') as z:
            np.testing.assert_array_equal(z['track_active'],[True,True,False,False]);self.assertEqual(len(z['time_seconds']),4)
            self.assertTrue(np.isfinite(z['vertices_world'][:2]).all());self.assertTrue(np.isnan(z['vertices_world'][2:]).all())
            self.assertFalse(z['vertices_in_frame'][2:].any());self.assertFalse(z['geometry_valid'][2:].any())

    def test_checks_exclude_inactive_floor_collision_and_verify_visibility(self):
        body,data=import_cache(self.cache)
        bpy.ops.mesh.primitive_cube_add(size=.15,location=(0,0,-99));bpy.context.object.name='Inactive-only collision'
        recipe=dict(timing=dict(start=1,end=4,frames=4,fps='30'),validation=dict(collisions='error',floor_min=.5,sample_frames='all'),body=dict(object_name=body.name))
        folder=self.out/'stages/assemble';folder.mkdir(parents=True)
        report=stage.checks(bpy.context.scene,body,data,recipe,folder)
        self.assertEqual(report['inactive_sampled_frames'],[3,4]);self.assertFalse(report['furniture_intersections'])
        self.assertGreater(report['floor_min_z_range_m'][0],.5)
        (self.out/'stages/verify').mkdir();stage.verify(self.out,recipe)
        # A broken hidden tail must fail saved-scene verification, independently
        # of its intentionally unassessed padded body coordinates.
        body.animation_data_clear();body.hide_render=False;body.hide_viewport=False
        with self.assertRaisesRegex(ValueError,'lifecycle visibility'):stage.verify(self.out,recipe)

    def test_reentry_is_rejected_before_import(self):
        self.data['track_active']=np.array([True,False,True,False]);np.savez_compressed(self.cache,**self.data)
        before=len(bpy.data.objects)
        with self.assertRaisesRegex(ValueError,'reentry'):import_cache(self.cache)
        self.assertEqual(len(bpy.data.objects),before)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);OUT=a.out.resolve();OUT.mkdir(parents=True,exist_ok=False)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SavedLifecycle))
    (OUT/'result.json').write_text(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),passed=result.wasSuccessful()),indent=2)+'\n')
    if not result.wasSuccessful():raise SystemExit(1)
