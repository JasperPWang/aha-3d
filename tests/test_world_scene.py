"""A room export must preserve scale and reject incompatible camera bases."""
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from tools.gvhmr.world_scene import camera_basis, room_mesh, horizontal_placement, cache_joint_names


class WorldSceneTests(unittest.TestCase):
    def test_export_names_the_actual_smplx_joint_set(self):
        official = [f'joint_{i}' for i in range(144)]
        names, body = cache_joint_names(127, official)
        self.assertEqual(len(names), 127); self.assertEqual(names[126], 'joint_126')
        self.assertEqual(body.tolist(), official[:22])
        for count in (55, 200):
            with self.assertRaisesRegex(ValueError, 'SMPL-X'):
                cache_joint_names(count, official)

    def test_stationary_camera_orientation_defines_basis(self):
        # Translation-only registration cannot resolve this stationary-camera case.
        source = np.repeat(np.eye(4)[None], 4, axis=0)
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_euler('xyz', [.2, .5, -.4]).as_matrix()
        transform[:3, 3] = [2, 3, 4]
        actual, report = camera_basis(source, transform @ source)
        np.testing.assert_allclose(actual, transform, atol=1e-12)
        points = np.array([[0, 0, 0], [1, 2, 3]])
        moved = room_mesh(points, actual)
        self.assertAlmostEqual(np.linalg.norm(moved[1]-moved[0]), np.sqrt(14))
        self.assertEqual(report['body_scale'], 1.)

    def test_camera_drift_or_reflection_is_rejected(self):
        source = np.repeat(np.eye(4)[None], 4, axis=0)
        target = source.copy(); target[-1, 0, 3] = .1
        with self.assertRaisesRegex(ValueError, 'fixed rigid basis'):
            camera_basis(source, target)
        target = source.copy(); target[:, 0, 0] = -1
        with self.assertRaisesRegex(ValueError, 'right-handed'):
            camera_basis(source, target)

    def test_placement_uses_training_xy_and_keeps_floor_height(self):
        times = np.arange(5) / 30
        joints = np.zeros((5, 1, 3))
        obs = dict(frame_indices=np.arange(5), time_seconds=times,
                   valid=np.ones(5, bool), train=np.array([True, True, True, False, False]),
                   weights=np.ones(5), root_targets=np.array([[1, 2, 30]]*3+[[100, 200, 300]]*2),
                   source_actor_id=np.asarray('actor'))
        delta, report = horizontal_placement(joints, times, np.ones(5, bool), obs, {'source_actor_id': 'actor'})
        np.testing.assert_equal(delta, [1, 2, 0])
        self.assertEqual(report['training_source_frames'], [0, 1, 2])
        with self.assertRaisesRegex(ValueError, 'source_actor_id'):
            horizontal_placement(joints, times, np.ones(5, bool), obs, {'source_actor_id': 'other'})


class ContactExportTests(unittest.TestCase):
    def test_refine_writes_geometry_and_keeps_visual_acceptance_separate(self):
        import argparse
        import json
        import tempfile
        from pathlib import Path
        import test_full_scene_constraints as fixtures
        from tools.gvhmr.world_scene import refine, fingerprint
        body, _, scene = fixtures.FullSceneTests().fixture()
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            np.savez(d/'body.npz', **body)
            (d/'room.blend').write_bytes(b'synthetic room provenance')
            cube = scene['objects'][0]
            np.savez(d/'geometry.npz', floor__vertices=scene['floor_vertices'], floor__faces=scene['floor_faces'],
                     box__vertices=cube['vertices'], box__faces=cube['faces'], box__planes=cube['planes'])
            np.savez(d/'surface.npz', vertices=scene['floor_vertices'], faces=scene['floor_faces'])
            sha = lambda p: fingerprint(d/p)['sha256']
            binding = dict(schema_version=1, source_body_sha256=sha('body.npz'), source_actor_id='actor',
                           source_video_sha256='a'*64, room_basis_sha256='b'*64, reviewed_by='synthetic test')
            spec = dict(binding, scope='all_active_vertices', geometry_file='geometry.npz',
                        geometry_sha256=sha('geometry.npz'), source_blend='room.blend', source_blend_sha256=sha('room.blend'),
                        floor=dict(key='floor', normal=[0,0,1], offset=0, coverage_vertex_indices=[0]),
                        objects=[dict(name='box', key='box')], **scene['spec'])
            (d/'scene.json').write_text(json.dumps(spec))
            contact = dict(name='foot', landmark=dict(kind='vertices', indices=[0]), intervals=[[0,51]],
                           train_frame_indices=list(range(51)), surface_file='surface.npz', surface_sha256=sha('surface.npz'),
                           plane_normal=[0,0,1], plane_offset=0, target_gap_m=.002, max_gap_m=.02,
                           max_penetration_m=.01, weight=10.)
            (d/'contacts.json').write_text(json.dumps(dict(binding, review_scope='synthetic support', contacts=[contact])))
            report = refine(argparse.Namespace(body=d/'body.npz', contacts=d/'contacts.json', scene_constraints=d/'scene.json',
                            out=d/'out', knot_spacing=.5, acceleration_penalty=.01, offset_penalty=.05, iterations=100))
            result = dict(np.load(d/'out/after/body_room.npz'))
            np.testing.assert_allclose(result['vertices']-result['joints'][:,:1], body['vertices']-body['joints'][:,:1], atol=1e-6)
            self.assertLess(report['contacts_after'][0]['max_gap_m'], report['contacts_before'][0]['max_gap_m'])
            self.assertFalse(report['accepted'])
            self.assertEqual(report['visual_review'], 'pending')
            self.assertTrue((d/'out/after/scene_metrics.json').is_file())
