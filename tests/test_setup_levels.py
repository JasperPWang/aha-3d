"""Check installation level selection without installing model runtimes."""
import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/setup.sh'


class SetupLevels(unittest.TestCase):
    def run_plan(self, *args, env=None):
        return subprocess.run(
            ['bash', str(SCRIPT), *args], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )

    def test_noninteractive_install_requires_explicit_level_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'unused-pi3x'
            env = dict(os.environ, PI3X_REFERENCE_ENV=str(target))
            result = self.run_plan(env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--level', result.stderr)
            self.assertFalse(target.exists())

    def test_each_level_has_a_distinct_plan(self):
        for level, required, excluded in (
            ('static', 'Static level', 'Core environment:'),
            ('human', 'GVHMR, PMPose', 'Core environment:'),
            ('robotics', 'Core environment:', 'SAM3 PyAV'),
        ):
            with self.subTest(level=level):
                result = self.run_plan('--level', level, '--plan')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Selected installation level: {level}', result.stdout)
                self.assertIn(required, result.stdout)
                self.assertNotIn(excluded, result.stdout)

    def test_interactive_prompt_rejects_invalid_then_accepts_selection(self):
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                ['bash', str(SCRIPT), '--plan'], cwd=ROOT, stdin=slave,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            os.close(slave)
            slave = -1
            os.write(master, b'5\n3\n')
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('Which installation level do you want?', stderr)
            self.assertIn('Invalid level: 5', stderr)
            self.assertIn('Selected installation level: robotics', stdout)
        finally:
            os.close(master)
            if slave != -1:
                os.close(slave)

    def test_invalid_or_repeated_level_fails(self):
        for args in (('--level', 'unknown', '--plan'),
                     ('--level', 'static', '--level', 'robotics', '--plan'),
                     ('--level', 'human', '--with-sam3d', '--plan')):
            with self.subTest(args=args):
                result = self.run_plan(*args)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Static level, first new-video reference', result.stdout)

    def test_direct_component_installs_require_prior_level_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ)
            env.pop('AHA3D_SETUP_LEVEL', None)
            env['PI3X_REFERENCE_ENV'] = str(Path(temporary) / 'pi3x')
            env['KIMODO_ENV'] = str(Path(temporary) / 'core')
            for name, arguments in (
                ('setup_reference.sh', ()),
                ('setup_core.sh', ('--pi3x-only',)),
                ('setup_core.sh', ()),
            ):
                with self.subTest(name=name, arguments=arguments):
                    result = subprocess.run(
                        ['bash', str(ROOT / 'tools' / name), *arguments],
                        cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn('tools/setup.sh', result.stderr)
            self.assertFalse((Path(temporary) / 'pi3x').exists())
            self.assertFalse((Path(temporary) / 'core').exists())

    def test_selected_level_is_forwarded_to_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            bin_dir = Path(temporary) / 'bin'
            bin_dir.mkdir()
            log = Path(temporary) / 'calls.txt'
            fake_bash = bin_dir / 'bash'
            fake_bash.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$AHA3D_SETUP_LEVEL" "$*" >> "$SETUP_CALL_LOG"\n')
            fake_bash.chmod(0o755)
            env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', SETUP_CALL_LOG=str(log))
            for level, expected_calls in (('static', 1), ('robotics', 2)):
                log.unlink(missing_ok=True)
                result = subprocess.run(
                    ['/bin/bash', str(SCRIPT), '--level', level], cwd=ROOT,
                    env=env, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = log.read_text().splitlines()
                self.assertEqual(len(calls), expected_calls)
                self.assertTrue(all(call.startswith(level + '|') for call in calls))


if __name__ == '__main__':
    unittest.main()
