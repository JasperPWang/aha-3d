"""Camera-ray, event timing, native FK and CLI regression checks (CPU)."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.motion.reference import build_guidance, camera_to_world, compile_constraints, digest, project
from aha3d.motion.sam3d import canonical_camera, normalize_output, pixel_transform, local_hub_loader

R = np.array([[-1., 0, 0], [0, 0, 1], [0, 1, 0]])
K = np.array([[200., 0, 320], [0, 200, 240], [0, 0, 1]])
NAMES = ['left-hip', 'right-hip', 'right-shoulder', 'right-elbow', 'right-wrist',
         'left-shoulder', 'left-elbow', 'left-wrist']
POINTS = np.array([[.2, 0, 5], [-.2, 0, 5], [-.4, -.5, 5], [-.6, -.8, 5],
                   [-.8, -1, 5], [.4, -.5, 5], [.6, -.8, 5], [.8, -1, 5]])


def fixture():
    pose = np.eye(4); pose[:3, :3] = R.T @ np.diag([1., -1., -1.])
    pose[:3, 3] = [10, 20, 1]
    cameras = dict(processed_size_wh=[640, 480], frames=[dict(source_frame=60,
                   timestamp_seconds=1.001, intrinsics=K.tolist(), c2w=pose.tolist())])
    obs = dict(schema_version=1, coordinate_convention='opencv_camera_metres_with_translation',
               processed_size_wh=[640, 480], keypoint_names=NAMES, frames=[dict(source_frame=60,
               timestamp_seconds=1.001, keypoints_camera_m=POINTS.tolist(), keypoints_2d=project(POINTS, K).tolist())])
    selection = dict(schema_version=1, native_frames=90, native_fps=30,
                     world_to_kimodo_rotation=R.tolist(), events=[dict(source_frame=60, side='right',
                     reviewed=True, review_note='Synthetic analytic fixture')])
    return obs, cameras, selection


def baseline():
    import torch
    from kimodo.skeleton import SMPLXSkeleton22
    skel = SMPLXSkeleton22().cpu()
    local = np.tile(np.eye(3, dtype=np.float32), (90, 22, 1, 1))
    root = np.tile(np.array([0., 1., 0.], dtype=np.float32), (90, 1))
    with torch.inference_mode():
        rots, points, _ = skel.fk(torch.from_numpy(local), torch.from_numpy(root))
    return dict(local_rot_mats=local, root_positions=root, smooth_root_pos=root.copy(),
                posed_joints=points.numpy(), global_rot_mats=rots.numpy())


class ReferenceMotion(unittest.TestCase):
    def test_hub_is_local_and_never_downloads_architecture_or_weights(self):
        from unittest.mock import Mock
        original = Mock(return_value='architecture')
        loader = local_hub_loader(original, '/local/pinned/dinov3')
        self.assertEqual(loader('facebookresearch/dinov3', 'model', source='github', pretrained=False), 'architecture')
        original.assert_called_once_with('/local/pinned/dinov3', 'model', source='local', pretrained=False)
        with self.assertRaises(ValueError): loader('other/repo', 'model', pretrained=False)
        with self.assertRaises(ValueError): loader('facebookresearch/dinov3', 'model', pretrained=True)

    def test_camera_homography_preserves_rays_with_offcenter_anisotropic_intrinsics(self):
        k = np.array([[510., 3, 287], [0, 620, 221], [0, 0, 1.]])
        ck, h = canonical_camera(k, 640, 480)
        np.testing.assert_allclose(pixel_transform(project(POINTS, k), h), project(POINTS, ck), atol=1e-10)
        self.assertEqual(ck[0, 0], ck[1, 1])
        np.testing.assert_allclose(ck[:2, 2], [320, 240])

    def test_sam_translation_applied_once_and_projection_guard(self):
        k = np.array([[510., 0, 287], [0, 620, 221], [0, 0, 1.]])
        ck, h = canonical_camera(k, 640, 480)
        p = np.tile(POINTS[0], (70, 1)); t = np.array([.3, -.1, 4.])
        raw = dict(pred_keypoints_3d=p-t, pred_cam_t=t, pred_keypoints_2d=project(p, ck))
        output = normalize_output(raw, k, ck, h, 640, 480)
        np.testing.assert_allclose(output['keypoints_camera_m'], p)
        np.testing.assert_allclose(output['keypoints_2d'], project(p, k))
        raw['pred_cam_t'] = t * 2
        with self.assertRaises(ValueError): normalize_output(raw, k, ck, h, 640, 480)

    def test_world_camera_roundtrip(self):
        _, cameras, _ = fixture(); pose = np.asarray(cameras['frames'][0]['c2w'])
        world = camera_to_world(POINTS, pose)
        np.testing.assert_allclose((world-pose[:3, 3]) @ pose[:3, :3], POINTS, atol=1e-12)

    def test_arm_directions_and_pts_not_source_frame_number(self):
        obs, cams, sel = fixture(); key = build_guidance(obs, cams, sel)[0]
        self.assertEqual(key['frame'], 30)  # source frame 60, PTS 1.001, native 30 fps
        self.assertAlmostEqual(key['quantization_error_seconds'], -.001)
        np.testing.assert_allclose(key['facing_xz'], [0, 1], atol=1e-10)
        np.testing.assert_allclose(key['upper_arm_direction'], np.array([.2, .3, 0])/np.sqrt(.13), atol=1e-10)
        self.assertNotIn('root_xz_m', key)

    def test_translation_does_not_change_relative_guidance(self):
        obs, cams, sel = fixture(); old = build_guidance(obs, cams, sel)
        cams['frames'][0]['c2w'][0][3] += 100
        new = build_guidance(obs, cams, sel)
        np.testing.assert_allclose(old[0]['upper_arm_direction'], new[0]['upper_arm_direction'], atol=1e-10)

    def test_reject_bad_review_timing_rotations_and_projection(self):
        def mutations(o, c, s):
            return [lambda: s['events'][0].update(reviewed=False),
                    lambda: c['frames'][0].update(timestamp_seconds=2),
                    lambda: s.update(world_to_kimodo_rotation=np.eye(3).tolist()),
                    lambda: s['events'][0].update(target_time_seconds=3),
                    lambda: o['frames'][0]['keypoints_2d'][2].__setitem__(0, 0),
                    lambda: o.update(keypoint_names=['x'] * len(NAMES)),
                    lambda: s['events'].append(deepcopy(s['events'][0])),
                    lambda: o['frames'][0]['keypoints_camera_m'][2].__setitem__(2, -1)]
        for i in range(8):
            o, c, s = fixture(); mutations(o, c, s)[i]()
            with self.subTest(case=i), self.assertRaises(ValueError): build_guidance(o, c, s)

    def test_override_facing_preserves_body_relative_action(self):
        o, c, s = fixture(); original = build_guidance(o, c, s)[0]
        s['events'][0]['facing_xz'] = [1, 0]
        changed = build_guidance(o, c, s)[0]
        np.testing.assert_allclose(original['upper_arm_direction'], changed['upper_arm_direction'])
        np.testing.assert_allclose(changed['facing_xz'], [1, 0])

    def test_both_hands_native_fk_mask_and_roundtrip(self):
        from kimodo.constraints import load_constraints_lst
        from kimodo.skeleton import SMPLXSkeleton22
        o, c, s = fixture(); s['events'].append(dict(s['events'][0], side='left'))
        keys = build_guidance(o, c, s)
        native, reports = compile_constraints(baseline(), keys, 90)
        loaded = load_constraints_lst(native, SMPLXSkeleton22().cpu())
        self.assertEqual([v.name for v in loaded], ['left-hand', 'right-hand'])
        self.assertEqual([v.pos_indices.tolist() for v in loaded], [[20], [21]])
        for condition, event in zip(loaded, keys):
            self.assertEqual(condition.frame_indices.tolist(), [30])
            bone, tip = (16, 18) if event['side'] == 'left' else (17, 19)
            points = condition.global_joints_positions.numpy()[0]
            direction = points[tip] - points[bone]; direction /= np.linalg.norm(direction)
            local = event['upper_arm_direction']
            expected = np.array([-local[0], local[1], local[2]])
            np.testing.assert_allclose(direction, expected, atol=1e-5)
        self.assertLess(max(r['fk_roundtrip_max_error_m'] for r in reports), 1e-5)
        np.testing.assert_allclose(loaded[0].global_joints_positions, loaded[1].global_joints_positions)

    def test_conflicting_hands_fail(self):
        o, c, s = fixture(); s['events'].append(dict(s['events'][0], side='left', facing_xz=[1, 0]))
        with self.assertRaises(ValueError): compile_constraints(baseline(), build_guidance(o, c, s), 90)

    def test_route_conflict_and_nonfinite_goals_fail(self):
        o, c, s = fixture(); keys = build_guidance(o, c, s)
        route = [dict(type='root2d', frame_indices=[30], smooth_root_2d=[[2., 0.]])]
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            compile_constraints(baseline(), keys, 90, route)
        route[0]['smooth_root_2d'] = [[0., 0.]]
        native, _ = compile_constraints(baseline(), keys, 90, route)
        self.assertEqual(native[0]['type'], 'root2d')
        route[0]['smooth_root_2d'][0][0] = float('nan')
        with self.assertRaises(ValueError): compile_constraints(baseline(), keys, 90, route)

    def test_contact_field_is_not_silently_ignored(self):
        o, c, s = fixture(); s['events'][0]['wrist_target_m'] = [0., 1., 0.]
        with self.assertRaisesRegex(ValueError, 'Unsupported event fields'):
            build_guidance(o, c, s)

    def test_degenerate_limb_is_rejected(self):
        o, c, s = fixture()
        o['frames'][0]['keypoints_camera_m'][3] = o['frames'][0]['keypoints_camera_m'][2]
        o['frames'][0]['keypoints_2d'][3] = o['frames'][0]['keypoints_2d'][2]
        with self.assertRaisesRegex(ValueError, 'Degenerate'):
            build_guidance(o, c, s)

    def test_cli_creates_usable_native_json_and_rejects_provenance_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); bundle = p/'pi3x'; bundle.mkdir()
            o, c, s = fixture()
            (bundle/'inputs.json').write_text(json.dumps(dict(source_sha256='a'*64)))
            (bundle/'cameras.json').write_text(json.dumps(c))
            o.update(source_sha256='a'*64, pi3x_inputs_sha256=digest(bundle/'inputs.json'),
                     pi3x_cameras_sha256=digest(bundle/'cameras.json'))
            (p/'obs.json').write_text(json.dumps(o)); (p/'selection.json').write_text(json.dumps(s))
            np.savez(p/'baseline.npz', **baseline())
            cmd = [sys.executable, '-m', 'aha3d.motion.reference', '--observations', str(p/'obs.json'),
                   '--pi3x', str(bundle), '--selection', str(p/'selection.json'), '--baseline', str(p/'baseline.npz'),
                   '--out', str(p/'out')]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((p/'out/constraints.json').read_text())[0]['type'], 'right-hand')
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)  # no overwrite
            o['source_sha256'] = 'b'*64; (p/'obs.json').write_text(json.dumps(o)); cmd[-1] = str(p/'other')
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('different or modified', result.stderr)
            self.assertFalse((p/'other').exists())


if __name__ == '__main__': unittest.main()
