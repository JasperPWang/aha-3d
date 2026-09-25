"""Geometry/basis contracts with synthetic numeric SMPL-X-shaped fixtures.

Real licensed asset cross-checks belong in the task run evidence, not fixtures.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from aha3d.motion.completion import JOINT_NAMES, PARENTS, source_from_gvhmr

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('motion_geometry_preparer', ROOT / 'tools/kimodo/prepare_geometry.py')
geometry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(geometry)


def source_fixture():
    frames = 6
    beta = np.array([.7, -.3, .2, 0, -.4, 0, .1, 0, 0, .25])
    return {
        'smpl_params_global__betas': np.broadcast_to(beta, (frames, 10)).copy(),
        'smpl_params_global__global_orient': np.broadcast_to([.2, -.7, .15], (frames, 3)).copy(),
        'smpl_params_global__body_pose': np.zeros((frames, 63)),
        'smpl_params_global__transl': np.broadcast_to([2., .3, -1.], (frames, 3)).copy(),
        'frame_times_seconds': np.arange(frames) / 30.,
    }


def model_fixture():
    rng = np.random.default_rng(6)
    template = np.zeros((10475, 3))
    template[:55] = rng.normal(size=(55, 3)) * .2 + [.05, .9, -.04]
    directions = np.zeros((10475, 3, 12))
    directions[:55] = rng.normal(size=(55, 3, 12)) * .03
    regressor = np.zeros((55, 10475))
    regressor[np.arange(55), np.arange(55)] = 1
    parents = np.zeros(55, np.int64)
    parents[:22] = PARENTS
    return dict(v_template=template, shapedirs=directions, J_regressor=regressor,
                kintree_table=np.stack([parents, np.arange(55)]))


class GeometryPreparationTests(unittest.TestCase):
    def test_nonzero_source_beta_and_original_pelvis_offset_are_used(self):
        model, source = model_fixture(), source_fixture()
        beta, frames = geometry.fixed_source_betas(source)
        actual = geometry.source_shaped_rest_joints(model, beta)
        expected = model['v_template'][:22].copy()
        for component in range(10):
            expected += model['shapedirs'][:22, :, component] * beta[component]
        np.testing.assert_allclose(actual, expected, atol=1e-14, rtol=0)
        self.assertEqual(frames, 6)
        self.assertGreater(np.linalg.norm(actual - model['v_template'][:22]), .01)
        self.assertGreater(np.linalg.norm(actual[0]), .5)
        prepared = source_from_gvhmr(source, actual, np.eye(4))
        np.testing.assert_allclose(prepared['root_positions'], source['smpl_params_global__transl'] + actual[0])
        rotated_rest = Rotation.from_rotvec(source['smpl_params_global__global_orient'][0]).apply(actual[0])
        self.assertGreater(np.linalg.norm(rotated_rest - actual[0]), .01)

    def test_missing_nonfinite_varying_or_wrong_beta_cannot_be_replaced(self):
        for change in ['missing', 'nonfinite', 'varying', 'dimensions']:
            source = source_fixture()
            key = 'smpl_params_global__betas'
            if change == 'missing':
                del source[key]
            elif change == 'nonfinite':
                source[key][2, 3] = np.nan
            elif change == 'varying':
                source[key][3, 1] += .01
            else:
                source[key] = source[key][:, :9]
            with self.subTest(change=change), self.assertRaises(ValueError):
                geometry.fixed_source_betas(source)

    def test_source_frame_and_parameter_shapes_must_agree(self):
        source = source_fixture()
        source['frame_times_seconds'] = np.arange(5) / 30.
        with self.assertRaisesRegex(ValueError, 'timestamps'):
            geometry.fixed_source_betas(source)
        source = source_fixture()
        source['smpl_params_global__body_pose'] = np.zeros((6, 72))
        with self.assertRaisesRegex(ValueError, 'axis-angle'):
            geometry.fixed_source_betas(source)

    def test_wrong_joint_topology_regressor_or_shape_directions_rejected(self):
        for change in ['parents', 'order', 'regressor', 'directions']:
            model = model_fixture()
            if change == 'parents':
                model['kintree_table'][0, 20] = 17
            elif change == 'order':
                model['kintree_table'][1, [19, 20]] = [20, 19]
            elif change == 'regressor':
                model['J_regressor'][5] *= 2
            else:
                model['shapedirs'] = model['shapedirs'][:, :, :9]
            with self.subTest(change=change), self.assertRaises(ValueError):
                geometry.source_shaped_rest_joints(model, np.ones(10))

    def test_basis_never_guessed_and_reflections_or_scale_rejected(self):
        with self.assertRaisesRegex(ValueError, 'explicit'):
            geometry.explicit_basis()
        transform, evidence = geometry.explicit_basis('gvhmr-y-up')
        np.testing.assert_array_equal(transform, np.eye(4))
        self.assertFalse(evidence['basis_inferred_from_pose'])
        for scale in (-1, 1.02):
            bad = np.eye(4)
            bad[0, 0] = scale
            with self.assertRaisesRegex(ValueError, 'proper rotation'):
                geometry.explicit_basis(source_to_kimodo=bad)

    def test_explicit_basis_does_not_rotate_source_rest_offsets(self):
        source = source_fixture()
        rest = geometry.source_shaped_rest_joints(model_fixture(), source['smpl_params_global__betas'][0])
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_rotvec([np.pi / 2, 0, 0]).as_matrix()
        transform[:3, 3] = [2., -.5, 1.]
        accepted, _ = geometry.explicit_basis(source_to_kimodo=transform)
        prepared = source_from_gvhmr(source, rest, accepted)
        np.testing.assert_array_equal(prepared['rest_joints'], rest)
        np.testing.assert_array_equal(prepared['source_to_kimodo'], transform)

    def test_file_adapter_provenance_and_existing_completion_prepare_interoperate(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source_path, model_path = folder / 'motion_native.npz', folder / 'SMPLX_NEUTRAL.npz'
            np.savez(source_path, **source_fixture())
            np.savez(model_path, **model_fixture())
            source_before = source_path.read_bytes()
            output = folder / 'geometry.npz'
            report = geometry.prepare_geometry(source_path, model_path, output, source_basis='gvhmr-y-up')
            self.assertFalse(report['learned_model_executed'])
            self.assertEqual(source_before, source_path.read_bytes())
            with np.load(output, allow_pickle=False) as arrays:
                self.assertEqual(tuple(arrays['joint_names']), JOINT_NAMES)
                self.assertEqual(str(arrays['source_sha256']), report['source']['sha256'])
                self.assertEqual(str(arrays['body_model_sha256']), report['body_model']['sha256'])
            result = subprocess.run([
                sys.executable, str(ROOT / 'tools/kimodo/complete_motion.py'), 'prepare',
                '--source', str(source_path), '--geometry', str(output), '--output', str(folder / 'prepared.npz'),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with self.assertRaises(FileExistsError):
                geometry.prepare_geometry(source_path, model_path, output, source_basis='gvhmr-y-up')


if __name__ == '__main__':
    unittest.main()
