"""Coordinate adapter tests against native constraints on both skeletons."""
import unittest
from types import SimpleNamespace
import numpy as np
import torch
from aha3d.motion.kimodo_frame import rotate_features, translate_features, sample_in_local_frame


class LocalFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kimodo.skeleton import G1Skeleton34,SMPLXSkeleton22
        from kimodo.motion_rep.reps.kimodo_motionrep import KimodoMotionRep
        from kimodo.motion_rep.stats import Stats
        cls.reps=[KimodoMotionRep(sk(),30) for sk in (G1Skeleton34,SMPLXSkeleton22)]
        for rep in cls.reps:
            rep.stats = Stats(load=False)
            rep.stats.register_from_tensors(torch.linspace(-.2,.2,rep.motion_rep_dim),torch.ones(rep.motion_rep_dim))

    def fixture(self,rep):
        from kimodo.geometry import angle_to_Y_rotation_matrix
        from kimodo.constraints import Root2DConstraintSet,RightHandConstraintSet
        from kimodo.motion_rep.conditioning import build_condition_dicts
        sk=rep.skeleton;theta=torch.tensor(1.2);R=angle_to_Y_rotation_matrix(theta)
        local=torch.eye(3).repeat(3,sk.nbjoints,1,1);local[:,0]=R
        root=torch.tensor([[2.,.83,-3.],[2.1,.85,-2.9],[2.2,.82,-2.8]])
        gr,jp,_=sk.fk(local,root);ids=torch.arange(3)
        constraints=[Root2DConstraintSet(sk,ids,root[:,[0,2]]),RightHandConstraintSet(sk,ids,jp,gr,root[:,[0,2]])]
        indices,data=build_condition_dicts(constraints)
        obs,mask=rep.create_conditions(indices,data,3,False,'cpu')
        return obs[None],mask[None],theta,R,jp

    def test_native_hand_constraints_transform_and_restore(self):
        for rep in self.reps:
            with self.subTest(skeleton=rep.skeleton.name):
                obs,mask,theta,R,jp=self.fixture(rep);receipt={};seen={};original_mask=mask.clone()
                def sample(texts,n,**kw):
                    self.assertTrue(torch.equal(kw['first_heading_angle'],torch.zeros(1)))
                    value=rep.unnormalize(kw['observed_motion']);seen['obs']=value
                    self.assertTrue(torch.isfinite(value).all())
                    decoded=rep.inverse(value,False,posed_joints_from='positions')
                    wrist=rep.skeleton.bone_index[rep.skeleton.right_hand_joint_names[0]]
                    target=(jp[:,wrist]-torch.tensor([2.,0.,-3.]))@R
                    np.testing.assert_allclose(decoded['posed_joints'][0,:,wrist],target,atol=2e-6)
                    # A neutral sampler proves no coordinate drift is introduced.
                    return kw['observed_motion']
                restored=sample_in_local_frame(SimpleNamespace(motion_rep=rep),sample,['A person reaches'],3,
                    receipt=receipt,observed_motion=rep.normalize(obs),motion_mask=mask,first_heading_angle=theta)
                np.testing.assert_allclose(rep.unnormalize(restored)[mask],obs[mask],atol=2e-6)
                np.testing.assert_allclose(receipt['sampler_first_root_xz'],0.,atol=1e-7)
                self.assertLess(receipt['masked_roundtrip_max_error'],2e-6)
                self.assertEqual(receipt['sampler_heading_radians'],[0.])
                self.assertTrue(torch.equal(mask,original_mask))

    def test_raw_sixd_columns_and_contact_values_survive_inverse(self):
        for rep in self.reps:
            x=torch.randn(2,7,rep.motion_rep_dim)
            theta=torch.tensor([2.3,-1.7])
            y=rotate_features(rep,rotate_features(rep,x,-theta),theta)
            np.testing.assert_allclose(y,x,atol=1e-6)
            sl=rep.slice_dict['foot_contacts'];self.assertTrue(torch.equal(x[...,sl],y[...,sl]))
            # Exact native column convention, no SO(3) projection in this transform.
            z=rotate_features(rep,torch.zeros_like(x),theta)
            self.assertTrue(torch.equal(z,torch.zeros_like(z)))

    def test_scene_placement_does_not_change_sampler_constraints(self):
        for rep in self.reps:
            obs,mask,theta,_,_=self.fixture(rep)
            yaw=torch.tensor([-.8]);offset=torch.tensor([[7.,-4.]])
            moved=translate_features(rep,rotate_features(rep,obs,yaw),offset)
            moved=torch.where(mask,moved,0.)
            captured=[]
            def sample(texts,n,**kw):
                captured.append(rep.unnormalize(kw['observed_motion']))
                return kw['observed_motion']
            for value,heading in [(obs,theta),(moved,theta+yaw)]:
                sample_in_local_frame(SimpleNamespace(motion_rep=rep),sample,[],3,
                    observed_motion=rep.normalize(value),motion_mask=mask,first_heading_angle=heading)
            np.testing.assert_allclose(captured[0],captured[1],atol=2e-6)

    def test_masks_cannot_invent_missing_planar_coordinates(self):
        rep=self.reps[0];obs,mask,theta,_,_=self.fixture(rep)
        mask[:,0,rep.slice_dict['smooth_root_pos'].start+2]=False
        with self.assertRaisesRegex(ValueError,'unpaired X/Z'):
            sample_in_local_frame(SimpleNamespace(motion_rep=rep),None,[],3,
                observed_motion=rep.normalize(obs),motion_mask=mask,first_heading_angle=theta)

    def test_global_rotation_uses_left_product_and_height_unchanged(self):
        from kimodo.geometry import angle_to_Y_rotation_matrix,matrix_to_cont6d,cont6d_to_matrix
        rep=self.reps[0];x=torch.zeros(1,2,rep.motion_rep_dim);r=angle_to_Y_rotation_matrix(torch.tensor(.7))
        x[...,rep.slice_dict['global_rot_data']]=matrix_to_cont6d(r).repeat(rep.nbjoints)
        x[...,rep.slice_dict['global_root_heading']]=torch.tensor([np.cos(.7),np.sin(.7)])
        x[...,rep.slice_dict['smooth_root_pos']]=torch.tensor([2.,.83,1.])
        result=rotate_features(rep,x,torch.tensor([-.7]));m=cont6d_to_matrix(result[...,rep.slice_dict['global_rot_data']].reshape(1,2,-1,6))
        np.testing.assert_allclose(m,np.broadcast_to(np.eye(3),m.shape),atol=1e-6)
        np.testing.assert_allclose(result[...,rep.slice_dict['global_root_heading']],[[[1.,0.],[1.,0.]]],atol=1e-6)
        self.assertTrue(torch.equal(result[...,rep.slice_dict['smooth_root_pos']][...,1],x[...,rep.slice_dict['smooth_root_pos']][...,1]))

if __name__=='__main__':unittest.main()
