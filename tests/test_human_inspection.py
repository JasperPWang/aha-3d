"""Pre-render gate regressions, including real decoded source evidence packages."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.workflow import human_inspection as inspection


class NumericalGate(unittest.TestCase):
    def setUp(self):
        self.active = np.array([True] * 6 + [False] * 2)

    def test_local_pass_cannot_override_active_occluded_failure(self):
        contact = np.array([.001] * 8)
        floor = np.array([0., 0., 0., 0., .13, 0., 9., 9.])
        checks = [inspection.series('floor', 'Floor', floor, self.active, limit=.02),
                  inspection.series('contact', 'Contact', contact, np.arange(8) < 3, limit=.02)]
        result = inspection.evaluate_series(checks, self.active)
        self.assertFalse(result['allow_render'])
        self.assertTrue(result['checks'][1]['numerical_pass'])
        self.assertEqual(result['checks'][0]['failing_source_frames'], [4])
        self.assertFalse(result['source_style_accepted'])
        self.assertFalse(result['complete_physics_accepted'])

    def test_missing_active_metrics_fail_not_missing_observation_implies_exit(self):
        values = np.zeros(8); values[3] = np.nan
        result = inspection.evaluate_series([inspection.series('floor', 'Floor', values, self.active, limit=.02)], self.active)
        self.assertEqual(result['checks'][0]['missing_source_frames'], [3])
        self.assertFalse(result['allow_render'])

    def test_inactive_padding_excluded_and_pass_is_only_pre_render(self):
        values = np.array([.001] * 6 + [np.nan, np.nan])
        result = inspection.evaluate_series([inspection.series('floor', 'Floor', values, self.active, limit=.02)], self.active)
        self.assertTrue(result['allow_render'])
        self.assertEqual(result['status'], 'numerical_gate_passed_awaiting_visual_review')

    def test_worst20_contact_exit_and_support_boundaries_selected(self):
        active = np.arange(40) < 35
        timeline = dict(times=np.arange(40) / 30, active=active, exit_frame=35)
        values = np.zeros(40); values[20] = .05
        metrics = [inspection.series('pantry', 'Pantry', values, active, limit=.002)]
        observed = np.ones(40, bool); observed[10:15] = False
        rows = inspection.select_frames(timeline, metrics, {},
            [dict(id='touch', kind='contact', frames=[12, 18])], dict(detected=observed))
        by_id = {r['source_frame']: r for r in rows}
        self.assertIn('Worst Pantry #1', by_id[20]['reasons'][0])
        self.assertTrue(by_id[10]['track_active'])
        for f in [11, 12, 13, 17, 18, 19, 33, 34, 35, 36, 39]:
            self.assertIn(f, by_id)
        self.assertFalse(by_id[35]['track_active'])


class EvidencePackage(unittest.TestCase):
    def setUp(self):
        try:
            import av
        except ImportError:
            self.skipTest('PyAV is required for exact decoded-source evidence tests')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.times = np.arange(8) / 30
        source = self.root / 'source.mkv'
        with av.open(str(source), 'w') as container:
            stream = container.add_stream('ffv1', rate=30); stream.width = 96; stream.height = 64; stream.pix_fmt = 'bgr0'
            for i in range(8):
                image = np.full((64, 96, 3), i * 20, np.uint8)
                frame = av.VideoFrame.from_ndarray(image, format='rgb24')
                for packet in stream.encode(frame): container.mux(packet)
            for packet in stream.encode(): container.mux(packet)
        # Matroska PTS use milliseconds: bind the actual source timeline.
        with av.open(str(source)) as container:
            self.times = np.array([float(f.pts * f.time_base) for f in container.decode(video=0)])
        (self.root / 'room.blend').write_bytes(b'Frozen fixture room; no render claimed')
        self.active = np.arange(8) < 6
        np.savez(self.root / 'body.npz', time_seconds=self.times, source_frame_indices=np.arange(8),
                 track_active=self.active, source_actor_id='target', source_video_sha256=inspection.digest(source), body_scale=1.)
        self.review = dict(schema_version=1, source_video_sha256=inspection.digest(source), actor_id='target',
                           time_seconds=self.times.tolist(), image_size=[96,64], terminal_exit_frame=6,
                           reviewer='fixture author', reason='Synthetic lifecycle, not source visibility truth')
        inspection.write_json(self.root / 'lifecycle.json', self.review)
        self.metrics = dict(cache_sha256=inspection.digest(self.root/'body.npz'),
                            source_room_sha256=inspection.digest(self.root/'room.blend'), rows=[])
        for f in range(8):
            row = dict(source_frame=f, time_seconds=float(self.times[f]), track_active=bool(self.active[f]),
                       geometry_assessed=bool(self.active[f]))
            if self.active[f]:
                row.update(whole_body_max_support_penetration_m=.13 if f == 4 else .0,
                           convex_furniture_penetrations={'FixtureBox':dict(max_depth_m=0.)})
            self.metrics['rows'].append(row)
        inspection.write_json(self.root/'metrics.json', self.metrics)
        self.config = dict(schema_version=1, case_id='fixture', variant_id='candidate', actor_id='target',
                           label='<script>alert("unsafe")</script>',
                           source_video=self.ref('source.mkv'), body_cache=self.ref('body.npz'), scene=self.ref('room.blend'),
                           lifecycle_review=self.ref('lifecycle.json'), metrics=dict(format='placement_json', **self.ref('metrics.json')),
                           policy=dict(id='frozen-test', max_floor_penetration_m=.02, max_object_penetration_m=.002))

    def ref(self, name):
        return dict(path=name, sha256=inspection.digest(self.root/name))

    def run_package(self, name='package'):
        inspection.write_json(self.root/'config.json', self.config)
        return inspection.build(self.root/'config.json', self.root/name)

    def test_rejected_package_contains_exact_source_and_hashed_inventory(self):
        report = self.run_package()
        self.assertFalse(report['decision']['allow_render'])
        self.assertEqual(report['source_decode']['decoded_frame_count'], 8)
        package = self.root/'package'
        manifest = inspection.read_json(package/'bundle_manifest.json')
        self.assertEqual(manifest['entry'], 'index.html')
        for path, expected in manifest['artifacts'].items():
            self.assertFalse(Path(path).is_absolute())
            self.assertEqual(inspection.digest(package/path), expected)
        text = (package/'index.html').read_text()
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertTrue((package/'frames/source_000006.png').exists())
        self.assertEqual(report['decision']['checks'][0]['failing_source_frames'], [4])

    def test_hash_mismatch_fails_before_output(self):
        self.config['source_video']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'): self.run_package()
        self.assertFalse((self.root/'package').exists())

    def test_same_source_other_actor_rejected(self):
        self.config['actor_id'] = 'someone else'
        with self.assertRaisesRegex(ValueError, 'Actor binding'): self.run_package()

    def test_geometry_row_missing_is_readable_gate_failure(self):
        self.metrics['rows'] = [r for r in self.metrics['rows'] if r['source_frame'] != 3]
        inspection.write_json(self.root/'metrics.json', self.metrics)
        self.config['metrics'].update(self.ref('metrics.json'))
        result = self.run_package()
        self.assertIn(3, result['decision']['checks'][0]['missing_source_frames'])

    def test_scene_rebinding_and_duplicate_rows_rejected(self):
        self.metrics['rows'].append(copy.deepcopy(self.metrics['rows'][0]))
        inspection.write_json(self.root/'metrics.json', self.metrics)
        self.config['metrics'].update(self.ref('metrics.json'))
        with self.assertRaisesRegex(ValueError, 'duplicate/invalid'): self.run_package()

    def test_invalid_source_time_never_leaves_allow_render(self):
        # A coherent body/review/metric timeline that still mismatches real PTS.
        wrong = self.times + .005
        with np.load(self.root/'body.npz', allow_pickle=False) as z: values = dict(z)
        values['time_seconds'] = wrong; np.savez(self.root/'body.npz', **values)
        self.config['body_cache'] = self.ref('body.npz')
        self.review['time_seconds'] = wrong.tolist(); inspection.write_json(self.root/'lifecycle.json', self.review)
        self.config['lifecycle_review'] = self.ref('lifecycle.json')
        self.metrics['cache_sha256'] = self.config['body_cache']['sha256']
        for f, row in enumerate(self.metrics['rows']): row['time_seconds'] = float(wrong[f])
        inspection.write_json(self.root/'metrics.json', self.metrics)
        self.config['metrics'].update(self.ref('metrics.json'))
        with self.assertRaisesRegex(ValueError, 'Fully decoded source video'): self.run_package()
        self.assertFalse((self.root/'package/decision.json').exists())
        self.assertTrue((self.root/'package/error.json').exists())

    def test_room_preview_wrong_candidate_and_hidden_flag_rejected(self):
        from PIL import Image
        Image.new('RGB',(32,32)).save(self.root/'preview.png')
        preview = dict(schema_version=1, body_sha256=self.config['body_cache']['sha256'],
                       scene_sha256=self.config['scene']['sha256'], all_visibility_verified=True,
                       views=[dict(source_frame=6, **self.ref('preview.png'), body_sha256=self.config['body_cache']['sha256'],
                                   scene_sha256=self.config['scene']['sha256'], relation='same_candidate',body_hidden=False)])
        inspection.write_json(self.root/'preview.json', preview)
        self.config['room_preview'] = self.ref('preview.json')
        with self.assertRaisesRegex(ValueError, 'hidden state'): self.run_package()

    def canonical_scene(self, outside=None, signed=None):
        floor = np.where(self.active, 0., np.nan)
        arrays = dict(time_seconds=self.times, track_active=self.active, source_frame_indices=np.arange(8),
                      floor_penetration_m=floor, object_max_penetration_m=floor[:,None], object_names=['Box'],
                      floor_min_signed_m=floor.copy() if signed is None else signed,
                      floor_support_outside_vertex_count=floor.copy() if outside is None else outside)
        np.savez(self.root/'scene_metrics.npz', **arrays)
        meta = dict(body_cache_sha256=self.config['body_cache']['sha256'], scene_sha256=self.config['scene']['sha256'],
                    source_video_sha256=self.config['source_video']['sha256'], actor_id='target',
                    metrics_sha256=inspection.digest(self.root/'scene_metrics.npz'), scope='Finite fixture floor and box')
        inspection.write_json(self.root/'scene_metrics.json', meta)
        self.config['metrics'] = dict(format='scene_npz', **self.ref('scene_metrics.npz'), provenance=self.ref('scene_metrics.json'))

    def canonical_contacts(self, values, *, kind='contact_gap', acceptance=(1,2,3)):
        values = np.asarray(values,float)
        np.savez(self.root/'contacts.npz', time_seconds=self.times, track_active=self.active,
                 source_frame_indices=np.arange(8), measurement=values[:,None])
        meta = dict(body_cache_sha256=self.config['body_cache']['sha256'], scene_sha256=self.config['scene']['sha256'],
                    source_video_sha256=self.config['source_video']['sha256'], actor_id='target',
                    metrics_sha256=inspection.digest(self.root/'contacts.npz'),
                    series=[dict(id='event',label='Finite target',field='measurement',column=0,
                                 source_frames=np.flatnonzero(np.isfinite(values)).tolist(),acceptance_source_frames=list(acceptance),
                                 threshold=.02,max_value=float(np.nanmax(values)),kind=kind,unit='m',review_scope='Synthetic event')])
        inspection.write_json(self.root/'contacts.json',meta)
        self.config['contact_metrics']=dict(**self.ref('contacts.npz'),provenance=self.ref('contacts.json'))

    def test_canonical_uses_threshold_not_measured_max_and_keeps_diagnostic_scope(self):
        self.canonical_scene()
        self.canonical_contacts([np.nan,.001,.03,.002,np.nan,99,np.nan,np.nan])
        result=self.run_package();checks={c['id']:c for c in result['decision']['checks']}
        self.assertEqual(checks['event']['threshold'],.02)
        self.assertEqual(checks['event']['failing_source_frames'],[2])
        self.assertIsNone(checks['event__diagnostic']['numerical_pass'])
        self.assertEqual(checks['event__diagnostic']['maximum'],99)

    def test_canonical_missing_slip_pair_fails_but_first_endpoint_is_undefined(self):
        self.canonical_scene()
        self.canonical_contacts([np.nan,np.nan,.01,np.nan,np.nan,np.nan,np.nan,np.nan],kind='slip')
        result=self.run_package();check=next(c for c in result['decision']['checks']if c['id']=='event')
        self.assertEqual(check['missing_source_frames'],[3])
        self.assertEqual(check['scope_source_frames'],[2,3])

    def canonical_v2_slip(self, *, acceptance=(2,3), missing_first=False):
        self.canonical_scene()
        self.canonical_contacts([np.nan,np.nan,np.nan if missing_first else .5,.001,np.nan,np.nan,np.nan,np.nan],
                                kind='slip',acceptance=acceptance)
        with np.load(self.root/'contacts.npz',allow_pickle=False) as z: arrays=dict(z)
        event=np.zeros((8,1),bool);event[1:4]=True;arrays['contact_event_mask']=event
        np.savez(self.root/'contacts.npz',**arrays)
        meta=inspection.read_json(self.root/'contacts.json')
        meta['metrics_sha256']=inspection.digest(self.root/'contacts.npz')
        meta['series'][0]['temporal_semantics']='adjacent_event_pair_ending_frame'
        inspection.write_json(self.root/'contacts.json',meta)
        self.config['contact_metrics']=dict(**self.ref('contacts.npz'),provenance=self.ref('contacts.json'))

    def test_v2_first_pair_is_retained_and_its_unique_failure_rejects(self):
        self.canonical_v2_slip()
        result=self.run_package();check=next(c for c in result['decision']['checks']if c['id']=='event')
        self.assertFalse(result['decision']['allow_render'])
        self.assertEqual(check['scope_source_frames'],[2,3])
        self.assertEqual(check['failing_source_frames'],[2])

    def test_v2_cannot_silently_drop_first_pair_or_include_acquisition(self):
        for i, acceptance in enumerate(((3,),(1,2,3))):
            self.canonical_v2_slip(acceptance=acceptance)
            with self.assertRaisesRegex(ValueError,'every adjacent event pair'):
                self.run_package(f'bad_scope_{i}')

    def test_v2_missing_first_pair_is_a_coverage_failure_not_a_skipped_sample(self):
        self.canonical_v2_slip(missing_first=True)
        result=self.run_package();check=next(c for c in result['decision']['checks']if c['id']=='event')
        self.assertFalse(result['decision']['allow_render'])
        self.assertEqual(check['missing_source_frames'],[2])

    def test_canonical_support_outside_floor_fails_even_with_zero_penetration(self):
        outside=np.zeros(8);outside[2]=1;outside[6:]=np.nan
        self.canonical_scene(outside)
        result=self.run_package();check=next(c for c in result['decision']['checks']if c['id']=='floor_support_outside')
        self.assertFalse(result['decision']['allow_render'])
        self.assertEqual(check['failing_source_frames'],[2])

    def test_positive_whole_body_clearance_selects_peak_without_new_gate(self):
        signed=np.zeros(8);signed[3]=.211493;signed[6:]=9.
        self.canonical_scene(signed=signed)
        result=self.run_package();check=next(c for c in result['decision']['checks']if c['id']=='whole_body_minimum_clearance')
        self.assertTrue(result['decision']['allow_render'])
        self.assertIsNone(check['threshold'])
        self.assertIsNone(check['numerical_pass'])
        self.assertEqual(check['worst_source_frame'],3)
        self.assertEqual(check['maximum'],.211493)
        selected=next(r for r in result['selected_frames']if r['source_frame']==3)
        self.assertTrue(any('Whole-body minimum clearance' in reason for reason in selected['reasons']))

    def test_external_decision_is_identical_and_not_written_after_failure(self):
        inspection.write_json(self.root/'config.json',self.config)
        with contextlib.redirect_stdout(io.StringIO()):
            inspection.main(['--config',str(self.root/'config.json'),'--output',str(self.root/'package'),
                             '--decision-output',str(self.root/'gate.json')])
        self.assertEqual((self.root/'gate.json').read_bytes(),(self.root/'package/decision.json').read_bytes())
        self.config['actor_id']='wrong';inspection.write_json(self.root/'bad.json',self.config)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            inspection.main(['--config',str(self.root/'bad.json'),'--output',str(self.root/'badpackage'),
                             '--decision-output',str(self.root/'badgate.json')])
        self.assertFalse((self.root/'badgate.json').exists())


if __name__ == '__main__': unittest.main()
