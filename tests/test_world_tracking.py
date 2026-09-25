"""Behavioral checks for the optional skill's bbox quality gate."""
import unittest
import numpy as np
from tools.gvhmr.world_tracking import gate_trailing_max, track_end

class WorldTrackingTests(unittest.TestCase):
    def test_rejects_thin_mask_with_plausible_box(self):
        boxes=np.tile([0,0,100,200.],(40,1))
        area=np.full(40,10000.);area[10:35]=100
        keep=gate_trailing_max(boxes,np.ones(40,bool),area=area)
        self.assertTrue(keep[:10].all());self.assertFalse(keep[10:35].any())
        self.assertTrue(keep[35:].all());self.assertIsNone(track_end(keep))

    def test_receding_full_person_not_rejected_by_raw_area(self):
        scale=np.linspace(1,.3,90)
        boxes=np.array([0,0,100,200.])[None]*scale[:,None]
        area=10000*scale**2
        self.assertTrue(gate_trailing_max(boxes,np.ones(90,bool),area=area).all())

    def test_long_collapse_does_not_become_new_reference(self):
        boxes=np.tile([0,0,100,200.],(90,1));boxes[10:]*=.1
        keep=gate_trailing_max(boxes,np.ones(90,bool),area=(boxes[:,2]*boxes[:,3]/2))
        self.assertEqual(track_end(keep),10)
        self.assertFalse(keep[10:].any())

if __name__=='__main__':unittest.main()
