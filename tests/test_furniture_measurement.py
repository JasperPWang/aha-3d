"""Numerical geometry, selector identity, failure and export contract checks."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from aha3d.io import digest, write
from aha3d.workflow.furniture import (MeasurementSession, evaluate, fit_plane,
                                               polygon_gap, ray_plane, rectangle_xy, sam3_selector)


class FurnitureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root/'bundle'; self.bundle.mkdir()
        self.make_bundle()

    def make_bundle(self, transform=None, corrupt_camera=False):
        T = np.eye(4) if transform is None else transform
        K = np.array([[80., 0, 39.5], [0, 80, 29.5], [0, 0, 1.]])
        pose = np.eye(4); pose[:3, :3] = np.diag([1., -1, -1]); pose[:3, 3] = [.3, -.4, 3.]
        vv, uu = np.mgrid[:60, :80]
        rays = np.stack([uu, vv, np.ones_like(uu)], -1) @ np.linalg.inv(K).T @ pose[:3, :3].T
        depth = np.full((60, 80), 3.); depth[15:46, 15:66] = 2.25
        xyz = pose[:3, 3] + rays*depth[..., None]
        aligned = T @ pose
        if corrupt_camera:
            aligned = aligned.copy(); aligned[0, 3] += .1
        write(self.bundle/'inputs.json', dict(frame_indices=[207], timestamps_seconds=[8.633625],
              processed_size_wh=[80, 60], source_sha256='fixture'))
        write(self.bundle/'cameras.json', dict(world_transform=T.tolist(), frames=[dict(
              source_frame=207, timestamp_seconds=8.633625, c2w=aligned.tolist(), intrinsics=K.tolist())]))
        np.savez(self.bundle/'predictions.npz', points=xyz[None], conf=np.full((1, 60, 80, 1), 4.),
                 non_edge=np.ones((1, 60, 80), bool), camera_poses=pose[None])
        (self.bundle/'frames').mkdir(exist_ok=True)
        Image.new('RGB', (80, 60), 'gray').save(self.bundle/'frames/000207.jpg')

    def request(self):
        return dict(id='table', source_frame=207, floor_reference='Fixture floor Z=0',
                    selector=dict(corners_uv=[[15, 15], [65, 15], [65, 45], [15, 45]]))

    def test_corner_dimensions_and_height_from_known_camera(self):
        result = MeasurementSession(self.bundle).measure(self.request())
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], [1.40625, .84375], atol=1e-7)
        self.assertAlmostEqual(result['surface_height_m'], .75)
        np.testing.assert_allclose(result['corner_xyz_m'][0], [-.3890625, .0078125, .75], atol=1e-7)

    def test_rigid_transform_preserves_dimensions_and_moves_center(self):
        original = MeasurementSession(self.bundle).measure(self.request())
        angle = np.deg2rad(37); T = np.eye(4)
        T[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
        T[:3, 3] = [4, -3, .1]
        self.make_bundle(T)
        result = MeasurementSession(self.bundle).measure(self.request())
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], original['rectangle']['size_xy_m'])
        np.testing.assert_allclose(result['rectangle']['center_xy_m'],
            np.asarray(original['rectangle']['center_xy_m']) @ T[:2, :2].T+T[:2, 3])
        self.assertAlmostEqual(result['surface_height_m'], .85)
        self.assertAlmostEqual(result['rectangle']['yaw_deg'], 37)

    def test_box_and_binary_mask_agree_and_remain_observed_extents(self):
        req = self.request(); req['selector'] = dict(box_xyxy=[15, 15, 66, 46])
        session = MeasurementSession(self.bundle); box = session.measure(req)
        mask = np.zeros((60, 80), np.uint8); mask[15:46, 15:66] = 255
        Image.fromarray(mask).save(self.root/'mask.png')
        req['selector'] = dict(mask='mask.png', image_sha256=digest(self.bundle/'frames/000207.jpg'), method='synthetic fixture')
        result = session.measure(req, self.root)
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], box['rectangle']['size_xy_m'])
        self.assertEqual(result['measurement_basis'], 'observed_surface_extent')
        self.assertIn('sha256', result['mask_provenance'])

    def test_mask_rejects_wrong_source_and_wrong_raster(self):
        req = self.request(); session = MeasurementSession(self.bundle)
        Image.new('L', (160, 120), 255).save(self.root/'mask.png')
        req['selector'] = dict(mask=str(self.root/'mask.png'), image_sha256='wrong', method='fixture')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): session.measure(req)
        req['selector']['image_sha256'] = digest(self.bundle/'frames/000207.jpg')
        with self.assertRaisesRegex(ValueError, 'resolution'): session.measure(req)

    def test_invalid_frame_floor_corners_and_camera_rejected(self):
        session = MeasurementSession(self.bundle)
        for mutation in [dict(source_frame=0), dict(floor_reference=''),
                         dict(selector=dict(corners_uv=[[0, 0], [200, 0], [60, 45], [0, 45]])),
                         dict(selector=dict(corners_uv=[[15, 15], [65, 45], [65, 15], [15, 45]]))]:
            req = self.request(); req.update(mutation)
            with self.assertRaises(ValueError): session.measure(req)
        self.make_bundle(corrupt_camera=True)
        with self.assertRaisesRegex(ValueError, 'basis'): MeasurementSession(self.bundle)

    def test_nonedge_filter_excludes_corrupted_depth(self):
        session = MeasurementSession(self.bundle)
        session.points[0, 20:30, 20:40] = [30, 40, 50]
        session.non_edge[0, 20:30, 20:40] = False
        result = session.measure(self.request())
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], [1.40625, .84375])
        self.assertLess(result['counts']['reliable_pixels'], result['counts']['selected_pixels'])

    def test_point_camera_disagreement_is_reported_and_boundary_stays_on_rays(self):
        session = MeasurementSession(self.bundle); session.points[..., 0] += .2
        req = self.request(); req['selector'] = dict(box_xyxy=[15, 15, 66, 46])
        result = session.measure(req)
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], [1.40625, .84375])
        self.assertGreater(result['geometry_consistency']['point_camera_reprojection_p50_px'], 7)
        np.testing.assert_allclose(result['rectangle']['center_xy_m'], [.3140625, -.4140625])

    def test_sam3_manifest_adapter_preserves_variant_and_rejects_wrong_frame(self):
        mask = self.root/'mask.png'; Image.new('L', (80, 60), 255).save(mask)
        manifest = self.root/'sam3.json'
        write(manifest, dict(status='pending_visual_review', objects=[dict(id='table', source_frame=207,
              image_sha256=digest(self.bundle/'frames/000207.jpg'), selected_variant='text_0',
              variants=[dict(variant='text_0', mask=str(mask)), dict(variant='box_0', mask=str(mask))])]))
        selector = sam3_selector(manifest, 'table', 'box_0')
        self.assertEqual(selector['variant'], 'box_0')
        self.assertEqual(selector['review_status'], 'pending_visual_review')
        req = self.request(); req['selector'] = selector; req['height_range_m'] = [.6, .9]
        MeasurementSession(self.bundle).measure(req)
        req['selector']['source_frame'] = 0
        with self.assertRaisesRegex(ValueError, 'frame mismatch'): MeasurementSession(self.bundle).measure(req)
        with self.assertRaisesRegex(ValueError, 'variant'): sam3_selector(manifest, 'table', 'bad')

    def test_occluded_region_not_promoted_to_full_dimension(self):
        req = self.request(); req['selector'] = dict(box_xyxy=[15, 15, 40, 46])
        partial = MeasurementSession(self.bundle).measure(req)
        self.assertEqual(partial['measurement_basis'], 'observed_surface_extent')
        self.assertLess(max(partial['rectangle']['size_xy_m']), 1.40625)

    def test_height_filter_prevents_background_floor_dominance(self):
        req = self.request(); req['selector'] = dict(box_xyxy=[0, 0, 80, 60]); req['height_range_m'] = [.6, .9]
        result = MeasurementSession(self.bundle).measure(req)
        self.assertAlmostEqual(result['surface_height_m'], .75)
        np.testing.assert_allclose(result['rectangle']['size_xy_m'], [1.40625, .84375])

    def test_robust_plane_with_outliers_and_degenerate_rejection(self):
        rng = np.random.default_rng(42)
        xy = rng.uniform(-1, 1, (900, 2)); z = .8+.02*xy[:, 0]+rng.normal(0, .001, 900)
        points = np.c_[xy, z]; points[:250, 2] = rng.uniform(0, 2, 250)
        plane, mask = fit_plane(points)
        self.assertGreater(mask.sum(), 640)
        self.assertAlmostEqual(plane['offset_m'], -.8, places=2)
        with self.assertRaises(ValueError): fit_plane(np.ones((100, 3)))
        with self.assertRaises(ValueError): fit_plane(np.c_[np.zeros(900), xy])

    def test_parallel_and_behind_camera_rays_rejected(self):
        with self.assertRaisesRegex(ValueError, 'parallel'):
            ray_plane(np.array([[0, 0]]), np.eye(3), np.eye(4), dict(normal=[1, 0, 0], offset_m=-1))
        with self.assertRaisesRegex(ValueError, 'behind'):
            ray_plane(np.array([[0, 0]]), np.eye(3), np.eye(4), dict(normal=[0, 0, 1], offset_m=1))

    def test_rectangle_orientation_and_clearance(self):
        a = np.array([[0, 0], [2, 0], [2, 1], [0, 1]])
        self.assertEqual(polygon_gap(a, a+[0, 3]), 2.)
        self.assertEqual(polygon_gap(a, a+[.5, .5]), 0.)
        self.assertAlmostEqual(polygon_gap(a, a+[3, 2]), np.sqrt(2))
        rect = rectangle_xy(a)
        np.testing.assert_allclose(rect['size_xy_m'], [2, 1])

    def test_export_partial_failure_no_overwrite_or_input_mutation(self):
        before = digest(self.bundle/'predictions.npz')
        bad = self.request(); bad.update(id='missing', source_frame=9)
        cfg = dict(schema_version=1, objects=[self.request(), bad])
        result = evaluate(self.bundle, cfg, self.root/'out')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['objects']), 1); self.assertEqual(len(result['failures']), 1)
        self.assertEqual(digest(self.bundle/'predictions.npz'), before)
        with Image.open(self.root/'out/table.png') as image: image.load()
        exported = json.loads((self.root/'out/authoring_surfaces.json').read_text())
        self.assertAlmostEqual(exported['objects']['table']['center_xyz_m'][2], .75)
        with self.assertRaises(FileExistsError): evaluate(self.bundle, cfg, self.root/'out')


if __name__ == '__main__':
    unittest.main()
