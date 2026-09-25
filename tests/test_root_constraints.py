import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.gvhmr.align_depth_trajectory import run_workflow
from tools.gvhmr.root_constraints import (
    active_mask, closest_surface, contact_metrics, event_strength, fit_constant_contact,
    fit_smooth_residual, load_contacts, spline_basis, vertical_origin,
)


class RootConstraintsTests(unittest.TestCase):
    def fixture(self):
        t = np.arange(121) / 30
        root = np.column_stack((t, t * 0, t * 0 + 1))
        body = dict(time_seconds=t, joints=root[:, None], vertices=root[:, None] + [[[0, 0, -.9], [.1, 0, 0]]],
                    track_active=np.arange(len(t)) < 100, source_frame_indices=np.arange(len(t)), body_scale=np.asarray(1.),
                    source_video_sha256=np.asarray('a' * 64), source_actor_id=np.asarray('actor'), room_basis_sha256=np.asarray('b' * 64))
        ids = np.arange(0, len(t), 5)
        obs = dict(frame_indices=ids, time_seconds=t[ids], root_targets=root[ids] + np.column_stack((.1 * np.sin(t[ids]), t[ids] * 0, t[ids] * 0)),
                   valid=np.ones(len(ids), bool), weights=np.ones(len(ids)), train=np.arange(len(ids)) % 3 != 0)
        return body, obs

    def contact(self, body, *, offset=0., train=(10, 20, 30), intervals=((10, 40),)):
        event = np.zeros(len(body['time_seconds']), bool)
        for a, b in intervals:
            event[a:b] = True
        return dict(name='floor', normal=np.array([0., 0, 1.]), plane_offset=offset,
                    kind='vertices', indices=np.array([0]), event_mask=event,
                    train_ids=np.asarray(train), heldout_ids=np.flatnonzero(event & ~np.isin(np.arange(len(event)), train)),
                    vertices=np.array([[-10., -10, -offset], [10., -10, -offset], [10., 10, -offset], [-10., 10, -offset]]),
                    faces=np.array([[0, 1, 2], [0, 2, 3]]), solids=[], target_gap_m=.002,
                    max_gap_m=.01, max_penetration_m=.01, weight=100.)

    def test_smooth_fit_has_no_heldout_or_inactive_target_leak(self):
        body, obs = self.fixture()
        a, _ = fit_smooth_residual(body, obs)
        obs['root_targets'][~obs['train'] | (obs['frame_indices'] >= 100)] += 1000
        b, report = fit_smooth_residual(body, obs)
        np.testing.assert_array_equal(a, b)
        self.assertLess(max(report['training_depth_frames']), 100)

    def test_clamped_support_is_c1_and_constant_outside(self):
        body, obs = self.fixture()
        offsets, report = fit_smooth_residual(body, obs)
        knots = np.asarray(report['knots_seconds']); coeff = np.asarray(report['coefficients'])
        self.assertLess(report['boundary_derivative_max_m_s'], 1e-12)
        np.testing.assert_allclose(offsets[body['time_seconds'] > knots[-1]], np.broadcast_to(coeff[-1], offsets[body['time_seconds'] > knots[-1]].shape), atol=1e-12)
        self.assertIn('acceleration may jump', report['boundary'])

    def test_plane_contact_fits_only_training_patch_and_preserves_relative_geometry(self):
        body, _ = self.fixture(); c = self.contact(body)
        offset, _ = fit_constant_contact(body, [c])
        np.testing.assert_allclose(offset, np.broadcast_to([0, 0, -.098], offset.shape), atol=1e-12)
        body['vertices'][25, 0, 2] += .5
        other, _ = fit_constant_contact(body, [c])
        np.testing.assert_array_equal(offset, other)
        report = contact_metrics(body, [c], offset)[0]
        self.assertFalse(report['accepted'])
        self.assertGreater(report['max_gap_m'], .4)

    def test_finite_surface_rejects_near_plane_point_outside_extent(self):
        body, _ = self.fixture(); c = self.contact(body)
        c['vertices'][:, :2] *= .001
        offset, _ = fit_constant_contact(body, [c])
        report = contact_metrics(body, [c], offset)[0]
        self.assertFalse(report['accepted'])
        self.assertGreater(report['max_gap_m'], .3)
        self.assertAlmostEqual(report['rows'][0]['minimum_plane_gap_m'], .002)

    def test_finite_triangle_distance_includes_edges_and_vertices(self):
        vertices = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0]])
        distances, points = closest_surface(np.array([[.2, .2, 2], [2., 0, 0], [.5, .5, 0]]), vertices, np.array([[0, 1, 2]]))
        np.testing.assert_allclose(distances, [2, 1, 0], atol=1e-12)
        np.testing.assert_allclose(points[1], [1, 0, 0], atol=1e-12)

    def test_smooth_conflicting_contacts_remain_rejected(self):
        body, obs = self.fixture()
        a = self.contact(body); b = self.contact(body, offset=-1.)
        b['name'] = 'incompatible_parallel_surface'
        offset, _ = fit_smooth_residual(body, obs, contacts=[a, b], max_nfev=30)
        self.assertFalse(all(c['accepted'] for c in contact_metrics(body, [a, b], offset)))

    def test_vertical_origin_ignores_inactive_and_heldout_heights(self):
        body, obs = self.fixture()
        cfg = dict(vertex_indices=[0], intervals=[[0, 121]], reviewed_by='reviewer', review_scope='hypothesized support', target_gap_m=.002)
        a, report = vertical_origin(body, obs, cfg)
        heldout = obs['frame_indices'][~obs['train']]
        body['vertices'][heldout, 0, 2] -= 10
        body['vertices'][100:, 0, 2] -= 10
        b, _ = vertical_origin(body, obs, cfg)
        np.testing.assert_array_equal(a, b)
        self.assertLess(max(report['training_frame_indices']), 100)
        np.testing.assert_allclose(a[:, :2], 0)
        np.testing.assert_allclose(np.diff(a, axis=0), 0)

    def test_explicit_plant_detects_and_reduces_surface_tangential_sliding(self):
        body, obs = self.fixture()
        c = self.contact(body, train=tuple(range(10, 40, 2)))
        c['plant'] = dict(reviewed_by='source reviewer', review_scope='synthetic planted hand', weight=1000., max_slip_m_s=.05)
        gap_offset, _ = fit_constant_contact(body, [c])
        before = contact_metrics(body, [c], gap_offset)[0]
        self.assertFalse(before['accepted'])
        self.assertGreater(before['plant']['max_patch_centroid_speed_m_s'], .9)
        after_offset, _ = fit_smooth_residual(body, obs, contacts=[c], knot_spacing_seconds=.25, acceleration_penalty=.0001, offset_penalty=.0001)
        after = contact_metrics(body, [c], after_offset)[0]
        self.assertLess(after['plant']['max_patch_centroid_speed_m_s'], .05)
        self.assertTrue(after['accepted'])

    def test_sparse_contact_keys_keep_intervening_frames_diagnostic_only(self):
        body, _ = self.fixture(); c = self.contact(body)
        c['diagnostic_mask'] = c['event_mask'].copy()
        c['event_mask'][:] = False; c['event_mask'][[10, 20, 30]] = True
        offset, _ = fit_constant_contact(body, [c])
        body['vertices'][25, 0, 2] += .5
        result = contact_metrics(body, [c], offset)[0]
        self.assertTrue(result['accepted'])
        row = next(r for r in result['rows'] if r['frame'] == 25)
        self.assertEqual(row['cohort'], 'diagnostic_only')
        self.assertFalse(row['acceptance_cohort'])
        self.assertGreater(row['minimum_patch_surface_distance_m'], .4)

    def test_rotating_patch_cannot_pass_plant_through_stationary_centroid(self):
        body, _ = self.fixture()
        body['vertices'][:] = [[-.1, 0, 0], [.1, 0, 0]]
        body['vertices'][11] = [[0, -.1, 0], [0, .1, 0]]
        c = self.contact(body, train=(10,), intervals=((10, 12),))
        c['indices'] = np.array([0, 1])
        c['plant'] = dict(weight=1000., max_slip_m_s=.05)
        c['plant_train_ids'] = np.array([10, 11])
        report = contact_metrics(body, [c])[0]
        self.assertAlmostEqual(report['plant']['max_patch_centroid_speed_m_s'], 0.)
        self.assertGreater(report['plant']['max_corresponding_point_speed_m_s'], 4.)
        self.assertFalse(report['accepted'])
        self.assertEqual(report['plant']['gate_version'], 2)
        row = next(r for r in report['rows'] if r['frame'] == 11)
        self.assertEqual(row['cohort'], 'plant_training_only')
        self.assertTrue(row['plant_endpoint_training'])
        self.assertFalse(row['contact_gap_training'])

    def test_plant_speed_never_bridges_a_release_or_counts_singleton_event(self):
        body, _ = self.fixture()
        body['vertices'][:] = [[0, 0, 0], [.1, 0, 0]]
        body['vertices'][20:] += [5, 0, 0]
        c = self.contact(body, train=(10, 11, 20, 21), intervals=((10, 12), (20, 22)))
        c['plant'] = dict(weight=100., max_slip_m_s=.05)
        report = contact_metrics(body, [c])[0]
        self.assertTrue(report['accepted'])
        self.assertEqual(report['plant']['frame_pair_count'], 2)
        self.assertEqual(report['plant']['training_endpoint_pairs'], [[10, 11], [20, 21]])
        c['event_mask'][:] = False; c['event_mask'][10] = True
        c['train_ids'] = np.array([10])
        self.assertFalse(contact_metrics(body, [c])[0]['accepted'])

    def test_separate_plant_training_frames_do_not_consume_heldout_geometry(self):
        body, obs = self.fixture(); c = self.contact(body, train=(10, 20, 30))
        c['plant'] = dict(reviewed_by='reviewer', review_scope='hypothesis', weight=10., max_slip_m_s=.05)
        c['plant_train_ids'] = np.array([10, 12, 14, 20, 22, 24, 30])
        first, report = fit_smooth_residual(body, obs, contacts=[c])
        body['vertices'][11, 0] += 10
        second, _ = fit_smooth_residual(body, obs, contacts=[c])
        np.testing.assert_array_equal(first, second)
        self.assertEqual(report['plant_training_frames']['floor'], c['plant_train_ids'].tolist())

    def test_raised_cosine_weight_ramp_preserves_full_event_acceptance_scope(self):
        strength = event_strength([[10, 30]], 40, 4)
        self.assertEqual(strength[10], 0.)
        self.assertEqual(strength[29], 0.)
        self.assertEqual(strength[14], 1.)
        np.testing.assert_allclose(strength[10:15], strength[25:30][::-1])
        body, _ = self.fixture(); c = self.contact(body)
        c['frame_strength'] = event_strength([[10, 40]], len(body['time_seconds']), 4)
        offset, _ = fit_constant_contact(body, [c])
        body['vertices'][10, 0, 2] += .1
        self.assertFalse(contact_metrics(body, [c], offset)[0]['accepted'])

    def test_activity_rejects_reactivation_and_non_boolean(self):
        body, _ = self.fixture(); body['track_active'][110] = True
        with self.assertRaisesRegex(ValueError, 'prefix'):
            active_mask(body)
        body['track_active'] = np.ones(121, int)
        with self.assertRaises(ValueError):
            active_mask(body)

    def test_contact_manifest_requires_exact_body_hash_and_active_training(self):
        body, _ = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'contacts.json'
            path.write_text(json.dumps(dict(schema_version=1, source_body_sha256='wrong')))
            with self.assertRaisesRegex(ValueError, 'exact initial body'):
                load_contacts(path, body, 'correct')

    def test_workflow_stage_offsets_are_immediate_parent_and_metadata_remains_archival(self):
        body, obs = self.fixture()
        body.update(transl=np.zeros((121, 3)), custom_world_points=body['vertices'].copy(), betas=np.ones((121, 10)))
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory); bp = d / 'source.npz'; op = d / 'obs.npz'; wp = d / 'workflow.json'
            np.savez(bp, **body)
            bh = hashlib.sha256(bp.read_bytes()).hexdigest()
            obs.update({k: body[k] for k in ('source_video_sha256', 'source_actor_id', 'room_basis_sha256')}, source_body_sha256=np.asarray(bh))
            np.savez(op, **obs)
            wp.write_text(json.dumps(dict(schema_version=1, source_body_sha256=bh, observations_sha256=hashlib.sha256(op.read_bytes()).hexdigest(), stages=[
                dict(name='scale', method='scale_translation'), dict(name='smooth', method='smooth_residual'),
                dict(name='floor', method='vertical_origin', options=dict(vertex_indices=[0], intervals=[[0, 100]], reviewed_by='reviewer', review_scope='support hypothesis'))])))
            run_workflow(bp, op, d / 'out', wp)
            parent = body
            for stage in ('scale', 'smooth', 'floor'):
                child = dict(np.load(d / 'out' / stage / 'body_room.npz'))
                np.testing.assert_allclose(child['vertices'].astype(float), parent['vertices'] + child['trajectory_offsets'][:, None], atol=3e-7)
                np.testing.assert_allclose(child['vertices'].astype(float) - child['joints'][:, :1], body['vertices'] - body['joints'][:, :1], atol=5e-7)
                np.testing.assert_array_equal(child['track_active'], body['track_active'])
                np.testing.assert_array_equal(child['time_seconds'], body['time_seconds'])
                np.testing.assert_array_equal(child['betas'], body['betas'])
                self.assertNotIn('transl', child); self.assertNotIn('custom_world_points', child)
                parent = child


if __name__ == '__main__':
    unittest.main()
