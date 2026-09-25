import unittest
import numpy as np
from tools.gvhmr.dense_anchors import collect_clip_anchors,anchor_candidates,sample_keypoint_surface,root_target_from_surface,robust_translation

class DenseAnchors(unittest.TestCase):
    def test_wrist_only_is_not_discarded(self):
        k=np.zeros((17,3));k[9]=[30,20,.9]
        c=anchor_candidates(k);self.assertEqual([a['name'] for a in c],['left_wrist'])
    def test_whole_clip_low_scores_still_produce_weak_anchors(self):
        k=np.zeros((4,17,3));k[:,9]=[30,20,.05]
        calls=[]
        def collect(frame,candidate):
            calls.append(candidate);return dict(target=[1.,2.,3.])
        rows=collect_clip_anchors(k,collect)
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r['keypoint_evidence']=='weak_keypoint' for r in rows))
        self.assertTrue(all(0<r['keypoint_weight']<.01 for r in rows))
    def test_failed_strong_depth_still_tries_weak_keypoint(self):
        k=np.zeros((3,17,3));k[:,[11,12]]=[30,20,.9];k[:,9]=[10,10,.1]
        rows=collect_clip_anchors(k,lambda f,c:dict(target=[0,0,0]) if c['name']=='left_wrist' else None)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['anchor']=='left_wrist' for r in rows))
    def test_zero_score_prediction_is_distinct_from_missing_sentinel(self):
        k=np.zeros((17,3));k[9]=[30,20,0.]
        rows=anchor_candidates(k,allow_weak=True)
        self.assertEqual(len(rows),1);self.assertGreater(rows[0]['weight'],0)
        self.assertEqual(anchor_candidates(np.zeros((17,3)),allow_weak=True),[])
    def test_pair_priority_retains_single_joint_fallback(self):
        k=np.zeros((17,3));k[[11,12,5,6,9],2]=.9
        self.assertEqual([a['name'] for a in anchor_candidates(k)][:2],['hips','shoulders'])
        self.assertIn('left_wrist',[a['name'] for a in anchor_candidates(k)])
    def test_low_depth_confidence_is_weighted_not_dropped(self):
        z=np.ones((15,15))*2;mask=np.ones((15,15),bool)
        point,detail=sample_keypoint_surface(z,np.full_like(z,-2.),mask,mask,[7,7],np.eye(3),np.eye(4))
        self.assertIsNotNone(point);self.assertTrue(detail['weak_depth'])
        self.assertGreater(detail['weight'],0);self.assertLess(detail['weight'],.5)
    def test_thin_limb_keeps_depth_and_excludes_background(self):
        z=np.full((15,15),9.);mask=np.zeros((15,15),bool);mask[3:12,7]=True;z[mask]=2.
        point,detail=sample_keypoint_surface(z,np.ones_like(z),np.ones_like(mask),mask,[7,7],np.eye(3),np.eye(4))
        self.assertAlmostEqual(point[2],2.);self.assertTrue(detail['valid'])
    def test_surface_to_root_keeps_limb_offset(self):
        # Hand lies one metre right of root; its front surface is 0.1 m nearer.
        verts=np.array([[.9,-.1,-.1],[1.1,-.1,-.1],[1.,.1,-.1]])
        target=root_target_from_surface(np.array([1.,0.,4.9]),(verts,np.array([[0,1,2]])),np.zeros(3),np.array([1.,0.,0.]),np.array([.2,0.]),np.eye(3),np.eye(4),5.)
        np.testing.assert_allclose(target,[.02,0.,5.],atol=1e-6)
    def test_robust_fit_does_not_follow_low_confidence_outlier(self):
        values=np.array([[1,2,0],[1.01,2,0],[.99,2,0],[50,50,10]])
        fitted=robust_translation(values,[1,1,1,.01]);self.assertLess(np.linalg.norm(fitted-[1,2,0]),.01)

if __name__=='__main__':unittest.main()
