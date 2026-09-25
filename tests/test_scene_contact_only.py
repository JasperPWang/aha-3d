"""Contact-only fitting retains contact objectives without invoking collision repair."""
import unittest
from unittest.mock import patch
import numpy as np
from tools.gvhmr.full_scene_constraints import solve_scene_coefficients
from tools.gvhmr.root_constraints import spline_basis
from tools.gvhmr.foot_contacts import prepare

class ContactOnlyTests(unittest.TestCase):
    def test_hand_and_foot_contacts_are_fitted_without_collision_objectives(self):
        n=61;t=np.arange(n)/30
        vertices=np.tile([[0.,0.,.1],[0.,0.,.1],[0.,0.,.1],[0.,0.,.1],[.2,0.,1.]],(n,1,1))
        body=dict(vertices=vertices,joints=np.tile([0.,0.,.1],(n,12,1)),time_seconds=t,source_frame_indices=np.arange(n),track_active=np.ones(n,bool))
        floor=np.array([[-2.,-2.,0],[2.,-2.,0],[2.,2.,0],[-2.,2.,0]])
        scene=dict(floor_offset=0.,floor_vertices=floor,floor_faces=np.array([[0,1,2],[0,2,3]]))
        foot=prepare(body,np.ones((n,4)),[np.array([i]) for i in range(4)],scene,height_weight=1000.)
        face=np.array([[0.,-2.,0],[0.,2.,0],[0.,2.,2],[0.,-2.,2]])
        contact=dict(kind='vertices',indices=np.array([4]),train_ids=np.arange(n),normal=np.array([1.,0.,0]),plane_offset=0.,vertices=face,faces=scene['floor_faces'],weight=1000.,target_gap_m=0.)
        B,D2,_,_,_=spline_basis(t,[0,n-1],.4);A=np.vstack([B/np.sqrt(n),D2*np.sqrt(20/n)]);target=np.zeros((2*n,3))
        with patch('tools.gvhmr.full_scene_constraints.evaluate_scene',side_effect=AssertionError('Collision objective must not run')):
            coefficients,report=solve_scene_coefficients(body,scene,[contact],B,A,target,np.zeros((B.shape[1],3)),foot_contacts=foot,max_iterations=200)
        delta=B@coefficients
        self.assertFalse(report['collision_correction'])
        self.assertLess(np.max(abs(.2+delta[:,0])),.001)
        self.assertLess(np.max(abs(.1+delta[:,2]-.002)),.001)
        self.assertLess(np.max(np.linalg.norm(np.diff(delta,axis=0),axis=1)),1e-5)
        updated=vertices+delta[:,None]
        np.testing.assert_allclose(updated-updated[:,:1],vertices-vertices[:,:1],atol=1e-12)

if __name__=='__main__':unittest.main()
