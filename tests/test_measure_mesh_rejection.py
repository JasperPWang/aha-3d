"""CLI regression coverage for source regions with no usable mesh support."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tools.layout_inspection.measure_mesh import main
from tools.layout_inspection.semantic import digest


class MeasureMeshRejectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mesh = self.root / 'layers.npz'
        self.config = self.root / 'surfaces.json'
        self.out = self.root / 'measurements'
        yy, xx = np.mgrid[:5, :5]
        self.vertices = np.column_stack([xx.ravel() * .02, yy.ravel() * .02, np.full(25, .8)])
        self.pixel = np.column_stack([yy.ravel(), xx.ravel()])
        self.faces = []
        for y in range(4):
            for x in range(4):
                a = y * 5 + x
                self.faces.extend([[a, a + 1, a + 5], [a + 1, a + 6, a + 5]])
        self.request = dict(id='vanity', normal_hint_world=[0, 0, 1], regions=[
            dict(source_frame=7, polygon_uv=[[0, 0], [4, 0], [4, 4], [0, 4]])])
        np.savez(self.root / 'inputs.npz', rgb=np.zeros((1, 5, 5, 3), dtype=np.uint8))

    def prepare(self, eligible, requests=None):
        np.savez(self.mesh, vertices=self.vertices, faces=np.array(self.faces),
                 face_layer=np.zeros(len(self.faces), dtype=np.int8),
                 frame_indices=np.array([7]), pixel_yx=self.pixel,
                 source_frame=np.full(25, 7), measurement_valid=eligible)
        (self.root / 'manifest.json').write_text(json.dumps(dict(
            layers_sha256=digest(self.mesh), processed_shape_nhw=[1, 5, 5],
            bundle=str(self.root), world_transform=np.eye(4).tolist())))
        self.config.write_text(json.dumps(dict(surfaces=requests or [self.request])))

    def invoke(self):
        argv = ['measure_mesh', '--mesh', str(self.mesh), '--config', str(self.config), '--out', str(self.out)]
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            main()

    def rejection(self, code, count):
        with self.assertRaises(SystemExit) as caught:
            self.invoke()
        self.assertEqual(caught.exception.code, 1)
        report = json.loads((self.out / 'rejection.json').read_text())
        self.assertEqual(report['status'], 'rejected')
        self.assertEqual(report['code'], code)
        self.assertEqual(report['selected_vertices'], count)
        self.assertEqual(report['mesh_sha256'], digest(self.mesh))
        self.assertEqual(report['config_sha256'], digest(self.config))
        self.assertEqual(report['frame_indices'], [7])
        self.assertEqual(report['processed_size_wh'], [5, 5])
        self.assertFalse(report['measurement_written'])
        self.assertFalse((self.out / 'measurements.json').exists())
        self.assertFalse((self.out / 'support_vertex_ids.npz').exists())
        return report

    def test_all_selected_points_ineligible_preserves_source_provenance(self):
        self.prepare(np.zeros(25, dtype=bool))
        report = self.rejection('no_eligible_surface_points', 0)
        self.assertEqual(report['selection'], self.request)
        self.assertEqual(report['region_selection_counts'], [dict(
            source_frame=7, polygon_uv=self.request['regions'][0]['polygon_uv'],
            region_vertices=25, eligible_vertices=0)])
        self.assertTrue((self.out / 'vanity_7.png').is_file())

    def test_insufficient_selection_keeps_twenty_point_threshold(self):
        self.prepare(np.arange(25) < 19)
        report = self.rejection('insufficient_surface_points', 19)
        self.assertEqual(report['minimum_surface_points'], 20)

    def test_empty_region_after_valid_surface_does_not_publish_partial_measurements(self):
        empty = dict(id='outside', regions=[dict(source_frame=7,
                     polygon_uv=[[8, 8], [9, 8], [9, 9], [8, 9]])])
        self.prepare(np.ones(25, dtype=bool), [self.request, empty])
        report = self.rejection('no_eligible_surface_points', 0)
        self.assertEqual(report['selection'], empty)
        self.assertEqual(report['completed_surface_ids'], ['vanity'])
        self.assertEqual(report['region_selection_counts'][0]['region_vertices'], 0)

    def test_nonfinite_surface_is_rejected_without_filtering_or_fallback(self):
        self.vertices[0, 2] = np.nan
        self.prepare(np.ones(25, dtype=bool))
        self.rejection('invalid_surface_points', 25)

    def test_valid_surface_retains_observed_plane_and_support(self):
        self.prepare(np.ones(25, dtype=bool))
        self.invoke()
        report = json.loads((self.out / 'measurements.json').read_text())
        surface = report['surfaces']['vanity']
        self.assertEqual(surface['support_vertices'], 25)
        self.assertEqual(surface['selection'], self.request)
        np.testing.assert_allclose(surface['normal_xyz'], [0, 0, 1], atol=1e-10)
        self.assertAlmostEqual(surface['center_xyz_m'][2], .8)
        with np.load(self.out / 'support_vertex_ids.npz') as support:
            np.testing.assert_array_equal(support['vanity'], np.arange(25))
        self.assertFalse((self.out / 'rejection.json').exists())


if __name__ == '__main__':
    unittest.main()
