import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.layout_inspection.build_reference import parser, run


def semantic_command(argv):
    """Run the bundle route with a fake runner; return the semantic stage command."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); bundle = root / 'bundle'; bundle.mkdir(); out = root / 'result'
        ids = list(range(32))
        (bundle / 'inputs.json').write_text(json.dumps(dict(frame_indices=ids, source_frame_count=32)))
        a = parser().parse_args(['--bundle', str(bundle), '--out', str(out), '--cameras', str(bundle / 'cameras.json'), *argv])
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            if command[2] == 'tools.layout_inspection.prepare':
                (out / 'mesh').mkdir()
                (out / 'mesh/manifest.json').write_text(json.dumps(dict(frame_indices=ids, geometry_representation={'method': 'tsdf-context'})))
            elif command[2] == 'tools.layout_inspection.reference_views':
                (out / 'source_views').mkdir()
                (out / 'source_views/reference_views.json').write_text(json.dumps(dict(source_frame_indices=[0, 15, 31])))
        run(a, runner=runner)
        return next(c for c in calls if c[2] == 'tools.layout_inspection.semantic')


class SemanticInterpreter(unittest.TestCase):
    def test_runtime_venv_is_the_fallback(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SAM3_PYTHON', None)
            command = semantic_command(['--semantic-runtime', '/runtime/sam3', '--reference-views', '3'])
        self.assertEqual(command[0], str(Path('/runtime/sam3').resolve() / 'venv/bin/python'))

    def test_sam3_python_environment_is_honoured(self):
        with patch.dict(os.environ, {'SAM3_PYTHON': '/conda/sam3/bin/python'}):
            command = semantic_command(['--semantic-runtime', '/runtime/sam3', '--reference-views', '3'])
        self.assertEqual(command[0], '/conda/sam3/bin/python')
        self.assertEqual(command[command.index('--runtime') + 1], str(Path('/runtime/sam3').resolve()))

    def test_explicit_option_overrides_environment(self):
        with patch.dict(os.environ, {'SAM3_PYTHON': '/conda/sam3/bin/python'}):
            command = semantic_command(['--semantic-python', '/explicit/python', '--reference-views', '3'])
        self.assertEqual(command[0], '/explicit/python')

    def test_missing_interpreter_names_the_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle'; bundle.mkdir()
            (bundle / 'inputs.json').write_text(json.dumps(dict(frame_indices=list(range(32)), source_frame_count=32)))
            a = parser().parse_args(['--bundle', str(bundle), '--out', str(Path(tmp) / 'out'),
                                     '--semantic-python', str(Path(tmp) / 'missing/python'), '--cameras', str(bundle / 'cameras.json')])
            with self.assertRaisesRegex(FileNotFoundError, 'semantic-python'):
                run(a)


if __name__ == '__main__':
    unittest.main()
