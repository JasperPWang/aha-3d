"""Grounded non-flight actions must not bypass support when contacts are missing."""
import unittest
import numpy as np
import torch
from types import SimpleNamespace
from aha3d.motion.g1_interaction import ground_supported_root,support_report,scene_support_heights,fingertip_point,closed_mesh_point_depth

class GroundSupportTests(unittest.TestCase):
    def test_mesh_depth_respects_hollow_space_and_rotated_surfaces(self):
        import trimesh
        mesh=trimesh.creation.annulus(r_min=.5,r_max=1.,height=1.)
        points=np.array([[0.,0.,0.],[.75,0.,0.],[1.2,0.,0.]])
        depths=closed_mesh_point_depth(points,mesh)
        self.assertEqual(depths[0],0.)  # In the AABB, but in the empty hole.
        self.assertGreater(depths[1],.2)
        self.assertEqual(depths[2],0.)
        transform=trimesh.transformations.rotation_matrix(.71,[1,2,3]);mesh.apply_transform(transform)
        np.testing.assert_allclose(closed_mesh_point_depth(points@transform[:3,:3].T,mesh),depths,atol=1e-6)
    def test_fingertip_is_real_distal_surface_not_hand_centroid(self):
        # Lots of wrist vertices must not bias the selected contact inward.
        vertices=np.concatenate([np.tile([[0.,0.,.04]],(100,1)),
                                 [[-.01,0.,.17],[0.,.001,.172],[.01,0.,.17]]])
        tip=fingertip_point(vertices)
        self.assertGreaterEqual(tip[2],.169)
        self.assertTrue(np.any(np.all(vertices==tip,axis=1)))
        self.assertGreater(np.linalg.norm(tip-vertices.mean(0)),.1)
        with self.assertRaises(ValueError):fingertip_point(np.empty((0,3)))
    def test_floating_feet_and_swing_foot(self):
        root=torch.tensor([[0.,1.,0.],[0.,1.,0.]],requires_grad=True)
        joints=root[:,None]+torch.tensor([[[0.,-.6,0.],[1.,-.5,0.]],[[0.,-.8,0.],[1.,-.4,0.]]])
        rotations=torch.eye(3).expand(2,2,3,3)
        sole=torch.tensor([[0.,-.1,0.],[0.,0.,0.]])
        r,j,_=ground_supported_root(root,joints,rotations,[(0,sole),(1,sole)],torch.tensor([[.0,.0],[.03,.03]]))
        torch.testing.assert_close(j[:,0,1]-.1,torch.tensor([.001,.031]),atol=1e-6,rtol=0)
        torch.testing.assert_close(j[:,1,1]-j[:,0,1],torch.tensor([.1,.4]),atol=1e-6,rtol=0)
        torch.testing.assert_close(j-joints,(r-root)[:,None].expand_as(j))
        j.square().sum().backward();self.assertTrue(torch.isfinite(root.grad).all())
    def test_report_catches_middle_flight_with_zero_contacts(self):
        jp=np.zeros((5,2,3));jp[:,:,1]=np.array([.0,.4,.4,.4,.0])[:,None]
        m=dict(posed_joints=jp,global_rot_mats=np.tile(np.eye(3),(5,2,1,1)),foot_contacts=np.zeros((5,4)))
        sk=SimpleNamespace(bone_index={'left':0,'right':1});patches={s+'_sole':(s,np.zeros((1,3))) for s in ['left','right']}
        r=support_report(m,sk,patches,fps=30)
        self.assertEqual(r['first_frame_foot_gaps_m'],[0.,0.]);self.assertEqual(r['both_feet_over_2cm_frames'],[1,2,3]);self.assertAlmostEqual(r['maximum_airborne_seconds'],.1)
    def test_authored_finite_floor_and_rug(self):
        def square(name,z,size):
            m=np.eye(4);m[2,3]=z
            return dict(name=name,owner=None,matrix=m.T.reshape(-1).tolist(),positions=[0,0,0,size,0,0,size,size,0,0,size,0],groups=[dict(indices=[0,1,2,0,2,3])])
        scene={'meshes':[square('Floor',.2,2),square('Rug',.23,1)]}
        np.testing.assert_allclose(scene_support_heights(scene,[[.5,.5],[1.5,1.5]]),[.23,.2])
        with self.assertRaisesRegex(ValueError,'no authored floor'):
            scene_support_heights(scene,[[3,3]])
if __name__=='__main__':unittest.main()
