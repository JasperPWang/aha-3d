import unittest
import numpy as np
from tools.gvhmr.trajectory_evaluation import evaluate_arrays,split_sparse_indices

class EvaluationTests(unittest.TestCase):
    def args(self,fps=25):
        n=51;t=np.arange(n)/fps;v=np.zeros((n,4,3));v[:,:,2]=.01;j=v.copy()
        return dict(baseline_vertices=v,candidate_vertices=v.copy(),baseline_joints=j,candidate_joints=j.copy(),times=t,foot_ids=[[0,1],[2,3]],contact_masks={k:np.ones((n,2),bool) for k in ('model','observed')},valid=np.ones(n,bool),root_offsets=np.zeros((n,3)),bounds_xyz=[.5,.5,.1],sparse_indices=[0,10,20,30])
    def test_split(self):
        a,b=split_sparse_indices([30,0,20,10]);np.testing.assert_equal(a,[0,20]);np.testing.assert_equal(b,[10,30])
        with self.assertRaises(ValueError):split_sparse_indices([1,1])
    def test_root_only(self):
        a=self.args();a['root_offsets'][:,0]=.2
        for key in ('candidate_vertices','candidate_joints'):a[key]+=a['root_offsets'][:,None]
        r=evaluate_arrays(**a);self.assertTrue(r['root_only_geometry_verified']);self.assertFalse(r['accepted'])
        a['candidate_vertices'][0,0,0]+=.01;self.assertFalse(evaluate_arrays(**a)['root_only_geometry_verified'])
    def test_empty_unknown(self):
        a=self.args();a['contact_masks']['observed'][:]=False
        r=evaluate_arrays(**a)['contact']['observed'];self.assertEqual(r['status'],'unverified');self.assertIsNone(r['after_speed_m_s']['p90'])
    def test_fps(self):
        for fps in (25,30):
            a=self.args(fps);a['root_offsets'][:,0]=a['times']*.1
            for key in ('candidate_vertices','candidate_joints'):a[key]+=a['root_offsets'][:,None]
            r=evaluate_arrays(**a);self.assertAlmostEqual(r['contact']['model']['after_speed_m_s']['p90'],.1)
    def test_excluded_boundary(self):
        a=self.args();a['valid'][20]=False;a['candidate_vertices'][20]+=100;a['root_offsets'][20]+=100
        r=evaluate_arrays(**a);self.assertEqual(r['contact']['model']['after_speed_m_s']['p90'],0);self.assertEqual(r['after_foot_acceleration_m_s2']['maximum'],0);self.assertFalse(r['bounds_verified'])
    def test_heldout_independent(self):
        a=self.args();uv=np.zeros((51,12,2));pred=uv.copy();pred[10,:,0]=20
        a.update(observed_uv=uv,predicted_before_uv=uv,predicted_after_uv=pred,observed_mask=np.ones((51,12),bool))
        r=evaluate_arrays(**a)['independent_detector_projection'];self.assertEqual(r['train_times']['after_error_px']['maximum'],0);self.assertEqual(r['heldout_times']['after_error_px']['maximum'],20)
        a['predicted_after_uv'][10,0,0]=np.nan
        with self.assertRaises(ValueError):evaluate_arrays(**a)

if __name__=='__main__':unittest.main()
