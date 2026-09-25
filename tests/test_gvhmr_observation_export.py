"""Offline contract tests: no pretrained models, tracking inference or video decode."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from tools.gvhmr import export_motion_quality as exporter
from tools.gvhmr import tracking_evidence as tracking


class Tensor:
    """Minimal CPU tensor fixture; verifies device/batch plumbing without Torch."""
    def __init__(self, values):
        self.values = np.asarray(values)

    @property
    def shape(self):
        return self.values.shape

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        return Tensor(self.values[key])

    def __array__(self, dtype=None, copy=None):
        return np.asarray(self.values, dtype=dtype)

    def sum(self, axis):
        return self.values.sum(axis)

    def to(self, *, device, dtype):
        return Tensor(self.values.astype(dtype))

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


def history_fixture():
    small = dict(id=2, bbx_xyxy=np.array([10., 20., 20., 30.]))
    large = dict(id=9, bbx_xyxy=np.array([30., 40., 60., 70.]))
    return [[], [small, large], [small], [], [small, large], []]


def fake_tracker_module(history):
    smoothing_calls = []

    class Tracker:
        def track(self, video):
            return copy.deepcopy(history)

        def get_one_track(self, video):
            return "original"

        @staticmethod
        def sort_track_length(rows, video):
            indices, boxes = {}, {}
            for i, frame in enumerate(rows):
                for row in frame:
                    indices.setdefault(row['id'], []).append(i)
                    boxes.setdefault(row['id'], []).append(row['bbx_xyxy'])
            boxes = {k: np.asarray(v) for k, v in boxes.items()}
            areas = {k: np.prod(v[:, 2:] - v[:, :2], axis=1).sum() for k, v in boxes.items()}
            return indices, boxes, sorted(areas, key=areas.get, reverse=True)

    def mask(ids, length):
        result = np.zeros(length, bool)
        result[np.asarray(ids)] = True
        return result

    def rearrange(boxes, valid):
        result = np.zeros((len(valid), 4))
        result[valid] = boxes
        return result

    def interpolate(boxes, missing):
        observed = np.flatnonzero(~missing)
        return Tensor(np.column_stack([np.interp(np.arange(len(boxes)), observed, boxes[observed, k]) for k in range(4)]))

    def smooth(boxes, *, window_size, dim):
        smoothing_calls.append((window_size, dim))
        return Tensor(np.asarray(boxes) + .25)

    return SimpleNamespace(Tracker=Tracker, torch=SimpleNamespace(tensor=np.asarray),
        get_video_lwh=lambda video: (len(history), 100, 80), frame_id_to_mask=mask,
        rearrange_by_mask=rearrange, get_frame_id_list_from_mask=lambda missing: missing,
        linear_interpolate_frame_ids=interpolate, moving_average_smooth=smooth,
        smoothing_calls=smoothing_calls)


class TrackingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.times = np.arange(6) / 30
        self.size = [100, 80]

    def test_area_selection_and_explicit_actor_keep_original_gaps(self):
        kwargs = dict(source_path="input.mp4", source_sha256="source")
        auto = tracking.build_tracking_evidence(history_fixture(), self.times, self.size, **kwargs)
        selected = tracking.build_tracking_evidence(history_fixture(), self.times, self.size,
                                                     selected_track_id=2, actor_id="rear", **kwargs)
        self.assertEqual(auto['selected_track_id'], 9)
        self.assertEqual(selected['selected_track_id'], 2)
        self.assertEqual(selected['detected'], [False, True, True, False, True, False])
        self.assertEqual(selected['box_fill_status'], ['held_leading', 'observed', 'observed', 'interpolated', 'observed', 'held_trailing'])
        self.assertEqual(len(selected['raw_history'][1]), 2)
        self.assertEqual(selected['raw_history'][3], [])

    def test_instrumentation_preserves_upstream_helpers_and_restores_method(self):
        module = fake_tracker_module(history_fixture())
        original = module.Tracker.get_one_track
        with tempfile.TemporaryDirectory() as tmp:
            video, sidecar = Path(tmp) / 'video.mp4', Path(tmp) / 'tracking.json'
            video.write_bytes(b'video-fixture')
            with tracking.record_tracking_evidence(sidecar, selected_track_id=2,
                    expected_video=video, time_seconds=self.times, tracker_module=module):
                dense = module.Tracker().get_one_track(str(video)).numpy()
            self.assertIs(module.Tracker.get_one_track, original)
            self.assertEqual(module.smoothing_calls, [(5, 0), (5, 0)])
            np.testing.assert_allclose(dense, np.tile([10.5, 20.5, 20.5, 30.5], (6, 1)))
            payload = json.loads(sidecar.read_text())
            mask = tracking.validated_detected(payload, self.times, self.size, tracking.file_sha256(video), dense)
            np.testing.assert_array_equal(mask, [False, True, True, False, True, False])
            with self.assertRaisesRegex(ValueError, 'different actor'):
                tracking.validated_detected(payload, self.times, self.size, tracking.file_sha256(video), dense + 10)
            with self.assertRaisesRegex(ValueError, 'source hash'):
                tracking.validated_detected(payload, self.times, self.size, 'other-source', dense)
            altered = copy.deepcopy(payload)
            altered['detected'][0] = True
            with self.assertRaisesRegex(ValueError, 'original selected-track'):
                tracking.validated_detected(altered, self.times, self.size, tracking.file_sha256(video), dense)

    def test_missing_selected_id_retains_raw_evidence_and_restores(self):
        module = fake_tracker_module(history_fixture())
        original = module.Tracker.get_one_track
        with tempfile.TemporaryDirectory() as tmp:
            video, output = Path(tmp) / 'video', Path(tmp) / 'evidence.json'
            video.write_bytes(b'video')
            with self.assertRaisesRegex(ValueError, 'tracker ID was not observed'):
                with tracking.record_tracking_evidence(output, selected_track_id=999,
                        time_seconds=self.times, tracker_module=module):
                    module.Tracker().get_one_track(str(video))
            self.assertIs(module.Tracker.get_one_track, original)
            payload = json.loads(output.read_text())
            self.assertFalse(payload['selection_found'])
            self.assertEqual(len(payload['raw_history']), 6)
            self.assertEqual(payload['status'], 'raw_captured_before_interpolation')

    def test_cached_tracking_cannot_manufacture_support_and_existing_sidecar_is_safe(self):
        module = fake_tracker_module(history_fixture())
        original = module.Tracker.get_one_track
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'evidence.json'
            with self.assertRaisesRegex(RuntimeError, 'existing dense caches'):
                with tracking.record_tracking_evidence(output, tracker_module=module):
                    pass
            self.assertIs(module.Tracker.get_one_track, original)
            output.write_text('existing')
            with self.assertRaises(FileExistsError):
                with tracking.record_tracking_evidence(output, tracker_module=module):
                    pass
            self.assertEqual(output.read_text(), 'existing')

    def test_wrong_timeline_duplicate_tracks_and_empty_history_rejected(self):
        with self.assertRaisesRegex(ValueError, '30 Hz'):
            tracking.validate_times([0, 1 / 30, 1])
        rows = history_fixture()
        rows[1].append(rows[1][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            tracking.build_tracking_evidence(rows, self.times, self.size, source_path='x', source_sha256='x')
        empty = tracking.build_tracking_evidence([[]] * 6, self.times, self.size, source_path='x', source_sha256='x')
        self.assertFalse(empty['selection_found'])
        self.assertIsNone(empty['selected_track_id'])


class ReviewedFragmentTests(unittest.TestCase):
    def fixture(self, root):
        def box(track, values):
            return dict(id=track, bbx_xyxy=values)
        history = [[], [box(2, [10, 20, 20, 30]), box(9, [40, 10, 90, 70])],
            [box(4, [14, 20, 17, 23]), box(9, [40, 10, 90, 70])], [],
            [box(5, [30, 20, 40, 30])], [box(6, [40, 20, 50, 30])]]
        times, size = np.arange(6) / 30, [100, 80]
        video, raw_path, review_path = root / 'video.mp4', root / 'raw.json', root / 'review.json'
        video.write_bytes(b'normalized-source-fixture')
        raw = tracking.build_tracking_evidence(history, times, size, source_path=video,
            source_sha256=tracking.file_sha256(video))
        raw_path.write_text(json.dumps(raw))
        review = dict(schema_version=1, kind='gvhmr_reviewed_actor_fragments',
            raw_tracking_path=str(raw_path), raw_tracking_sha256=tracking.file_sha256(raw_path),
            source_video_sha256=tracking.file_sha256(video), time_seconds=times.tolist(), image_size=size,
            actor_id='rear_maroon', usable_body_box_track_ids=[2, 5, 6], observed_but_body_box_unusable_ids=[4],
            reviewed_by='synthetic_fixture', review_scope='all six synthetic frames', reviewed_frame_indices=list(range(6)))
        review_path.write_text(json.dumps(review))
        return history, times, size, video, raw_path, review_path, raw, review

    def test_reviewed_merge_retains_head_evidence_but_excludes_it_from_usable_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            history, times, size, video, raw_path, review_path, raw, _ = self.fixture(Path(tmp))
            source_bytes = raw_path.read_bytes()
            result = tracking.load_reviewed_fragment_evidence(raw_path, review_path, times, size,
                source_sha256=tracking.file_sha256(video), source_path=video)
            self.assertEqual(result['detected'], [False, True, False, False, True, True])
            self.assertEqual(result['actor_detection_present'], [False, True, True, False, True, True])
            self.assertEqual(result['unusable_body_box_detection_present'], [False, False, True, False, False, False])
            self.assertEqual(result['usable_track_id_by_frame'], [None, 2, None, None, 5, 6])
            self.assertEqual(result['observed_actor_track_ids_by_frame'][2], [4])
            self.assertEqual(result['box_fill_status'][2], 'interpolated')
            self.assertEqual(result['usable_source_frame_indices'], [1, 4, 5])
            self.assertEqual(result['observed_usable_body_boxes_xyxy'], [[10, 20, 20, 30], [30, 20, 40, 30], [40, 20, 50, 30]])
            self.assertEqual(result['raw_history'], raw['raw_history'])
            self.assertIsNone(result['selected_track_id'])
            self.assertEqual(result['selected_track_ids'], [2, 5, 6])
            self.assertEqual(raw_path.read_bytes(), source_bytes)

    def test_cached_mode_never_retracks_and_uses_original_interpolation_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history, times, size, video, raw_path, review_path, _, _ = self.fixture(root)
            module = fake_tracker_module(history)
            original = module.Tracker.get_one_track
            output = root / 'new-evidence.json'
            with patch.object(module.Tracker, 'track', side_effect=AssertionError('No tracking inference allowed')) as track:
                with tracking.record_tracking_evidence(output, expected_video=video, time_seconds=times,
                        cached_raw_tracking_path=raw_path, actor_review_path=review_path, tracker_module=module):
                    dense = module.Tracker().get_one_track(str(video)).numpy()
            track.assert_not_called()
            self.assertIs(module.Tracker.get_one_track, original)
            self.assertEqual(module.smoothing_calls, [(5, 0), (5, 0)])
            np.testing.assert_allclose(dense[:, 0], np.interp(np.arange(6), [1, 4, 5], [10, 30, 40]) + .5)
            payload = json.loads(output.read_text())
            mask = tracking.validated_detected(payload, times, size, tracking.file_sha256(video), dense)
            np.testing.assert_array_equal(mask, [False, True, False, False, True, True])
            tampered = copy.deepcopy(payload)
            tampered['usable_body_box_detected'][2] = True
            with self.assertRaisesRegex(ValueError, 'original raw history'):
                tracking.validated_detected(tampered, times, size, tracking.file_sha256(video), dense)
            tampered = copy.deepcopy(payload)
            tampered['raw_history'][2][0]['bbx_xyxy'][0] += 1
            with self.assertRaisesRegex(ValueError, 'content hash differs'):
                tracking.validated_detected(tampered, times, size, tracking.file_sha256(video), dense)

    def test_wrong_file_hash_source_timestamps_raster_and_actor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, times, size, video, raw_path, review_path, _, review = self.fixture(Path(tmp))
            kwargs = dict(source_sha256=tracking.file_sha256(video), source_path=video)
            for field, value, message in [
                ('raw_tracking_sha256', 'wrong', 'file hash'), ('source_video_sha256', 'wrong', 'source video hash'),
                ('time_seconds', (times + 1 / 30).tolist(), 'timestamps differ'),
                ('image_size', [101, 80], 'raster differs')]:
                candidate = copy.deepcopy(review)
                candidate[field] = value
                review_path.write_text(json.dumps(candidate))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                    tracking.load_reviewed_fragment_evidence(raw_path, review_path, times, size, **kwargs)
            review_path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ValueError, 'actor_id differs'):
                tracking.load_reviewed_fragment_evidence(raw_path, review_path, times, size, actor_id='other', **kwargs)
            raw_path.write_text(raw_path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'file hash'):
                tracking.load_reviewed_fragment_evidence(raw_path, review_path, times, size, **kwargs)

    def test_unknown_ambiguous_and_conflicting_track_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, times, size, video, _, _, raw, review = self.fixture(Path(tmp))
            kwargs = dict(source_sha256=tracking.file_sha256(video), source_path=video,
                          raw_tracking_sha256=review['raw_tracking_sha256'])
            missing = copy.deepcopy(review)
            missing['usable_body_box_track_ids'].append(999)
            with self.assertRaisesRegex(ValueError, 'must exist in raw history'):
                tracking.build_reviewed_fragment_evidence(raw, missing, times, size, **kwargs)
            conflict = copy.deepcopy(review)
            conflict['usable_body_box_track_ids'].append(4)
            with self.assertRaisesRegex(ValueError, 'must be disjoint'):
                tracking.build_reviewed_fragment_evidence(raw, conflict, times, size, **kwargs)
            overlap = copy.deepcopy(raw)
            overlap['raw_history'][4].append(overlap['raw_history'][5][0])
            with self.assertRaisesRegex(ValueError, 'Overlapping selected usable track IDs at frame 4'):
                tracking.build_reviewed_fragment_evidence(overlap, review, times, size, **kwargs)

    def test_fragment_context_requires_paired_inputs_and_no_single_id_override(self):
        module = fake_tracker_module(history_fixture())
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in [dict(cached_raw_tracking_path='raw.json'), dict(actor_review_path='review.json'),
                           dict(cached_raw_tracking_path='raw.json', actor_review_path='review.json', selected_track_id=2)]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'require both cached raw'):
                    with tracking.record_tracking_evidence(Path(tmp) / 'output.json', tracker_module=module, **kwargs):
                        pass


class ExportTests(unittest.TestCase):
    def arrays(self, frames=6):
        times = np.arange(frames) / 30
        kp = np.full((frames, 17, 3), [120., 230., .9])
        joints = np.broadcast_to([.2, .3, 2.], (frames, 17, 3)).copy()
        K = np.array([[200., 0., 100.], [0., 200., 200.], [0., 0., 1.]])
        return kp, joints, K, times, [640, 480]

    def test_projection_is_native_coco17_without_score_rewriting(self):
        kp, joints, K, times, size = self.arrays()
        kp[1, 9] = [np.nan, np.nan, 0.]
        kp[2, 10] = [700., 250., .8]
        before = kp.copy()
        observations, prediction = exporter.projection_arrays(kp, joints, K, times, size)
        np.testing.assert_allclose(prediction['uv'], np.broadcast_to([120, 230], (6, 17, 2)))
        np.testing.assert_array_equal(observations['keypoints'], before)
        np.testing.assert_array_equal(kp, before)
        self.assertNotIn('detected', observations)
        self.assertNotIn('reviewed_visible', observations)
        self.assertEqual(observations['joint_names'].tolist(), exporter.JOINT_NAMES)

    def test_invalid_predicted_depth_remains_visible_to_diagnostic(self):
        kp, joints, K, times, size = self.arrays()
        joints[0, 9, 2] = 0
        joints[1, 9, 2] = -1
        observations, projection = exporter.projection_arrays(kp, joints, K, times, size)
        report = exporter.diagnose(observations['keypoints'], times, size,
            predictions={'native': (projection['uv'], projection['depth'])})
        row = report['joints']['left_wrist']['predictions']['native']
        self.assertEqual(row['invalid_observed_predictions'], 2)
        self.assertEqual(row['cohort_samples'], 6)

    def test_timing_shape_and_intrinsics_cannot_silently_change(self):
        kp, joints, K, times, size = self.arrays()
        with self.assertRaisesRegex(ValueError, 'every input frame'):
            exporter.projection_arrays(kp[:-1], joints, K, times, size)
        with self.assertRaisesRegex(ValueError, '30 Hz'):
            exporter.projection_arrays(kp, joints, K, times * 2, size)
        K[2, 2] = 2
        with self.assertRaisesRegex(ValueError, 'intrinsics'):
            exporter.projection_arrays(kp, joints, K, times, size)

    def fake_model(self):
        calls = []
        class Model:
            def to(self, device):
                return self
            def eval(self):
                return self
            def __call__(self, **params):
                calls.append({name: np.asarray(value).copy() for name, value in params.items()})
                return Tensor(np.repeat(np.asarray(params['transl'])[:, None], 17, axis=1))
        return Model(), calls

    def test_exact_body_api_batched_without_pose_resampling(self):
        model, calls = self.fake_model()
        params = {name: Tensor(np.arange(5 * width).reshape(5, width)) for name, width in exporter.PARAMETERS.items()}
        fake_torch = SimpleNamespace(float32=np.float32, inference_mode=nullcontext)
        joints = exporter.regress_coco17({'smpl_params_incam': params}, model, fake_torch, batch_size=2)
        self.assertEqual([len(row['body_pose']) for row in calls], [2, 2, 1])
        np.testing.assert_array_equal(np.concatenate([row['body_pose'] for row in calls]), np.asarray(params['body_pose']))
        np.testing.assert_array_equal(joints[:, 0], np.asarray(params['transl']))
        with self.assertRaisesRegex(ValueError, 'schema'):
            exporter.regress_coco17({'smpl_params_incam': {**params, 'left_hand_pose': Tensor(np.zeros((5, 45)))}}, model, fake_torch)

    def test_mocked_file_export_writes_consumable_npz_and_provenance(self):
        kp, joints, K, times, size = self.arrays()
        model, calls = self.fake_model()
        params = {name: Tensor(np.zeros((6, width))) for name, width in exporter.PARAMETERS.items()}
        params['transl'] = Tensor(joints[:, 0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {name: root / name for name in ['prediction.pt', 'vitpose.pt', 'input.mp4']}
            for name, path in files.items():
                path.write_bytes(name.encode())
            body_source = root / 'hmr4d/utils/smplx_utils.py'
            body_source.parent.mkdir(parents=True)
            body_source.write_text('# mocked module\n')
            artifacts = {files['prediction.pt']: dict(smpl_params_incam=params, K_fullimg=Tensor(K)),
                         files['vitpose.pt']: Tensor(kp)}
            fake_torch = SimpleNamespace(float32=np.float32, inference_mode=nullcontext,
                load=lambda path, **kwargs: artifacts[Path(path)])
            factory_names = []
            def factory(name):
                factory_names.append(name)
                return model
            fake_module = SimpleNamespace(__file__=str(body_source), make_smplx=factory)
            timeline = dict(time_seconds=times, image_size=np.asarray(size), frames=6, fully_decoded=True, duration_seconds=.2)
            with patch.object(exporter, 'verify_upstream', return_value={'revision': tracking.REVISION}), \
                    patch.object(exporter, 'video_timeline', return_value=timeline), \
                    patch.object(exporter.importlib, 'import_module', return_value=fake_module), \
                    patch.dict(sys.modules, {'torch': fake_torch}):
                report = exporter.export_quality(repo=root, prediction_path=files['prediction.pt'],
                    vitpose_path=files['vitpose.pt'], video_path=files['input.mp4'], output=root / 'export')
            self.assertEqual(factory_names, ['supermotion_coco17'])
            self.assertFalse(report['motion_accepted'])
            self.assertEqual(report['tracking_support'], 'unknown_no_raw_sidecar')
            with np.load(root / 'export/observations.npz', allow_pickle=False) as observations:
                self.assertNotIn('detected', observations)
                np.testing.assert_array_equal(observations['keypoints'], kp)
            diagnostic = json.loads((root / 'export/diagnostics.json').read_text())
            self.assertLess(diagnostic['joints']['left_wrist']['predictions']['native_camera']['residual_px']['maximum'], 1e-5)
            script = Path(exporter.__file__).with_name('motion_quality.py')
            result = subprocess.run([sys.executable, str(script), '--observations', str(root / 'export/observations.npz'),
                '--prediction', str(root / 'export/native_camera.npz'), '--output', str(root / 'independent_recheck.json')],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            boxes_file = root / 'bbx.pt'
            boxes_file.write_bytes(b'box-fixture')
            boxes = np.tile([10.5, 20.5, 20.5, 30.5], (6, 1))
            artifacts[boxes_file] = {'bbx_xyxy': Tensor(boxes)}
            evidence = tracking.build_tracking_evidence(history_fixture(), times, size,
                source_path=files['input.mp4'], source_sha256=tracking.file_sha256(files['input.mp4']),
                selected_track_id=2, actor_id='rear')
            evidence.update(status='dense_boxes_returned', dense_bbx_xyxy_sha256=tracking.array_sha256(boxes))
            tracking_path = root / 'raw_tracking.json'
            tracking_path.write_text(json.dumps(evidence))
            with patch.object(exporter, 'verify_upstream', return_value={'revision': tracking.REVISION}), \
                    patch.object(exporter, 'video_timeline', return_value=timeline), \
                    patch.object(exporter.importlib, 'import_module', return_value=fake_module), \
                    patch.dict(sys.modules, {'torch': fake_torch}):
                tracked = exporter.export_quality(repo=root, prediction_path=files['prediction.pt'],
                    vitpose_path=files['vitpose.pt'], video_path=files['input.mp4'], output=root / 'tracked',
                    tracking_path=tracking_path)
            self.assertEqual(tracked['actor_id'], 'rear')
            self.assertEqual(tracked['selected_track_id'], 2)
            with np.load(root / 'tracked/observations.npz', allow_pickle=False) as observations:
                np.testing.assert_array_equal(observations['detected'], [False, True, True, False, True, False])
                np.testing.assert_array_equal(observations['keypoints'], kp)

    def test_cli_help_needs_no_pretrained_runtime(self):
        result = subprocess.run([sys.executable, exporter.__file__, '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--tracking-evidence', result.stdout)


if __name__ == '__main__':
    unittest.main()
