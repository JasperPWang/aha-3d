import unittest
import numpy as np
from tools.layout_inspection.measure_mesh import fit_surface, measurement_support
class MeshMeasurementTests(unittest.TestCase):
 def test_display_context_cannot_become_measurement_support(self):
  faces=np.array([[0,1,2],[3,4,5]]);layers=np.array([0,2])
  eligible=np.array([True,True,False,True,True,True])
  np.testing.assert_array_equal(measurement_support(6,faces,layers,eligible),[True,True,False,False,False,False])
 def test_plane_with_outliers(self):
  rng=np.random.default_rng(5);xy=rng.uniform(-2,2,(300,2));z=.8+xy[:,0]*.2+rng.normal(0,.002,300)
  points=np.column_stack([xy,z]);points=np.concatenate([points,rng.uniform(-2,2,(80,3))])
  center,normal,good,residual=fit_surface(points)
  expected=np.array([-.2,0,1]);expected/=np.linalg.norm(expected)
  self.assertGreater(abs(normal@expected),.999);self.assertGreater(good[:300].mean(),.99);self.assertLess(good[300:].mean(),.1)
 def test_insufficient_surface_rejected(self):
  with self.assertRaises(ValueError):fit_surface(np.zeros((3,3)))
 def test_surface_orientation_rejects_dominant_neighbor_wall(self):
  rng=np.random.default_rng(2);xy=rng.uniform(-2,2,(400,2));roof=np.column_stack([xy,3+.7*xy[:,1]])
  yz=rng.uniform(-2,2,(600,2));wall=np.column_stack([np.zeros(600),yz]);points=np.concatenate([roof,wall])
  hint=np.array([0,-.7,1]);hint/=np.linalg.norm(hint)
  _,normal,good,_=fit_surface(points,normal_hint=hint)
  self.assertGreater(abs(normal@hint),.999);self.assertGreater(good[:400].mean(),.99)
if __name__=='__main__':unittest.main()
