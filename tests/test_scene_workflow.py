"""Meaningful timing, camera, identity and array-I/O invariants for staged reuse."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import numpy as np
from aha3d.workflow.camera import interpolate
from aha3d.workflow.crossview import load_arrays
from aha3d.workflow.people import place_cache, validate_config


class CameraTests(unittest.TestCase):
    def fixture(self):
        frames = []
        for i in range(2):
            pose = np.eye(4); pose[0, 3] = i
            frames.append(dict(source_frame=i*10, timestamp_seconds=float(i), c2w=pose.tolist(),
                intrinsics=[[100, 0, 12.], [0, 90, 20.], [0, 0, 1]]))
        return {'frames': frames}

    def test_observed_endpoints_offcenter_resize_and_rotations(self):
        z, held = interpolate(self.fixture(), [0, .5, 1], [100, 60], [200, 120])
        np.testing.assert_allclose(z['c2w'][:, 0, 3], [0, .5, 1])
        np.testing.assert_allclose(z['K'][:, 0, 2], 25.)
        np.testing.assert_allclose(z['K'][:, 1, 2], 41.)
        np.testing.assert_allclose(np.linalg.det(z['c2w'][:, :3, :3]), 1)
        self.assertEqual(held, 0)

    def test_endpoint_policy_and_invalid_camera(self):
        with self.assertRaises(ValueError): interpolate(self.fixture(), [-.1, 1.1], [100, 60], [100, 60])
        z, held = interpolate(self.fixture(), [-.1, 1.1], [100, 60], [100, 60], 'hold')
        self.assertEqual(held, 2)
        np.testing.assert_allclose(z['c2w'][:, 0, 3], [0, 1])
        cam = self.fixture(); cam['frames'][1]['c2w'][0][0] = -1
        with self.assertRaises(ValueError): interpolate(cam, [0, 1], [100, 60], [100, 60])

    def test_dense_npz_members_read_once(self):
        seen = {}
        class Archive:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __getitem__(self, name):
                seen[name] = seen.get(name, 0) + 1
                return np.zeros((2, 4, 4, 3))
        rgb, pred = load_arrays(Path('/unused'), lambda p: Archive())
        for _ in range(1000):
            pred['points'][0, 0, 0]; pred['conf'][0, 0, 0]
        self.assertEqual(seen, dict(rgb=1, points=1, conf=1, non_edge=1))


class PeopleTests(unittest.TestCase):
    def test_placement_timing_and_immutable_source(self):
        t = dict(frames=2, fps='2')
        data = dict(vertices=np.array([[[1., 0, .2], [1, 0, 2]], [[2, 0, .4], [2, 0, 2]]]),
            joints=np.array([[[1., 0, 1]], [[2., 0, 1]]]), fps=np.array(2.), time_seconds=np.array([0., .5]))
        person = dict(scale=.5, yaw=90, anchor_xy=[3, 4], ground_z=.01)
        result, matrix = place_cache(data, person, t)
        np.testing.assert_allclose(result['vertices'][:, :, 2].min(1), .01)
        root = matrix[:3, :3] @ result['joints'][0, 0] + matrix[:3, 3]
        np.testing.assert_allclose(root[:2], [3, 4])
        np.testing.assert_array_equal(data['vertices'][0, 0], [1., 0, .2])
        data['time_seconds'][1] = .4
        with self.assertRaises(ValueError): place_cache(data, person, t)

    def test_duplicate_identity_rejected(self):
        person = dict(id=1, label='adult', cache='cache.npz', anchor_xy=[0, 0])
        cfg = dict(schema_version=1, timing=dict(frames=2, fps='2'), image_size=[100, 60], people=[person, person])
        with self.assertRaises(ValueError): validate_config(cfg)


if __name__ == '__main__': unittest.main()
