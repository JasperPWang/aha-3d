import math
import unittest
from lightmap_uv import pack_planar_charts

class LightmapUVTests(unittest.TestCase):
    def test_coplanar_split_and_opposite_faces(self):
        vertices=[(0,0,0),(2,0,0),(2,2,0),(0,2,0),(0,0,1),(2,0,1),(2,2,1)]
        faces=[(0,1,2),(0,2,3),(4,5,6),(2,1,0)]
        uv, report=pack_planar_charts(vertices,faces,[0]*4)
        self.assertEqual(report['charts'],3)
        self.assertEqual(uv[0][0],uv[1][0]);self.assertEqual(uv[0][2],uv[1][1])
        self.assertNotEqual(uv[0][0],uv[3][2])
        for corners in uv:
            for point in corners:
                self.assertTrue(all(math.isfinite(x) and 0<x<1 for x in point))
        self.assert_disjoint(report)

    def assert_disjoint(self, report):
        rectangles=report['rectangles'];n=report['resolution']
        for i,(x,y,w,h) in enumerate(rectangles):
            self.assertTrue(0<=x<x+w<=n and 0<=y<y+h<=n)
            for xx,yy,ww,hh in rectangles[:i]:
                self.assertTrue(x+w<=xx or xx+ww<=x or y+h<=yy or yy+hh<=y)

    def test_distinct_meshes_do_not_share_charts(self):
        vertices=[(0,0,0),(1,0,0),(0,1,0)]
        uv,report=pack_planar_charts(vertices,[(0,1,2)]*300,list(range(300)))
        self.assertEqual(report['charts'],300);self.assert_disjoint(report)
        self.assertLessEqual(report['packing_attempts'],64)

if __name__=='__main__':unittest.main()
