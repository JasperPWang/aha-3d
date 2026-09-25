"""Real hook adapter invoked by Stop, with no optional finish tool involved."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from aha3d.io import read, write
from aha3d.workflow import completion
from aha3d.workflow.acceptance_cli import main as cli
import test_acceptance


class Completion(test_acceptance.Acceptance):
    def setUp(self):
        super().setUp();completion.bind(self.root,'room','task','session')
        self.event=dict(hook_event_name='Stop',session_id='session',turn_id='turn',last_assistant_message='Done!')

    def test_stop_event_blocks_without_finish_tool(self):
        result=completion.handle(self.root,self.event)
        self.assertEqual(result['decision'],'block');self.assertIn('ACCEPTANCE_REFRESH_REQUIRED',result['reason'])
        self.assertEqual(read(self.out/'state.json')['status'],'blocked')

    def test_claim_completion_requires_current_selected_evidence(self):
        with self.assertRaises(ValueError):
            completion.require_completed_claim(self.root, 'room', 'task')
        self.complete(); self.delivery()
        with self.assertRaises(ValueError):
            completion.require_completed_claim(self.root, 'room', 'task')
        test_acceptance.registry.select(self.root, 'room', 'v1')
        completion.require_completed_claim(self.root, 'room', 'task')
        with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
            completion.require_completed_claim(self.root, 'room', 'another-task')
        (self.root / 'technical.json').write_text('stale evidence')
        with self.assertRaises(ValueError):
            completion.require_completed_claim(self.root, 'room', 'task')

    def test_claim_release_uses_gate_without_hook_or_session_binding(self):
        root = Path(__file__).resolve().parents[1]
        script = root / 'tools/task_claim.py'
        env = dict(os.environ, PYTHONPATH=str(root / 'src'))
        env.pop('CODEX_THREAD_ID', None)
        def run(*args):
            return subprocess.run([os.sys.executable, str(script), '--root',
                                   str(self.root), *args], env=env, text=True,
                                  capture_output=True, timeout=30)
        result = run('claim', 'writer', '--owner', 'agent', '--title', 'room',
                     '--scene', 'room', '--acceptance-task', 'task', '--paths', 'scenes/room', 'deliveries/room')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = ('release', 'writer', '--owner', 'agent', '--status', 'completed',
                '--note', 'validated delivery')
        self.assertEqual(run(*args).returncode, 2)
        self.assertEqual(read(self.root / 'tasks/writer/task.json')['status'], 'active')
        self.complete(); self.delivery(); test_acceptance.registry.select(self.root, 'room', 'v1')
        result = run(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read(self.root / 'tasks/writer/task.json')['status'], 'completed')

    def test_claim_completion_rejects_scope_redirection_and_nonreconstruction(self):
        pointer = self.root / 'scenes/room/task_scope.json'
        write(pointer, dict(task_scope=str(self.root / 'outside/scope.json')))
        with self.assertRaises(ValueError):
            completion.require_completed_claim(self.root, 'room', 'task')
        test_acceptance.gate.init(self.root, dict(scene='room', task='code', kind='code'))
        write(pointer, dict(task_scope=str(self.root / 'deliveries/room/acceptance/code/scope.json')))
        with self.assertRaises(ValueError):
            completion.require_completed_claim(self.root, 'room', 'task')

    def test_completion_validation_releases_registry_lock_and_detects_claim_change(self):
        import argparse
        import importlib.util
        script = Path(__file__).resolve().parents[1] / 'tools/task_claim.py'
        spec = importlib.util.spec_from_file_location('task_claim_test', script)
        claims = importlib.util.module_from_spec(spec); spec.loader.exec_module(claims)
        common = dict(root=self.root, task='task', owner='agent')
        claims.execute(argparse.Namespace(**common, command='claim', title='room',
                       paths=['scenes/room'], scene='room', kind='reconstruction',
                       acceptance_task=None, depends_on=[]))
        def concurrent_checkpoint(*unused):
            result = subprocess.run([os.sys.executable, str(script), '--root', str(self.root),
                                     'checkpoint', 'task', '--owner', 'agent', '--note',
                                     'new work during validation'], text=True,
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        with patch.object(completion, 'require_completed_claim', side_effect=concurrent_checkpoint):
            with self.assertRaisesRegex(ValueError, 'Claim changed during validation'):
                claims.execute(argparse.Namespace(**common, command='release',
                               status='completed', note='done'))
        self.assertEqual(read(self.root / 'tasks/task/task.json')['status'], 'active')

    def test_cancellation_exhaustion_and_interrupt_never_accept(self):
        self.assertEqual(completion.handle(self.root,self.event)['decision'],'block')
        self.event.update(stop_hook_active=True,turn_id='another-turn')
        self.assertEqual(completion.handle(self.root,self.event)['decision'],'block')
        self.assertFalse(completion.handle(self.root,self.event)['continue'])
        self.assertEqual(read(self.out/'state.json')['status'],'incomplete')
        self.assertFalse((self.root/'deliveries/room/selected.json').exists())
        state=read(self.out/'state.json');state['status']='cancelled';write(self.out/'state.json',state)
        self.assertFalse(completion.handle(self.root,self.event)['continue'])
        self.event['hook_event_name']='Interrupt';completion.handle(self.root,self.event)
        self.assertEqual(read(self.out/'state.json')['status'],'incomplete')

    def test_code_only_and_unrelated_tasks_do_not_block(self):
        self.event['session_id']='unrelated';self.assertEqual(completion.handle(self.root,self.event),{})
        gate=test_acceptance.gate
        gate.init(self.root,dict(scene='code',task='maintenance',kind='code'))
        completion.bind(self.root,'code','maintenance','coding');self.event['session_id']='coding'
        self.assertEqual(completion.handle(self.root,self.event),{})

    def test_current_selected_acceptance_allows_stop_and_stale_evidence_blocks(self):
        self.complete();self.delivery();test_acceptance.registry.select(self.root,'room','v1')
        self.assertEqual(completion.handle(self.root,self.event),{})
        (self.root/'technical.json').write_text('changed')
        self.assertEqual(completion.handle(self.root,self.event)['decision'],'block')

    def test_lightweight_hook_never_launches_compute_or_hashes_large_artifacts(self):
        self.complete();self.delivery();test_acceptance.registry.select(self.root,'room','v1')
        with patch.dict(os.environ,{},clear=True),patch('subprocess.run',side_effect=AssertionError('compute launched')),patch('aha3d.workflow.acceptance.capture',side_effect=AssertionError('heavy hashing')):
            self.assertEqual(completion.handle(self.root,self.event),{})

    def test_cli_records_pause_and_reports_blocked_with_nonzero_exit(self):
        import contextlib,io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli(['state','room','task','paused','--reason','User requested pause'],self.root),0)
            self.assertEqual(cli(['check','room','task'],self.root),2)
        self.assertFalse(completion.handle(self.root,self.event)['continue'])

    def test_installed_hook_config_has_real_stop_and_interrupt(self):
        root=Path(__file__).resolve().parents[1]
        hooks=read(root/'.codex/hooks.json')['hooks']
        self.assertEqual(set(hooks),{'Stop','Interrupt'})
        self.assertIn('completion-hook',hooks['Stop'][0]['hooks'][0]['command'])
        env=dict(os.environ,PYTHONPATH=str(root/'src'))
        result=subprocess.run([os.sys.executable,str(root/'tools/indoor_completion_hook.py')],input=json.dumps(dict(self.event,session_id='unbound-fixture')),text=True,capture_output=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),{})

    def test_cancelled_task_cannot_be_reactivated_by_a_writer_or_candidate(self):
        gate=test_acceptance.gate
        state=read(self.out/'state.json');state['status']='cancelled';write(self.out/'state.json',state)
        gate.register_candidate(self.root,'room','task',self.spec)
        gate.record_job(dict(task_scope=str(self.out/'scope.json')),self.root/'manifest.json','123','completed')
        self.assertEqual(read(self.out/'state.json')['status'],'cancelled')
        self.assertFalse(self.complete()['permitted'])
        self.assertFalse(completion.handle(self.root,self.event)['continue'])

    def test_refresh_cannot_certify_a_selection_pointing_at_other_artifacts(self):
        self.complete();self.delivery();test_acceptance.registry.select(self.root,'room','v1')
        path=self.root/'deliveries/room/versions/v1.json';delivery=read(path)
        delivery['artifacts'][0]['path']='room.blend';write(path,delivery)
        pointer_path=self.root/'deliveries/room/selected.json';pointer=read(pointer_path)
        pointer['delivery_sha256']=test_acceptance.digest(path);write(pointer_path,pointer)
        result=test_acceptance.gate.evaluate(self.root,'room','task')
        completion.cache_result(self.out,result)
        self.assertEqual(completion.handle(self.root,self.event)['decision'],'block')

    def test_session_bindings_do_not_break_the_existing_task_registry(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([os.sys.executable,str(root/'tools/task_claim.py'),'--root',str(self.root),'list'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[])
        self.assertTrue((self.root/'tasks/.acceptance_sessions/session.json').is_file())
