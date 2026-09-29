"""Pi3X processed-grid intrinsics converted for GVHMR's full-image K_fullimg."""
import unittest

import numpy as np

from tools.gvhmr import camera_tracks as camera


class FullImageIntrinsicsTest(unittest.TestCase):
    def test_centred_principal_point_matches_upstream_convention_and_scales_focal(self):
        K = np.array([[[282.6, 0, 335.5], [0, 281.3, 188.5], [0, 0, 1]]] * 2)
        out = camera.fullimg_intrinsics(K, [0., 1.], [0., .5, 1.], [672, 378], [1280, 720])
        self.assertEqual(out.shape, (3, 3, 3))
        np.testing.assert_allclose(out[0, :2, 2], [640., 360.], atol=1e-9)
        np.testing.assert_allclose(out[0, 0, 0], 282.6 * 1280 / 672)
        np.testing.assert_allclose(out[0, 1, 1], 281.3 * 720 / 378)
        np.testing.assert_allclose(out[:, 2], [[0, 0, 1]] * 3)

    def test_linear_interpolation_between_observations(self):
        K = np.array([[[100, 0, 50], [0, 100, 40], [0, 0, 1]], [[200, 0, 50], [0, 200, 40], [0, 0, 1]]], float)
        out = camera.fullimg_intrinsics(K, [0., 2.], [1.], [100, 80], [100, 80])
        np.testing.assert_allclose(out[0, 0, 0], 150.)

    def test_extrapolation_and_bad_rasters_are_rejected(self):
        K = np.array([[[100, 0, 50], [0, 100, 40], [0, 0, 1]]] * 2, float)
        with self.assertRaisesRegex(ValueError, 'extrapolation'):
            camera.fullimg_intrinsics(K, [0., 1.], [0., 1.5], [100, 80], [200, 160])
        with self.assertRaises(ValueError):
            camera.fullimg_intrinsics(K, [0., 1.], [0., 1.], [0, 80], [200, 160])


if __name__ == '__main__':
    unittest.main()
