"""Geometry checks require the configured Kimodo runtime; no model/GPU download."""
import unittest
import numpy as np
import torch
from aha3d.motion.g1_interaction import HingeRig,ROOM,validate_state_change


class G1HingeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kimodo.skeleton import G1Skeleton34
        cls.rig=HingeRig(G1Skeleton34())
    def test_hinge_limits_and_rotation_roundtrip(self):
        r=self.rig;n=8;base=torch.eye(3).repeat(n,r.sk.nbjoints,1,1)
        q=r.lo[None]+torch.linspace(.1,.9,n)[:,None]*(r.hi-r.lo)[None]
        local=r.decode(q,base);decoded=r.encode(local)
        np.testing.assert_allclose(decoded.numpy(),q.numpy(),atol=1e-5)
        np.testing.assert_allclose((local@local.transpose(-1,-2)).numpy(),np.broadcast_to(np.eye(3),local.shape),atol=1e-5)
        self.assertTrue(bool((torch.linalg.det(local)>.9999).all()))
    def test_root_orientation_is_preserved(self):
        from kimodo.geometry import angle_to_Y_rotation_matrix
        r=self.rig;base=torch.eye(3).repeat(3,r.sk.nbjoints,1,1)
        base[:,0]=angle_to_Y_rotation_matrix(torch.tensor([3.13,3.15,3.17]))
        local=r.decode(r.encode(base),base)
        self.assertTrue(torch.equal(local[:,0],base[:,0]))
    def test_room_basis_preserves_handedness(self):
        np.testing.assert_allclose(ROOM@ROOM.T,np.eye(3))
        self.assertAlmostEqual(float(np.linalg.det(ROOM)),1.)
    def test_state_change_and_contact_timing(self):
        plan=dict(fps=30,segments=[dict(seconds=4)],root_xy_keys=[[0,0,0],[4,0,0]],heading_keys=[[0,0],[4,0]],object_translation_keys=[[0,0,0,0],[4,0,0,0]],hand_contact_seconds=[1,3],hand_surface_point=[0,0,1])
        with self.assertRaisesRegex(ValueError,'must change'):validate_state_change(plan)
        plan['object_translation_keys']=[[0,0,0,0],[1.5,0,0,0],[2.5,.3,0,0],[4,.3,0,0]]
        validate_state_change(plan)
        plan['hand_contact_seconds']=[2,3]
        with self.assertRaisesRegex(ValueError,'outside planned'):validate_state_change(plan)


if __name__=='__main__':unittest.main()
