import copy
import unittest

import numpy as np

from tools.gvhmr.root_constraints import fit_smooth_residual


class ContactOnlyDepthWeightTests(unittest.TestCase):
    def fixture(self):
        times = np.arange(61) / 30.
        roots = np.tile([0., 0., 1.], (len(times), 1))
        body = dict(time_seconds=times, joints=roots[:, None],
                    vertices=roots[:, None] + [[[0., 0., -.9]]])
        ids = np.array([0, 10, 20, 30, 40, 50, 60])
        observations = dict(frame_indices=ids, root_targets=roots[ids].copy(),
                            weights=np.ones(len(ids)), valid=np.ones(len(ids), bool),
                            train=np.ones(len(ids), bool))
        event = np.zeros(len(times), bool)
        event[10:51] = True
        contact = dict(name='floor', kind='vertices', indices=np.array([0]),
                       normal=np.array([0., 0., 1.]), plane_offset=0.,
                       train_ids=np.array([10, 30, 50]), event_mask=event,
                       vertices=np.array([[-100., -100., 0.], [100., -100., 0.],
                                          [100., 100., 0.], [-100., 100., 0.]]),
                       faces=np.array([[0, 1, 2], [0, 2, 3]]),
                       weight=10., target_gap_m=.002)
        return body, observations, contact

    def test_conflicting_depth_changes_solution_only_when_enabled(self):
        body, observations, contact = self.fixture()
        conflicting = copy.deepcopy(observations)
        conflicting['root_targets'] += [3., 0., 2.]
        original, report = fit_smooth_residual(body, observations, contacts=[contact], depth_weight=0.)
        changed, _ = fit_smooth_residual(body, conflicting, contacts=[contact], depth_weight=0.)
        np.testing.assert_array_equal(original, changed)
        self.assertLess(abs(original[30, 2] + .098), .001)
        self.assertEqual(report['training_depth_frames'], [])
        self.assertEqual(report['diagnostic_depth_frames'], observations['frame_indices'].tolist())
        self.assertEqual(report['depth_weight'], 0.)
        enabled, _ = fit_smooth_residual(body, observations, contacts=[contact], depth_weight=1.)
        enabled_conflict, _ = fit_smooth_residual(body, conflicting, contacts=[contact], depth_weight=1.)
        self.assertGreater(np.linalg.norm(enabled_conflict - enabled, axis=1).max(), 1.)

    def test_disabled_depth_does_not_extend_spline_support(self):
        body, observations, contact = self.fixture()
        offsets, report = fit_smooth_residual(body, observations, contacts=[contact], depth_weight=0.)
        np.testing.assert_allclose([report['knots_seconds'][0], report['knots_seconds'][-1]],
                                   body['time_seconds'][[10, 50]])
        np.testing.assert_allclose(offsets[:10], np.tile(offsets[10], (10, 1)))
        np.testing.assert_allclose(offsets[51:], np.tile(offsets[50], (10, 1)))

    def test_default_retains_depth_fit(self):
        body, observations, contact = self.fixture()
        default, report = fit_smooth_residual(body, observations, contacts=[contact])
        explicit, _ = fit_smooth_residual(body, observations, contacts=[contact], depth_weight=1.)
        np.testing.assert_array_equal(default, explicit)
        self.assertEqual(report['training_depth_frames'], observations['frame_indices'].tolist())

    def test_invalid_weight_and_missing_contact_support_fail(self):
        body, observations, contact = self.fixture()
        for weight in [-1., float('nan'), float('inf')]:
            with self.subTest(weight=weight), self.assertRaisesRegex(ValueError, 'depth_weight'):
                fit_smooth_residual(body, observations, contacts=[contact], depth_weight=weight)
        with self.assertRaisesRegex(ValueError, 'Two distinct training times'):
            fit_smooth_residual(body, observations, depth_weight=0.)


if __name__ == '__main__':
    unittest.main()
