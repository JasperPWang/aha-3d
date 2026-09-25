"""Frozen-input and rejected-output contracts; no learned model is executed."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from aha3d.motion.completion import JOINT_NAMES, PARENTS, CompletionSettings, finalize_candidate
from tools.kimodo.batch_experiments import (
    PROTOCOL, finalize_with_diagnostic, native_export, preservation_merge,
    provenance, validate_case, validate_manifest,
)


def fixture():
    T = 36
    offsets = np.array([[0, .9, 0], [.1, -.05, 0], [-.1, -.05, 0], [0, .1, 0],
        [0, -.4, 0], [0, -.4, 0], [0, .1, 0], [0, -.4, 0], [0, -.4, 0],
        [0, .1, 0], [0, 0, .12], [0, 0, .12], [0, .12, 0], [.1, .1, 0],
        [-.1, .1, 0], [0, .15, 0], [.12, 0, 0], [-.12, 0, 0], [.26, 0, 0],
        [-.26, 0, 0], [.22, 0, 0], [-.22, 0, 0]])
    rest = offsets.copy()
    for j in range(1, 22):
        rest[j] += rest[PARENTS[j]]
    local = np.tile(np.eye(3), (T, 22, 1, 1))
    root = np.column_stack([np.arange(T) * .01, np.full(T, .93), np.zeros(T)])
    source = dict(local_rot_mats=local, root_positions=root, rest_joints=rest,
        joint_names=np.asarray(JOINT_NAMES), time_seconds=np.arange(T) / 30,
        betas=np.zeros(10), source_to_kimodo=np.eye(4),
        source_video_sha256=np.asarray('a' * 64), source_actor_id=np.asarray('reviewed_actor'))
    prefix = 'source_gvhmr__smpl_params_global__'
    source.update({prefix + 'body_pose': np.zeros((T, 63), np.float32),
        prefix + 'global_orient': np.zeros((T, 3), np.float32),
        prefix + 'transl': (root - rest[0]).astype(np.float32),
        prefix + 'betas': np.zeros((T, 10), np.float32)})
    visible = np.ones((T, 22), bool)
    visible[:, [1, 2, 4, 5, 7, 8, 10, 11]] = False
    observations = dict(visible_joint_mask=visible, constraint_joint_mask=visible.copy(),
        visibility_state=visible.astype(np.int8), joint_names=np.asarray(JOINT_NAMES),
        time_seconds=source['time_seconds'].copy(), visibility_evidence=np.asarray('Unit test reviewed visibility fixture'),
        source_video_sha256=source['source_video_sha256'].copy(), source_actor_id=source['source_actor_id'].copy())
    interval = [4, 32]
    candidate = local[4:32].copy()
    candidate[:, 4] = Rotation.from_rotvec([.04, 0, 0]).as_matrix()
    return source, observations, interval, candidate


class MergeTests(unittest.TestCase):
    def test_diagnostic_merge_is_exactly_existing_accepted_merge(self):
        s, o, interval, c = fixture()
        mask = o['constraint_joint_mask']
        exact, report = finalize_candidate(s, mask, interval, c, s['root_positions'][4:32], CompletionSettings())
        self.assertTrue(report['parameter_candidate_accepted'])
        merged = preservation_merge(s, mask, interval, c, CompletionSettings())
        for k in ('local_rot_mats', 'root_positions', 'generated_joint_mask', 'protected_joint_mask',
                  'smpl_params_global__body_pose', 'smpl_params_global__transl'):
            np.testing.assert_array_equal(exact[k], merged[k])

    def test_rejected_raw_root_still_exports_preserved_full_duration_diagnostic(self):
        s, o, interval, c = fixture()
        roots = s['root_positions'][4:32].copy() + [.3, 0, 0]
        result, report = finalize_with_diagnostic(s, o, o['constraint_joint_mask'], interval, c, roots, CompletionSettings())
        self.assertFalse(report['parameter_candidate_accepted'])
        self.assertIn('contradicts dense', report['rejection'])
        self.assertEqual(str(result['candidate_status']), 'REJECTED_DIAGNOSTIC_ONLY')
        np.testing.assert_array_equal(result['root_positions'], s['root_positions'])
        np.testing.assert_array_equal(result['local_rot_mats'][o['visible_joint_mask']], s['local_rot_mats'][o['visible_joint_mask']])
        self.assertGreater(result['generated_joint_mask'].sum(), 0)
        self.assertEqual(report['diagnostic_preservation']['visible_fk_max_error_m'], 0)

    def test_rejected_distal_transition_is_retained_not_adopted(self):
        s, o, interval, c = fixture()
        c[:, 4] = Rotation.from_rotvec([.25, 0, 0]).as_matrix()
        result, report = finalize_with_diagnostic(s, o, o['constraint_joint_mask'], interval, c,
            s['root_positions'][4:32], CompletionSettings())
        self.assertFalse(report['parameter_candidate_accepted'])
        self.assertFalse(report['temporal_gates']['boundary_distal_kinematics']['passed'])
        self.assertTrue(report['temporal_gates']['local_rotation_step']['passed'])
        self.assertGreater(result['generated_joint_mask'].sum(), 0)

    def test_visible_reappearance_tapers_and_preserves_source_axis_angles(self):
        s, o, interval, c = fixture()
        o['constraint_joint_mask'][17:20, 4] = True
        merged = preservation_merge(s, o['constraint_joint_mask'], interval, c, CompletionSettings())
        np.testing.assert_array_equal(merged['local_rot_mats'][17:20, 4], s['local_rot_mats'][17:20, 4])
        np.testing.assert_array_equal(merged['smpl_params_global__body_pose'][17:20], s['source_gvhmr__smpl_params_global__body_pose'][17:20])
        np.testing.assert_array_equal(merged['local_rot_mats'][:5], s['local_rot_mats'][:5])
        np.testing.assert_array_equal(merged['local_rot_mats'][31:], s['local_rot_mats'][31:])

    def test_raw_pelvis_translation_export_keeps_template_pelvis_offset(self):
        s, o, interval, c = fixture()
        roots = s['root_positions'].copy(); roots[6:9, 1] += .1
        raw = native_export(s, s['local_rot_mats'], roots, np.zeros((36, 22), bool))
        np.testing.assert_allclose(raw['smpl_params_global__transl'][6:9], roots[6:9] - s['rest_joints'][0], atol=1e-7)
        np.testing.assert_array_equal(raw['smpl_params_global__transl'][:6], s['source_gvhmr__smpl_params_global__transl'][:6])

    def test_source_roundtrip_is_zero_edit_not_generated_success(self):
        s, o, interval, _ = fixture()
        result, report = finalize_with_diagnostic(s, o, o['constraint_joint_mask'], interval,
            s['local_rot_mats'][4:32], s['root_positions'][4:32], CompletionSettings())
        self.assertFalse(report['parameter_candidate_accepted'])
        self.assertIn('no effective generated motion', report['rejection'])
        self.assertFalse(result['generated_joint_mask'].any())


class FrozenInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.s, self.o, interval, _ = fixture()
        self.case = dict(id='clip_fixture', kind='reviewed_hidden_part_completion', interval=interval,
                         prompt='A person walks slowly indoors with relaxed legs.')
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        np.savez_compressed(self.path / 'source.npz', **self.s)
        np.savez_compressed(self.path / 'visibility.npz', **self.o)
        self.case.update(source=provenance(self.path / 'source.npz'), visibility=provenance(self.path / 'visibility.npz'))

    def test_checked_valid_case_reports_real_editable_names(self):
        report = validate_case(self.case)[3]
        self.assertIn('left_knee', report['editable_joint_names'])
        self.assertNotIn('head', report['editable_joint_names'])

    def test_input_mutation_after_freeze_is_rejected(self):
        self.s['betas'][0] = 1
        np.savez_compressed(self.path / 'source.npz', **self.s)
        with self.assertRaisesRegex(ValueError, 'Frozen input hash mismatch'):
            validate_case(self.case)

    def test_unknown_joint_cannot_be_freed_to_force_completion(self):
        self.o['visibility_state'][10, 4] = -1; self.save()
        with self.assertRaisesRegex(ValueError, 'reviewed hidden'):
            validate_case(self.case)

    def test_complete_absence_cannot_use_only_conservative_constraints(self):
        self.o['visible_joint_mask'][10] = False
        self.o['visibility_state'][10] = 0
        self.save()
        with self.assertRaisesRegex(ValueError, 'actual visible-body evidence'):
            validate_case(self.case)

    def test_source_actor_and_timestamp_mismatches_rejected(self):
        self.o['source_actor_id'] = np.asarray('other_actor'); self.save()
        with self.assertRaisesRegex(ValueError, 'different source video or actor'):
            validate_case(self.case)
        self.o['source_actor_id'] = self.s['source_actor_id']; self.o['time_seconds'][10] += 1e-10; self.save()
        with self.assertRaisesRegex(ValueError, 'PTS must match exactly'):
            validate_case(self.case)

    def test_text_and_medium_strength_are_mandatory(self):
        self.case['prompt'] = ' '
        with self.assertRaisesRegex(ValueError, 'Nonempty'):
            validate_case(self.case)
        bad = deepcopy(PROTOCOL); bad['variants']['medium_noise_24'] = 3
        with self.assertRaisesRegex(ValueError, 'exact reviewed'):
            validate_manifest(dict(schema_version=1, protocol=bad, cases=[self.case]))

    def test_deliberate_visible_leg_replacement_is_explicit_and_upper_protected(self):
        from tools.kimodo.batch_experiments import REPLACEMENT_AUTHORIZATION, LOWER_BODY_IDS
        self.o['visible_joint_mask'][:] = True
        self.o['visibility_state'][:] = 1
        self.o['constraint_joint_mask'][:] = True
        self.save()
        self.case.update(kind='deliberate_lower_body_replacement',
            editing_authorization=REPLACEMENT_AUTHORIZATION,
            editing_reason='Explicit user test of unreliable lower-body motion', released_joint_ids=list(LOWER_BODY_IDS))
        _, actual, mask, report = validate_case(self.case)
        self.assertTrue(actual['visible_joint_mask'].all())
        self.assertTrue(mask[4:32, [0, 3, 6, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]].all())
        self.assertFalse(mask[4:32, LOWER_BODY_IDS].any())
        self.assertGreater(report['constraint_review']['actual_visible_released_joint_samples'], 0)
        self.case['kind'] = 'reviewed_hidden_part_completion'
        with self.assertRaisesRegex(ValueError, 'no editable hidden'):
            validate_case(self.case)

    def test_replacement_cannot_release_upper_body_or_omit_authorization(self):
        from tools.kimodo.batch_experiments import REPLACEMENT_AUTHORIZATION
        self.case.update(kind='deliberate_lower_body_replacement', editing_reason='Reviewed user request', released_joint_ids=[4])
        with self.assertRaisesRegex(ValueError, 'explicit authorization'):
            validate_case(self.case)
        self.case['editing_authorization'] = REPLACEMENT_AUTHORIZATION
        self.case['released_joint_ids'] = [4, 20]
        with self.assertRaisesRegex(ValueError, 'lower-body joints'):
            validate_case(self.case)

    def test_unobserved_replacement_requires_explicit_estimate_scope_and_is_not_completion(self):
        from tools.kimodo.batch_experiments import REPLACEMENT_AUTHORIZATION
        self.o['visible_joint_mask'][10] = False
        self.o['visibility_state'][10] = -1
        self.save()
        self.case.update(kind='deliberate_lower_body_replacement', editing_reason='Explicit user experiment',
            editing_authorization=REPLACEMENT_AUTHORIZATION, released_joint_ids=[4, 5, 7, 8, 10, 11])
        with self.assertRaisesRegex(ValueError, 'separate explicit declaration'):
            validate_case(self.case)
        self.case.update(allow_unobserved_source_estimates=True,
            unobserved_constraints_scope='At frame10 source upper body is estimated and unverified; no visibility claim')
        report = validate_case(self.case)[3]
        self.assertEqual(report['constraint_review']['frames_without_positive_upper_visibility_annotation'], 1)
        self.case['kind'] = 'reviewed_hidden_part_completion'
        with self.assertRaises(ValueError):
            validate_case(self.case)

    def test_contact_strength_cannot_silently_replace_medium_with_old_low_trial(self):
        from tools.kimodo.batch_experiments import validate_contact_case
        with self.assertRaisesRegex(ValueError, 'medium24/50'):
            validate_contact_case(dict(id='clip39_medium', warm_start_step=8, steps=50, seed=7, blend_frames=18))


if __name__ == '__main__':
    unittest.main()
