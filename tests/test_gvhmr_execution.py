"""Offline execution-policy and child-instrumentation tests; no GPU inference."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from tools.gvhmr import demo_entry, run, tracking_evidence


class ExecutionPolicyTests(unittest.TestCase):
    def test_default_uses_device_zero_or_respects_inherited_mask(self):
        env, report = run.configure_execution(None, environ={}, hostnames=['workstation'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '0')
        self.assertEqual(env['CUDA_DEVICE_ORDER'], 'PCI_BUS_ID')
        self.assertEqual(report['gpu_selection_policy'], 'default_physical_device_0')
        self.assertTrue(report['run_id'])
        for mask in ('3,5', 'GPU-abc'):
            with self.subTest(mask=mask):
                env, report = run.configure_execution(None, environ={'CUDA_VISIBLE_DEVICES': mask, 'INDOOR_RUN_ID': 'r1'},
                                                      hostnames=['workstation'])
                self.assertEqual(env['CUDA_VISIBLE_DEVICES'], mask)
                self.assertNotIn('CUDA_DEVICE_ORDER', env)
                self.assertEqual(report['gpu_selection_policy'], 'inherited_cuda_visible_devices')
                self.assertEqual(report['run_id'], 'r1')

    def test_explicit_numeric_gpu_preserves_original_env(self):
        original = {}
        env, report = run.configure_execution(2, environ=original, hostnames=['workstation1'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '2')
        self.assertEqual(env['CUDA_DEVICE_ORDER'], 'PCI_BUS_ID')
        self.assertEqual(original, {})
        self.assertEqual(report['gpu_selection_policy'], 'explicit_physical_device_index')
        self.assertEqual(report['execution'], 'local')
        for gpu in (-1, '0', True):
            with self.subTest(gpu=gpu), self.assertRaises(ValueError):
                run.configure_execution(gpu, environ={}, hostnames=['workstation'])

    def test_explicit_gpu_cannot_escape_inherited_mask_or_reinterpret_its_device_order(self):
        original = {'CUDA_VISIBLE_DEVICES': '2,7', 'CUDA_DEVICE_ORDER': 'FASTEST_FIRST'}
        env, report = run.configure_execution(7, environ=original, hostnames=['workstation'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '7')
        self.assertEqual(env['CUDA_DEVICE_ORDER'], 'FASTEST_FIRST')
        self.assertEqual(original['CUDA_VISIBLE_DEVICES'], '2,7')
        self.assertEqual(report['gpu_selection_policy'], 'explicit_device_within_inherited_numeric_mask')
        for mask, gpu in [('2,7', 0), ('', 0), ('GPU-abc', 0), ('MIG-abc', 0)]:
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                run.configure_execution(gpu, environ={'CUDA_VISIBLE_DEVICES': mask}, hostnames=['workstation'])
        without_order, _ = run.configure_execution(2, environ={'CUDA_VISIBLE_DEVICES': '2,7'}, hostnames=['workstation'])
        self.assertNotIn('CUDA_DEVICE_ORDER', without_order)

    def test_cli_sets_gpu_visibility_before_preflight(self):
        observed = []
        def preflight(*args):
            observed.append(os.environ.get('CUDA_VISIBLE_DEVICES'))
            return {'ready_for_attempt': False}
        with patch.dict(os.environ, {}, clear=True), patch.object(run.socket, 'gethostname', return_value='workstation'), \
                patch.object(run.socket, 'getfqdn', return_value='workstation'), \
                patch.object(run, 'preflight', side_effect=preflight), redirect_stdout(io.StringIO()):
            status = run.main(['check', '--camera', 'static', '--gpu', '3'])
        self.assertEqual(status, 2)
        self.assertEqual(observed, ['3'])

    def test_cli_default_selects_device_zero_before_preflight(self):
        observed = []
        def preflight(*args):
            observed.append(os.environ.get('CUDA_VISIBLE_DEVICES'))
            return {'ready_for_attempt': False}
        with patch.dict(os.environ, {}, clear=True), patch.object(run, 'preflight', side_effect=preflight), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(['check', '--camera', 'static']), 2)
        self.assertEqual(observed, ['0'])

    def test_nfs_git_trust_is_command_scoped_to_exact_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / '.git').write_text('gitdir: fake-worktree')
            with patch.object(run, 'call', return_value=SimpleNamespace(stdout=run.REVISION)) as call, \
                    patch.object(run.importlib.util, 'find_spec', return_value=object()):
                report = run.preflight(repo, repo / 'checkpoint', static=True)
            self.assertEqual(report['source_revision'], run.REVISION)
            self.assertEqual(call.call_args.args[0], ['git', '-c', f'safe.directory={repo.resolve()}',
                                                     '-C', str(repo.resolve()), 'rev-parse', 'HEAD'])

    def test_camera_selection_rejects_static_bundle_and_ambiguous_estimator(self):
        for mode, estimator, bundle in [('static', 'pi3x', Path('bundle')),
                ('static', 'dpvo', Path('bundle')), ('moving', 'pi3x', None), ('moving', 'dpvo', Path('bundle'))]:
            with self.subTest(mode=mode, estimator=estimator), self.assertRaises(ValueError):
                run.validate_camera_selection(mode, estimator, bundle)
        run.validate_camera_selection('moving', 'dpvo', None)
        run.validate_camera_selection('moving', 'pi3x', Path('bundle'))

    def test_pi3x_preflight_does_not_require_dpvo_module_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / '.git').write_text('gitdir: fixture')
            for name in [*run.ASSETS, 'tools/demo/demo.py', 'checkpoint']:
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            bundle = repo / 'bundle'
            bundle.mkdir()
            for name in ('inputs.json', 'cameras.json', 'camera_review.json'):
                (bundle / name).write_text('{}')
            with patch.object(run, 'call', return_value=SimpleNamespace(stdout=run.REVISION)), \
                    patch.object(run.importlib.util, 'find_spec', side_effect=lambda name: None if name == 'dpvo' else object()), \
                    patch.object(run.shutil, 'which', return_value='/usr/bin/ffmpeg'):
                pi3x = run.preflight(repo, repo / 'checkpoint', False, 'pi3x', bundle)
                dpvo = run.preflight(repo, repo / 'checkpoint', False)
            self.assertTrue(pi3x['ready_for_attempt'])
            self.assertEqual(pi3x['camera_estimator'], 'pi3x')
            self.assertFalse(dpvo['ready_for_attempt'])
            self.assertIn('dpvo', dpvo['missing_modules'])
            self.assertTrue(any(path.endswith('dpvo.pth') for path in dpvo['missing_files']))


class NormalizationTests(unittest.TestCase):
    @staticmethod
    def probe(count, fps=30., offset=0.):
        return dict(streams=[dict(nb_read_frames=str(count), duration=str(count / fps),
                                  width=1280, height=720)],
                    presentation_timestamps_seconds=[offset + i / fps for i in range(count)])

    def test_fractional_source_rate_preserves_endpoint_and_origin_relation(self):
        source = self.probe(243, 30000 / 1001, .033)
        normalized = self.probe(243)
        report = run.normalization_timing(source, normalized)
        self.assertEqual(report['target_frame_count'], 243)
        self.assertAlmostEqual(report['duration_difference_seconds'], -.0081)
        self.assertEqual(report['source_first_pts_seconds'], .033)
        self.assertIn('source_first_pts_seconds', report['normalized_to_source_time'])
        self.assertEqual(report['filter'], 'setpts=PTS-STARTPTS,fps=30:eof_action=pass')
        with self.assertRaisesRegex(ValueError, 'duration differs'):
            run.normalization_timing(source, self.probe(242))
        for count in (260, 429):
            self.assertEqual(run.normalization_frame_count(self.probe(count)), count)
            with self.assertRaisesRegex(ValueError, 'frame count differs'):
                run.normalization_timing(self.probe(count), self.probe(count + 1))

    def test_invalid_duration_raster_origin_and_timeline_rejected(self):
        for duration in (0., -1., float('nan'), float('inf')):
            source = self.probe(4)
            source['streams'][0]['duration'] = duration
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, 'finite and positive'):
                run.normalization_frame_count(source)
        for field in ('origin', 'raster', 'timeline'):
            normalized = self.probe(4)
            if field == 'origin':
                normalized = self.probe(4, offset=.033)
            elif field == 'raster':
                normalized['streams'][0]['width'] = 640
            else:
                normalized['presentation_timestamps_seconds'][-1] += .01
            with self.subTest(field=field), self.assertRaises(ValueError):
                run.normalization_timing(self.probe(4), normalized)


class InstrumentationTests(unittest.TestCase):
    def test_postprocess_override_handles_keywords_positions_and_restores(self):
        class Pipeline:
            def forward(self, inputs, train=False, postproc=False, static_cam=False):
                return inputs, train, postproc, static_cam
        original = Pipeline.forward
        with demo_entry.disable_postprocessing(Pipeline):
            self.assertEqual(Pipeline().forward('x', postproc=True, static_cam=True), ('x', False, False, True))
            self.assertEqual(Pipeline().forward('x', False, True, True), ('x', False, False, True))
        self.assertIs(Pipeline.forward, original)
        self.assertTrue(Pipeline().forward('x', postproc=True)[2])
        with self.assertRaises(RuntimeError):
            with demo_entry.disable_postprocessing(Pipeline):
                raise RuntimeError('fixture failure')
        self.assertIs(Pipeline.forward, original)

    def test_child_options_bind_tracking_timestamps_and_scoped_ablation(self):
        class Pipeline:
            def forward(self, inputs, train=False, postproc=False, static_cam=False):
                return postproc
        renderer = SimpleNamespace(get_global_cameras_static=lambda **kw: kw)
        original_camera = renderer.get_global_cameras_static
        original_forward = Pipeline.forward
        seen = {}
        @contextmanager
        def tracking(path, **kwargs):
            seen['path'], seen['tracking'] = path, kwargs
            yield
            seen['tracking_restored'] = True
        real_disable = demo_entry.disable_postprocessing
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            script = folder / 'tools/demo/demo.py'
            script.parent.mkdir(parents=True)
            script.write_text('# fixture')
            options = dict(raw_tracking_path=str(folder / 'raw.json'), selected_track_id=7,
                actor_id='39woman', expected_video=str(folder / 'input.mp4'),
                time_seconds=[.2, .2 + 1 / 30], no_postprocess=True)
            options_path = folder / 'options.json'
            options_path.write_text(json.dumps(options))
            def run_script(path, run_name):
                seen['argv'] = sys.argv.copy()
                seen['postproc'] = Pipeline().forward({}, postproc=True)
                seen['beta'] = renderer.get_global_cameras_static()['beta']
            old_argv, old_path = sys.argv.copy(), sys.path.copy()
            with patch.object(demo_entry, 'legacy_compatibility'), \
                    patch.object(tracking_evidence, 'record_tracking_evidence', tracking), \
                    patch.object(demo_entry, 'disable_postprocessing', side_effect=lambda: real_disable(Pipeline)), \
                    patch.object(demo_entry.runpy, 'run_path', side_effect=run_script), \
                    patch.dict(sys.modules, {'hmr4d.utils.vis': SimpleNamespace(renderer=renderer)}):
                demo_entry.main(['--launcher-options', str(options_path), str(script), '--cfg_file', 'config.yaml'])
            self.assertEqual(sys.argv, old_argv)
            self.assertEqual(sys.path, old_path)
            self.assertEqual(seen['tracking']['time_seconds'], options['time_seconds'])
            self.assertEqual(seen['tracking']['selected_track_id'], 7)
            self.assertEqual(seen['argv'], [str(script), '--cfg_file', 'config.yaml'])
            self.assertFalse(seen['postproc'])
            self.assertTrue(seen['tracking_restored'])
            self.assertIs(renderer.get_global_cameras_static, original_camera)
            self.assertIs(Pipeline.forward, original_forward)

    def test_mocked_local_launch_records_exact_pts_gpu_actor_and_ablation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'source.mp4'
            source.write_bytes(b'source-video-fixture')
            output = folder / 'run'
            pts = [i / 30 for i in range(4)]
            probe = dict(streams=[dict(nb_read_frames='4', duration=str(4 / 30), width=640,
                                      height=480, avg_frame_rate='30/1', time_base='1/30000')],
                         presentation_timestamps_seconds=pts, probe_backend='fixture')
            source_probe = dict(probe, presentation_timestamps_seconds=[.125 + value for value in pts])
            cfg = SimpleNamespace(paths=SimpleNamespace())
            omega = SimpleNamespace(OmegaConf=SimpleNamespace(load=lambda _: cfg,
                save=lambda cfg, path, resolve: Path(path).write_text('fixture-config')))
            children = []
            def call(command, **kwargs):
                if command[0] == 'ffmpeg' and run.NORMALIZATION_FILTER in command:
                    self.assertEqual(command[command.index('-frames:v') + 1], 4)
                    Path(command[-1]).write_bytes(b'normalized-video-fixture')
                if '--launcher-options' in command:
                    children.append((command, kwargs))
                    slam = Path(cfg.paths.slam)
                    slam.parent.mkdir(parents=True, exist_ok=True)
                    slam.write_bytes(b'dpvo-track-fixture')
                    (output / 'dpvo_timing.json').write_text(json.dumps(dict(status='completed', mode='source-pts',
                        completed_calls=len(pts), source_time_seconds=pts,
                        source=dict(sha256=tracking_evidence.file_sha256(output / '0_input_video.mp4')))))
                    (output / 'raw_tracking.json').write_text('{}')
                    (output / 'preprocess/bbx.pt').write_bytes(b'boxes')
                    (output / 'body_input_gating.npz').write_bytes(b'effective-array-fixture')
                    (output / 'body_input_gating.json').write_text(json.dumps(dict(status='completed',
                        mode='confidence-and-features', calls=1, source_time_seconds=pts, gated_frames=2,
                        source_sha256=tracking_evidence.file_sha256(output / '0_input_video.mp4'),
                        raw_tracking=dict(sha256=tracking_evidence.file_sha256(output / 'raw_tracking.json')),
                        boxes=dict(sha256=tracking_evidence.file_sha256(output / 'preprocess/bbx.pt')),
                        effective_inputs=dict(sha256=tracking_evidence.file_sha256(output / 'body_input_gating.npz')))))
                return SimpleNamespace(returncode=0)
            with patch.dict(os.environ, {}, clear=True), patch.object(run.socket, 'gethostname', return_value='workstation'), \
                    patch.object(run.socket, 'getfqdn', return_value='workstation'), \
                    patch.object(run, 'preflight', return_value={'ready_for_attempt': True}), \
                    patch.object(run, 'probe_video', side_effect=lambda path: source_probe if Path(path) == source else probe), \
                    patch.object(run, 'call', side_effect=call), \
                    patch.dict(sys.modules, {'omegaconf': omega}), redirect_stdout(io.StringIO()):
                status = run.main(['run', '--gpu', '1', '--camera', 'moving',
                    '--repo', str(folder), '--video', str(source), '--output', str(output),
                    '--track-id', '7', '--actor-id', 'rear', '--no-postprocess',
                    '--unsupported-body-inputs', 'confidence-and-features'])
            self.assertEqual(status, 0)
            provenance = json.loads((output / 'provenance.json').read_text())
            options = json.loads((output / 'launcher_options.json').read_text())
            self.assertEqual(options['time_seconds'], pts)
            self.assertEqual(options['selected_track_id'], 7)
            self.assertFalse(provenance['upstream_postprocessing'])
            self.assertEqual(provenance['execution'], 'local')
            self.assertEqual(provenance['camera_estimator'], 'dpvo')
            self.assertEqual(provenance['dpvo_timing'], 'source-pts')
            self.assertEqual(provenance['normalization']['source_first_pts_seconds'], .125)
            self.assertEqual(options['dpvo_timing'], 'source-pts')
            self.assertEqual(provenance['unsupported_body_inputs'], 'confidence-and-features')
            self.assertEqual(provenance['body_input_gating_evidence']['gated_frames'], 2)
            self.assertEqual(provenance['dpvo_timing_evidence']['sha256'], tracking_evidence.file_sha256(output / 'dpvo_timing.json'))
            self.assertEqual(provenance['camera_track']['sha256'], tracking_evidence.file_sha256(output / 'preprocess/slam_results.pt'))
            self.assertTrue(provenance['run_id'])
            self.assertEqual(children[0][1]['env']['CUDA_VISIBLE_DEVICES'], '1')
            self.assertEqual(children[0][1]['env']['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'], '1')
            self.assertTrue((output / 'normalized_probe.json').is_file())

    def test_shell_forwards_backend_options_without_importing_torch(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / 'python-stub'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            stub.chmod(0o755)
            env = dict(os.environ, GVHMR_PYTHON=str(stub))
            result = subprocess.run(['bash', str(Path(run.__file__).with_name('run.sh')), 'run',
                '--gpu', '2', '--camera', 'static'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[1:], ['run', '--gpu', '2', '--camera', 'static'])

    def test_pi3x_launch_preloads_cache_before_demo_and_records_true_estimator(self):
        from tools.gvhmr import camera_tracks
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'source.mp4'
            source.write_bytes(b'original')
            output = folder / 'run'
            pts = [i / 30 for i in range(4)]
            probe = dict(streams=[dict(nb_read_frames='4', duration=str(4 / 30), width=640, height=360)],
                         presentation_timestamps_seconds=pts)
            cfg = SimpleNamespace(paths=SimpleNamespace())
            omega = SimpleNamespace(OmegaConf=SimpleNamespace(load=lambda _:cfg,
                save=lambda cfg, path, resolve:Path(path).write_text('fixture-config')))
            seen = []
            def preload(**kwargs):
                self.assertEqual(kwargs['times'], pts)
                self.assertEqual(kwargs['image_size'], [640, 360])
                self.assertEqual(kwargs['source_sha256'], tracking_evidence.file_sha256(output / '0_input_video.mp4'))
                path = Path(kwargs['slam_path'])
                path.parent.mkdir(parents=True)
                path.write_bytes(b'pi3x-track')
                seen.append('preload')
                return dict(estimator='pi3x', frames=4)
            def call(command, **kwargs):
                if command[0] == 'ffmpeg' and run.NORMALIZATION_FILTER in command:
                    Path(command[-1]).write_bytes(b'exact-normalized')
                if '--launcher-options' in command:
                    self.assertTrue(Path(cfg.paths.slam).is_file())
                    self.assertEqual(Path(cfg.paths.slam).read_bytes(), b'pi3x-track')
                    seen.append('demo')
                return SimpleNamespace(returncode=0)
            with patch.dict(os.environ, {}, clear=True), patch.object(run.socket, 'gethostname', return_value='workstation'), \
                    patch.object(run.socket, 'getfqdn', return_value='workstation'), \
                    patch.object(run, 'preflight', return_value={'ready_for_attempt':True}), \
                    patch.object(run, 'probe_video', return_value=probe), patch.object(run, 'call', side_effect=call), \
                    patch.object(camera_tracks, 'preload_pi3x_slam', side_effect=preload), \
                    patch.dict(sys.modules, {'omegaconf':omega}), redirect_stdout(io.StringIO()):
                status = run.main(['run', '--gpu', '0', '--camera', 'moving',
                    '--camera-estimator', 'pi3x', '--pi3x-bundle', str(folder / 'bundle'),
                    '--repo', str(folder), '--video', str(source), '--output', str(output)])
            self.assertEqual(status, 0)
            self.assertEqual(seen, ['preload', 'demo'])
            provenance = json.loads((output / 'provenance.json').read_text())
            self.assertEqual(provenance['camera_estimator'], 'pi3x')
            self.assertEqual(provenance['camera_track']['estimator'], 'pi3x')
            self.assertEqual(provenance['camera_adapter']['estimator'], 'pi3x')
            self.assertIn('unused', provenance['intrinsics_estimator'])
            options = json.loads((output / 'launcher_options.json').read_text())
            self.assertIsNone(options['dpvo_timing'])
            self.assertEqual(options['unsupported_body_inputs'], 'keep')
            self.assertIsNone(options['body_input_evidence_path'])
            self.assertIsNone(options['dpvo_timing_path'])
            self.assertEqual(provenance['dpvo_timing'], 'not_used')


class DpvoTimingTests(unittest.TestCase):
    @staticmethod
    def model_class(fail_at=None):
        class TimingSensitiveModel:
            def __init__(self):
                self.counter = 0
                self.n = 0  # Deliberately never advances: incoming counter must be used.
                self.tlist = []
                self.factors = []
            def __call__(self, tstamp, image, intrinsics):
                if self.counter == fail_at:
                    raise RuntimeError('model failure fixture')
                self.tlist.append(tstamp)
                if len(self.tlist) >= 3:
                    a, b, c = self.tlist[-3:]
                    self.factors.append((c-b)/(b-a))  # Actual upstream DAMPED_LINEAR time factor.
                self.counter += 1
                return image, intrinsics
        return TimingSensitiveModel

    def test_source_pts_remove_processing_jitter_from_actual_time_ratio_and_restore(self):
        times = [.125 + i / 30 for i in range(4)]
        received = [100., 100.01, 101.01, 101.03]
        model_class = self.model_class()
        original = model_class.__call__
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'source.mp4'
            video.write_bytes(b'normalized-source')
            models = {}
            for mode in ('source-pts', 'upstream-wallclock'):
                model = model_class()
                image, intrinsics = object(), object()
                with demo_entry.dpvo_timing(root / (mode + '.json'), times, video, mode=mode, dpvo_class=model_class):
                    for index, stamp in enumerate(received):
                        result = model(stamp, image, intrinsics) if index % 2 == 0 else model(tstamp=stamp, image=image, intrinsics=intrinsics)
                        self.assertEqual(result, (image, intrinsics))
                self.assertIs(model_class.__call__, original)
                models[mode] = model
                report = json.loads((root / (mode + '.json')).read_text())
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['completed_calls'], 4)
                self.assertEqual([row['upstream_received_time_seconds'] for row in report['calls']], received)
                self.assertEqual([row['source_time_seconds'] for row in report['calls']], times)
                self.assertEqual([row['supplied_time_seconds'] for row in report['calls']], model.tlist)
                self.assertTrue(report['upstream_timer_profiling_unchanged'])
            np.testing.assert_allclose(models['source-pts'].factors, [1., 1.], atol=1e-12)
            np.testing.assert_allclose(models['upstream-wallclock'].factors, [100., .02], atol=1e-8)
            self.assertEqual(models['source-pts'].tlist, times)
            self.assertEqual(models['upstream-wallclock'].tlist, received)

    def test_missing_extra_reordered_and_multiple_instance_calls_fail_with_evidence(self):
        times = [0., 1 / 30, 2 / 30]
        cases = ['missing', 'extra', 'counter', 'second_instance']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'video'
            video.write_bytes(b'video')
            for case in cases:
                cls = self.model_class()
                original = cls.__call__
                model = cls()
                with self.subTest(case=case), self.assertRaises(ValueError):
                    with demo_entry.dpvo_timing(root / (case + '.json'), times, video, dpvo_class=cls):
                        if case == 'counter':
                            model.counter = 1
                        model(100., None, None)
                        if case == 'second_instance':
                            cls()(101., None, None)
                        if case == 'extra':
                            for stamp in [101., 102., 103.]:
                                model(stamp, None, None)
                self.assertIs(cls.__call__, original)
                self.assertEqual(json.loads((root / (case + '.json')).read_text())['status'], 'failed')

    def test_model_exception_restores_method_and_marks_incomplete_row(self):
        cls = self.model_class(fail_at=1)
        original = cls.__call__
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'video'
            video.write_bytes(b'video')
            with self.assertRaisesRegex(RuntimeError, 'model failure'):
                with demo_entry.dpvo_timing(root / 'failed.json', [0, 1 / 30], video, dpvo_class=cls):
                    model = cls()
                    model(100., None, None)
                    model(101., None, None)
            self.assertIs(cls.__call__, original)
            report = json.loads((root / 'failed.json').read_text())
            self.assertEqual(report['completed_calls'], 1)
            self.assertEqual(report['calls'][1]['status'], 'started')
            self.assertEqual(report['status'], 'failed')

    def test_bad_source_timeline_wallclock_monotonicity_and_existing_sidecar_rejected(self):
        cls = self.model_class()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'video'
            video.write_bytes(b'video')
            with self.assertRaisesRegex(ValueError, '30 Hz'):
                with demo_entry.dpvo_timing(root / 'bad.json', [0, .1], video, dpvo_class=cls):
                    pass
            with self.assertRaisesRegex(ValueError, 'strictly increasing'):
                with demo_entry.dpvo_timing(root / 'clock.json', [0, 1 / 30], video, mode='upstream-wallclock', dpvo_class=cls):
                    model = cls()
                    model(100., None, None)
                    model(100., None, None)
            before = (root / 'clock.json').read_bytes()
            with self.assertRaises(FileExistsError):
                with demo_entry.dpvo_timing(root / 'clock.json', [0, 1 / 30], video, dpvo_class=cls):
                    pass
            self.assertEqual((root / 'clock.json').read_bytes(), before)

    def test_cli_fragment_flags_are_paired_and_exclude_single_id(self):
        for arguments in [['--cached-raw-tracking', 'raw'], ['--actor-review', 'review'],
                ['--cached-raw-tracking', 'raw', '--actor-review', 'review', '--track-id', '2']]:
            with self.subTest(arguments=arguments), patch.object(run, 'preflight') as preflight, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run.main(['check', '--camera', 'static', *arguments])
            preflight.assert_not_called()

    def test_child_wires_reviewed_fragments_and_only_enters_dpvo_for_active_estimator(self):
        from contextlib import nullcontext
        renderer = SimpleNamespace(get_global_cameras_static=lambda **kw:kw)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / 'tools/demo/demo.py'
            script.parent.mkdir(parents=True)
            script.write_text('# fixture')
            for mode, estimator, timing in [('static', 'dpvo', None), ('moving', 'pi3x', None), ('moving', 'dpvo', 'source-pts')]:
                options = dict(raw_tracking_path=str(root / 'new_tracking.json'), selected_track_id=None,
                    actor_id='rear', expected_video=str(root / 'video.mp4'), time_seconds=[0, 1 / 30], no_postprocess=False,
                    cached_raw_tracking_path=str(root / 'prior_raw.json'), actor_review_path=str(root / 'review.json'),
                    camera_mode=mode, camera_estimator=estimator, dpvo_timing=timing,
                    dpvo_timing_path=str(root / 'timing.json') if timing else None)
                path = root / 'options.json'
                path.write_text(json.dumps(options))
                with self.subTest(mode=mode, estimator=estimator), \
                        patch.object(demo_entry, 'legacy_compatibility'), patch.object(demo_entry.runpy, 'run_path'), \
                        patch.object(tracking_evidence, 'record_tracking_evidence', return_value=nullcontext()) as tracking, \
                        patch.object(demo_entry, 'dpvo_timing', return_value=nullcontext()) as dpvo, \
                        patch.dict(sys.modules, {'hmr4d.utils.vis':SimpleNamespace(renderer=renderer)}):
                    demo_entry.main(['--launcher-options', str(path), str(script)])
                self.assertEqual(tracking.call_args.kwargs['cached_raw_tracking_path'], options['cached_raw_tracking_path'])
                self.assertEqual(tracking.call_args.kwargs['actor_review_path'], options['actor_review_path'])
                if timing:
                    self.assertEqual(dpvo.call_args.args, (options['dpvo_timing_path'], options['time_seconds'], options['expected_video']))
                    self.assertEqual(dpvo.call_args.kwargs, dict(mode='source-pts'))
                else:
                    dpvo.assert_not_called()


class BodyInputGatingTests(unittest.TestCase):
    def data(self):
        rng = np.random.default_rng(4)
        return dict(kp2d=rng.random((4,17,3)), f_imgseq=rng.normal(size=(4,8)),
                    length=np.array(4),bbx_xys=np.ones((4,3)),K_fullimg=np.tile(np.eye(3),(4,1,1)),
                    cam_angvel=np.ones((4,6)))

    def test_keep_is_identical_and_nonkeep_clones_only_requested_rows(self):
        data = self.data(); before = {k:v.copy() for k,v in data.items()}
        detected = np.array([True,False,False,True])
        self.assertIs(demo_entry.gate_body_conditions(data,None,'keep'),data)
        for mode in demo_entry.BODY_INPUT_MODES[1:]:
            out = demo_entry.gate_body_conditions(data,detected,mode)
            np.testing.assert_array_equal(out['kp2d'][detected],before['kp2d'][detected])
            np.testing.assert_array_equal(out['kp2d'][...,:2],before['kp2d'][...,:2])
            self.assertFalse(out['kp2d'][~detected,:,2].any())
            np.testing.assert_array_equal(out['f_imgseq'][detected],before['f_imgseq'][detected])
            if mode=='confidence-and-features': self.assertFalse(out['f_imgseq'][~detected].any())
            else: self.assertIs(out['f_imgseq'],data['f_imgseq'])
            for key in ('length','bbx_xys','K_fullimg','cam_angvel'): self.assertIs(out[key],data[key])
            for key in data: np.testing.assert_array_equal(data[key],before[key])

    def test_bad_support_and_inputs_are_rejected(self):
        for support in ([1,0,0,1],np.array([True,False]),np.ones((4,1),dtype=bool)):
            with self.assertRaises(ValueError): demo_entry.gate_body_conditions(self.data(),support,'confidence-only')
        data=self.data();data['f_imgseq'][0,0]=np.nan
        with self.assertRaises(ValueError): demo_entry.gate_body_conditions(data,np.ones(4,dtype=bool),'confidence-only')

    def test_context_passes_cloned_inputs_and_restores_with_failure_evidence(self):
        class Model:
            def predict(self,data,static_cam=False):
                if static_cam: raise RuntimeError('fixture model failure')
                return data
        original=Model.predict
        detected=np.array([True,False,False,True])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for mode in demo_entry.BODY_INPUT_MODES[1:]:
                data=self.data();path=root/(mode+'.json')
                with patch.object(demo_entry,'validated_body_support',return_value=(detected,dict(source_sha256='fixture'))):
                    with demo_entry.unsupported_body_inputs(path,mode=mode,raw_tracking_path='raw',boxes_path='boxes',
                            expected_video='video',time_seconds=np.arange(4)/30,image_size=[640,480],demo_class=Model):
                        out=Model().predict(data)
                self.assertIs(Model.predict,original)
                np.testing.assert_array_equal(out['kp2d'][detected],data['kp2d'][detected])
                report=json.loads(path.read_text());self.assertEqual(report['status'],'completed')
                self.assertEqual(report['gated_frames'],2)
                with np.load(path.with_suffix('.npz')) as arrays:
                    np.testing.assert_array_equal(arrays['original_kp2d'],data['kp2d'])
                    np.testing.assert_array_equal(arrays['effective_kp2d'],out['kp2d'])
            for case in ('missing','twice','failure'):
                path=root/(case+'.json')
                with patch.object(demo_entry,'validated_body_support',return_value=(detected,dict(source_sha256='fixture'))), self.assertRaises((ValueError,RuntimeError)):
                    with demo_entry.unsupported_body_inputs(path,mode='confidence-only',raw_tracking_path='raw',boxes_path='boxes',
                            expected_video='video',time_seconds=np.arange(4)/30,image_size=[640,480],demo_class=Model):
                        if case=='twice': Model().predict(self.data());Model().predict(self.data())
                        if case=='failure': Model().predict(self.data(),static_cam=True)
                self.assertIs(Model.predict,original)
                self.assertEqual(json.loads(path.read_text())['status'],'failed')
            with self.assertRaises(FileExistsError):
                with demo_entry.unsupported_body_inputs(root/'confidence-only.json',mode='confidence-only',raw_tracking_path='raw',
                        boxes_path='boxes',expected_video='video',time_seconds=np.arange(4)/30,image_size=[640,480],demo_class=Model): pass

    def test_child_wires_only_explicit_gate(self):
        from contextlib import nullcontext
        renderer=SimpleNamespace(get_global_cameras_static=lambda **kw:kw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'tools/demo/demo.py';script.parent.mkdir(parents=True);script.write_text('# fixture')
            for mode in demo_entry.BODY_INPUT_MODES:
                options=dict(raw_tracking_path='raw',selected_track_id=3,actor_id='rear',expected_video='video',
                    time_seconds=[0,1/30],no_postprocess=False,cached_raw_tracking_path=None,actor_review_path=None,
                    camera_mode='static',camera_estimator='dpvo',dpvo_timing=None,dpvo_timing_path=None,
                    unsupported_body_inputs=mode,body_input_evidence_path=None if mode=='keep' else 'gate.json',
                    image_size=[640,480],bbx_path='boxes')
                path=root/'options.json';path.write_text(json.dumps(options))
                with patch.object(demo_entry,'legacy_compatibility'),patch.object(demo_entry.runpy,'run_path'), \
                        patch.object(tracking_evidence,'record_tracking_evidence',return_value=nullcontext()), \
                        patch.object(demo_entry,'unsupported_body_inputs',return_value=nullcontext()) as gate, \
                        patch.dict(sys.modules,{'hmr4d.utils.vis':SimpleNamespace(renderer=renderer)}):
                    demo_entry.main(['--launcher-options',str(path),str(script)])
                if mode=='keep': gate.assert_not_called()
                else:
                    self.assertEqual(gate.call_args.kwargs['mode'],mode)
                    self.assertEqual(gate.call_args.kwargs['boxes_path'],'boxes')


if __name__ == '__main__':
    unittest.main()
