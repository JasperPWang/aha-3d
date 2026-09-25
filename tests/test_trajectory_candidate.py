import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/gvhmr'))
from trajectory_candidate import propose_trajectory,evaluate_offsets
from placement_diagnostics import SMPL,COCO,project


def fixture(fps=24,seconds=3):
    t=np.arange(int(fps*seconds))/fps;n=len(t)
    j=np.zeros((n,22,3));j[:,:,2]=4
    for k in range(22):j[:,k,0]=(k%2-.5)*.3;j[:,k,1]=((k//2)%6-2.5)*.18
    C=np.tile(np.eye(4),(n,1,1));K=np.tile(np.array([[650.,0,640],[0,650.,360],[0,0,1]]),(n,1,1))
    uv,_=project(j[:,SMPL],C,K);kp=np.zeros((n,17,3));kp[:,COCO,:2]=uv;kp[:,COCO,2]=.99
    return j,t,C,K,kp


class TrajectoryProposal(unittest.TestCase):
    def test_smooth_drift_recovered_variable_fps(self):
        for fps in (24,30):
            j,t,C,K,kp=fixture(fps)
            drift=.20*np.sin(np.pi*t/t[-1])**2
            wrong=j.copy();wrong[:,:,0]+=drift[:,None]
            proposal=propose_trajectory(wrong,t,C,K,kp,t,[1280,720])
            self.assertLess(proposal['report']['after']['p90_px'],proposal['report']['before']['p90_px']*.3)
            self.assertLess(np.sqrt(np.mean((proposal['offsets_world'][:,0]+drift)**2)),.04)
            self.assertFalse(proposal['report']['accepted'])
            self.assertTrue(proposal['report']['proposal_only'])
    def test_clean_noop_and_inputs_unchanged(self):
        j,t,C,K,kp=fixture();original=j.copy()
        p=propose_trajectory(j,t,C,K,kp,t,[1280,720])
        np.testing.assert_allclose(p['offsets_world'],0,atol=1e-9)
        np.testing.assert_array_equal(j,original)
    def test_insufficient_observation_rejected(self):
        j,t,C,K,kp=fixture();kp[:,:,2]=0;kp[:2,COCO,2]=.99
        with self.assertRaisesRegex(ValueError,'Insufficient'):propose_trajectory(j,t,C,K,kp,t,[1280,720])
    def test_z_and_bone_lengths_exactly_preserved(self):
        j,t,C,K,kp=fixture();wrong=j.copy();wrong[:,:,0]+=.15
        p=propose_trajectory(wrong,t,C,K,kp,t,[1280,720]);moved=wrong+p['offsets_world'][:,None,:]
        np.testing.assert_array_equal(moved[:,:,2],wrong[:,:,2])
        np.testing.assert_allclose(np.diff(moved,axis=1),np.diff(wrong,axis=1),atol=1e-14)
    def test_extrapolation_holds_observed_endpoint_offsets(self):
        j,t,C,K,kp=fixture();kp[:12,:,2]=0;kp[-12:,:,2]=0;j[:,:,0]+=.1
        p=propose_trajectory(j,t,C,K,kp,t,[1280,720]);o=p['offsets_world']
        np.testing.assert_allclose(o[:12],np.tile(o[12],(12,1)),atol=1e-14)
        np.testing.assert_allclose(o[-12:],np.tile(o[-13],(12,1)),atol=1e-14)
        native=evaluate_offsets(p['knot_times'],p['knot_xy'],np.linspace(-1,4,151))
        np.testing.assert_array_equal(native[:,2],0)
    def test_stationary_foot_cohort_is_not_reselected_after_correction(self):
        j,t,C,K,kp=fixture()
        kp[:,COCO,0]+=(30*np.sin(np.pi*t/t[-1])**2)[:,None]
        p=propose_trajectory(j,t,C,K,kp,t,[1280,720]);f=p['report']['baseline_stationary_foot_cohort']
        self.assertGreater(f['total_samples'],0)
        self.assertEqual(f['baseline']['samples'],f['candidate']['samples'])
        self.assertLess(f['baseline']['p90_mps'],1e-10)
        self.assertGreater(f['candidate']['p90_mps'],.01)
    def test_bad_timing_rejected(self):
        j,t,C,K,kp=fixture();t[10]+=.01
        with self.assertRaises(ValueError):propose_trajectory(j,t,C,K,kp,t,[1280,720])
if __name__=='__main__':unittest.main()
