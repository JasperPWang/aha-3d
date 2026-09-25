"""Coordinate and geometry-safety checks for the opt-in geometry experiment."""
import unittest
import importlib.util
import numpy as np
from tools.layout_inspection.geometry_study import camera_rays, grid_arrays, rigid, tsdf, scene_for, cast


class GeometryStudyTests(unittest.TestCase):
    def test_camera_ray_parameter_is_axial_depth(self):
        k = np.array([[100., 0, 9], [0, 100., 8], [0, 0, 1]])
        pose = np.eye(4); pose[:3, 3] = [3, -2, 1]
        rays = camera_rays(k, pose, 17, 19)
        point = rays[2, 4, :3]+6*rays[2, 4, 3:]
        local = np.linalg.inv(pose)@np.r_[point, 1]
        np.testing.assert_allclose(local[2], 6, atol=1e-6)
        uv = k@local[:3]
        np.testing.assert_allclose(uv[:2]/uv[2], [4, 2], atol=1e-5)

    def test_no_triangles_across_a_depth_jump(self):
        y, x = np.mgrid[:8, :8]
        depth = np.full((8, 8), 4.); depth[:, 4:] = 8
        points = np.stack([x*.02, y*.02, depth], -1)
        v, _, f, _ = grid_arrays(points, np.zeros_like(points), np.ones_like(depth, bool), depth, adaptive=True)
        self.assertGreater(len(f), 0)
        self.assertTrue(np.all(np.ptp(v[f, 2], axis=1) == 0))

    def test_invalid_or_masked_pixels_do_not_make_faces(self):
        y, x = np.mgrid[:8, :8]
        points = np.stack([x*.02, y*.02, np.ones_like(x)], -1)
        valid = np.ones((8, 8), bool); valid[3:5, 3:5] = False
        _, _, _, pix = grid_arrays(points, np.zeros_like(points), valid, points[..., 2], adaptive=True)
        self.assertTrue(valid[tuple(pix.T)].all())

    def test_scale_is_rejected_in_world_transform(self):
        matrix = np.eye(4); matrix[0, 0] = 2
        with self.assertRaises(ValueError): rigid(matrix)

    @unittest.skipUnless(importlib.util.find_spec('open3d') is not None, 'Optional Open3D study runtime required')
    def test_tsdf_far_plane_units_and_pose_inverse(self):
        h = w = 64
        k = np.array([[60., 0, 31.5], [0, 60., 31.5], [0, 0, 1]])
        pose = np.eye(4); theta = .4
        pose[:3, :3] = [[np.cos(theta), 0, np.sin(theta)], [0, 1, 0], [-np.sin(theta), 0, np.cos(theta)]]
        pose[:3, 3] = [1, -.3, .8]
        depth = np.full((1, h, w), 6., np.float32)
        data = dict(ids=[0], rgb=np.full((1, h, w, 3), 128, np.uint8), depth=depth,
                    finite=np.ones_like(depth, bool), k=k[None], poses=pose[None])
        mesh = tsdf(data, data['finite'], voxel=.04)
        self.assertGreater(len(mesh.triangles), 100)
        result = cast(scene_for(mesh), k, pose, h, w, 1)
        self.assertTrue(np.isfinite(result['t_hit'][16:48, 16:48]).all())
        np.testing.assert_allclose(result['t_hit'][16:48, 16:48], 6, atol=.025)


if __name__ == '__main__':
    unittest.main()
