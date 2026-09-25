import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.gvhmr.full_scene_constraints import (
    evaluate_scene, floor_inside_xy, load_scene_constraints, object_depth,
    save_contact_series, save_scene_metrics, scene_report,
)
from tools.gvhmr.root_constraints import fit_smooth_residual, contact_metrics
from tools.gvhmr.align_depth_trajectory import move_fixed_size_body


def cube(lo, hi):
    a,b,c=lo; x,y,z=hi
    v=np.array([[a,b,c],[x,b,c],[x,y,c],[a,y,c],[a,b,z],[x,b,z],[x,y,z],[a,y,z]])
    f=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
    planes=np.array([[-1.,0,0,a],[1.,0,0,-x],[0,-1.,0,b],[0,1.,0,-y],[0,0,-1.,c],[0,0,1.,-z]])
    return dict(vertices=v,faces=f,planes=planes,lower=np.array(lo),upper=np.array(hi),name='box',key='box')


class FullSceneTests(unittest.TestCase):
    def fixture(self):
        t=np.arange(61)/30; root=np.tile([0.,0.,1.],(61,1))
        body=dict(vertices=root[:,None]+np.array([[[0,0,-1.1],[.53,.04,-.73],[.1,0,-.1]]]),joints=root[:,None],time_seconds=t,
                  track_active=np.arange(61)<51,source_frame_indices=np.arange(61),body_scale=np.asarray(1.),
                  source_actor_id=np.asarray('actor'),source_video_sha256=np.asarray('a'*64),room_basis_sha256=np.asarray('b'*64))
        ids=np.arange(0,61,3);obs=dict(frame_indices=ids,root_targets=root[ids],valid=np.ones(len(ids),bool),train=np.arange(len(ids))%3!=0,weights=np.ones(len(ids)))
        floor=np.array([[-2.,-2,0],[2.,-2,0],[2.,2,0],[-2.,2,0]])
        scene=dict(floor_vertices=floor,floor_faces=np.array([[0,1,2],[0,2,3]]),floor_offset=0.,coverage_vertex_indices=np.array([0]),
                   objects=[cube([.4,-.3,.1],[.8,.3,.5])],spec=dict(floor_weight=100.,object_weight=100.,max_floor_penetration_m=.02,max_object_penetration_m=.002))
        return body,obs,scene

    def test_all_active_vertices_including_unobserved_frames_are_evaluated(self):
        body,obs,scene=self.fixture();a=evaluate_scene(body,scene)
        self.assertAlmostEqual(a['floor_penetration_m'][0],.1)
        self.assertGreater(a['object_max_penetration_m'][1,0],.1)
        self.assertTrue(np.isnan(a['floor_penetration_m'][51:]).all())
        self.assertTrue(np.isnan(a['object_max_penetration_m'][51:]).all())
        self.assertEqual(a['floor_penetration_m'].shape,(61,))

    def test_exact_piecewise_full_mesh_translation_gradient(self):
        body,obs,scene=self.fixture();d=np.tile([.011,.017,.019],(61,1))
        value,g=evaluate_scene(body,scene,d,objective=True)
        for axis in range(3):
            plus=d.copy();minus=d.copy();plus[7,axis]+=1e-6;minus[7,axis]-=1e-6
            finite=(evaluate_scene(body,scene,plus,objective=True)[0]-evaluate_scene(body,scene,minus,objective=True)[0])/2e-6
            self.assertAlmostEqual(g[7,axis],finite,places=6)
        np.testing.assert_array_equal(g[51:],0)

    def test_convex_component_is_finite_not_an_infinite_plane(self):
        component=cube([0,0,0],[1,1,1])
        depth,count,gradient,index=object_depth(np.array([[.2,.4,.5],[2.,.4,.5]]),component)
        self.assertAlmostEqual(depth,.2);self.assertEqual(count,1);self.assertEqual(index,0)
        self.assertEqual(object_depth(np.array([[2.,.4,.5]]),component)[0],0.)

    def test_multiple_finite_supports_use_rug_height_only_within_its_footprint(self):
        body,obs,scene=self.fixture()
        scene['floor_surfaces']=[dict(vertices=scene['floor_vertices'],faces=scene['floor_faces'],offset=0.),
                                 dict(vertices=np.array([[-.2,-.2,.008],[.2,-.2,.008],[.2,.2,.008],[-.2,.2,.008]]),faces=scene['floor_faces'],offset=-.008)]
        a=evaluate_scene(body,scene)
        self.assertAlmostEqual(a['floor_penetration_m'][0],.108)
        offsets=np.tile([1.,0,0],(61,1));b=evaluate_scene(body,scene,offsets)
        self.assertAlmostEqual(b['floor_penetration_m'][0],.1)

    def test_default_scene_solve_preserves_pose_and_does_not_correct_collisions(self):
        body,obs,scene=self.fixture()
        before=evaluate_scene(body,scene)
        delta,report=fit_smooth_residual(body,obs,scene_constraints=scene,max_scene_iterations=80)
        after=evaluate_scene(body,scene,delta)
        self.assertAlmostEqual(np.nanmax(after['floor_penetration_m']),np.nanmax(before['floor_penetration_m']))
        self.assertAlmostEqual(np.nanmax(after['object_max_penetration_m']),np.nanmax(before['object_max_penetration_m']))
        self.assertEqual(report['knots_seconds'][0],0.)
        self.assertAlmostEqual(report['knots_seconds'][-1],body['time_seconds'][50])
        v,j,_=move_fixed_size_body(body['vertices'],body['joints'],body['joints'][:,0]+delta)
        np.testing.assert_allclose(v-j[:,:1],body['vertices']-body['joints'][:,:1],atol=1e-12)

    def test_scene_solver_does_not_consume_inactive_geometry_or_heldout_depth_targets(self):
        body,obs,scene=self.fixture()
        a,_=fit_smooth_residual(body,obs,scene_constraints=scene,max_scene_iterations=50)
        body['vertices'][51:]=[-100,-100,-100];obs['root_targets'][~obs['train']]+=1000
        b,_=fit_smooth_residual(body,obs,scene_constraints=scene,max_scene_iterations=50)
        np.testing.assert_array_equal(a,b)

    def test_finite_floor_escape_is_rejected_by_coverage_gate(self):
        body,obs,scene=self.fixture();scene.update(path='unused',geometry_path='unused',source_blend='unused')
        values=evaluate_scene(body,scene,np.tile([10.,0,0],(61,1)))
        self.assertTrue((values['floor_support_outside_vertex_count'][:51]==1).all())
        self.assertTrue(np.isnan(values['floor_penetration_m'][:51]).all())

    def test_scene_loader_rejects_wrong_body_and_accepts_closed_exact_geometry(self):
        body,obs,scene=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);mesh=d/'geometry.npz';blend=d/'scene.blend';blend.write_bytes(b'synthetic scene fixture')
            c=scene['objects'][0];np.savez(mesh,floor__vertices=scene['floor_vertices'],floor__faces=scene['floor_faces'],box__vertices=c['vertices'],box__faces=c['faces'],box__planes=c['planes'])
            digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            spec=dict(schema_version=1,source_body_sha256='bodyhash',source_video_sha256='a'*64,source_actor_id='actor',room_basis_sha256='b'*64,
                      scope='all_active_vertices',reviewed_by='synthetic test',geometry_file=mesh.name,geometry_sha256=digest(mesh),source_blend=blend.name,source_blend_sha256=digest(blend),
                      floor=dict(key='floor',normal=[0,0,1],offset=0,coverage_vertex_indices=[0]),objects=[dict(name='box',key='box')],**scene['spec'])
            p=d/'scene.json';p.write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError,'exact initial body'):
                load_scene_constraints(p,body,'wrong')
            loaded=load_scene_constraints(p,body,'bodyhash')
            np.savez(d/'body_room.npz',**body)
            report=save_scene_metrics(d,body,loaded)
            self.assertFalse(report['accepted']);self.assertEqual(report['active_frames'],51)
            self.assertEqual(report['source_video_sha256'],'a'*64)
            saved=np.load(d/'scene_metrics.npz');self.assertTrue(np.isnan(saved['object_max_penetration_m'][51:]).all())
            self.assertEqual(json.loads((d/'scene_metrics.json').read_text())['rows'][51],dict(source_frame=51,time_seconds=1.7,active=False))

    def test_contact_series_distinguishes_training_objectives_and_derivative_endpoints(self):
        body, _, scene = self.fixture()
        body['vertices'][:] = [[-.1, 0, 0], [.1, 0, 0], [0, 0, .1]]
        body['vertices'][11, :2] = [[0, -.1, 0], [0, .1, 0]]
        event = np.zeros(61, bool); event[10:13] = True
        c = dict(name='plant', normal=np.array([0., 0, 1.]), plane_offset=0., kind='vertices', indices=np.array([0, 1]),
                 event_mask=event, train_ids=np.array([10]), plant_train_ids=np.array([10, 11]),
                 vertices=scene['floor_vertices'], faces=scene['floor_faces'], solids=[], target_gap_m=0.,
                 max_gap_m=.02, max_penetration_m=.01, weight=100., intervals=[[10, 13]], surface_sha256='surface',
                 plant=dict(weight=100., max_slip_m_s=.05))
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory); np.savez(d / 'body_room.npz', **body)
            for key in ('source_blend', 'geometry_path'):
                scene[key] = d / key; scene[key].write_bytes(b'synthetic')
            result = save_contact_series(d, body, [c], scene, contact_metrics(body, [c]))
            with np.load(d / 'contact_metrics.npz') as a:
                self.assertTrue(a['contact_gap_train_mask'][10, 0])
                self.assertFalse(a['contact_gap_train_mask'][11, 0])
                self.assertTrue(a['plant_train_endpoint_mask'][11, 0])
                self.assertFalse(a['union_constraint_train_mask'][12, 0])
                self.assertEqual(a['contact_cohort'][11, 0], 4)
                self.assertTrue(np.isnan(a['contact_point_slip_m_s'][10, 0]))
                self.assertGreater(a['contact_point_slip_m_s'][11, 0], 4.)
            derivative = next(s for s in result['series'] if s['field'] == 'contact_point_slip_m_s')
            self.assertEqual(derivative['acceptance_source_frames'], [11, 12])
            self.assertEqual(derivative['temporal_semantics'], 'adjacent_event_pair_ending_frame')
            self.assertEqual(derivative['threshold'], .05)
            self.assertEqual(result['contact_patch_provenance'][0]['plant_training_endpoint_pairs'], [[10, 11]])


if __name__=='__main__':unittest.main()
