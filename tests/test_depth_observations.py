import unittest
import json
import tempfile
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from tools.gvhmr.depth_observations import cache_identity_fields, confidence_anchors, prepare, validate_cache_binding, camera_mesh, floor_up_yaw, ray_hit, resize_uv, rigid_transform


class DepthObservationTests(unittest.TestCase):
    def test_confidence_hip_priority_shoulder_fallback_and_inactive_nan(self):
        kp = np.ones((5, 17, 3)); active = np.array([True, True, True, False, True])
        kp[1, 11, 2] = .49
        kp[2, 11, 0] = np.nan
        kp[2, 5, 2] = .49
        kp[4, [11, 12], 2] = .5
        hips, shoulders = confidence_anchors(kp, active)
        np.testing.assert_array_equal(hips, [True, False, False, False, True])
        np.testing.assert_array_equal(shoulders, [False, True, False, False, False])
        for threshold in [-.1, 1.1, float('nan')]:
            with self.assertRaises(ValueError):
                confidence_anchors(kp, active, threshold)

    def test_confidence_cache_binding_requires_exact_actor_video_and_bytes(self):
        from tools.gvhmr.root_constraints import sha256
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache'; path.write_bytes(b'cached input')
            paths = {name: path for name in ('native', 'ground', 'observations')}
            binding = dict(actor_id='person', source_video_sha256='video',
                           **{name + '_sha256': sha256(path) for name in paths})
            validate_cache_binding(binding, paths, 'video', 'person')
            with self.assertRaisesRegex(ValueError, 'actor/video'):
                validate_cache_binding(binding, paths, 'other', 'person')
            path.write_bytes(b'changed cache')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                validate_cache_binding(binding, paths, 'video', 'person')

    def test_prepare_confidence_without_diagnostic_reports_or_review_and_preserves_body(self):
        import torch
        from tools.gvhmr.root_constraints import sha256
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); n, h, w = 5, 64, 64
            times = np.arange(n) / 30.; active = np.array([True, True, True, True, False])
            names = ['body_' + str(i) for i in range(144)]
            pose = np.zeros((n, 63)); betas = np.zeros((n, 10)); orient = np.zeros((n, 3))
            transl = np.tile([0., 0., 2.5], (n, 1))
            K = np.broadcast_to(np.array([[50., 0, 32], [0, 50, 32], [0, 0, 1]]), (n, 3, 3)).copy()
            native = dict(source_actor_id=np.asarray('person'), source_video_sha256=np.asarray('video'),
                          frame_times_seconds=times, track_active=active, K_fullimg=K)
            for space in ('global', 'incam'):
                for name, array in [('body_pose', pose), ('betas', betas), ('global_orient', orient), ('transl', transl)]:
                    native['smpl_params_' + space + '__' + name] = array
            verts = np.tile(np.array([[-1., -1, 2], [1., -1, 2], [0, 2, 2]]), (n, 1, 1))
            ground = dict(body_pose=pose, betas=betas, global_orient=orient, transl=transl,
                          vertices=verts, joints=np.tile(transl[:, None], (1, 127, 1)), faces=np.array([[0, 1, 2]]),
                          body_joint_names=np.asarray(names[:22]), time_seconds=times, track_active=active)
            kp = np.tile([30., 30., .9], (n, 17, 1)); kp[1, 11, 2] = .1; kp[3] = np.nan
            obs = dict(time_seconds=times, image_size=np.array([w, h]), keypoints=kp,
                       reviewed_visible=np.zeros((n, 17), bool), detected=np.zeros(n, bool))
            C = np.tile(np.eye(4), (n, 1, 1)); C[:, :3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
            inputs = dict(frame_indices=np.arange(n), timestamps_seconds=times, rgb=np.zeros((n, h, w, 3), np.uint8))
            predictions = dict(camera_poses=C, local_points=np.tile([0., 0., 2.], (n, h, w, 1)),
                               conf=np.ones((n, h, w, 1)), non_edge=np.ones((n, h, w), bool), intrinsics=K)
            caches = dict(native=native, ground=ground, observations=obs,
                          cameras=dict(dense_c2w_room_cv=C, dense_time_seconds=times, source_video_sha256=np.asarray('video')),
                          pi3x_inputs=inputs, pi3x_predictions=predictions)
            paths = {}
            for name, data in caches.items():
                paths[name] = name + '.npz'; np.savez(root / paths[name], **data)
            paths.update(tracking='tracking.json', masks='masks.npy', pi3x_input_report='input.json',
                         coco_regressor='coco.pt', smplx_to_smpl='mapping.pt', smplx_joint_names='names.py',
                         review='DOES_NOT_EXIST', quality_report='DOES_NOT_EXIST', ground_report='DOES_NOT_EXIST')
            (root / 'tracking.json').write_text(json.dumps(dict(actor_id='person', source_video_sha256='video')))
            (root / 'input.json').write_text(json.dumps(dict(source_sha256='video', source_frame_count=n,
                 original_size_wh=[w, h], processed_size_wh=[w, h], frame_indices=list(range(n)), timestamps_seconds=times.tolist())))
            (root / 'names.py').write_text('JOINT_NAMES = ' + repr(names))
            np.save(root / 'masks.npy', np.ones((n, h, w), np.uint8))
            torch.save(torch.full((17, 3), 1 / 3), root / 'coco.pt'); torch.save(torch.eye(3), root / 'mapping.pt')
            binding = dict(actor_id='person', source_video_sha256='video', **{
                name + '_sha256': sha256(root / paths[name]) for name in ('native', 'ground', 'observations')})
            cfg = dict(schema_version=1, observation_policy='confidence', source_video_sha256='video', actor_id='person',
                       paths=paths, cache_binding=binding, raw_to_room=np.eye(4).tolist(), max_model_anchor_error_px=.001)
            (root / 'config.json').write_text(json.dumps(cfg))
            report = prepare(root / 'config.json', root / 'output')
            self.assertEqual(report['valid_rows'], [0, 1, 2])
            self.assertEqual(report['rotation']['frames'], [0, 1, 2])
            self.assertFalse(report['model_anchor_reprojection_filter_enabled'])
            self.assertGreater(report['rows'][0]['model_to_observed_anchor_residual_px'], .001)
            self.assertEqual(report['anchor_counts']['valid_shoulder_rows'], 1)
            self.assertEqual(report['rows'][1]['anatomical_anchor'], 'shoulder_midpoint')
            with np.load(root / 'output/rigid_body_room.npz') as result:
                self.assertEqual(float(result['body_scale']), 1.)
                np.testing.assert_array_equal(result['track_active'], active)
                original_edges = verts[:, 1:] - verts[:, :1]
                output_edges = result['vertices'][:, 1:] - result['vertices'][:, :1]
                np.testing.assert_allclose(np.linalg.norm(output_edges, axis=2), np.linalg.norm(original_edges, axis=2), atol=1e-6)
            # Diagnostics are not even read/hashed, and an unknown mode cannot silently fall back.
            self.assertNotIn(str(root / 'DOES_NOT_EXIST'), report['input_hashes'])
            cfg['observation_policy'] = 'typo'; (root / 'config.json').write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError, 'observation_policy'):
                prepare(root / 'config.json', root / 'bad_output')

    def test_shared_import_export_schema_covers_actual_full_joint_count_and_fps(self):
        names = ['body_' + str(i) for i in range(144)]
        ground = dict(joints=np.zeros((5, 127, 3)), body_joint_names=np.asarray(names[:22]))
        fields = cache_identity_fields(ground, np.arange(5) / 30., names)
        self.assertEqual(fields['joint_names'].shape, (127,))
        self.assertAlmostEqual(float(fields['fps']), 30.)
        self.assertEqual(fields['joint_names'][126], names[126])
        with self.assertRaises(ValueError):
            cache_identity_fields(ground, np.arange(5) / 30., names[:22])
        with self.assertRaisesRegex(ValueError, 'uniform'):
            cache_identity_fields(ground, np.array([0., .03, .06, .09, .2]), names)

    def test_half_pixel_resize_roundtrip_nonstandard_raster(self):
        uv = np.array([[0., 0], [1920, 1078], [321.5, 400.1]])
        mapped = resize_uv(uv, [1921, 1079], [700, 394])
        np.testing.assert_allclose(resize_uv(mapped, [700, 394], [1921, 1079]), uv, atol=3e-13)
        self.assertNotEqual(mapped[0, 0], 0.)

    def test_source_shaped_pelvis_offset_and_camera_rotation_apply_once(self):
        rest = np.array([.02, -.12, .03]); transl = np.array([1., 2., 3.]); root = transl + rest
        vg = root + np.array([[.1, 0, 0], [0, .2, 0]])
        rg = Rotation.from_euler('y', .4).as_matrix(); ri = Rotation.from_euler('x', -.2).as_matrix()
        incam = np.array([.2, .3, 5.])
        mesh, pelvis, R = camera_mesh(vg, root, rg, ri, incam, rest)
        np.testing.assert_allclose(pelvis, incam + rest)
        np.testing.assert_allclose((mesh - pelvis) @ R + root, vg, atol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(mesh[1] - mesh[0]), np.linalg.norm(vg[1] - vg[0]))

    def test_front_hit_uses_nearest_positive_intersection_and_rejects_behind(self):
        v = np.array([[-1., -1, 2], [1., -1, 2], [0., 1, 2], [-1., -1, 4], [1., -1, 4], [0., 1, 4]])
        np.testing.assert_allclose(ray_hit(v, np.array([[0, 1, 2], [3, 4, 5]]), [0, 0, 1]), [0, 0, 2])
        self.assertIsNone(ray_hit(-v, np.array([[0, 1, 2]]), [0, 0, 1]))

    def test_room_transform_rejects_body_scale_and_reflection(self):
        transform = np.eye(4); transform[0, 0] = 1.2
        with self.assertRaises(ValueError):
            rigid_transform(transform)
        transform[0, 0] = -1
        with self.assertRaises(ValueError):
            rigid_transform(transform)

    def test_camera_up_yaw_uses_only_supplied_training_frames(self):
        base = np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]])
        native = {'smpl_params_global__global_orient': np.zeros((8, 3)), 'smpl_params_incam__global_orient': np.zeros((8, 3))}
        cameras = np.broadcast_to(np.eye(4), (8, 4, 4)).copy(); cameras[:, :3, :3] = base
        a, _ = floor_up_yaw(native, cameras, np.array([0, 2, 4]))
        cameras[[1, 3, 5, 6, 7], :3, :3] = Rotation.from_euler('z', 1.).as_matrix() @ base
        b, _ = floor_up_yaw(native, cameras, np.array([0, 2, 4]))
        np.testing.assert_array_equal(a, b)
        np.testing.assert_allclose(a @ [0, 1, 0], [0, 0, 1], atol=1e-12)


if __name__ == '__main__':
    unittest.main()
