import unittest
import numpy as np

from tools.gvhmr.foot_contacts import prepare, objective, metrics
from tools.gvhmr.full_scene_constraints import solve_scene_coefficients
from tools.gvhmr.root_constraints import spline_basis


class PredictedFootTests(unittest.TestCase):
    def fixture(self):
        n = 31; t = np.arange(n)/30
        body = dict(time_seconds=t, source_frame_indices=np.arange(n), track_active=np.ones(n, bool),
                    vertices=np.zeros((n, 5, 3)), joints=np.zeros((n, 12, 3)))
        body['vertices'][:, 4, 0] = .2*t
        floor = np.array([[-2., -2, 0], [2, -2, 0], [2, 2, 0], [-2, 2, 0]])
        scene = dict(floor_vertices=floor, floor_faces=np.array([[0,1,2], [0,2,3]]), floor_offset=0.,
                     coverage_vertex_indices=np.arange(4), objects=[], spec=dict(floor_weight=100., object_weight=100.))
        foot = prepare(body, np.ones((n, 4)), [[0], [1], [2], [3]], scene)
        return body, scene, foot

    def test_exact_gradient_and_contact_release(self):
        body, scene, _ = self.fixture()
        body['track_active'][25:] = False
        conf = np.ones((31,4)); conf[10:15] = .5
        foot = prepare(body, conf, [[0],[1],[2],[3]], scene)
        d = np.random.default_rng(4).normal(0, .01, (31,3))
        _, grad = objective(foot, d)
        for frame in [0, 5, 10, 14, 15, 24, 25, 30]:
            for axis in range(3):
                a=d.copy(); b=d.copy(); a[frame,axis]+=1e-6; b[frame,axis]-=1e-6
                fd=(objective(foot,a)[0]-objective(foot,b)[0])/2e-6
                self.assertAlmostEqual(fd,grad[frame,axis],places=5)
        np.testing.assert_array_equal(grad[10:15],0)
        np.testing.assert_array_equal(grad[25:],0)
        self.assertEqual(foot['pairs'][9:15].sum(),0)

    def test_joint_scene_solve_preserves_foot_when_hand_wants_root_motion(self):
        body, scene, foot = self.fixture()
        t=body['time_seconds']; B,D2,_,_,_=spline_basis(t,np.arange(31),.5)
        contact=dict(train_ids=np.arange(31),kind='vertices',indices=np.array([4]),normal=np.array([1.,0,0]),
                     plane_offset=0.,weight=10.,target_gap_m=0.,vertices=np.array([[0,-2,-2],[0,2,-2],[0,2,2],[0,-2,2.]]),
                     faces=np.array([[0,1,2],[0,2,3]]))
        A=np.vstack([.01*B,.01*D2]); initial=np.zeros((B.shape[1],3)); target=np.zeros((len(A),3))
        old,_=solve_scene_coefficients(body,scene,[contact],B,A,target,initial)
        new,_=solve_scene_coefficients(body,scene,[contact],B,A,target,initial,foot_contacts=foot)
        old_speed=np.linalg.norm(np.diff(B@old,axis=0),axis=-1).mean()*30
        new_speed=np.linalg.norm(np.diff(B@new,axis=0),axis=-1).mean()*30
        self.assertGreater(old_speed,.1)
        self.assertLess(new_speed,old_speed/20)
        result=dict(body,vertices=body['vertices']+(B@new)[:,None],joints=body['joints']+(B@new)[:,None])
        report,_=metrics(result,foot)
        self.assertLess(report['support_abs_height_mean_m'],.003)
        self.assertEqual(report['support_outside_floor_samples'],0)

    def test_invalid_evidence_is_rejected(self):
        body,scene,_=self.fixture()
        with self.assertRaisesRegex(ValueError,'probabilities'):
            prepare(body,np.full((31,4),np.nan),[[0],[1],[2],[3]],scene)
        with self.assertRaisesRegex(ValueError,'nonempty'):
            prepare(body,np.ones((31,4)),[[],[1],[2],[3]],scene)
