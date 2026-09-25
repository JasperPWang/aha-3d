"""Camera convention, interpolation and provenance tests without inference."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from scipy.spatial.transform import Rotation

from tools.gvhmr import camera_tracks as camera


def poses():
    result = np.tile(np.eye(4), (3, 1, 1))
    result[:, :3, :3] = Rotation.from_euler('xyz', [[25, -30, 12], [40, 7, 51], [-15, 45, 80]], degrees=True).as_matrix()
    result[:, :3, 3] = [[1, 2, 3], [2, -1, 4], [0, 3, -2]]
    return result


def bundle_fixture():
    t = np.arange(5) / 30
    ids = [0, 2, 4]
    cameras = dict(convention=camera.PI3X_CONVENTION, world_transform=np.eye(4).tolist(),
        processed_size_wh=[320, 180], units='predicted metres; uncalibrated',
        frames=[dict(source_frame=i, timestamp_seconds=t[i], c2w=pose.tolist(),
                     intrinsics=[[300, 0, 159.5], [0, 300, 89.5], [0, 0, 1]]) for i, pose in zip(ids, poses())])
    inputs = dict(source_sha256='sourcehash', source_frame_count=5, frame_indices=ids,
        timestamps_seconds=t[ids].tolist(), original_size_wh=[640, 360], processed_size_wh=[320, 180])
    review = dict(source_sha256='sourcehash', continuous_shot_reviewed=True, cut_frame_indices=[],
        reviewed_by='fixture', review_scope='three synthetic keys only', reviewed_frame_indices=ids)
    return cameras, inputs, review, t


def upstream_quaternion_conversion(track):
    """Independent NumPy transcription of upstream WXYZ conversion and transpose.

    Matches PyTorch3D quaternion_to_matrix used by pinned load_data_dict;
    adapter implementation instead uses SciPy's XYZW API.
    """
    w, x, y, z = np.asarray(track)[:, [6, 3, 4, 5]].T
    two_s = 2 / (w*w + x*x + y*y + z*z)
    matrix = np.stack([1-two_s*(y*y+z*z), two_s*(x*y-z*w), two_s*(x*z+y*w),
        two_s*(x*y+z*w), 1-two_s*(x*x+z*z), two_s*(y*z-x*w),
        two_s*(x*z-y*w), two_s*(y*z+x*w), 1-two_s*(x*x+y*y)], axis=-1).reshape(-1, 3, 3)
    w2c = matrix.swapaxes(-1, -2)
    return w2c[1:] @ w2c[:-1].swapaxes(-1, -2)


class CameraTrackTests(unittest.TestCase):
    def test_exact_upstream_quaternion_order_transpose_and_sixd_on_nonidentity_poses(self):
        original = poses()
        track = camera.c2w_to_slam(original)
        np.testing.assert_allclose(track[:, :3], original[:, :3, 3])
        np.testing.assert_allclose(camera.slam_to_c2w(track), original, atol=1e-12)
        expected = upstream_quaternion_conversion(track)
        actual = camera.gvhmr_relative_rotations(original)
        np.testing.assert_allclose(actual, expected, atol=1e-12)
        sixd = camera.gvhmr_sixd(actual)
        np.testing.assert_allclose(sixd[:-1], expected[:, :2].reshape(-1, 6), atol=1e-7)
        np.testing.assert_array_equal(sixd[-1], sixd[-2])
        wrong_order = track.copy()
        wrong_order[:, 3:] = track[:, [6, 3, 4, 5]]
        self.assertGreater(np.max(np.abs(upstream_quaternion_conversion(wrong_order) - actual)), .1)

    def test_common_world_basis_cancels_but_inverse_direction_does_not(self):
        original = poses()
        world = np.eye(4)
        world[:3, :3] = Rotation.from_euler('xyz', [90, -24, 37], degrees=True).as_matrix()
        world[:3, 3] = [10, -20, 5]
        expected = camera.gvhmr_relative_rotations(original)
        np.testing.assert_allclose(camera.gvhmr_relative_rotations(world @ original), expected, atol=1e-12)
        inverse_wrong_direction = np.linalg.inv(original)
        self.assertGreater(np.max(np.abs(camera.gvhmr_relative_rotations(inverse_wrong_direction) - expected)), .1)
        _, comparison = camera.compare_relative_tracks(camera.c2w_to_slam(original),
            camera.c2w_to_slam(inverse_wrong_direction), np.arange(3) / 30)
        self.assertGreater(comparison['relative_angle_discrepancy_degrees']['maximum'], 10)

    def test_slerp_preserves_keys_and_correct_nonidentity_midpoint_without_extrapolation(self):
        start = poses()[0]
        delta = np.array([.2, .4, -.3])
        end = start.copy()
        end[:3, :3] = start[:3, :3] @ Rotation.from_rotvec(delta).as_matrix()
        end[:3, 3] += [2, -4, 6]
        ts = np.arange(3) / 30
        result = camera.interpolate_c2w([start, end], ts[[0, 2]], ts)
        np.testing.assert_allclose(result[[0, 2]], [start, end], atol=1e-12)
        np.testing.assert_allclose(result[1, :3, :3], start[:3, :3] @ Rotation.from_rotvec(delta / 2).as_matrix(), atol=1e-12)
        np.testing.assert_allclose(result[1, :3, 3], (start[:3, 3] + end[:3, 3]) / 2)
        with self.assertRaisesRegex(ValueError, 'forbids extrapolation'):
            camera.interpolate_c2w([start, end], ts[[0, 2]], [-1e-3, ts[0]])

    def test_rigidity_rejects_reflection_scale_and_bad_projective_row(self):
        original = poses()
        for matrix in [np.diag([-1., 1, 1, 1]), np.diag([2., 2, 2, 1])]:
            with self.assertRaisesRegex(ValueError, 'proper rigid'):
                camera.rigid(matrix @ original)
        original[0, 3, 0] = .01
        with self.assertRaisesRegex(ValueError, 'proper rigid'):
            camera.c2w_to_slam(original)
        track = camera.c2w_to_slam(poses())
        track[:, 3:] *= 2
        with self.assertRaisesRegex(ValueError, 'unit norm'):
            camera.slam_to_c2w(track)

    def test_bundle_exact_source_hash_frame_ids_pts_raster_and_review(self):
        cams, inputs, review, times = bundle_fixture()
        result = camera.validate_bundle(cams, inputs, review, times, [640, 360], 'sourcehash')
        np.testing.assert_array_equal(result['observation_time_seconds'], times[[0, 2, 4]])
        cases = [
            ('inputs', 'source_sha256', 'other', 'source hash'),
            ('inputs', 'original_size_wh', [640, 480], 'source raster'),
            ('inputs', 'processed_size_wh', [320, 200], 'processed rasters'),
            ('inputs', 'timestamps_seconds', [0, .06, times[-1]], 'timestamps differ'),
            ('inputs', 'frame_indices', [1, 2, 4], 'both source endpoints'),
            ('cameras', 'convention', 'world-to-camera OpenCV', 'camera-to-world convention'),
            ('review', 'cut_frame_indices', [2], 'without cuts'),
            ('review', 'continuous_shot_reviewed', False, 'without cuts'),
        ]
        for name, key, value, error in cases:
            fields = copy.deepcopy(dict(cameras=cams, inputs=inputs, review=review))
            fields[name][key] = value
            with self.subTest(name=name, key=key), self.assertRaisesRegex(ValueError, error):
                camera.validate_bundle(fields['cameras'], fields['inputs'], fields['review'], times, [640, 360], 'sourcehash')

    def test_full_rows_required_and_pi3x_intrinsics_preserved_but_unused(self):
        cams, inputs, review, times = bundle_fixture()
        with self.assertRaisesRegex(ValueError, 'missing rows retained'):
            camera.validate_bundle(cams, inputs, review, times[[0, 1, 3, 4]], [640, 360], 'sourcehash')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in [('cameras.json', cams), ('inputs.json', inputs), ('camera_review.json', review)]:
                (root / name).write_text(json.dumps(content))
            original, report = camera.prepare_pi3x(root, times, [640, 360], 'sourcehash')
            cams['frames'][1]['intrinsics'][0][0] = 900
            (root / 'cameras.json').write_text(json.dumps(cams))
            changed, other_report = camera.prepare_pi3x(root, times, [640, 360], 'sourcehash')
            np.testing.assert_array_equal(original['slam'], changed['slam'])
            self.assertEqual(changed['observation_K'][1, 0, 0], 900)
            self.assertIn('unused', report['intrinsics_use'])
            self.assertNotEqual(report['bundle_sha256']['cameras.json'], other_report['bundle_sha256']['cameras.json'])

    def test_relative_comparison_ignores_world_origin_basis_and_translation(self):
        original = poses()
        world = np.eye(4)
        world[:3, :3] = Rotation.from_euler('x', 90, degrees=True).as_matrix()
        changed = world @ original
        changed[:, :3, 3] += [[100, 0, 0], [-100, 50, 40], [0, 900, 2]]
        arrays, report = camera.compare_relative_tracks(camera.c2w_to_slam(original), camera.c2w_to_slam(changed), np.arange(3) / 30)
        self.assertLess(report['relative_angle_discrepancy_degrees']['maximum'], 2e-6)
        self.assertFalse(report['absolute_world_poses_compared'])
        self.assertFalse(report['physical_accuracy_validated'])
        self.assertEqual(len(report['intervals']), 2)
        np.testing.assert_array_equal(arrays['interval_start_seconds'], [0, 1 / 30])

    def test_preload_keeps_all_source_poses_and_provenance_and_refuses_cache_reuse(self):
        cams, inputs, review, times = bundle_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / 'bundle'
            bundle.mkdir()
            for name, content in [('cameras.json', cams), ('inputs.json', inputs), ('camera_review.json', review)]:
                (bundle / name).write_text(json.dumps(content))
            def save(value, path):
                with Path(path).open('wb') as stream:
                    np.save(stream, value)
            kwargs = dict(repo=root, bundle=bundle, slam_path=root / 'run/preprocess/slam_results.pt',
                          output=root / 'run/camera_adapter', times=times, image_size=[640, 360],
                          source_sha256='sourcehash', torch_module=SimpleNamespace(save=save))
            with patch.object(camera, 'verify_upstream', return_value=dict(revision=camera.REVISION)):
                report = camera.preload_pi3x_slam(**kwargs)
                with self.assertRaises(FileExistsError):
                    camera.preload_pi3x_slam(**kwargs)
            track = np.load(kwargs['slam_path'])
            self.assertEqual(track.shape, (5, 7))
            np.testing.assert_allclose(camera.slam_to_c2w(track)[[0, 2, 4]], poses(), atol=1e-12)
            self.assertEqual(report['estimator'], 'pi3x')
            self.assertEqual(report['slam_sha256'], camera.file_sha256(kwargs['slam_path']))
            self.assertEqual(json.loads((kwargs['output'] / 'camera_review.json').read_text()), review)

    def test_help_requires_no_body_model_or_video(self):
        result = subprocess.run([sys.executable, 'tools/gvhmr/camera_tracks.py', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--dpvo-slam', result.stdout)

    def test_dpvo_comparison_requires_true_estimator_source_and_completed_track_hash(self):
        manifest = dict(camera_estimator='dpvo', camera_mode='moving', normalized_input_sha256='source',
                        camera_track=dict(estimator='dpvo', sha256='track'))
        camera.validate_dpvo_provenance(manifest, 'source', 'track')
        for key, value in [('camera_estimator', 'pi3x'), ('camera_mode', 'static'),
                           ('normalized_input_sha256', 'other')]:
            candidate = copy.deepcopy(manifest)
            candidate[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'moving-camera DPVO'):
                camera.validate_dpvo_provenance(candidate, 'source', 'track')
        with self.assertRaisesRegex(ValueError, 'track hash'):
            camera.validate_dpvo_provenance(manifest, 'source', 'pi3x-track')
        manifest['camera_track']['estimator'] = 'pi3x'
        with self.assertRaisesRegex(ValueError, 'track hash'):
            camera.validate_dpvo_provenance(manifest, 'source', 'track')


if __name__ == '__main__':
    unittest.main()
