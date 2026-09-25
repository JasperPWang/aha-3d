"""Analytic rotation/timestamp checks without model loading or skinning."""
from pathlib import Path
import sys
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.motion.cache import resample_body


class Motion(unittest.TestCase):
    def clip(self, frames):
        rotation = Rotation.from_rotvec(np.column_stack([np.zeros((frames, 2)), np.arange(frames) / 30])).as_matrix()
        local = np.repeat(rotation[:, None], 22, axis=1)
        root = np.column_stack([np.arange(frames) / 30, np.zeros((frames, 2))])
        return local, root

    def test_slerp_preserves_duration_and_valid_rotations(self):
        local, root = self.clip(150)
        output, positions, times = resample_body(local, root, 30, 24)
        self.assertEqual(len(times), 120)
        np.testing.assert_allclose(positions[:, 0], times, atol=1e-6)
        expected = Rotation.from_rotvec(np.column_stack([np.zeros((len(times), 2)), times])).as_matrix()
        np.testing.assert_allclose(output[:, 0], expected, atol=1e-6)
        self.assertAlmostEqual(len(times) / 24, 5)

    def test_fractional_fps_uses_exact_output_timestamps(self):
        local, root = self.clip(450)
        output, positions, times = resample_body(local, root, 30, 30000 / 1001, frames=450)
        self.assertAlmostEqual(len(times) / (30000 / 1001), 15.015)
        np.testing.assert_allclose(np.diff(times), 1001 / 30000)
        np.testing.assert_allclose(output[-1], local[-1], atol=1e-6)

    def test_invalid_rotations_and_nonfinite_positions_fail(self):
        local, root = self.clip(5)
        broken = local.copy(); broken[0, 0, 0, 0] = -10
        with self.assertRaises(ValueError): resample_body(broken, root, 30, 24)
        root[0, 0] = np.nan
        with self.assertRaises(ValueError): resample_body(local, root, 30, 24)


if __name__ == '__main__': unittest.main()
