import importlib.util
import unittest
import numpy as np

from tools.layout_inspection.object_outline import clip_plane, clipped, contours, object_color, silhouette


class OutlineMath(unittest.TestCase):
    def test_clip_crossing_triangle_retains_intersection(self):
        triangle = np.array([[[-2., 0, 0], [2., 0, 0], [0, 2, 0]]])
        result = clip_plane(triangle, 0, 0, 1)
        self.assertTrue((result[..., 0] <= 0).all())
        area = np.linalg.norm(np.cross(result[:, 1]-result[:, 0], result[:, 2]-result[:, 0]), axis=-1).sum()/2
        self.assertAlmostEqual(area, 2.)
        self.assertEqual(len(clipped(triangle, [[4,5],[-1,3],[-1,1]])), 0)

    def test_color_follows_identity_not_order(self):
        self.assertEqual(object_color('chair-1'), object_color('chair-1'))
        self.assertNotEqual(object_color('chair-1'), object_color('chair-2'))

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'Needs OpenCV')
    def test_external_contour_omits_internal_hole(self):
        mask = np.zeros((20,20), bool); mask[2:18,2:18] = True; mask[7:13,7:13] = False
        paths = contours(mask)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(paths[0]), 4)


@unittest.skipUnless(importlib.util.find_spec('open3d'), 'Needs Open3D')
class ProjectedOutlines(unittest.TestCase):
    def view(self, crop=None):
        return {'camera_matrix_world':np.diag([1,-1,-1,1]).tolist(),
                'settings': {'source_record': {'intrinsics': [[4,0,4.5],[0,4,4.5],[0,0,1]]},
                             'crop_xyz_m': crop or [[-10,10],[-10,10],[.1,10]]}}

    def square(self, z, radius):
        v=np.array([[-radius,-radius,z],[radius,-radius,z],[radius,radius,z],[-radius,radius,z]])
        return v[np.array([[0,1,2],[0,2,3]])]

    def test_each_object_has_full_silhouette(self):
        front=silhouette(self.square(2,.8), self.view(), 9,9,1)
        rear=silhouette(self.square(4,3), self.view(), 9,9,1)
        self.assertTrue(front[4,4] and rear[4,4])
        self.assertTrue(rear[4,6] and not front[4,6])
        self.assertFalse(front[0,0])

    def test_crop_is_applied_before_first_hit(self):
        both=np.concatenate([self.square(2,.8),self.square(4,3)])
        mask=silhouette(both,self.view([[-10,10],[-10,10],[3,5]]),9,9,1)
        self.assertTrue(mask[4,4])
        self.assertTrue(mask[4,6])

    def test_orthographic_pixel_basis(self):
        view={'camera_matrix_world':np.diag([1,-1,-1,1]).tolist(),
              'settings':{'ortho_scale':9,'crop_xyz_m':[[-10,10],[-10,10],[.1,10]]}}
        mask=silhouette(self.square(4,1.1),view,9,9,1)
        self.assertEqual(int(mask.sum()),9)
        self.assertTrue(mask[4,4])

    def test_displaced_geometry_moves_the_contour(self):
        triangles = self.square(4, 1.1)
        original = silhouette(triangles, self.view(), 9, 9, 1)
        shifted = silhouette(triangles + [2., 0., 0.], self.view(), 9, 9, 1)
        self.assertGreater(np.where(shifted)[1].mean(), np.where(original)[1].mean())
        self.assertFalse(np.array_equal(original, shifted))


if __name__ == '__main__': unittest.main()
