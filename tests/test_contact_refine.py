"""Geometry invariants for reusable contact refinement (CPU, no model assets)."""
import unittest
import tempfile
import os
import subprocess
from pathlib import Path
import numpy as np
from tools.gvhmr.contact_refine import smooth_targets, contact_mask, fixed_floor_shift, acceptance, preserve_native_actor


class NativePlacementTests(unittest.TestCase):
    def test_wrapper_requires_explicit_contact_opt_in(self):
        wrapper = Path(__file__).resolve().parents[1]/'tools/gvhmr/run_contact.sh'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root/'python'
            python.write_text('#!/bin/bash\nif [[ "$1" == -c ]]; then echo 0; elif [[ "$1" == */contact_refine.py ]]; then printf "%s\\n" "$@"; fi\n')
            python.chmod(0o755)
            for extra in ([], ['--refine-contact']):
                result = subprocess.run(['bash', str(wrapper), '--manifest', str(root/'input.json'),
                                         '--models', str(root/'models'), '--output', str(root/'out'), *extra],
                                        capture_output=True, text=True,
                                        env={**os.environ, 'CONTACT_PYTHON':str(python)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('contact_refine.py', result.stdout)
                self.assertEqual('--refine-contact' in result.stdout.splitlines(), bool(extra))

    def test_only_selected_actor_moves_by_one_constant_offset(self):
        cache = dict(vertices=np.random.default_rng(4).normal(size=(12, 8, 3)),
                     joints=np.random.default_rng(5).normal(size=(12, 22, 3)),
                     time_seconds=np.arange(12)/30., fps=30., faces=np.array([[0,1,2]]),
                     vertex_ids=np.arange(8))
        params = dict(body_pose=np.ones((12,63)), transl=np.ones((12,3)))
        alignment = dict(rotation=np.eye(3), translation=[1.,2.,3.])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source.npz'; np.savez(source, **cache)
            for actor_id, shift in [('lifted', .2), ('untouched', 0.)]:
                out = root/actor_id; out.mkdir()
                actor = dict(id=actor_id, cache=str(source))
                if shift: actor['vertical_translation_m'] = shift
                report = preserve_native_actor(actor, cache, out, params, alignment, {}, 0.)
                self.assertFalse(report['ik_applied'])
                self.assertFalse(report['contact_validated'])
                with np.load(out/'body_room.npz') as result:
                    for key in ('vertices', 'joints'):
                        np.testing.assert_array_equal(result[key][..., :2], cache[key][..., :2])
                        np.testing.assert_allclose(result[key][..., 2], cache[key][..., 2]+shift)
                        np.testing.assert_allclose(np.diff(result[key], axis=0), np.diff(cache[key], axis=0), atol=1e-12)
                    for key in ('fps', 'time_seconds', 'faces', 'vertex_ids'):
                        np.testing.assert_array_equal(result[key], cache[key])
                with np.load(out/'refined_parameters.npz') as result:
                    np.testing.assert_array_equal(result['refined_body_pose'], params['body_pose'])
                    np.testing.assert_array_equal(result['transl'], params['transl'])
                    np.testing.assert_allclose(result['translation'], [1.,2.,3.+shift])
                if not shift: self.assertEqual(source.read_bytes(), (out/'body_room.npz').read_bytes())
            with np.load(source) as original:
                np.testing.assert_array_equal(original['vertices'], cache['vertices'])

    def test_framewise_or_nonfinite_offsets_are_rejected(self):
        for value in ([0., .1], float('nan'), float('inf'), True, '0.1'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite scalar'):
                preserve_native_actor(dict(vertical_translation_m=value), {}, None, {}, {}, {}, 0.)


class TemporalTargetTests(unittest.TestCase):
    def test_constant_target_stays_constant(self):
        targets = np.tile([.1, -.4, .015], (40, 1))
        result = smooth_targets(targets, 10.)
        np.testing.assert_allclose(result, targets, atol=1e-9)

    def test_affine_trajectory_is_not_distorted(self):
        t = np.arange(30, dtype=float)
        targets = np.column_stack((t, -2*t+.4, .1*t))
        np.testing.assert_allclose(smooth_targets(targets, 100.), targets, atol=1e-8)

    def test_zero_strength_preserves_targets(self):
        targets = np.random.default_rng(7).normal(size=(40, 3))
        np.testing.assert_allclose(smooth_targets(targets, 0.), targets, atol=1e-9)

    def test_smoothing_reduces_acceleration_without_nonfinite_edges(self):
        t = np.linspace(0, 1, 60)
        targets = np.column_stack((t, .1*np.sin(30*t), np.zeros(60)))
        result = smooth_targets(targets, 10.)
        self.assertEqual(result.shape, targets.shape)
        self.assertTrue(np.isfinite(result).all())
        self.assertLess(np.linalg.norm(np.diff(result, n=2, axis=0)), np.linalg.norm(np.diff(targets, n=2, axis=0)))


class ContactDetectionTests(unittest.TestCase):
    def test_swinging_or_invalid_foot_cannot_be_support(self):
        heights = np.zeros((12, 2))
        heights[6:, 1] = .2
        speeds = np.zeros((12, 2))
        speeds[:6, 1] = .8
        valid = np.ones(12, dtype=bool)
        valid[5] = False
        mask = contact_mask(heights, speeds, valid)
        self.assertEqual(mask.shape, heights.shape)
        self.assertFalse(mask[5].any())
        self.assertFalse(mask[:, 1].any())
        self.assertTrue(mask[:5, 0].all())
        self.assertTrue(mask[6:, 0].all())

    def test_short_contact_is_removed(self):
        heights = np.ones((12, 2))
        heights[3:5, 0] = 0.
        heights[6:10, 1] = 0.
        mask = contact_mask(heights, np.zeros_like(heights), np.ones(12, bool), min_frames=3)
        self.assertFalse(mask[:, 0].any())
        self.assertTrue(mask[6:10, 1].all())


class FixedFloorTests(unittest.TestCase):
    def test_large_constant_below_floor_offset_is_fixed_once(self):
        heights = np.full((30, 2), -.2)
        shift = fixed_floor_shift(heights, np.ones(30, bool), 0.)
        self.assertAlmostEqual(shift, .205, places=6)

    def test_already_grounded_sequence_is_unchanged(self):
        heights = np.full((30, 2), .005)
        self.assertEqual(fixed_floor_shift(heights, np.ones(30, bool), 0.), 0.)

    def test_invalid_frames_do_not_determine_ground(self):
        heights = np.full((30, 2), .005)
        heights[:10] = -1.
        valid = np.ones(30, bool)
        valid[:10] = False
        self.assertEqual(fixed_floor_shift(heights, valid, 0.), 0.)


    def test_unreviewable_large_offset_is_rejected_not_clamped(self):
        with self.assertRaises(ValueError):
            fixed_floor_shift(np.full((30, 2), -2.), np.ones(30, bool), 0.)

    def test_no_valid_grounded_frames_is_rejected(self):
        with self.assertRaises(ValueError):
            fixed_floor_shift(np.zeros((30, 2)), np.zeros(30, bool), 0.)


class AcceptanceTests(unittest.TestCase):
    def test_horizontal_root_edit_is_rejected(self):
        metrics = dict(penetration_depth_max_m=0., contact_speed_p90_m_s=.01, foot_acceleration_p90_m_s2=.1)
        ok, reasons = acceptance(metrics, metrics, .1)
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_clear_contact_regressions_are_rejected(self):
        before = dict(penetration_depth_max_m=.001, contact_speed_p90_m_s=.01, foot_acceleration_p90_m_s2=.1)
        after = dict(penetration_depth_max_m=.5, contact_speed_p90_m_s=1., foot_acceleration_p90_m_s2=10.)
        ok, reasons = acceptance(before, after, 0.)
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_nonfinite_result_is_rejected(self):
        before = dict(penetration_depth_max_m=0., contact_speed_p90_m_s=.01, foot_acceleration_p90_m_s2=.1)
        after = dict(before, contact_speed_p90_m_s=float('nan'))
        ok, reasons = acceptance(before, after, 0.)
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_identical_safe_result_is_accepted(self):
        metrics = dict(penetration_depth_max_m=0., contact_speed_p90_m_s=.01, foot_acceleration_p90_m_s2=.1)
        ok, reasons = acceptance(metrics, metrics, 0.)
        self.assertTrue(ok, reasons)


if __name__ == '__main__':
    unittest.main()
