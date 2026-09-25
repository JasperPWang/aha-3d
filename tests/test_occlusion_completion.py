import unittest
import numpy as np
from aha3d.motion.endpoint_completion import propose_gaps, transition_report, splice_endpoint_motion


class OcclusionTests(unittest.TestCase):
    def evidence(self, n=30):
        kp = np.ones((n, 17, 3)); kp[..., :2] = 20
        return kp, np.ones(n, bool)

    def test_three_frame_windows_and_exact_threshold(self):
        kp, active = self.evidence()
        kp[10:15, 4:, 2] = 0  # Four remain: low evidence.
        kp[18, 5:, 2] = 0  # Five remain: valid.
        result = propose_gaps(kp, active)
        self.assertEqual(len(result['gaps']), 1)
        self.assertEqual(result['gaps'][0]['constraints'], [7, 8, 9, 15, 16, 17])
        self.assertEqual(result['gaps'][0]['status'], 'ready')

    def test_two_frame_fallback_no_extrapolation_no_exit_generation(self):
        kp, active = self.evidence()
        kp[2:7, :, 2] = 0; kp[25:, :, 2] = 0; active[28:] = False
        result = propose_gaps(kp, active)
        self.assertEqual(result['gaps'][0]['left'], 2)
        self.assertEqual(result['gaps'][0]['status'], 'ready')
        self.assertEqual(result['gaps'][1]['end'], 28)
        self.assertEqual(result['gaps'][1]['status'], 'unresolved_missing_reliable_context')
        self.assertFalse(any(result['low_evidence'][28:]))

    def test_mask_and_nonfinite_predictions_do_not_count_as_visible(self):
        kp, active = self.evidence()
        support = np.ones((30, 17), bool); support[10:12] = False
        kp[15:17] = np.nan
        result = propose_gaps(kp, active, mask_support=support)
        self.assertEqual(result['visible_counts'][10:12], [0, 0])
        self.assertEqual(result['visible_counts'][15:17], [0, 0])

    def test_seam_speed_jump_rejected_even_when_positions_finite(self):
        local = np.broadcast_to(np.eye(3), (30, 22, 3, 3)).copy()
        roots = np.zeros((30, 3)); rest = np.zeros((22, 3))
        gap = dict(start=10, end=15)
        self.assertTrue(transition_report(local, roots, rest, gap)['passed'])
        roots[10:15, 0] = 1
        self.assertFalse(transition_report(local, roots, rest, gap)['passed'])

    def test_splice_does_not_read_rejected_gvhmr_gap(self):
        local = np.broadcast_to(np.eye(3), (30, 22, 3, 3)).copy()
        roots = np.zeros((30, 3)); roots[:, 0] = np.arange(30)/30
        gap = dict(start=10, end=20, constraints=[7, 8, 9, 20, 21, 22])
        generated_local = local[10:20].copy(); generated_root = roots[10:20]+[0, .1, 0]
        first = splice_endpoint_motion(local, roots, gap, generated_local, generated_root)
        roots[10:20] = np.nan; local[10:20] = np.nan
        second = splice_endpoint_motion(local, roots, gap, generated_local, generated_root)
        for a, b in zip(first, second):
            np.testing.assert_array_equal(a, b)
        np.testing.assert_allclose(first[0].swapaxes(-1, -2)@first[0], np.broadcast_to(np.eye(3), first[0].shape))


if __name__ == '__main__':
    unittest.main()
