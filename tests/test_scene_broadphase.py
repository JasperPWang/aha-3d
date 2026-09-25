import unittest
from unittest.mock import patch
import numpy as np
from tools.gvhmr.full_scene_constraints import evaluate_scene,object_depth

class BroadPhase(unittest.TestCase):
 def test_disjoint_components_and_contact_boundaries_preserve_exact_results(self):
  v=np.array([[[0.,0.,.5],[.3,.2,.8]],[[10.,0,.5],[10.3,.2,.8]]]);body=dict(vertices=v,time_seconds=np.arange(2)/30,source_frame_indices=np.arange(2),track_active=np.ones(2,bool))
  def box(lo,hi):
   lo=np.asarray(lo);hi=np.asarray(hi);planes=np.vstack([np.c_[np.eye(3),-hi],np.c_[-np.eye(3),lo]])
   return dict(lower=lo,upper=hi,planes=planes,name='box')
  objects=[box([-.2,-.2,0],[.2,.2,1]),box([.3,-.2,0],[.6,.2,1]),box([100,100,0],[101,101,1])]
  scene=dict(objects=objects,floor_vertices=np.array([[-20,-20,0],[20,-20,0],[20,20,0],[-20,20,0]]),floor_faces=np.array([[0,1,2],[0,2,3]]),floor_offset=0,coverage_vertex_indices=np.array([0]),spec=dict(floor_weight=1,object_weight=1))
  expected=np.array([[object_depth(p,o)[0] for o in objects] for p in v])
  with patch('tools.gvhmr.full_scene_constraints.object_depth',wraps=object_depth) as fn:
   result=evaluate_scene(body,scene)
  np.testing.assert_array_equal(result['object_max_penetration_m'],expected)
  self.assertEqual(fn.call_count,2)
  d=np.zeros((2,3));value,grad=evaluate_scene(body,scene,d,objective=True)
  self.assertEqual(value,.2**2/2)
  np.testing.assert_array_equal(grad[1],0)
