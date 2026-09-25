"""Pure CPU floor-diagnostic contracts; no actual body model or Torch is loaded."""
from contextlib import nullcontext
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from tools.gvhmr import audit_native_ground as ground


def geometry(frames=5):
    times = np.arange(frames) / 30
    vertices = np.tile(np.array([[-.5, .1, -.1], [-.5, .1, .1], [-.4, .2, 0],
                                 [.5, .3, -.1], [.5, .3, .1], [.4, .4, 0]], dtype=float), (frames, 1, 1))
    joints = np.zeros((frames, 22, 3))
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    return vertices, joints, faces, [np.array([0, 1, 2]), np.array([3, 4, 5])], times


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values)
    def detach(self):
        return self
    def cpu(self):
        return self
    def numpy(self):
        return self.values


class NativeGroundTests(unittest.TestCase):
    def test_y_is_height_plane_is_fixed_and_geometry_untouched(self):
        values = geometry()
        values[0][2, 0, 1] = -.07
        source = copy.deepcopy(values)
        arrays, report = ground.native_ground_arrays(*values, 0.)
        self.assertAlmostEqual(report['mesh']['maximum_penetration_m'], .07)
        self.assertEqual(report['mesh']['frames_with_vertices_below_plane'], 1)
        self.assertAlmostEqual(arrays['left_min_height_m'][2], -.07)
        np.testing.assert_allclose(arrays['right_min_height_m'], .3)
        other, other_report = ground.native_ground_arrays(*values, .2)
        self.assertAlmostEqual(other_report['mesh']['maximum_penetration_m'], .27)
        np.testing.assert_allclose(other['left_min_height_m'], arrays['left_min_height_m'] - .2)
        self.assertFalse(report['plane']['plane_fitted_per_variant'])
        np.testing.assert_array_equal(values[0], source[0])
        np.testing.assert_array_equal(arrays['vertices'], source[0])

    def test_no_stationary_review_means_unknown_not_zero_slip(self):
        values = geometry()
        values[0][:, :, 0] += np.arange(5)[:, None] * .02
        arrays, report = ground.native_ground_arrays(*values, 0.)
        slip = report['feet']['left']['reviewed_stationary_slip']
        self.assertEqual(slip['status'], 'unknown_no_reviewed_mask')
        self.assertIsNone(slip['tangential_vertex_speed_m_s']['p90'])
        self.assertEqual(slip['reviewed_pair_count'], 0)
        self.assertNotIn('reviewed_stationary', arrays)
        self.assertGreater(report['feet']['left']['general_motion']['vertex_tangential_speed_m_s']['p90'], .5)

    def test_stationary_pair_mask_never_bridges_release_or_unknown(self):
        values = geometry()
        values[0][:, :3, 0] += np.array([0, .01, 10, 20, 20.02])[:, None]
        mask = np.array([[1, 0], [1, 0], [0, 0], [1, 0], [1, 0]], bool)
        arrays, report = ground.native_ground_arrays(*values, 0., stationary=mask)
        slip = report['feet']['left']['reviewed_stationary_slip']
        self.assertEqual(slip['pair_start_frame_ids'], [0, 3])
        self.assertEqual(slip['vertex_samples'], 6)
        self.assertAlmostEqual(slip['reviewed_duration_seconds'], 2 / 30)
        self.assertAlmostEqual(slip['tangential_vertex_speed_m_s']['maximum'], .6)
        self.assertEqual(report['feet']['right']['reviewed_stationary_slip']['status'], 'no_reviewed_stationary_pairs')
        np.testing.assert_array_equal(arrays['left_reviewed_stationary_pairs'], [1, 0, 0, 1])

    def test_fixed_vertices_detect_rotation_even_when_centroid_stationary(self):
        vertices, joints, faces, ids, times = geometry(2)
        vertices[0, :3] = [[1, 0, 0], [-1, 0, 0], [0, 0, 0]]
        vertices[1, :3] = [[0, 0, 1], [0, 0, -1], [0, 0, 0]]
        np.testing.assert_array_equal(vertices[0, :3].mean(0), vertices[1, :3].mean(0))
        arrays, report = ground.native_ground_arrays(vertices, joints, faces, ids, times, 0.,
                                                    stationary=np.ones((2, 2), bool))
        slip = report['feet']['left']['reviewed_stationary_slip']
        self.assertAlmostEqual(slip['tangential_vertex_speed_m_s']['maximum'], np.sqrt(2) * 30)
        np.testing.assert_allclose(arrays['left_vertex_velocity_m_s'][0, 0], [-30, 0, 30])

    def test_vertical_motion_is_separate_from_tangential_sliding(self):
        values = geometry()
        values[0][:, :3, 1] += np.arange(5)[:, None] * .01
        _, report = ground.native_ground_arrays(*values, 0., stationary=np.ones((5, 2), bool))
        slip = report['feet']['left']['reviewed_stationary_slip']
        self.assertEqual(slip['tangential_vertex_speed_m_s']['maximum'], 0)
        self.assertAlmostEqual(slip['vertical_vertex_speed_m_s']['maximum'], .3)

    def test_skinweight_selection_uses_sum_of_correct_ankle_toe_joints(self):
        weights = np.zeros((7, 55))
        weights[:3, 7] = .3
        weights[:3, 10] = .4
        weights[3:6, 8] = .4
        weights[3:6, 11] = .3
        weights[:6, 0] = .3
        weights[6, 0] = 1
        ids = ground.foot_vertices_from_weights(weights)
        np.testing.assert_array_equal(ids[0], [0, 1, 2])
        np.testing.assert_array_equal(ids[1], [3, 4, 5])
        with self.assertRaisesRegex(ValueError, 'empty or overlapping'):
            ground.foot_vertices_from_weights(weights, .9)
        weights[6, [0, 7, 8]] = [0, .5, .5]
        with self.assertRaisesRegex(ValueError, 'empty or overlapping'):
            ground.foot_vertices_from_weights(weights, .5)

    def test_invalid_geometry_masks_and_dropped_rows_rejected(self):
        v, j, f, ids, times = geometry()
        with self.assertRaisesRegex(ValueError, 'missing rows retained'):
            ground.native_ground_arrays(v[[0, 1, 3, 4]], j[[0, 1, 3, 4]], f, ids, times[[0, 1, 3, 4]], 0.)
        with self.assertRaisesRegex(ValueError, 'duplicate fixed'):
            ground.native_ground_arrays(v, j, f, [np.array([0, 0]), ids[1]], times, 0.)
        with self.assertRaisesRegex(ValueError, 'boolean mask'):
            ground.native_ground_arrays(v, j, f, ids, times, 0., stationary=np.full((5, 2), .5))
        v[2, 0, 1] = np.nan
        with self.assertRaisesRegex(ValueError, 'finite complete'):
            ground.native_ground_arrays(v, j, f, ids, times, 0.)

    def test_review_mask_binds_actor_video_pts_order_and_reviewer(self):
        times = np.arange(5) / 30
        data = dict(time_seconds=times, foot_names=np.asarray(['left', 'right']),
                    stationary=np.ones((5, 2), bool), actor_id=np.asarray('maroon'),
                    source_video_sha256=np.asarray('sourcehash'), reviewed_by=np.asarray('reviewer'))
        mask, info = ground.reviewed_stationary(data, times, 'sourcehash', 'maroon')
        self.assertTrue(mask.all())
        self.assertEqual(info['reviewed_by'], 'reviewer')
        for field, value, error in [('actor_id', 'other', 'actor identity'),
            ('source_video_sha256', 'other', 'source hash'),
            ('time_seconds', times + 1 / 30, 'timestamps differ'),
            ('foot_names', ['right', 'left'], 'left,right order'),
            ('reviewed_by', '', 'reviewed_by')]:
            modified = copy.deepcopy(data)
            modified[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                ground.reviewed_stationary(modified, times, 'sourcehash', 'maroon')

    def test_native_parameter_file_keeps_actual_shape_and_requires_pts(self):
        times = np.arange(5) / 30
        params = {key:np.full((5, width), (i + 1) * .013, dtype='f4') for i, (key, width) in enumerate(ground.PARAMETERS.items())}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'motion_native.npz'
            np.savez(path, frame_times_seconds=times, **{'smpl_params_global__' + key:value for key, value in params.items()})
            loaded = ground.load_parameters(path, times, None)
            np.testing.assert_array_equal(loaded['betas'], params['betas'])
            with self.assertRaisesRegex(ValueError, 'timestamps differ'):
                ground.load_parameters(path, times + 1 / 30, None)
        params['betas'] = params['betas'][:1]
        with self.assertRaisesRegex(ValueError, 'betas'):
            ground.validate_parameters(params, times)

    def test_batched_skinning_passes_every_original_parameter_and_frame(self):
        params = {key:np.arange(5 * width, dtype='f4').reshape(5, width) * .001 for key, width in ground.PARAMETERS.items()}
        calls = []
        def model(**batch):
            calls.append({key:value.numpy().copy() for key, value in batch.items()})
            n = len(batch['transl'].numpy())
            return SimpleNamespace(vertices=Tensor(np.zeros((n, 6, 3))), joints=Tensor(np.zeros((n, 22, 3))))
        fake_torch = SimpleNamespace(inference_mode=nullcontext, float32=np.float32,
            as_tensor=lambda value, dtype, device:Tensor(np.asarray(value, dtype=dtype)))
        v, j = ground.skin_global_parameters(params, model, fake_torch, batch_size=2)
        self.assertEqual([len(batch['betas']) for batch in calls], [2, 2, 1])
        for key in params:
            np.testing.assert_array_equal(np.concatenate([batch[key] for batch in calls]), params[key])
        self.assertEqual(v.shape, (5, 6, 3))
        self.assertEqual(j.shape, (5, 22, 3))

    def test_pt_loader_uses_global_params_and_safe_cpu_deserialization(self):
        times = np.arange(5) / 30
        params = {key:np.full((5, width), .125, dtype='f4') for key, width in ground.PARAMETERS.items()}
        calls = []
        def load(path, *, map_location, weights_only):
            calls.append((str(path), map_location, weights_only))
            return dict(smpl_params_global={key:Tensor(value) for key, value in params.items()},
                        smpl_params_incam={key:Tensor(value * 100) for key, value in params.items()})
        result = ground.load_parameters(Path('hmr4d_results.pt'), times, SimpleNamespace(load=load))
        self.assertEqual(calls, [('hmr4d_results.pt', 'cpu', True)])
        for key in params:
            np.testing.assert_array_equal(result[key], params[key])

    def test_cli_requires_explicit_plane_and_help_needs_no_models(self):
        script = 'tools/gvhmr/audit_native_ground.py'
        help_result = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('not scene-aligned ground', help_result.stdout)
        missing = subprocess.run([sys.executable, script, '--repo', 'r', '--motion', 'm', '--video', 'v', '--output', 'o'],
                                 capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn('--ground-y', missing.stderr)


if __name__ == '__main__':
    unittest.main()
