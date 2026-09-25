"""Guard against false quality claims in missing-body and contact diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from tools.gvhmr.motion_quality import diagnose, JOINT_NAMES, surface_contact_metrics


def observation_fixture():
    times = np.arange(60) / 10
    keypoints = np.ones((60, 17, 3))
    keypoints[..., :2] = [320, 240]
    return keypoints, times, [640, 480]


class MotionQualityTests(unittest.TestCase):
    def test_missing_legs_do_not_inherit_upper_body_support(self):
        kp, t, size = observation_fixture()
        kp[20:40, 11:, 2] = 0
        r = diagnose(kp, t, size)
        self.assertEqual(r['groups']['upper_body']['joint_coverage'], 1)
        lower = r['windows'][1]['groups']['lower_body']
        self.assertEqual(lower['supported_joint_samples'], 0)
        self.assertEqual(lower['support_status'], 'partial_or_unknown')
        gap = r['groups']['lower_body']['unsupported_intervals'][0]
        self.assertAlmostEqual(gap['duration_seconds'], 2)
        self.assertFalse(r['motion_accepted'])

    def test_confident_hallucinations_rejected_by_raw_detector_mask(self):
        kp, t, size = observation_fixture()
        detected = np.ones(len(t), bool)
        detected[20:40] = False
        r = diagnose(kp, t, size, detected=detected)
        self.assertEqual(r['windows'][1]['groups']['upper_body']['supported_joint_samples'], 0)
        self.assertEqual(r['evidence']['undetected_frames'], 20)

    def test_unknown_visibility_is_not_inferred_from_confidence(self):
        kp, t, size = observation_fixture()
        r = diagnose(kp, t, size)
        self.assertEqual(r['evidence']['visibility_evidence'], 'unknown')
        self.assertEqual(r['evidence']['raw_tracking_support'], 'unknown')
        mask = np.ones((len(t), 17), bool)
        mask[:, 9] = False
        r = diagnose(kp, t, size, reviewed_visible=mask)
        self.assertEqual(r['joints']['left_wrist']['supported_joint_samples'], 0)

    def test_nonfinite_and_outside_points_are_missing_not_clip_errors(self):
        kp, t, size = observation_fixture()
        kp[:, 9, 0] = np.nan
        kp[:, 10, 0] = 700
        r = diagnose(kp, t, size)
        self.assertEqual(r['groups']['wrists']['supported_joint_samples'], 0)
        json.dumps(r, allow_nan=False)

    def test_candidate_cannot_hide_error_by_emitting_nan_or_negative_depth(self):
        kp, t, size = observation_fixture()
        uv, depth = kp[..., :2].copy(), np.ones((len(t), 17))
        broken_uv, broken_depth = uv.copy(), depth.copy()
        broken_uv[20:30, 9] = np.nan
        broken_depth[30:40, 9] = -1
        r = diagnose(kp, t, size, predictions={'base': (uv, depth), 'broken': (broken_uv, broken_depth)})
        row = r['joints']['left_wrist']['predictions']
        self.assertEqual(row['base']['cohort_samples'], row['broken']['cohort_samples'])
        self.assertEqual(row['broken']['invalid_observed_predictions'], 20)
        self.assertEqual(row['broken']['review_flag'], 'invalid_prediction')

    def test_local_large_error_survives_good_whole_clip_median(self):
        kp, t, size = observation_fixture()
        uv = kp[..., :2].copy()
        uv[20:40, 9, 0] += 200
        r = diagnose(kp, t, size, predictions={'base': (uv, np.ones((len(t), 17)))})
        self.assertEqual(r['joints']['left_wrist']['predictions']['base']['residual_px']['median'], 0)
        row = r['windows'][1]['groups']['wrists']['predictions']['base']
        self.assertEqual(row['review_flag'], 'large_residual')
        self.assertEqual(row['residual_px']['p90'], 200)

    def test_invalid_timing_and_masks_rejected(self):
        kp, t, size = observation_fixture()
        with self.assertRaises(ValueError):
            diagnose(kp, t[::-1], size)
        with self.assertRaises(ValueError):
            diagnose(kp, t, size, detected=np.full(len(t), np.nan))
        with self.assertRaisesRegex(ValueError, 'uniform full-frame'):
            diagnose(kp[:4], [0, .1, 10, 10.1], size)

    def test_short_wrist_spike_is_flagged_even_when_p90_is_zero(self):
        kp, t, size = observation_fixture()
        uv = kp[..., :2].copy()
        uv[25, 9, 0] += 200
        r = diagnose(kp, t, size, predictions={'base': (uv, np.ones((len(t), 17)))})
        row = r['joints']['left_wrist']['predictions']['base']
        self.assertEqual(row['residual_px']['p90'], 0)
        self.assertEqual(row['review_flag'], 'large_residual')
        self.assertEqual(row['excessive_residual_joint_samples'], 1)
        self.assertAlmostEqual(row['flagged_intervals'][0]['start_seconds'], 2.5)

    def test_cli_records_hashes_and_rejects_time_or_raster_mismatch(self):
        kp, t, size = observation_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            observations = folder / 'observations.npz'
            prediction = folder / 'candidate.npz'
            np.savez(observations, keypoints=kp, time_seconds=t, image_size=size, joint_names=JOINT_NAMES)
            def save(time=t, raster=size):
                np.savez(prediction, uv=kp[..., :2], depth=np.ones((len(t), 17)),
                         time_seconds=time, image_size=raster, joint_names=JOINT_NAMES)
            save()
            script = Path(__file__).resolve().parents[1] / 'tools/gvhmr/motion_quality.py'
            cmd = [sys.executable, str(script), '--observations', str(observations),
                   '--prediction', str(prediction), '--output', str(folder / 'report.json')]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((folder / 'report.json').read_text())
            self.assertEqual(len(report['provenance']['observations']['sha256']), 64)
            save(time=t + .1)
            bad_time = subprocess.run(cmd[:-1] + [str(folder / 'bad_time.json')], capture_output=True, text=True)
            self.assertNotEqual(bad_time.returncode, 0)
            self.assertIn('Prediction timestamps differ', bad_time.stderr)
            self.assertFalse((folder / 'bad_time.json').exists())
            save(raster=[1280, 720])
            bad_raster = subprocess.run(cmd[:-1] + [str(folder / 'bad_raster.json')], capture_output=True, text=True)
            self.assertNotEqual(bad_raster.returncode, 0)
            self.assertIn('full-image rasters differ', bad_raster.stderr)
            self.assertFalse((folder / 'bad_raster.json').exists())


class SurfaceContactTests(unittest.TestCase):
    def setup_geometry(self):
        t = np.arange(10) / 10
        d = np.zeros((10, 1, 4))
        areas = np.full((1, 4), .005)
        p = np.zeros((10, 1, 4, 3))
        contact = np.ones((10, 1), bool)
        return d, areas, p, t, contact

    def test_float_penetration_and_area_remain_separate(self):
        d, areas, p, t, contact = self.setup_geometry()
        d[:3] = .06
        d[3:6] = -.03
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertAlmostEqual(r['gap_m']['maximum'], .06)
        self.assertAlmostEqual(r['penetration_m_all_supplied_frames']['maximum'], .03)
        self.assertAlmostEqual(r['near_contact_area_m2']['maximum'], .02)
        self.assertEqual(r['near_contact_area_m2']['median'], 0)

    def test_stationary_contact_speed_uses_support_frame(self):
        d, areas, p, t, contact = self.setup_geometry()
        # An object and hand translating together have constant object-local p.
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertEqual(r['stationary_relative_surface_speed_m_s']['maximum'], 0)
        p[:, 0, :, 0] = .1 * t[:, None]
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertAlmostEqual(r['stationary_relative_surface_speed_m_s']['p90'], .1)

    def test_rotation_about_fixed_centroid_is_not_zero_slip(self):
        d, areas, p, t, contact = self.setup_geometry()
        p[:, 0, 0, 0] = np.cos(t)
        p[:, 0, 0, 1] = np.sin(t)
        p[:, 0, 1] = -p[:, 0, 0]
        np.testing.assert_allclose(p.mean(2), 0)
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertGreater(r['stationary_relative_surface_speed_m_s']['p90'], .49)

    def test_no_velocity_across_unknown_interval_and_no_empty_pass(self):
        d, areas, p, t, contact = self.setup_geometry()
        contact[3:7] = False
        p[5:, 0, :, 0] = 1
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertEqual(r['stationary_pairs'], 4)
        self.assertEqual(r['stationary_relative_surface_speed_m_s']['maximum'], 0)
        contact[:] = False
        r = surface_contact_metrics(d, areas, p, t, contact, contact)['patches'][0]
        self.assertIsNone(r['gap_m']['p90'])
        self.assertEqual(r['contact_status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
