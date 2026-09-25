"""Dense-observation and FK preservation contracts; no model weights are required."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from aha3d.motion.completion import (
    CompletionRejected, CompletionSettings, FEATURE_SLICES, JOINT_NAMES, PARENTS,
    ancestor_protection, boundary_kinematics_report, complete_motion, finalize_candidate, forward_kinematics,
    prepare_conditions, rotation_error, source_from_gvhmr, validate_source,
)


def fixture():
    frames = 36
    offsets = np.array([
        [0, .9, 0], [.1, -.05, 0], [-.1, -.05, 0], [0, .1, 0],
        [0, -.4, 0], [0, -.4, 0], [0, .1, 0], [0, -.4, 0], [0, -.4, 0],
        [0, .1, 0], [0, 0, .12], [0, 0, .12], [0, .12, 0], [.1, .1, 0],
        [-.1, .1, 0], [0, .15, 0], [.12, 0, 0], [-.12, 0, 0], [.26, 0, 0],
        [-.26, 0, 0], [.22, 0, 0], [-.22, 0, 0],
    ])
    rest = offsets.copy()
    for joint in range(1, 22):
        rest[joint] += rest[PARENTS[joint]]
    local = np.broadcast_to(np.eye(3), (frames, 22, 3, 3)).copy()
    local[:, 0] = Rotation.from_rotvec(np.column_stack([np.zeros(frames), np.arange(frames) * .01, np.zeros(frames)])).as_matrix()
    local[:, 17] = Rotation.from_rotvec(np.column_stack([np.zeros(frames), np.zeros(frames), .15 * np.sin(np.arange(frames) / 8)])).as_matrix()
    roots = np.column_stack([np.arange(frames) * .01, np.full(frames, .93), np.zeros(frames)])
    basis = np.eye(4)
    basis[:3, :3] = Rotation.from_rotvec([0, .43, 0]).as_matrix()
    basis[:3, 3] = [2., .03, -3.]
    source = dict(local_rot_mats=local, root_positions=roots, rest_joints=rest,
                  joint_names=np.array(JOINT_NAMES), time_seconds=np.arange(frames) / 30.,
                  betas=np.zeros(10), source_to_kimodo=basis, original_metadata=np.array('keep'))
    visible = np.ones((frames, 22), bool)
    visible[:, [1, 2, 4, 5, 7, 8, 10, 11]] = False
    return source, visible, [4, 32]


def leg_candidate(source, interval):
    start, end = interval
    local = source['local_rot_mats'][start:end].copy()
    # This fixture isolates preservation, not a fast transition. Larger constant
    # edits have a dedicated distal-return rejection regression below.
    local[:, 4] = Rotation.from_rotvec([.04, 0, 0]).as_matrix()
    return local, source['root_positions'][start:end].copy()


class CompletionGeometryTests(unittest.TestCase):
    def test_visible_wrist_protects_every_ancestor_but_not_hidden_legs(self):
        visible = np.zeros((4, 22), bool)
        visible[:, 21] = True
        protected = ancestor_protection(visible)
        expected = {0, 3, 6, 9, 14, 17, 19, 21}
        self.assertEqual(set(np.flatnonzero(protected[0])), expected)
        self.assertFalse(protected[:, 4].any())

    def test_hidden_leg_edit_keeps_visible_fk_root_metadata_and_outside_exact(self):
        source, visible, interval = fixture()
        candidate, root = leg_candidate(source, interval)
        original = deepcopy(source)
        output, report = finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())
        self.assertTrue(report['parameter_candidate_accepted'])
        self.assertFalse(report['motion_quality_validated'])
        self.assertFalse(report['contact_validated'])
        self.assertGreater(report['generated_joint_samples'], 0)
        source_rot, source_pos = forward_kinematics(source['local_rot_mats'], source['root_positions'], source['rest_joints'])
        output_rot, output_pos = forward_kinematics(output['local_rot_mats'], output['root_positions'], source['rest_joints'])
        np.testing.assert_array_equal(source_pos[visible], output_pos[visible])
        np.testing.assert_array_equal(source_rot[visible], output_rot[visible])
        for name in ['root_positions', 'betas', 'source_to_kimodo', 'time_seconds', 'original_metadata']:
            np.testing.assert_array_equal(output[name], original[name])
        start, end = interval
        np.testing.assert_array_equal(output['local_rot_mats'][:start + 1], source['local_rot_mats'][:start + 1])
        np.testing.assert_array_equal(output['local_rot_mats'][end - 1:], source['local_rot_mats'][end - 1:])
        np.testing.assert_array_equal(source['local_rot_mats'], original['local_rot_mats'])

    def test_mid_interval_reappearance_is_preserved_and_tapered(self):
        source, visible, interval = fixture()
        visible[17:20, 4] = True
        candidate, root = leg_candidate(source, interval)
        output, _ = finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())
        np.testing.assert_array_equal(output['local_rot_mats'][17:20, 4], source['local_rot_mats'][17:20, 4])
        angles = rotation_error(source['local_rot_mats'], output['local_rot_mats'])[:, 4]
        self.assertLess(angles[16], angles[14])
        self.assertLess(angles[20], angles[22])
        self.assertFalse(output['generated_joint_mask'][17:20, 4].any())

    def test_dense_missing_evidence_and_no_editable_body_rejected(self):
        source, visible, interval = fixture()
        visible[10] = False
        with self.assertRaisesRegex(ValueError, 'Every completion frame'):
            validate_source(source, visible, interval)
        with self.assertRaisesRegex(ValueError, 'no editable hidden'):
            validate_source(source, np.ones_like(visible), interval)

    def test_parameter_inputs_reject_scale_bad_rotations_and_fps_relabel(self):
        source, visible, interval = fixture()
        source['source_to_kimodo'][0, 0] *= 1.1
        with self.assertRaisesRegex(ValueError, 'orthonormal'):
            validate_source(source, visible, interval)
        source, visible, interval = fixture()
        source['time_seconds'] *= 1.25
        with self.assertRaisesRegex(ValueError, 'timestamp-resampled'):
            validate_source(source, visible, interval)
        source, visible, interval = fixture()
        candidate, root = leg_candidate(source, interval)
        candidate[:, 4] *= .99
        with self.assertRaisesRegex(ValueError, 'orthonormal'):
            finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())

    def test_contradictory_root_or_visible_arm_is_not_hidden_by_hard_projection(self):
        source, visible, interval = fixture()
        candidate, root = leg_candidate(source, interval)
        root[:, 0] += .3
        with self.assertRaisesRegex(CompletionRejected, 'contradicts dense'):
            finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())
        candidate, root = leg_candidate(source, interval)
        candidate[:, 17] = Rotation.from_rotvec([0, 0, 1.5]).as_matrix()
        with self.assertRaisesRegex(CompletionRejected, 'contradicts dense'):
            finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())

    def test_joint_jump_is_rejected_even_when_visible_motion_is_exact(self):
        source, visible, interval = fixture()
        candidate, root = leg_candidate(source, interval)
        candidate[10:15, 4] = Rotation.from_rotvec([2., 0, 0]).as_matrix()
        with self.assertRaisesRegex(CompletionRejected, 'rotation step'):
            finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())

    def test_codec_roundoff_alone_is_not_accepted_as_a_generated_improvement(self):
        source, visible, interval = fixture()
        local = source['local_rot_mats'][interval[0]:interval[1]].copy()
        local[:, 4] = Rotation.from_rotvec([1e-7, 0, 0]).as_matrix()
        root = source['root_positions'][interval[0]:interval[1]].copy()
        with self.assertRaisesRegex(CompletionRejected, 'no effective generated motion'):
            finalize_candidate(source, visible, interval, local, root, CompletionSettings())

    def test_smooth_local_angles_reject_fast_distal_foot_return(self):
        source, visible, interval = fixture()
        candidate, root = leg_candidate(source, interval)
        candidate[:, 4] = Rotation.from_rotvec([.25, 0, 0]).as_matrix()
        with self.assertRaisesRegex(CompletionRejected, 'distal velocity or acceleration') as caught:
            finalize_candidate(source, visible, interval, candidate, root, CompletionSettings())
        gates = caught.exception.report['temporal_gates']
        self.assertTrue(gates['local_rotation_step']['passed'])
        self.assertTrue(gates['local_rotation_step_increase']['passed'])
        self.assertFalse(gates['boundary_distal_kinematics']['passed'])
        self.assertGreater(gates['boundary_distal_kinematics']['velocity_delta_m_s']['maximum'], .5)

    def test_boundary_derivatives_are_source_relative_and_use_exact_time(self):
        frames = 7
        times = np.array([0., .03, .07, .12, .18, .25, .33])
        source = np.zeros((frames, 22, 3))
        source[:, :, 0] = (9 * times ** 2)[:, None]
        generated = np.zeros((frames, 22), bool)
        generated[1:5, 4] = True  # Knee edit affects ankle/foot, not only edited nodes.
        report = boundary_kinematics_report(source, source.copy(), times, generated, CompletionSettings())
        self.assertTrue(report['passed'])
        self.assertEqual(report['acceleration_delta_m_s2']['maximum'], 0)
        self.assertEqual(report['transition_pair_start_frame_ids']['left_foot'], [0, 4])
        self.assertEqual(report['transition_pair_start_frame_ids']['right_foot'], [])
        candidate = source.copy()
        candidate[:, 10, 1] += .1 * times
        report = boundary_kinematics_report(source, candidate, times, generated, CompletionSettings())
        self.assertAlmostEqual(report['velocity_delta_m_s']['maximum'], .1)
        self.assertLess(report['acceleration_delta_m_s2']['maximum'], 1e-12)

    def test_acceleration_gate_catches_return_with_small_velocity_delta(self):
        frames = 8
        times = np.arange(frames) / 30.
        source = np.zeros((frames, 22, 3))
        candidate = source.copy()
        # 0.3 m/s in opposite directions: velocity delta <0.5, acceleration 18.
        candidate[2, 10, 0] = .01
        generated = np.zeros((frames, 22), bool)
        generated[1:5, 4] = True
        report = boundary_kinematics_report(source, candidate, times, generated, CompletionSettings())
        self.assertTrue(report['velocity_delta_m_s']['passed'])
        self.assertFalse(report['acceleration_delta_m_s2']['passed'])
        self.assertAlmostEqual(report['acceleration_delta_m_s2']['maximum'], 18.)

    def test_velocity_gate_catches_equal_speed_opposite_direction(self):
        frames = 8
        times = np.arange(frames)/30.
        source = np.zeros((frames, 22, 3))
        source[:, 10, 0] = .4 * times
        candidate = source.copy()
        candidate[:, 10, 0] *= -1
        generated = np.zeros((frames, 22), bool)
        generated[1:6, 4] = True
        report = boundary_kinematics_report(source, candidate, times, generated, CompletionSettings())
        gate = report['velocity_delta_m_s']
        self.assertFalse(gate['passed'])
        self.assertAlmostEqual(gate['maximum'], .8)
        self.assertAlmostEqual(gate['worst_sample']['source_magnitude'],
                               gate['worst_sample']['candidate_magnitude'])

    def test_mid_interval_reappearance_is_in_boundary_scope(self):
        frames = 30
        source = np.zeros((frames, 22, 3))
        generated = np.zeros((frames, 22), bool)
        generated[1:29, 4] = True
        generated[14:16, 4] = False
        report = boundary_kinematics_report(source, source, np.arange(frames)/30., generated, CompletionSettings())
        self.assertEqual(report['transition_pair_start_frame_ids']['left_foot'], [0, 13, 15, 28])
        self.assertIn(14, report['velocity_pair_start_frame_ids']['left_foot'])

    def test_gvhmr_conversion_and_export_keep_original_parameters_outside_edit(self):
        source, visible, interval = fixture()
        local = source['local_rot_mats']
        arrays = {
            'smpl_params_global__global_orient': Rotation.from_matrix(local[:, 0]).as_rotvec(),
            'smpl_params_global__body_pose': Rotation.from_matrix(local[:, 1:].reshape(-1, 3, 3)).as_rotvec().reshape(len(local), 63),
            'smpl_params_global__transl': source['root_positions'] - source['rest_joints'][0],
            'smpl_params_global__betas': np.zeros((len(local), 10)),
            'smpl_params_incam__body_pose': np.ones((len(local), 63)),
            'frame_times_seconds': source['time_seconds'],
        }
        prepared = source_from_gvhmr(arrays, source['rest_joints'], source['source_to_kimodo'])
        np.testing.assert_allclose(prepared['root_positions'], source['root_positions'], atol=1e-12)
        candidate, root = leg_candidate(prepared, interval)
        output, _ = finalize_candidate(prepared, visible, interval, candidate, root, CompletionSettings())
        self.assertNotIn('smpl_params_incam__body_pose', output)
        np.testing.assert_array_equal(output['source_gvhmr__smpl_params_incam__body_pose'], arrays['smpl_params_incam__body_pose'])
        for key in ['global_orient', 'transl', 'betas']:
            np.testing.assert_array_equal(output['smpl_params_global__' + key], arrays['smpl_params_global__' + key])
        original_pose = arrays['smpl_params_global__body_pose'].reshape(len(local), 21, 3)
        out_pose = output['smpl_params_global__body_pose'].reshape(len(local), 21, 3)
        np.testing.assert_array_equal(out_pose[~output['generated_joint_mask'][:, 1:]], original_pose[~output['generated_joint_mask'][:, 1:]])

    def test_video_binding_rejects_same_timeline_wrong_actor_or_video(self):
        from tools.kimodo.complete_motion import validate_video_binding
        source = dict(source_video_sha256=np.asarray('a' * 64), source_actor_id=np.asarray('reviewed_actor'))
        visibility = {key: value.copy() for key, value in source.items()}
        self.assertEqual(validate_video_binding(source, visibility)['source_actor_id'], 'reviewed_actor')
        for field, value in [('source_video_sha256', 'b' * 64), ('source_actor_id', 'other_actor')]:
            changed = dict(visibility, **{field: np.asarray(value)})
            with self.assertRaisesRegex(ValueError, 'different source'):
                validate_video_binding(source, changed)
        with self.assertRaisesRegex(ValueError, 'requires source and visibility binding'):
            validate_video_binding(source, {})

    def test_real_cli_requires_hidden_uncertain_distinction(self):
        from tools.kimodo.complete_motion import constraint_mask
        visible = np.zeros((12, 22), dtype=bool)
        visible[:, 15] = True
        with self.assertRaisesRegex(ValueError, 'requires visibility_state'):
            constraint_mask(dict(visible_joint_mask=visible), [1, 11], require_reviewed_states=True)

    def test_native_export_binding_rejects_same_length_stale_parameters_or_camera(self):
        from tools.kimodo.complete_motion import validate_prediction_export
        prediction = {'K_fullimg': np.repeat(np.eye(3, dtype=np.float32)[None], 12, axis=0)}
        native = {'K_fullimg': prediction['K_fullimg'].copy()}
        for group in ('smpl_params_global', 'smpl_params_incam'):
            prediction[group] = {}
            for field, count in [('body_pose', 63), ('global_orient', 3), ('transl', 3), ('betas', 10)]:
                array = np.zeros((12, count), dtype=np.float32)
                prediction[group][field] = array
                native[group + '__' + field] = array.copy()
        self.assertEqual(len(validate_prediction_export(native, prediction)), 9)
        for field in native:
            changed = {key: array.copy() for key, array in native.items()}
            changed[field].flat[0] += 1
            with self.assertRaisesRegex(ValueError, 'differs from the actual GVHMR prediction'):
                validate_prediction_export(changed, prediction)

    def test_prepare_cli_binds_rest_geometry_to_source_beta_and_refuses_overwrite(self):
        source, _, _ = fixture()
        frames = len(source['time_seconds'])
        raw = {
            'smpl_params_global__global_orient': np.zeros((frames, 3)),
            'smpl_params_global__body_pose': np.zeros((frames, 63)),
            'smpl_params_global__transl': source['root_positions'] - source['rest_joints'][0],
            'smpl_params_global__betas': np.zeros((frames, 10)),
            'frame_times_seconds': source['time_seconds'],
        }
        script = Path(__file__).resolve().parents[1] / 'tools/kimodo/complete_motion.py'
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            np.savez(folder / 'raw.npz', **raw)
            geometry = {key: source[key] for key in ('rest_joints', 'betas', 'joint_names', 'source_to_kimodo')}
            geometry['source_sha256'] = np.asarray(hashlib.sha256((folder / 'raw.npz').read_bytes()).hexdigest())
            np.savez(folder / 'geometry.npz', **geometry)
            cmd = [sys.executable, str(script), 'prepare', '--source', str(folder / 'raw.npz'),
                   '--geometry', str(folder / 'geometry.npz'), '--output', str(folder / 'prepared.npz')]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with np.load(folder / 'prepared.npz', allow_pickle=False) as prepared:
                np.testing.assert_allclose(prepared['root_positions'], source['root_positions'], atol=1e-12)
            second = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('already exists', second.stderr)
            geometry['betas'] = np.ones(10)
            np.savez(folder / 'geometry.npz', **geometry)
            mismatch = subprocess.run(cmd[:-1] + [str(folder / 'bad.npz')], capture_output=True, text=True)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn('exact source beta', mismatch.stderr)
            self.assertFalse((folder / 'bad.npz').exists())
            geometry['betas'] = source['betas']
            geometry['source_sha256'] = np.asarray('0' * 64)
            np.savez(folder / 'geometry.npz', **geometry)
            wrong_source = subprocess.run(cmd[:-1] + [str(folder / 'wrong_source.npz')], capture_output=True, text=True)
            self.assertNotEqual(wrong_source.returncode, 0)
            self.assertIn('different source file', wrong_source.stderr)
            self.assertFalse((folder / 'wrong_source.npz').exists())


try:
    import torch
except ImportError:
    torch = None


class ContractRepresentation:
    """Small independent 6D/FK codec with deliberately nonidentity normalization."""
    motion_rep_dim = 273
    slice_dict = FEATURE_SLICES

    def __init__(self, rest):
        self.rest = rest * 1.1  # Source-shaped channels must replace this mean-shape FK.
        self.mean = torch.linspace(-.2, .2, 273)
        self.std = torch.linspace(.5, 1.5, 273)
        self.decode_error = 0.

    def normalize(self, value):
        return (value - self.mean) / self.std

    def __call__(self, local, root, **kwargs):
        local, root = local[0].numpy(), root[0].numpy()
        global_rot, joints = forward_kinematics(local, root, self.rest)
        relative = joints - root[:, None] * [1, 0, 1]
        features = np.zeros((1, len(root), 273), dtype=np.float32)
        features[0, :, :3] = root
        features[0, :, 3] = 1
        features[0, :, 5:71] = relative.reshape(len(root), 66)
        features[0, :, 71:203] = np.concatenate([global_rot[..., 0], global_rot[..., 1]], axis=-1).reshape(len(root), 132)
        return torch.from_numpy(features)

    def inverse(self, features, **kwargs):
        raw = (features * self.std + self.mean).numpy()[0]
        columns = raw[:, 71:203].reshape(-1, 22, 6)
        x = columns[..., :3]
        x = x / np.linalg.norm(x, axis=-1, keepdims=True)
        z = np.cross(x, columns[..., 3:])
        z = z / np.linalg.norm(z, axis=-1, keepdims=True)
        y = np.cross(z, x)
        global_rot = np.stack([x, y, z], axis=-1)
        local = global_rot.copy()
        for joint in range(1, 22):
            local[:, joint] = global_rot[:, PARENTS[joint]].swapaxes(-1, -2) @ global_rot[:, joint]
        root = raw[:, 5:8] + raw[:, :3] * [1, 0, 1] + self.decode_error
        return {'local_rot_mats': torch.from_numpy(local[None]), 'root_positions': torch.from_numpy(root[None])}


class ContractDiffusion:
    num_base_steps = 100

    def space_timesteps(self, steps):
        indices = torch.linspace(0, 99, int(steps)).round().long()
        return indices, indices

    def calc_diffusion_vars(self, indices):
        self.alphas = torch.linspace(.99, .01, 100)[indices]

    def q_sample(self, x0, t, noise):
        return self.alphas[t, None, None].sqrt() * x0 + (1 - self.alphas[t, None, None]).sqrt() * noise


class ContractModel:
    """Records real adapter calls, substituting a controlled clean-pose prediction."""
    fps = 30
    device = 'cpu'

    def __init__(self, rest):
        from types import SimpleNamespace
        self.skeleton = SimpleNamespace(bone_order_names=JOINT_NAMES)
        self.motion_rep = ContractRepresentation(rest)
        self.diffusion = ContractDiffusion()
        self.calls = []

    def text_encoder(self, texts):
        self.texts = texts
        return torch.ones((1, 3, 4)), [3]

    def denoising_step(self, current, pad, text, text_pad, t, heading, mask, observed, steps, cfg, **kwargs):
        self.calls.append({'input': current.clone(), 'step': int(t[0]), 'mask': mask.clone(), 'observed': observed.clone()})
        return self.target.clone()


@unittest.skipIf(torch is None, 'Torch is optional for pure geometry tests')
class SamplingContractTests(unittest.TestCase):
    def model_fixture(self, settings):
        source, visible, interval = fixture()
        model = ContractModel(source['rest_joints'])
        target_source = deepcopy(source)
        target_source['local_rot_mats'][interval[0]:interval[1]], _ = leg_candidate(source, interval)
        model.target = prepare_conditions(model, target_source, visible, interval, settings)['encoded']
        return source, visible, interval, model

    def test_real_adapter_calls_dense_conditions_with_text_on_every_step(self):
        settings = replace(CompletionSettings(), denoising_steps=5)
        source, visible, interval, model = self.model_fixture(settings)
        output, report = complete_motion(model, source, visible, interval, 'A person stands and gestures.', settings=settings)
        self.assertEqual(model.texts, ['A person stands and gestures.'])
        self.assertEqual([call['step'] for call in model.calls], [4, 3, 2, 1, 0])
        observed = visible[interval[0]:interval[1]]
        for call in model.calls:
            pos_mask = call['mask'][0, :, 5:71].numpy().reshape(-1, 22, 3)
            rot_mask = call['mask'][0, :, 71:203].numpy().reshape(-1, 22, 6)
            self.assertTrue(pos_mask[observed].all())
            self.assertTrue(rot_mask[observed].all())
            self.assertTrue(call['mask'].any(dim=-1).all())
        self.assertEqual(report['sampling']['source_conditioned_frames'], 28)
        self.assertLess(report['roundtrip']['max_source_shaped_fk_error_m'], 2e-5)
        self.assertTrue(output['generated_joint_mask'][:, 4].any())

    def test_warm_start_uses_q_sample_at_the_selected_schedule_index(self):
        settings = replace(CompletionSettings(), denoising_steps=5, warm_start_step=1)
        source, visible, interval, model = self.model_fixture(settings)
        conditions = prepare_conditions(model, source, visible, interval, settings)
        output, report = complete_motion(model, source, visible, interval, 'A person stands.', seed=7, settings=settings)
        generator = torch.Generator(device='cpu').manual_seed(7)
        noise = torch.randn(conditions['encoded'].shape, generator=generator)
        expected = model.diffusion.q_sample(conditions['encoded'], torch.tensor([1]), noise)
        torch.testing.assert_close(model.calls[0]['input'], expected)
        self.assertEqual([call['step'] for call in model.calls], [1, 0])
        self.assertEqual(report['sampling']['start_training_timestep'], 25)
        self.assertEqual(report['sampling']['reverse_steps_executed'], 2)

    def test_roundtrip_failure_stops_before_sampling_and_blank_text_has_no_fallback(self):
        settings = replace(CompletionSettings(), denoising_steps=5)
        source, visible, interval, model = self.model_fixture(settings)
        model.motion_rep.decode_error = .02
        with self.assertRaisesRegex(CompletionRejected, 'roundtrip failed'):
            complete_motion(model, source, visible, interval, 'A person stands.', settings=settings)
        self.assertEqual(model.calls, [])
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            complete_motion(model, source, visible, interval, '  ', settings=settings)


class ConservativeConstraintTests(unittest.TestCase):
    def fixture(self):
        visible = np.zeros((12, 22), bool)
        visible[:, [15, 20, 21]] = True
        constraints = np.ones_like(visible)
        constraints[:, [4, 5, 7, 8, 10, 11]] = False
        state = np.full(visible.shape, -1, dtype=np.int8)
        state[visible] = 1
        state[:, [4, 5, 7, 8, 10, 11]] = 0
        return dict(visible_joint_mask=visible, constraint_joint_mask=constraints, visibility_state=state)

    def test_uncertain_hips_can_be_preserved_without_claiming_visibility(self):
        from tools.kimodo.complete_motion import constraint_mask
        observations = self.fixture()
        constraints, report = constraint_mask(observations, [1, 11])
        self.assertTrue(constraints[:, [1, 2]].all())
        self.assertFalse(observations['visible_joint_mask'][:, [1, 2]].any())
        self.assertEqual(report['actual_visible_joint_samples'], 30)
        self.assertGreater(report['conservative_extra_samples'], 0)
        self.assertTrue(report['reviewed_visibility_states_provided'])

    def test_editable_uncertainty_and_discarded_observation_are_rejected(self):
        from tools.kimodo.complete_motion import constraint_mask
        observations = self.fixture()
        observations['visibility_state'][5, 7] = -1
        with self.assertRaisesRegex(ValueError, 'reviewed hidden'):
            constraint_mask(observations, [1, 11])
        observations['constraint_joint_mask'][5, 7] = True
        constraint_mask(observations, [1, 11])
        observations['constraint_joint_mask'][5, 21] = False
        with self.assertRaisesRegex(ValueError, 'superset'):
            constraint_mask(observations, [1, 11])

    def test_conservative_constraints_cannot_stand_in_for_actual_observations(self):
        from tools.kimodo.complete_motion import constraint_mask
        observations = self.fixture()
        observations['visible_joint_mask'][5] = False
        observations['visibility_state'][5] = -1
        observations['constraint_joint_mask'][5] = True
        with self.assertRaisesRegex(ValueError, 'actual visible-body'):
            constraint_mask(observations, [1, 11])


if __name__ == '__main__':
    unittest.main()
