"""Small geometric regression fixtures; execute in the Open3D runtime."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from tools.layout_inspection.quick_check import run


@unittest.skipUnless(importlib.util.find_spec('open3d'), 'Needs the Open3D runtime')
class NativeContourGeometry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # A small foreground square at Z=2, a larger rear square at Z=4.
        # Some pixels see the rear; outside both squares must remain a miss.
        vertices = []
        for radius, z in ((.9, 2.), (3., 4.)):
            vertices.extend([[-radius, -radius, z], [radius, -radius, z],
                             [radius, radius, z], [-radius, radius, z]])
        np.savez(self.root / 'model.npz', vertices=np.asarray(vertices, np.float32),
                 faces=np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.int32),
                 face_object_id=np.array([0, 0, 1, 1], np.int32))
        self.meta = {'world_transform': np.eye(4).tolist(),
                     'object_names': ['foreground', 'rear']}
        (self.root / 'model.json').write_text(json.dumps(self.meta))
        camera = {'world_transform': np.eye(4).tolist(), 'processed_size_wh': [9, 9],
                  'frames': [{'source_frame': 7, 'timestamp_seconds': .25,
                              'c2w': np.eye(4).tolist(),
                              'intrinsics': [[4., 0., 4.], [0., 4., 4.], [0., 0., 1.]]}]}
        (self.root / 'cameras.json').write_text(json.dumps(camera))
        self.rgb = np.full((1, 9, 9, 3), 73, np.uint8)
        np.savez(self.root / 'inputs.npz', rgb=self.rgb,
                 frame_indices=np.array([7]), timestamps_seconds=np.array([.25]))

    def check(self, **kwargs):
        return run(self.root / 'model.npz', self.root / 'model.json',
                   self.root / 'cameras.json', self.root / 'inputs.npz',
                   self.root / 'out', [7], threads=1, **kwargs)

    def test_first_hit_depth_is_camera_z_and_misses_are_explicit(self):
        self.check()
        with np.load(self.root / 'out/source_000007_visibility.npz') as data:
            self.assertEqual(data['object_id'][4, 4], 0)
            self.assertEqual(data['object_id'][4, 6], 1)
            self.assertAlmostEqual(float(data['depth_camera_z'][4, 5]), 2., places=5)
            self.assertAlmostEqual(float(data['depth_camera_z'][4, 6]), 4., places=5)
            self.assertEqual(data['object_id'][0, 0], -1)
            self.assertTrue(np.isinf(data['depth_camera_z'][0, 0]))

    def test_highlighting_rear_does_not_reveal_it_through_foreground(self):
        self.check(highlight=['rear'], only_highlight=True)
        with Image.open(self.root / 'out/source_000007_overlay.png') as img:
            pixels = np.asarray(img)
        np.testing.assert_array_equal(pixels[3:6, 3:6], self.rgb[0, 3:6, 3:6])
        self.assertFalse(np.array_equal(pixels[4, 6], self.rgb[0, 4, 6]))

    def test_invalid_comparison_inputs_are_rejected_before_output(self):
        with self.assertRaisesRegex(ValueError, 'matched no exported model names'):
            self.check(highlight=['misspelled-object'], only_highlight=True)
        self.assertFalse((self.root / 'out').exists())
        self.meta['world_transform'][0][3] = 1.
        (self.root / 'model.json').write_text(json.dumps(self.meta))
        with self.assertRaisesRegex(ValueError, 'different reviewed world bases'):
            self.check()
        self.assertFalse((self.root / 'out').exists())

    def test_exact_bed_id_does_not_match_bedside(self):
        self.meta['object_names'] = ['bed', 'bedside']
        self.meta['object_groups'] = [{'id': 'bed'}, {'id': 'bedside'}]
        (self.root/'model.json').write_text(json.dumps(self.meta))
        self.check(object_ids=['bed'], only_highlight=True)
        with Image.open(self.root/'out/source_000007_overlay.png') as image:
            pixels = np.asarray(image)
        np.testing.assert_array_equal(pixels[4,6], self.rgb[0,4,6])
        self.assertFalse(np.array_equal(pixels[3,3], self.rgb[0,3,3]))

    def test_unknown_exact_id_fails_before_output(self):
        with self.assertRaisesRegex(ValueError, 'Exact object ID absent'):
            self.check(object_ids=['bed'], only_highlight=True)
        self.assertFalse((self.root/'out').exists())


if __name__ == '__main__':
    unittest.main()
