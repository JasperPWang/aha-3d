"""Saved-animation verification regression, including compressed archive read counts.

Run with background Blender: --python check_stage_verify_cache.py -- --out CLAIMED_DIR
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy
import numpy as np
from numpy.lib.npyio import NpzFile
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.blender import stage


class SavedVerification(unittest.TestCase):
    def setUp(self):
        # Keep tiny fixtures as audit artifacts; immediate deletion can race NFS tombstones.
        self.run = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=OUTPUT))
        (self.run / 'stages/assemble').mkdir(parents=True)
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 1, 4
        self.scene.render.fps, self.scene.render.fps_base = 24, 1.
        self.scene.render.resolution_x, self.scene.render.resolution_y = 160, 90
        self.scene.render.resolution_percentage = 100
        bpy.ops.mesh.primitive_cube_add(size=.4)
        self.body = bpy.context.object
        self.body.name = 'Person_001_Body'
        self.body.shape_key_add(name='Basis')
        key = self.body.shape_key_add(name='BakedPose')
        key.data[0].co.z += .1
        key.value = 0.; key.keyframe_insert('value', frame=1)
        key.value = 1.; key.keyframe_insert('value', frame=4)
        data = bpy.data.cameras.new('Verification camera')
        cam = bpy.data.objects.new('Verification camera', data)
        self.scene.collection.objects.link(cam)
        self.scene.camera = cam
        for frame in range(1, 5):
            cam.location = (frame * .01, -3, 1)
            cam.rotation_euler = (Vector((0, 0, 0)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
            cam.keyframe_insert('location', frame=frame)
            cam.keyframe_insert('rotation_euler', frame=frame)
        self.recipe = {'body': {'object_name': self.body.name},
                       'timing': {'start': 1, 'end': 4, 'frames': 4, 'fps': '24'}}
        world, cameras = [], []
        for frame in range(1, 5):
            self.scene.frame_set(frame)
            dg = bpy.context.evaluated_depsgraph_get()
            co, _, transform, _ = stage.mesh_arrays(self.body, dg)
            world.append(co @ transform[:3, :3].T + transform[:3, 3])
            cameras.append(stage.camera_matrices(self.scene, dg)[1])
        self.arrays = dict(frames=np.arange(1, 5), world=np.asarray(world), camera=np.asarray(cameras))
        self.save()

    def save(self):
        np.savez_compressed(self.run / 'stages/assemble/verification_samples.npz', **self.arrays)

    def counted_verify(self):
        original_getitem = NpzFile.__getitem__
        reads = {}
        def counted_getitem(archive, key):
            reads[key] = reads.get(key, 0) + 1
            return original_getitem(archive, key)
        # Keep NumPy's real context manager/ownership; instrument only member reads.
        with patch.object(NpzFile, '__getitem__', counted_getitem):
            stage.verify(self.run, self.recipe)
        return reads

    def test_baked_mesh_and_camera_read_each_archive_member_once(self):
        self.assertEqual(self.counted_verify(), {'frames': 1, 'camera': 1, 'world': 1})
        report = json.loads((self.run / 'stages/verify/validation.json').read_text())
        self.assertEqual(report['maximum_vertex_error_m'], 0.)
        self.assertEqual(report['maximum_camera_error'], 0.)
        self.assertEqual(report['frames'], 4)
        self.assertTrue(report['self_contained_playback'])

    def test_last_frame_vertex_corruption_is_rejected(self):
        self.arrays['world'][-1, 0, 0] += .01
        self.save()
        with self.assertRaisesRegex(ValueError, 'Saved animation differs'):
            stage.verify(self.run, self.recipe)

    def test_last_frame_camera_corruption_is_rejected(self):
        self.arrays['camera'][-1, 0, 3] += .01
        self.save()
        with self.assertRaisesRegex(ValueError, 'Saved animation differs'):
            stage.verify(self.run, self.recipe)

    def test_camera_only_does_not_require_world_member(self):
        bpy.data.objects.remove(self.body, do_unlink=True)
        del self.arrays['world']
        self.save()
        self.assertEqual(self.counted_verify(), {'frames': 1, 'camera': 1})

    def test_empty_samples_preserve_existing_lazy_member_behavior(self):
        self.arrays = {'frames': np.array([], dtype=np.int64)}
        self.save()
        self.assertEqual(self.counted_verify(), {'frames': 1})

    def test_scene_timing_mismatch_is_rejected(self):
        self.scene.frame_end = 5
        with self.assertRaisesRegex(ValueError, 'timing mismatch'):
            stage.verify(self.run, self.recipe)

    def test_unbaked_body_is_rejected(self):
        self.body.shape_key_clear()
        # Capture matching geometry first so the playback guard is the rejecting check.
        del self.arrays['world']; self.arrays['frames'] = np.array([], dtype=np.int64)
        self.save()
        with self.assertRaisesRegex(ValueError, 'baked playback'):
            stage.verify(self.run, self.recipe)

    def test_external_texture_dependency_is_rejected(self):
        image = bpy.data.images.new('Unpacked fixture', 1, 1)
        image.source = 'FILE'; image.filepath = '/unpacked-fixture.png'
        try:
            with self.assertRaisesRegex(ValueError, 'external library/texture dependencies'):
                stage.verify(self.run, self.recipe)
        finally:
            bpy.data.images.remove(image)

    def check_policy(self):
        return dict(self.recipe, validation={'sample_frames': 'all', 'collisions': 'report'})

    def test_checks_without_samples_preserves_full_collision_report(self):
        bpy.ops.mesh.primitive_cube_add(size=.3, location=(.15, 0, 0))
        bpy.context.object.name = 'Intersecting furniture'
        full, lean = self.run / 'full', self.run / 'lean'
        full.mkdir(); lean.mkdir()
        expected = stage.checks(self.scene, self.body, None, self.check_policy(), full)
        actual = stage.checks(self.scene, self.body, None, self.check_policy(), lean, save_samples=False)
        self.assertEqual(expected, actual)
        self.assertEqual(expected['sampled_frames'], [1, 2, 3, 4])
        self.assertTrue(expected['furniture_intersections'])
        self.assertEqual((full / 'scene_validation.json').read_bytes(), (lean / 'scene_validation.json').read_bytes())
        self.assertTrue((full / 'verification_samples.npz').is_file())
        self.assertFalse((lean / 'verification_samples.npz').exists())

    def test_checks_without_samples_still_rejects_floor_threshold(self):
        recipe = self.check_policy(); recipe['validation']['floor_min'] = 1.
        with self.assertRaisesRegex(ValueError, 'floor threshold'):
            stage.checks(self.scene, self.body, None, recipe, self.run, save_samples=False)

    def test_checks_without_samples_still_rejects_cache_mismatch(self):
        self.scene.frame_set(1)
        local, faces, _, ids = stage.mesh_arrays(self.body, bpy.context.evaluated_depsgraph_get())
        data = {'faces': faces, 'vertex_ids': ids, 'vertices': np.repeat(local[None], 4, axis=0) + .01}
        with self.assertRaisesRegex(ValueError, 'Body/cache mismatch'):
            stage.checks(self.scene, self.body, data, self.check_policy(), self.run, save_samples=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    OUTPUT = args.out.resolve(); OUTPUT.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SavedVerification))
    (OUTPUT / 'result.json').write_text(json.dumps({'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'successful': result.wasSuccessful()}, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)
