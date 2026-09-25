"""Single-workstation execution context and schema-2 runtime profiles."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d import runtime
from aha3d.config import load_runtime


class RunIdentity(unittest.TestCase):
    def test_run_id_is_created_once_and_inherited_by_children(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('INDOOR_RUN_ID', None)
            value = runtime.run_id()
            self.assertTrue(value.startswith('local-'))
            self.assertEqual(runtime.run_id(), value); self.assertEqual(os.environ['INDOOR_RUN_ID'], value)
            child = subprocess.check_output([sys.executable, '-c', 'import os; print(os.environ["INDOOR_RUN_ID"])'], text=True)
            self.assertEqual(child.strip(), value)
        with patch.dict(os.environ, INDOOR_RUN_ID='batch_3'):
            self.assertEqual(runtime.run_id(), 'batch_3')


class Resources(unittest.TestCase):
    def test_threads_precedence_env_then_profile_then_cores(self):
        with patch.dict(os.environ, INDOOR_THREADS='3'):
            self.assertEqual(runtime.threads({'threads': 6}), 3)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('INDOOR_THREADS', None)
            self.assertEqual(runtime.threads({'threads': 6}), 6)
            self.assertEqual(runtime.threads({'threads': None}), os.cpu_count() or 4)
            self.assertEqual(runtime.threads(), os.cpu_count() or 4)
        with patch.dict(os.environ, INDOOR_THREADS='0'), self.assertRaises(ValueError):
            runtime.threads()

    def test_gpu_visible_only_hidden_when_explicitly_disabled(self):
        self.assertTrue(runtime.gpu_visible({}))
        self.assertTrue(runtime.gpu_visible({'CUDA_VISIBLE_DEVICES': '0'}))
        for hidden in ('', '-1', 'none', 'NoDevFiles', ' '):
            self.assertFalse(runtime.gpu_visible({'CUDA_VISIBLE_DEVICES': hidden}))
        runtime.require_gpu('render', {})
        with self.assertRaisesRegex(ValueError, 'render needs a GPU'):
            runtime.require_gpu('render', {'CUDA_VISIBLE_DEVICES': '-1'})


class Worker(unittest.TestCase):
    def test_sequential_script_records_exit_codes_and_continues_past_failures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); env = root / 'env.sh'; env.write_text('export FIXTURE_VALUE=sourced\n')
            logs = [root / f'{i}.log' for i in range(3)]
            order = root / 'order.txt'
            commands = [f'echo first >>{order}; echo "$FIXTURE_VALUE"', f'echo second >>{order}; exit 7', f'echo third >>{order}; echo "$PREAMBLE"']
            script = root / 'job.sh'
            script.write_text(runtime.sequential_script(commands, logs, env, ['export PREAMBLE=shared']))
            completed = subprocess.run(['bash', str(script)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(order.read_text().split(), ['first', 'second', 'third'])
            self.assertEqual([Path(str(p) + '.exit').read_text().strip() for p in logs], ['0', '7', '0'])
            self.assertEqual(logs[0].read_text().strip(), 'sourced'); self.assertEqual(logs[2].read_text().strip(), 'shared')

    def test_all_successful_tasks_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); script = root / 'job.sh'
            script.write_text(runtime.sequential_script(['true', 'true'], [root / '0.log', root / '1.log']))
            self.assertEqual(subprocess.run(['bash', str(script)]).returncode, 0)

    def test_start_background_detaches_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); script = root / 'job.sh'; done = root / 'done'
            script.write_text(f'echo started\ntouch {done}\n')
            pid = runtime.start_background(script, root / 'logs/batch.log')
            self.assertIsInstance(pid, int)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:  # Already reaped by subprocess bookkeeping.
                pass
            self.assertFalse(runtime.alive(pid))
            self.assertTrue(done.exists()); self.assertEqual((root / 'logs/batch.log').read_text().strip(), 'started')
        self.assertTrue(runtime.alive(os.getpid()))
        self.assertFalse(runtime.alive(None)); self.assertFalse(runtime.alive('not-a-pid'))


class LiveStatus(unittest.TestCase):
    def test_batches_report_pid_liveness_and_task_exit_codes(self):
        from aha3d.cli import batches
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, pid, runs, exits in [('a', os.getpid(), 2, {}), ('b', 999999999, 2, {'0': '0', '1': '3'}),
                                           ('c', 999999999, 1, {'0': '0'}), ('d', 999999999, 2, {'0': '0'}), ('e', None, 1, {})]:
                folder = root / 'runs/batches' / name; folder.mkdir(parents=True)
                (folder / 'submission.json').write_text(json.dumps(dict(job_id=name, pid=pid, runs=['r'] * runs)))
                for i, code in exits.items(): (folder / f'{i}.log.exit').write_text(code + '\n')
            rows = {r['job_id']: r for r in batches(root)}
            self.assertEqual({k: r['status'] for k, r in rows.items()},
                             {'a': 'running', 'b': 'failed', 'c': 'completed', 'd': 'stopped', 'e': 'unknown'})
            self.assertEqual(rows['b']['exit_codes'], {'0': 0, '1': 3}); self.assertTrue(rows['a']['alive'])


class Profiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.folder = self.root / 'configs/runtimes'; self.folder.mkdir(parents=True)
        for name in ('python', 'blender', 'skin', 'env', 'upstream', 'checkpoint'):
            (self.root / name).touch()
        self.cfg = dict(schema_version=2, python='python', blender='blender', skin_blender='skin',
                        env_script='env', upstream='upstream', checkpoint='checkpoint', threads=None, gpu=0)

    def load(self, **changes):
        (self.folder / 'local.json').write_text(json.dumps(dict(self.cfg, **changes)))
        return load_runtime(self.root, 'local')

    def test_schema_two_defaults_and_validation(self):
        self.assertEqual((self.load()['threads'], self.load()['gpu']), (None, 0))
        cfg = {k: v for k, v in self.cfg.items() if k not in ('threads', 'gpu')}
        (self.folder / 'local.json').write_text(json.dumps(cfg))
        self.assertEqual((load_runtime(self.root, 'local')['threads'], load_runtime(self.root, 'local')['gpu']), (None, 0))
        self.assertEqual(self.load(threads=12, gpu=1)['threads'], 12)
        for bad in (dict(threads=0), dict(threads='8'), dict(threads=True), dict(gpu=-1), dict(gpu=None), dict(memory='64G')):
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.load(**bad)

    def test_unsupported_schema_profiles_are_rejected_with_regeneration_advice(self):
        for old in (dict(schema_version=1), dict(schema_version=3)):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'configure_runtime.py'): self.load(**old)

    def test_template_uses_schema_two_workstation_fields(self):
        template = json.loads((Path(__file__).resolve().parents[1] / 'configs/runtimes/local.example.json').read_text())
        self.assertEqual(template['schema_version'], 2)
        self.assertEqual(set(template), {'schema_version', 'python', 'blender', 'skin_blender', 'env_script',
                                         'upstream', 'checkpoint', 'threads', 'gpu'})
        self.assertEqual(template['env_script'], 'kimodo_blender/env.sh')


if __name__ == '__main__': unittest.main()
