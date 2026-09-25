"""Regression boundaries for the failures observed in references 32-35."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.config import timing
from aha3d.io import digest, write
from aha3d.motion.diagnostics import root_report
from aha3d.pipeline.runner import completed_artifact
from aha3d.workflow.compare import comparison_inputs
from aha3d.workflow.people import place_cache, validate_config
from aha3d.workflow.preflight import camera_report, pixel_aspect_pair


class CameraPreflightTests(unittest.TestCase):
    def fixture(self):
        K = np.repeat(np.array([[[100., 0, 31.], [0, 100, 22.], [0, 0, 1]]]), 3, axis=0)
        return dict(c2w=np.repeat(np.eye(4)[None], 3, axis=0), K=K,
                    time_seconds=np.array([7., 7.5, 8.]), image_size=[100, 60])

    def test_fixed_aspect_error_at_late_frame(self):
        data = self.fixture(); data['K'][-1, 1, 1] = 97
        report = camera_report(data, dict(frames=3, fps='2', start=10), [100, 60])
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(report['worst_output_frame'], 12)
        self.assertEqual(report['maximum_K_element_error_px'], 3.)
        self.assertEqual(camera_report(data, dict(frames=3, fps='2'), [100, 60], 3.)['status'], 'passed')

    def test_offcenter_and_nonzero_clock_are_representable(self):
        data = self.fixture(); data['K'][:, 0, 2] = [-5, 35, 130]
        report = camera_report(data, dict(frames=3, fps='2'), [100, 60])
        self.assertEqual(report['maximum_K_element_error_px'], 0.)

    def test_subunit_pixel_ratio_uses_two_legal_axes(self):
        data = self.fixture(); data['K'][:, 0, 0] = 90
        report = camera_report(data, dict(frames=3, fps='2'), [100, 60])
        self.assertGreater(report['fixed_pixel_aspect_x'], 1.)
        self.assertEqual(report['fixed_pixel_aspect_y'], 1.)
        self.assertEqual(report['maximum_K_element_error_px'], 0.)
        for ratio in (0, .001, 201, float('nan')):
            with self.assertRaises(ValueError): pixel_aspect_pair(ratio)

    def test_malformed_or_scaled_camera_rejected(self):
        for field in ('cadence', 'count', 'raster', 'scale', 'skew', 'nonfinite'):
            with self.subTest(field=field):
                data = self.fixture()
                if field == 'cadence': data['time_seconds'][-1] += .1
                if field == 'count': data['c2w'] = data['c2w'][:2]
                if field == 'raster': data['image_size'] = [200, 120]
                if field == 'scale': data['c2w'][:, :3, :3] *= 1.1
                if field == 'skew': data['K'][:, 0, 1] = .1
                if field == 'nonfinite': data['K'][0, 0, 0] = np.nan
                with self.assertRaises(ValueError): camera_report(data, dict(frames=3, fps='2'), [100, 60])


class ConstantPlacementTests(unittest.TestCase):
    def test_world_offset_after_scale_preserves_native_vertical_motion(self):
        vertices = np.array([[[1., 0, -.1], [1, 0, 2]], [[2, 0, .3], [2, 0, 2.4]]])
        before = vertices.copy()
        data = dict(vertices=vertices, joints=vertices[:, :1].copy(), fps=2., time_seconds=np.array([0., .5]))
        person = dict(scale=.5, yaw=90, anchor_xy=[3, 4], z_offset=.25)
        result, matrix = place_cache(data, person, dict(frames=2, fps='2'))
        world = result['vertices'] @ matrix[:3, :3].T + matrix[:3, 3]
        np.testing.assert_allclose(world[:, 0, 2], [.2, .4])
        np.testing.assert_allclose(world[0, 0, :2], [3, 4])
        np.testing.assert_array_equal(data['vertices'], before)
        np.testing.assert_array_equal(result['vertices'], vertices * .5)
        self.assertNotIn('vertical_ground_correction_m', result)

    def test_conflicting_or_nonfinite_vertical_config_rejected(self):
        person = dict(id=1, label='adult', cache='future.npz', anchor_xy=[0, 0], z_offset=.01)
        cfg = dict(schema_version=1, timing=dict(frames=2, fps='2'), image_size=[100, 60], people=[person])
        validate_config(cfg)
        person['ground_z'] = 0.
        with self.assertRaises(ValueError): validate_config(cfg)
        person.pop('ground_z'); person['z_offset'] = float('nan')
        with self.assertRaises(ValueError): validate_config(cfg)


class NativeDiagnosticsTests(unittest.TestCase):
    def test_y_up_distance_height_limits_and_immutable_input(self):
        root = np.array([[0., 1., 0.], [3, 1, 4.], [3, -1, 4.]])
        before = root.copy()
        report = root_report(root[None], 30, limits=dict(max_travel_m=4, min_root_height_m=0))
        self.assertEqual(report['metrics']['planar_travel_m'], 5.)
        self.assertEqual(report['metrics']['root_height_range_m'], 2.)
        self.assertEqual(len(report['violations']), 2)
        self.assertEqual(report['status'], 'needs_review')
        np.testing.assert_array_equal(root, before)

    def test_segment_join_and_return_trip_differ_from_displacement(self):
        root = np.array([[0., 1, 0], [1, 1, 0], [4, 1, 0], [0, 1, 0]])
        report = root_report(root, fps=2, durations=[1, 1])
        self.assertEqual(report['metrics']['planar_displacement_m'], 0.)
        self.assertEqual(report['metrics']['planar_travel_m'], 8.)
        self.assertEqual(report['segment_boundaries'][0]['root_step_m'], 3.)
        self.assertEqual(report['status'], 'diagnostic')

    def test_bad_motion_fps_or_mismatched_segments_rejected(self):
        for root, fps, durations in [(np.zeros((0, 3)), 30, None), (np.ones((2, 2, 3)), 30, None),
                (np.full((3, 3), np.nan), 30, None), (np.ones((3, 3)), 0, None), (np.ones((3, 3)), 30, [1])]:
            with self.assertRaises(ValueError): root_report(root, fps, durations)


class RunArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.recipe = dict(timing=timing(dict(frames=208, fps='24000/1001')), body=dict(mode='keep'))
        write(self.run / 'snapshot/recipe.json', self.recipe)
        video = self.run / 'stages/video/video.mp4'; video.parent.mkdir(parents=True); video.write_bytes(b'recorded-video')
        self.manifest = dict(schema_version=1, status='failed', snapshot={'recipe.json': digest(self.run / 'snapshot/recipe.json')},
            stages=dict(video=dict(status='completed', outputs={'video.mp4': digest(video)})))
        write(self.run / 'run.json', self.manifest)

    def test_completed_video_recovery_and_nonterminating_timing(self):
        video, t, provenance = comparison_inputs(run=self.run)
        self.assertEqual(video.name, 'video.mp4')
        self.assertEqual(t['frames'], 208); self.assertEqual(t['fps'], '24000/1001')
        self.assertAlmostEqual(t['duration_seconds'], 8.675333333333333)
        self.assertIn('recipe_sha256', provenance)
        # Resolving this completed stage does not promote the failed parent run.
        self.assertEqual(self.manifest['status'], 'failed')

    def test_changed_video_or_recipe_rejected(self):
        (self.run / 'stages/video/video.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError): completed_artifact(self.run, 'video')
        write(self.run / 'snapshot/recipe.json', dict(timing=dict(frames=2, fps='2')))
        with self.assertRaises(ValueError): completed_artifact(self.run, 'video')

    def test_unrecorded_or_incomplete_artifact_rejected(self):
        for status, outputs in [('failed', self.manifest['stages']['video']['outputs']), ('completed', {})]:
            self.manifest['stages']['video'].update(status=status, outputs=outputs)
            write(self.run / 'run.json', self.manifest)
            with self.assertRaises(ValueError): completed_artifact(self.run, 'video')

    def test_active_writer_and_mixed_inputs_rejected(self):
        (self.run / '.execute.lock').mkdir()
        with self.assertRaises(ValueError): completed_artifact(self.run, 'video')
        with self.assertRaises(ValueError): comparison_inputs(run=self.run, config=Path('unused'))
        with self.assertRaises(ValueError): comparison_inputs(render=Path('unused'))

    def test_legacy_explicit_comparison_input(self):
        cfg = self.run / 'legacy.json'; write(cfg, dict(timing=dict(frames=208, fps='24000/1001')))
        video, t, _ = comparison_inputs(render=self.run / 'custom.mp4', config=cfg)
        self.assertEqual(video.name, 'custom.mp4'); self.assertEqual(t['frames'], 208)


class AuthoredDocsTests(unittest.TestCase):
    def test_root_runtime_excluded_but_authored_nested_directory_checked(self):
        spec = importlib.util.spec_from_file_location('check_docs', ROOT / 'tools/check_docs.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('.runtime/upstream/README.md', 'docs/.runtime/notes.md', 'tasks/ours/HANDOFF.md'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('[broken](missing.md)')
            count, problems = module.check(root)
            self.assertEqual(count, 2)
            self.assertEqual(len(problems), 2)
            self.assertTrue(any(p.startswith('tasks/ours/') for p in problems))


if __name__ == '__main__':
    unittest.main()
