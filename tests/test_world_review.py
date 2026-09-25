import unittest
import numpy as np
from tools.gvhmr.world_review import yaw_xz_alignment

class WorldReviewTests(unittest.TestCase):
    def test_recovers_yaw_and_xz_without_changing_height_or_scale(self):
        source=np.array([[0.,1.,0.],[2.,1.1,0.],[2.,1.2,1.],[1.,1.3,2.]])
        angle=.7;c,s=np.cos(angle),np.sin(angle)
        r=np.array([[c,0,s],[0,1,0],[-s,0,c]])
        target=source@r.T+[3,5,-2]
        rotation,translation=yaw_xz_alignment(source,target)
        np.testing.assert_allclose(rotation,r,atol=1e-12)
        np.testing.assert_allclose(translation,[3,0,-2],atol=1e-12)
        transformed=source@rotation.T+translation
        np.testing.assert_allclose(transformed[:,1],source[:,1])
        np.testing.assert_allclose(np.linalg.norm(np.diff(transformed,axis=0),axis=1),np.linalg.norm(np.diff(source,axis=0),axis=1))
