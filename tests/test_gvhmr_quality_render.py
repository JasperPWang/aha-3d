"""Diagnostic overlay contracts and a tiny CPU-only real-video round trip."""
import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from tools.gvhmr import render_quality as renderer


def arrays(frames=6):
    names = np.asarray(renderer.JOINT_NAMES)
    times = np.arange(frames) / 30
    size = np.array([640, 360])
    # COCO17 skeleton, with enough top margin for diagnostic labels.
    points = np.array([[320, 120], [311, 115], [329, 115], [300, 121], [340, 121],
                       [285, 155], [355, 155], [270, 205], [370, 205],
                       [255, 250], [385, 250], [298, 230], [342, 230],
                       [290, 278], [350, 278], [285, 330], [355, 330]], dtype=float)
    keypoints = np.concatenate([np.tile(points, (frames, 1, 1)), np.ones((frames, 17, 1))], axis=-1)
    observation = dict(time_seconds=times, image_size=size, joint_names=names, keypoints=keypoints,
                       detected=np.ones(frames, bool))
    prediction = dict(time_seconds=times.copy(), image_size=size.copy(), joint_names=names.copy(),
                      uv=keypoints[..., :2].copy() + [3, 4], depth=np.full((frames, 17), 3.))
    return observation, prediction


def write_fixture(root, *, frames=6):
    import av
    obs, pred = arrays(frames)
    obs['detected'][2] = False
    obs['keypoints'][3, 15:, 2] = .2
    pred['depth'][4, 9] = -1
    video = root / 'source.mp4'
    with av.open(str(video), mode='w') as container:
        stream = container.add_stream('libx264', rate=30)
        stream.width, stream.height, stream.pix_fmt = 640, 360, 'yuv420p'
        for index in range(frames):
            image = Image.new('RGB', (640, 360), (25 + index * 8, 35, 45))
            frame = av.VideoFrame.from_image(image)
            frame.pts, frame.time_base = index, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    paths = dict(video=video, observations=root / 'observations.npz', prediction=root / 'native_camera.npz')
    np.savez_compressed(paths['observations'], **obs)
    np.savez_compressed(paths['prediction'], **pred)
    provenance = dict(scope='native_camera_observation_consistency',
        inputs=dict(video=dict(sha256=renderer.file_sha256(video))),
        outputs={path.name: renderer.file_sha256(path) for name, path in paths.items() if name != 'video'},
        actor_id='synthetic_fixture', selected_track_id=7, identity_review='fixture_only')
    (root / 'provenance.json').write_text(json.dumps(provenance))
    return paths


class OverlayContractTests(unittest.TestCase):
    def test_anatomical_order_raster_timestamps_and_gaps_must_match(self):
        obs, pred = arrays()
        for field, replacement, message in [
            ('joint_names', pred['joint_names'][::-1], 'anatomical order'),
            ('image_size', [641, 360], 'rasters differ'),
            ('time_seconds', pred['time_seconds'] + 1 / 30, 'timestamps differ'),
            ('depth', np.ones((5, 17)), 'shapes differ')]:
            candidate = copy.deepcopy(pred)
            candidate[field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                renderer.validate_arrays(obs, candidate)
        obs['time_seconds'][3:] += 1 / 30
        with self.assertRaisesRegex(ValueError, 'missing rows retained'):
            renderer.validate_arrays(obs, pred)

    def test_support_fixed_when_model_missing_and_detector_score_low(self):
        obs, pred = arrays()
        obs['keypoints'][0, 15, 2] = .2
        obs['keypoints'][0, 16, :2] = [-1, 100]
        pred['depth'][0, 9] = -1
        pred['uv'][0, 10] = np.nan
        data = renderer.validate_arrays(obs, pred)
        row = renderer.frame_metrics(data, 0)
        self.assertEqual(row['supported_joints'], 15)
        self.assertEqual(row['invalid_supported_predictions'], 2)
        self.assertEqual(row['invalid_depth_joints'], 1)
        self.assertEqual(row['invalid_projection_joints'], 1)
        self.assertEqual(row['residual_samples'], 13)
        self.assertEqual(row['maximum_error_px'], 5.)
        self.assertAlmostEqual(row['maximum_error_image_diagonal_fraction'], 5 / np.hypot(640, 360))

    def test_unknown_tracking_and_unsupported_rows_do_not_become_visible(self):
        obs, pred = arrays()
        obs['detected'][2] = False
        data = renderer.validate_arrays(obs, pred)
        row = renderer.frame_metrics(data, 2)
        self.assertEqual(row['supported_joints'], 0)
        self.assertIsNone(row['maximum_error_px'])
        self.assertEqual(row['tracking_support'], 'no_assigned_track')
        self.assertEqual(data['evidence']['visibility_evidence'], 'unknown')
        obs.pop('detected')
        data = renderer.validate_arrays(obs, pred)
        self.assertEqual(renderer.frame_metrics(data, 2)['tracking_support'], 'unknown')
        self.assertEqual(data['evidence']['raw_tracking_support'], 'unknown')
        obs['reviewed_visible'] = np.zeros((6, 17), bool)
        self.assertEqual(renderer.frame_metrics(renderer.validate_arrays(obs, pred), 2)['supported_joints'], 0)

    def test_draw_colors_and_no_input_mutation(self):
        obs, pred = arrays()
        obs['keypoints'][0, 15, 2] = .2
        obs['reviewed_visible'] = np.ones((6, 17), bool)
        obs['reviewed_visible'][0, 16] = False
        original = copy.deepcopy(obs)
        image = Image.new('RGB', (640, 360), 'black')
        drawn, _ = renderer.draw_overlay(image, renderer.validate_arrays(obs, pred), 0)
        for joint, color in [(9, 'detector'), (15, 'low_score'), (16, 'unsupported')]:
            x, y = obs['keypoints'][0, joint, :2].astype(int)
            self.assertEqual(drawn.getpixel((x, y)), renderer.COLORS[color])
        self.assertEqual(image.getbbox(), None)
        for key in obs:
            np.testing.assert_array_equal(obs[key], original[key])

    def test_distant_projection_clipping_remains_bounded(self):
        clipped = renderer.clipped_line([-1e8, 200], [1e8, 200], 640, 360)
        np.testing.assert_allclose(clipped, [[0, 200], [639, 200]], atol=1e-6)
        self.assertIsNone(renderer.clipped_line([-10, -10], [-5, -5], 640, 360))
        self.assertIsNone(renderer.clipped_line([np.nan, 0], [10, 10], 640, 360))
        self.assertIsNone(renderer.clipped_line([-1e308, 0], [1e308, 0], 640, 360))
        obs, pred = arrays()
        pred['uv'][0, 5:7] = [[-1e8, 200], [1e8, 200]]
        obs['detected'][0] = False
        renderer.draw_overlay(Image.new('RGB', (640, 360)), renderer.validate_arrays(obs, pred), 0)

    def test_full_decode_validator_catches_missing_frames_and_raster(self):
        t = np.arange(6) / 30
        renderer.validate_video_frames(t, [640, 360], t, [640, 360], label='Fixture')
        with self.assertRaisesRegex(ValueError, 'frame count differ'):
            renderer.validate_video_frames(t[:-1], [640, 360], t, [640, 360], label='Fixture')
        with self.assertRaisesRegex(ValueError, 'raster differs'):
            renderer.validate_video_frames(t, [320, 180], t, [640, 360], label='Fixture')

    def test_help_requires_no_video_or_models(self):
        result = subprocess.run([sys.executable, 'tools/gvhmr/render_quality.py', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--provenance', result.stdout)


@unittest.skipUnless(importlib.util.find_spec('av') is not None, 'PyAV not available in this test interpreter')
class TinyVideoTests(unittest.TestCase):
    def test_real_decode_draw_encode_decode_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_fixture(root)
            report = renderer.render_quality(paths['video'], paths['observations'], paths['prediction'], root / 'overlay', review_frames=3)
            self.assertEqual(report['source_frames_decoded'], 6)
            self.assertEqual(report['output_frames_decoded'], 6)
            self.assertEqual(report['duration_seconds'], .2)
            self.assertEqual(report['image_size'], [640, 360])
            self.assertEqual(report['visual_review'], 'pending')
            self.assertFalse(report['motion_accepted'])
            self.assertEqual(report['export_provenance']['selected_track_id'], 7)
            self.assertEqual(report['frame_metrics'][2]['supported_joints'], 0)
            self.assertEqual(report['frame_metrics'][4]['invalid_supported_predictions'], 1)
            self.assertEqual(len(report['sampled_review_frame_indices']), 3)
            for name, digest in report['outputs'].items():
                self.assertEqual(renderer.file_sha256(root / 'overlay' / name), digest)
            self.assertFalse((root / 'overlay' / 'overlay.partial.mp4').exists())
            with self.assertRaises(FileExistsError):
                renderer.render_quality(paths['video'], paths['observations'], paths['prediction'], root / 'overlay')

    def test_video_and_actor_npz_mismatch_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_fixture(root)
            # Same-shape/timing replacement could be another actor; bytes must match the exporter.
            with np.load(paths['prediction']) as loaded:
                pred = {key: loaded[key] for key in loaded.files}
            pred['uv'] = pred['uv'] + 1
            np.savez_compressed(paths['prediction'], **pred)
            with self.assertRaisesRegex(ValueError, 'prediction hash differs'):
                renderer.render_quality(paths['video'], paths['observations'], paths['prediction'], root / 'rejected')
            self.assertFalse((root / 'rejected').exists())
            paths['video'].write_bytes(b'wrong source')
            with self.assertRaisesRegex(ValueError, 'Source video hash differs'):
                renderer.validate_export_provenance(paths, root / 'provenance.json')

    def test_actual_video_timestamp_mismatch_fails_without_completed_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_fixture(root)
            # Hash-valid malformed export: all NPZ timestamps agree but source video starts at 0.
            for key in ('observations', 'prediction'):
                with np.load(paths[key]) as loaded:
                    values = {name: loaded[name] for name in loaded.files}
                values['time_seconds'] += 1 / 30
                np.savez_compressed(paths[key], **values)
            provenance_path = root / 'provenance.json'
            provenance = json.loads(provenance_path.read_text())
            for key in ('observations', 'prediction'):
                provenance['outputs'][paths[key].name] = renderer.file_sha256(paths[key])
            provenance_path.write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError, 'Source timestamp differs at frame 0'):
                renderer.render_quality(paths['video'], paths['observations'], paths['prediction'], root / 'rejected')
            self.assertEqual(json.loads((root / 'rejected' / 'failure.json').read_text())['status'], 'failed')
            self.assertFalse((root / 'rejected' / 'overlay.mp4').exists())


if __name__ == '__main__':
    unittest.main()
