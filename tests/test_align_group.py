"""Synthetic calibration invariants; no licensed model files required."""
import unittest
import numpy as np
from tools.gvhmr.align_group import gravity_rotation, project, fit_group, apparent_height_ratios, pose_evidence_mask

UP=np.array([[1.,0,0],[0,0,-1],[0,1,0]])


class SharedAlignmentTests(unittest.TestCase):
    def test_yaw_preserves_gravity_and_lengths(self):
        for yaw in (-2.,0.,1.3):
            R=gravity_rotation(yaw,UP)
            np.testing.assert_allclose(R@[0,1,0],[0,0,1],atol=1e-12)
            np.testing.assert_allclose(R.T@R,np.eye(3),atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(R),1.)

    def test_group_preserves_native_dimensions_and_constant_transforms(self):
        frames=8
        camera=np.tile(np.eye(4),(frames,1,1))
        camera[:,:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
        camera[:,:3,3]=[0,-5,1.5]
        K=np.tile([[800.,0,640],[0,800,360],[0,0,1]],(frames,1,1))
        actors=[]
        scale=1.
        for i,yaw in enumerate((.2,-.3)):
            j=np.zeros((frames,22,3));j[:,:,1]=np.linspace(0,1.8,22)
            j[:,:,0]=.15*np.sin(np.arange(22))[None,:]+np.arange(frames)[:,None]*.03
            j[:,:,2]=.1*np.cos(np.arange(22))[None,:]
            R=gravity_rotation(yaw,UP);translation=np.array([-.8+i*1.8,3+i,.005])
            world=scale*(j@R.T)+translation
            uv,depth=project(world,camera,K)
            self.assertTrue((depth>0).all())
            actors.append(dict(native_joints=j,native_vertices=j.copy(),valid=np.ones(frames,bool),joint_valid=np.ones((frames,22),bool),target=uv,
                old=dict(rotation=R.tolist(),translation=translation.tolist(),body_scale=(.7,1.4)[i])))
        fit,world_fn,_=fit_group(actors,camera,K,dict(up_rotation=UP.tolist()))
        self.assertTrue(fit.success)
        self.assertEqual(len(fit.x),3*len(actors))
        for i,actor in enumerate(actors):
            world,R,t=world_fn(fit.x,i)
            np.testing.assert_allclose(project(world,camera,K)[0],actor['target'],atol=1e-3)
            np.testing.assert_allclose(np.diff(world,axis=0),scale*(np.diff(actor['native_joints'],axis=0)@R.T),atol=1e-6)
            np.testing.assert_allclose(np.linalg.norm(world[:,15]-world[:,0],axis=1),np.linalg.norm(actor['native_joints'][:,15]-actor['native_joints'][:,0],axis=1),atol=1e-10)
            self.assertAlmostEqual(t[2],.005,places=6)

    def test_height_uses_head_and_feet_only_on_fullbody_frames(self):
        target=np.zeros((3,22,2));target[:,15,1]=100;target[:,[10,11],1]=400
        projected=target.copy();projected[:,[10,11],1]=430
        target[:,20,1]=-10000  # Hands cannot redefine anatomical image height.
        valid=np.ones((3,22),bool);valid[1,10]=False;valid[2,15]=False
        ratios,frames=apparent_height_ratios(target,projected,valid)
        np.testing.assert_allclose(ratios,[1.1]);np.testing.assert_array_equal(frames,[True,False,False])

    def test_scale_fitting_configuration_is_rejected(self):
        for key,value in [('scale_anchor',.9),('scale_bounds',[.5,2]),('scale_prior_sigma',.15),('body_scale',1.),('shared_scale',1.),('optimize_scale',False)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                fit_group([],np.empty((0,4,4)),np.empty((0,3,3)),dict(up_rotation=UP.tolist(),**{key:value}))

    def test_pose_confidence_masks_low_scores_and_maps_both_feet(self):
        kp=np.ones((4,17,3));kp[:,:,:2]=100.;kp[:,:,2]=.9;kp[1,15,2]=.4
        nt=np.arange(4)/30
        mask,report=pose_evidence_mask(kp,nt,nt,[1280,720])
        self.assertFalse(mask[1,7]);self.assertFalse(mask[1,10]);self.assertTrue(mask[1,8]);self.assertTrue(mask[1,11])
        self.assertEqual(report['maximum_time_error_seconds'],0.)

    def test_unmatched_confidence_timestamps_fail(self):
        kp=np.ones((4,17,3));kp[:,:,:2]=100.
        with self.assertRaises(ValueError):pose_evidence_mask(kp,np.arange(4)/30,np.array([0.,.5]),[1280,720])

    def test_improper_up_mapping_rejected(self):
        with self.assertRaises(ValueError):
            fit_group([],np.empty((0,4,4)),np.empty((0,3,3)),dict(up_rotation=np.eye(3).tolist()))


if __name__=='__main__':unittest.main()
