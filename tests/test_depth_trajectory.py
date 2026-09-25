import unittest
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import numpy as np

from tools.gvhmr.align_depth_trajectory import (
    fit_trajectory, move_fixed_size_body, sample_surface, candidate_metadata, main,
)


class TrajectoryTests(unittest.TestCase):
    def fixture(self):
        t = np.arange(90) / 30
        root = np.column_stack((t, .2 * t ** 2, .9 + .02 * np.sin(t)))
        ids = np.arange(0, 90, 3)
        target = 1.8 * root[ids] + [2., -1., .3]
        valid = np.ones(len(ids), bool)
        train = np.arange(len(ids)) % 3 != 0
        return root, ids, target, valid, np.ones(len(ids)), train

    def test_recovers_trajectory_scale_without_scaling_body(self):
        args = self.fixture()
        corrected, report = fit_trajectory(*args)
        self.assertAlmostEqual(report['trajectory_scale'], 1.8, places=7)
        root = args[0]
        joints = root[:, None] + np.array([[[0., 0, 0], [.2, 0, .4], [-.2, 0, -.8]]])
        vertices = root[:, None] + np.array([[[.3, .1, .9], [-.3, -.1, -.9]]])
        v, j, _ = move_fixed_size_body(vertices, joints, corrected)
        np.testing.assert_allclose(v - j[:, :1], vertices - joints[:, :1], atol=1e-12)
        np.testing.assert_allclose(j - j[:, :1], joints - joints[:, :1], atol=1e-12)
        np.testing.assert_allclose(j[:, 0], 1.8 * root + [2., -1., .3], atol=1e-7)

    def test_heldout_targets_never_affect_fit(self):
        args = list(self.fixture())
        first, _ = fit_trajectory(*args)
        args[2][~args[5]] += 100
        second, report = fit_trajectory(*args)
        np.testing.assert_array_equal(first, second)
        self.assertGreater(report['heldout']['median_m'], 100)

    def test_invalid_depth_rows_are_retained_but_not_fitted(self):
        args = list(self.fixture())
        args[3][4] = False
        args[2][4] = np.nan
        _, report = fit_trajectory(*args)
        self.assertAlmostEqual(report['trajectory_scale'], 1.8, places=7)
        self.assertEqual(len(report['valid_row_mask']), len(args[1]))
        self.assertFalse(report['valid_row_mask'][4])

    def test_translation_only_does_not_change_displacement(self):
        args = self.fixture()
        corrected, report = fit_trajectory(*args, fit_scale=False)
        self.assertEqual(report['trajectory_scale'], 1.)
        np.testing.assert_allclose(np.diff(corrected, axis=0), np.diff(args[0], axis=0), atol=1e-12)

    def test_inactive_targets_are_excluded_from_fit_and_heldout_metrics(self):
        args = list(self.fixture()); active = np.arange(len(args[0])) < 65
        first, report = fit_trajectory(*args, track_active=active)
        args[2][args[1] >= 65] += 1000
        second, _ = fit_trajectory(*args, track_active=active)
        np.testing.assert_array_equal(first, second)
        self.assertFalse(any(v for frame, v in zip(report['source_frame_indices'], report['valid_row_mask']) if frame >= 65))

    def test_stationary_scale_is_not_silently_fitted(self):
        args = list(self.fixture())
        args[0][:] = [1, 2, .9]
        with self.assertRaisesRegex(ValueError, 'unidentifiable'):
            fit_trajectory(*args)

    def test_invalid_correspondence_and_nonfinite_valid_target_rejected(self):
        args = list(self.fixture())
        args[1][1] = args[1][0]
        with self.assertRaises(ValueError):
            fit_trajectory(*args)
        args = list(self.fixture())
        args[2][0] = np.nan
        with self.assertRaises(ValueError):
            fit_trajectory(*args)


class SurfaceTests(unittest.TestCase):
    def fixture(self):
        depth = np.full((25, 25), 9.)
        mask = np.zeros_like(depth, bool)
        mask[6:19, 6:19] = True
        depth[mask] = 2.
        K = np.array([[100., 0, 12], [0, 100., 12], [0, 0, 1]])
        C = np.eye(4)
        C[:3, 3] = [1, 2, 3]
        return depth, np.ones_like(depth), np.ones_like(mask), mask, np.array([12., 12.]), K, C

    def test_actor_mask_excludes_background_depth_and_camera_translation_applies_once(self):
        world, report = sample_surface(*self.fixture(), radius=10)
        np.testing.assert_allclose(world, [1, 2, 5])
        self.assertEqual(report['camera_depth'], 2.)

    def test_landmark_outside_actor_or_no_confidence_is_not_an_anchor(self):
        args = list(self.fixture())
        args[4] = np.array([3., 3.])
        self.assertIsNone(sample_surface(*args)[0])
        args = list(self.fixture())
        args[1][:] = -50
        self.assertIsNone(sample_surface(*args)[0])

    def test_mixed_foreground_background_layer_is_rejected(self):
        args = list(self.fixture())
        yy, xx = np.ogrid[:25, :25]
        circle = (xx - 12) ** 2 + (yy - 12) ** 2 <= 5 ** 2
        values = np.r_[np.full(40, 2.), np.full(40, 8.), 5.]
        self.assertEqual(circle.sum(), len(values))
        args[0][circle] = values
        args[3][:] = True
        point, report = sample_surface(*args)
        self.assertIsNone(point)
        self.assertEqual(report['reason'], 'broad or mixed depth layers')


class ExportTests(unittest.TestCase):
    def test_cli_archives_native_ground_world_fields_and_preserves_body(self):
        root = np.column_stack((np.arange(12) * .1, np.zeros(12), np.ones(12)))
        joints = root[:, None] + np.array([[[0., 0, 0], [.1, 0, .4]]])
        vertices = root[:, None] + np.array([[[0., 0, 0], [.2, .1, .8], [-.2, -.1, -.8]]])
        fields = dict(vertices=vertices, joints=joints, body_scale=np.asarray(1.),
                      source_video_sha256=np.asarray('a' * 64), source_actor_id=np.asarray('test_actor'),
                      room_basis_sha256=np.asarray('b' * 64), time_seconds=np.arange(12) / 30,
                      faces=np.array([[0, 1, 2]]), left_vertex_ids=np.array([0]),
                      betas=np.ones((12, 10)), body_pose=np.zeros((12, 63)),
                      transl=root.copy(), global_orient=np.zeros((12, 3)),
                      body_joints=joints.copy(), left_surface_vertices=vertices[:, :1].copy(),
                      left_height_m=np.ones((12, 1)), left_vertex_velocity_m_s=np.ones((11, 1, 3)),
                      mesh_max_penetration_m=np.zeros(12), ground_y=np.asarray(0.),
                      custom_world_points=vertices.copy())
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); body = folder / 'body.npz'; observations = folder / 'obs.npz'
            np.savez(body, **fields)
            shared = {k: fields[k] for k in ('source_video_sha256', 'source_actor_id', 'room_basis_sha256', 'time_seconds')}
            np.savez(observations, **shared, source_body_sha256=np.asarray(hashlib.sha256(body.read_bytes()).hexdigest()),
                     frame_indices=np.arange(12), root_targets=root + [1., 2., 3.], valid=np.ones(12, bool),
                     weights=np.ones(12), train=np.arange(12) % 3 != 0)
            output = folder / 'output'
            argv = ['align_depth_trajectory.py', '--body', str(body), '--observations', str(observations), '--output', str(output)]
            with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                main()
            with np.load(output / 'body_room.npz') as result:
                for key in ('transl', 'global_orient', 'body_joints', 'left_surface_vertices', 'left_height_m',
                            'left_vertex_velocity_m_s', 'mesh_max_penetration_m', 'ground_y', 'custom_world_points'):
                    self.assertNotIn(key, result.files)
                    np.testing.assert_array_equal(result['original_input__' + key], fields[key])
                for key in ('faces', 'left_vertex_ids', 'betas', 'body_pose', 'time_seconds'):
                    np.testing.assert_array_equal(result[key], fields[key])
                np.testing.assert_allclose(result['joints'][:, 0], root + [1., 2., 3.], atol=3e-7)
                np.testing.assert_allclose(result['vertices'].astype(float) - result['joints'][:, :1].astype(float),
                                           vertices - joints[:, :1], atol=3e-7)
            report = json.loads((output / 'report.json').read_text())
            self.assertIn('transl', report['archived_source_fields'])
            self.assertLess(report['saved_body_relative_vertex_error_m'], 3e-7)

    def test_existing_source_provenance_survives_without_double_prefix(self):
        params = np.zeros((2, 3))
        body = {'source_native__smpl_params_global__transl': params, 'original_input__ground_y': np.asarray(0.)}
        result, archived = candidate_metadata(body)
        self.assertEqual(set(result), set(body))
        self.assertEqual(archived, [])
        np.testing.assert_array_equal(result['source_native__smpl_params_global__transl'], params)

    def test_provenance_collision_is_rejected_without_overwriting_source(self):
        body = {'transl': np.ones((2, 3)), 'original_input__transl': np.zeros((2, 3))}
        for entries in (body, dict(reversed(list(body.items())))):
            with self.assertRaisesRegex(ValueError, 'provenance name collision'):
                candidate_metadata(entries)
        np.testing.assert_array_equal(body['transl'], np.ones((2, 3)))


if __name__ == '__main__':
    unittest.main()
