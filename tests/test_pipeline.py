"""Filesystem integration tests with tiny subprocess stages, not Blender/ML loads."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.config import timing, validate_recipe
from aha3d.io import lock, read, write
from aha3d.pipeline import runner


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='indoor-test-')
        self.root = Path(self.tmp.name)
        for folder in ['src/pkg', 'runtime/upstream/kimodo', 'runtime/checkpoint', 'configs/runtimes', 'scenes/one/recipes']:
            (self.root / folder).mkdir(parents=True)
        (self.root / 'src/pkg/__init__.py').write_text('value = 1\n')
        (self.root / 'source.blend').write_bytes(b'test-source')
        (self.root / 'runtime/exe').write_text('fixture')
        (self.root / 'runtime/env.sh').write_text('fixture-environment')
        write(self.root / 'configs/runtimes/test.json', dict(schema_version=2, python='runtime/exe',
            blender='runtime/exe', skin_blender='runtime/exe', env_script='runtime/env.sh',
            upstream='runtime/upstream', checkpoint='runtime/checkpoint', threads=1, gpu=0))
        write(self.root / 'scenes/one/scene.json', dict(schema_version=1, id='one'))
        self.recipe = dict(schema_version=1, scene='one', id='replay', source='source.blend',
            timing=dict(fps='30000/1001', frames=450, duration_seconds=15.015), runtime='test', body=dict(mode='keep'))
        write(self.root / 'scenes/one/recipes/replay.json', self.recipe)
        self.fixture = self.root / 'stage.py'
        self.fixture.write_text("from pathlib import Path\nimport sys\nr=Path(sys.argv[1]);s=sys.argv[2];o=r/'stages'/s;o.mkdir(parents=True,exist_ok=True)\n(o/'artifact.txt').write_text(s)\nif s=='assemble':(o/'scene.blend').write_bytes(b'assembled')\n")

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, name='test'):
        run = runner.prepare(self.root, 'one', 'replay', run_id=name)
        # These tests exercise historical manifest compatibility; new gates have dedicated coverage.
        data = read(run / 'run.json'); data.pop('preview_policy', None); data.pop('acceptance_policy', None); (run/'snapshot/workflow_policy.json').unlink(); data['snapshot'].pop('workflow_policy.json'); write(run / 'run.json', data)
        return run

    def run_stages(self, run, **kwargs):
        def command(run, recipe, runtime, stage, budget):
            return [sys.executable, str(self.fixture), str(run), stage]
        with patch.object(runner, 'command', side_effect=command), patch('aha3d.workflow.submission_preflight.device_check'):
            return runner.execute(run, **kwargs)

    def test_rational_timing_and_schema_validation(self):
        self.assertEqual(timing(self.recipe['timing'])['duration_seconds'], 15.015)
        for value in [dict(fps='0', frames=1), dict(fps='24', frames=True), dict(fps='24', frames=120, duration_seconds=6)]:
            with self.assertRaises(ValueError): timing(value)
        invalid = copy.deepcopy(self.recipe); invalid['render'] = {'sampls': 8}
        with self.assertRaises(ValueError): validate_recipe(invalid)

    def test_new_scope_policy_cannot_be_removed_to_skip_prerequisites(self):
        run=runner.prepare(self.root,'one','replay',run_id='guarded')
        data=read(run/'run.json');data.pop('acceptance_policy');write(run/'run.json',data)
        with self.assertRaisesRegex(ValueError,'workflow policy'):runner.load(run)

    def test_new_unscoped_run_is_blocked_before_assembly(self):
        run=runner.prepare(self.root,'one','replay',run_id='unscoped')
        result=self.run_stages(run)
        self.assertEqual(result['status'],'blocked');self.assertNotIn('assemble',result['stages'])

    def test_diagnostic_producer_scope_is_frozen(self):
        run=runner.prepare(self.root,'one','replay',run_id='diagnostic',preview=True)
        data=read(run/'run.json');self.assertTrue(data['diagnostic_only'])
        data['diagnostic_only']=False;write(run/'run.json',data)
        with self.assertRaisesRegex(ValueError,'workflow policy'):runner.load(run)

    def test_snapshot_is_independent_and_rejects_tampering(self):
        run = self.prepare()
        (self.root / 'source.blend').write_bytes(b'changed-live-source')
        (self.root / 'src/pkg/__init__.py').write_text('value = 2\n')
        runner.load(run)
        self.assertEqual((run / 'inputs/source.blend').read_bytes(), b'test-source')
        (run / 'snapshot/src/pkg/__init__.py').write_text('tampered')
        with self.assertRaises(ValueError): runner.load(run)

    def test_duplicate_run_id_never_overwrites(self):
        run = self.prepare()
        before = (run / 'run.json').read_bytes()
        with self.assertRaises(FileExistsError): self.prepare()
        self.assertEqual(before, (run / 'run.json').read_bytes())

    def test_concurrent_run_creation_is_isolated(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(self.prepare, ['one', 'two']))
        self.assertNotEqual(runs[0], runs[1])
        self.assertEqual(read(runs[0] / 'run.json')['code_signature'], read(runs[1] / 'run.json')['code_signature'])

    def test_resume_skips_intact_stages_and_repairs_corruption(self):
        run = self.prepare()
        first = self.run_stages(run, until='assemble')
        self.assertEqual(first['status'], 'staged')
        final = self.run_stages(run)
        self.assertEqual(final['status'], 'validated')
        self.assertEqual(final['stages']['assemble']['attempts'], 1)
        (run / 'stages/verify/artifact.txt').write_text('corrupt')
        repaired = self.run_stages(run)
        self.assertEqual(repaired['stages']['verify']['attempts'], 2)
        self.assertEqual(repaired['stages']['render']['attempts'], 1)

    def test_failed_stage_is_not_marked_complete(self):
        run = self.prepare()
        self.fixture.write_text('raise SystemExit(3)\n')
        with self.assertRaises(RuntimeError): self.run_stages(run)
        state = read(run / 'run.json')
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['stages']['assemble']['status'], 'failed')
        self.assertNotIn('render', state['stages'])

    def test_execution_lock_and_local_run_identity(self):
        run = self.prepare()
        with lock(run / '.execute.lock'):
            owner = read(run / '.execute.lock/owner.json')
            with self.assertRaises(ValueError): self.run_stages(run)
        self.assertEqual(owner['job_id'], os.environ['INDOOR_RUN_ID'])
        self.assertFalse((run / '.execute.lock').exists())

    def test_unrecorded_snapshot_files_are_rejected(self):
        run = self.prepare()
        (run / 'snapshot/src/extra.py').write_text('unrecorded = True\n')
        with self.assertRaises(ValueError): runner.load(run)

    def test_queued_recipe_changes_fail_before_snapshot(self):
        with patch.object(runner.host, 'start_background', return_value=4321) as start:
            result = runner.submit_recipes(self.root, [('one', 'replay')], preview=True)
        start.assert_called_once()
        self.assertFalse(Path(result['runs'][0]).exists())
        self.recipe['timing']['frames'] = 451
        self.recipe['timing'].pop('duration_seconds')
        write(self.root / 'scenes/one/recipes/replay.json', self.recipe)
        with self.assertRaises(ValueError): runner.launch(Path(result['batch']) / 'request-0.json')
        self.assertFalse(Path(result['runs'][0]).exists())

    def test_runtime_changes_reject_resume(self):
        run = self.prepare()
        (self.root / 'runtime/env.sh').write_text('changed')
        with self.assertRaises(ValueError): self.run_stages(run)

    def test_camera_edits_do_not_change_motion_fingerprint(self):
        run = self.prepare(); manifest, recipe, runtime = runner.load(run)
        recipe['body'] = dict(mode='generate', prompt='A person walks. A person pauses.', durations=[10, 5], seed=42)
        before = runner.fingerprint(run, manifest, recipe, 'motion')
        other = copy.deepcopy(recipe); other['assembly']['camera'] = {'location': [1, 2, 3]}
        other['render']['samples'] = 99
        self.assertEqual(before, runner.fingerprint(run, manifest, other, 'motion'))
        other['body']['seed'] = 43
        self.assertNotEqual(before, runner.fingerprint(run, manifest, other, 'motion'))

    def test_motion_only_needs_no_room_and_stops_at_skin(self):
        self.recipe['body'] = dict(mode='generate', prompt='A person walks. A person pauses.', durations=[10, 5.015])
        write(self.root / 'scenes/one/recipes/replay.json', self.recipe)
        (self.root / 'source.blend').unlink()
        run = runner.prepare(self.root, 'one', 'replay', run_id='motion', motion_only=True)
        self.assertNotIn('source.blend', read(run / 'run.json')['inputs'])
        # Fixture native/resample outputs are sufficient for fingerprinting the next stage.
        with self.fixture.open('a') as stream:
            stream.write("if s=='motion':(o/'motion.npz').write_bytes(b'native')\nif s=='resample':(o/'motion.npz').write_bytes(b'resampled')\n")
        final = self.run_stages(run)
        self.assertEqual(final['status'], 'staged')
        self.assertEqual(list(final['stages']), ['motion', 'resample', 'skin'])
        resumed = self.run_stages(run)
        self.assertTrue(all(v['attempts'] == 1 for v in resumed['stages'].values()))
        with self.assertRaises(ValueError): self.run_stages(run, until='assemble')

    def test_keep_cannot_be_prepared_motion_only(self):
        with self.assertRaises(ValueError):
            runner.prepare(self.root, 'one', 'replay', run_id='bad-scope', motion_only=True)
        self.assertFalse((self.root / 'runs/one/bad-scope').exists())

    def test_per_prompt_duration_and_count_rejected_before_snapshot(self):
        cases = [('A person sits.', [15.015], '10 seconds'),
                 ('A person sits. A person stays seated.', [10.0001, 5.0149], '10 seconds'),
                 ('A person sits.', [5, 5, 5.015], 'one duration'),
                 ('A person sits. A person stays seated.', [7.5], 'one duration')]
        for index, (prompt, durations, error) in enumerate(cases):
            with self.subTest(durations=durations, prompt=prompt):
                self.recipe['body'] = dict(mode='generate', prompt=prompt, durations=durations)
                write(self.root / 'scenes/one/recipes/replay.json', self.recipe)
                run_id = 'bad-duration-' + str(index)
                with self.assertRaisesRegex(ValueError, error):
                    runner.prepare(self.root, 'one', 'replay', run_id=run_id, motion_only=True)
                self.assertFalse((self.root / 'runs/one' / run_id).exists())



class LocalBatch(unittest.TestCase):
    """Background batches run tasks sequentially in one detached local worker."""
    setUp, tearDown, prepare = Pipeline.setUp, Pipeline.tearDown, Pipeline.prepare

    def test_submit_writes_sequential_worker_and_submission(self):
        runs = [self.prepare('first'), self.prepare('second')]
        with patch.object(runner.host, 'start_background', return_value=4321) as start:
            result = runner.submit(runs, until='assemble')
        batch = Path(result['batch']); job = batch.name
        self.assertEqual((result['status'], result['job_id'], result['pid']), ('submitted', job, 4321))
        self.assertEqual(result['runs'], [str(r) for r in runs])
        self.assertEqual(start.call_args.args, (batch / 'job.sh', batch / 'batch.log'))
        script = (batch / 'job.sh').read_text()
        self.assertIn('runtime/env.sh', script)
        for i, run in enumerate(runs):
            self.assertIn(f'export INDOOR_RUN_ID={job}_{i}; export PYTHONPATH={run}/snapshot/src; ', script)
            self.assertIn(f'>{batch}/{i}.log 2>&1', script); self.assertIn(f'>{batch}/{i}.log.exit', script)
            self.assertEqual(read(run / f'submission-{job}.json')['job_id'], f'{job}_{i}')
        self.assertLess(script.index(str(runs[0])), script.index(str(runs[1])))
        self.assertIn('execute ' + str(runs[0]) + ' --until assemble', script)
        submission = read(batch / 'submission.json')
        self.assertEqual((submission['job_id'], submission['pid'], submission['runs']), (job, 4321, [str(r) for r in runs]))
        self.assertNotIn('concurrency', submission)

    def test_submit_recipes_worker_launches_each_request_with_its_run_id(self):
        with patch.object(runner.host, 'start_background', return_value=99) as start:
            result = runner.submit_recipes(self.root, [('one', 'replay')], preview=True)
        batch = Path(result['batch']); job = batch.name; script = (batch / 'job.sh').read_text()
        self.assertEqual((result['job_id'], result['pid'], read(batch / 'submission.json')['pid']), (job, 99, 99))
        self.assertIn('export PYTHONPATH=' + str(self.root.resolve() / 'src'), script)
        self.assertIn(f'export INDOOR_RUN_ID={job}_0; ', script)
        self.assertIn('launch ' + str(batch / 'request-0.json'), script)
        start.assert_called_once_with(batch / 'job.sh', batch / 'batch.log')

    def test_launch_records_inherited_run_id(self):
        with patch.object(runner.host, 'start_background', return_value=1):
            result = runner.submit_recipes(self.root, [('one', 'replay')], preview=True)
        with patch.dict(os.environ, INDOOR_RUN_ID='batchid_0'), patch.object(runner.subprocess, 'run') as child:
            runner.launch(Path(result['batch']) / 'request-0.json')
        run = Path(result['runs'][0])
        self.assertEqual(read(run / 'submission-batchid_0.json')['job_id'], 'batchid_0')
        self.assertEqual(child.call_args.kwargs['env']['INDOOR_RUN_ID'], 'batchid_0')


if __name__ == '__main__': unittest.main()
