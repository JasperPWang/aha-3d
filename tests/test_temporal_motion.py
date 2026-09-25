"""Behavioral checks for temporal input refit."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.motion.temporal import refit, angle, diagnostics


def sample(i, degrees=0, side='right'):
    v = [np.sin(np.radians(degrees)), 0., np.cos(np.radians(degrees))]
    return dict(source_frame=i, frame=i, side=side, source_timestamp_seconds=i/30,
                target_time_seconds=i/30, upper_arm_direction=v, forearm_direction=v,
                facing_xz=[0., 1.], review_note='Synthetic test')


class TemporalTests(unittest.TestCase):
    def test_sparse_real_events_remain_unchanged(self):
        keys=[sample(i) for i in (327, 367, 408)]
        out, report=refit(keys)
        self.assertEqual(out,keys)
        self.assertTrue(all('insufficient' in x['status'] for x in report['records']))

    def test_isolated_moderate_error_reduced_without_mutation(self):
        support=[sample(i, 12 if i==6 else 0) for i in range(13)]
        original=deepcopy(support)
        out,_=refit([support[6]],support)
        self.assertLess(angle(out[0]['upper_arm_direction'],[0,0,1]),3)
        self.assertEqual(support,original)
        self.assertEqual(out[0]['facing_xz'], support[6]['facing_xz'])
        self.assertEqual(len(out),1)
        self.assertAlmostEqual(np.linalg.norm(out[0]['upper_arm_direction']),1)

    def test_smooth_turn_is_preserved(self):
        support=[sample(i,(i-6)*2) for i in range(13)]
        out,_=refit([support[6]],support)
        self.assertLess(angle(out[0]['upper_arm_direction'],[0,0,1]),.1)

    def test_limb_flip_is_not_blended(self):
        support=[sample(i,180 if i==6 else 0) for i in range(13)]
        out,report=refit([support[6]],support)
        self.assertEqual(out,[support[6]])
        self.assertIn('abrupt',report['records'][0]['fields']['upper_arm_direction']['status'])

    def test_gap_and_boundary_not_extrapolated(self):
        support=[sample(i) for i in (0,1,2,6,7,8)]
        out,report=refit([support[2]],support)
        self.assertIn('gap',report['records'][0]['status'])
        out,report=refit([support[0]],support)
        self.assertIn('insufficient',report['records'][0]['status'])

    def test_large_correction_requires_review(self):
        support=[sample(i,40 if i==6 else 0) for i in range(13)]
        out,report=refit([support[6]],support)
        self.assertEqual(out,[support[6]])
        self.assertIn('requires review',report['records'][0]['fields']['forearm_direction']['status'])

    def test_invalid_and_mismatched_support(self):
        keys=[sample(i) for i in range(13)]
        with self.assertRaises(ValueError): refit([keys[6]],keys+[keys[6]])
        with self.assertRaises(ValueError): refit([sample(6,2)],keys)
        with self.assertRaises(ValueError): refit(keys,window_seconds=float('nan'))
        with self.assertRaises(ValueError): diagnostics([sample(1),sample(1)])

    def test_side_separation_and_close_key_diagnostic(self):
        support=[sample(i) for i in range(13)]+[sample(i,30,'left') for i in range(13)]
        out,_=refit([support[6],support[19]],support)
        self.assertLess(angle(out[1]['upper_arm_direction'],sample(6,30)['upper_arm_direction']),.01)
        self.assertTrue(diagnostics([sample(1),sample(2,10)])[0]['close_keys'])

if __name__=='__main__': unittest.main()
