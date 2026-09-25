"""Exercise real subprocess contention and handoff safety on a temporary registry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'task_claim.py'


class TaskClaims(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.claims-test-', dir=os.environ.get('TASK_TEST_TMPDIR'))
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, *args):
        return [sys.executable, str(SCRIPT), '--root', str(self.root)] + list(args)

    def run_tool(self, *args, **kwargs):
        result = subprocess.run(self.command(*args), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
        self.assertEqual(result.returncode, kwargs.get('code', 0), result.stderr)
        return json.loads(result.stdout) if result.returncode == 0 else result.stderr

    def claim(self, task, path, owner='agent-a', **kwargs):
        return self.run_tool('claim', task, '--owner', owner, '--title', task, '--paths', path, **kwargs)

    def test_simultaneous_parent_child_claim_has_one_winner(self):
        processes = []
        for task, path in [('first', 'scenes/a'), ('second', 'scenes/a/scene.blend')]:
            processes.append(subprocess.Popen(self.command('claim', task, '--owner', task,
                '--title', task, '--paths', path), stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        outputs = [p.communicate(timeout=15) for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2], outputs)
        self.assertEqual(len(self.run_tool('list')), 1)
        self.assertFalse((self.root / 'tasks/.registry.lock').exists())

    def test_independent_scenes_and_sibling_names_do_not_conflict(self):
        self.claim('one', 'scenes/a')
        self.claim('two', 'scenes/ab', owner='agent-b')
        self.assertEqual(len(self.run_tool('list')), 2)

    def test_handoff_owner_checks_resume_and_history(self):
        self.claim('one', 'scenes/a')
        self.run_tool('release', 'one', '--owner', 'wrong', '--status', 'completed', '--note', 'wrong', code=2)
        self.run_tool('checkpoint', 'one', '--owner', 'agent-a', '--note', 'job recorded', '--job-id', '123')
        self.run_tool('release', 'one', '--owner', 'agent-a', '--status', 'handoff', '--note', 'writers stopped')
        self.claim('two', 'scenes/a', owner='agent-b')
        self.run_tool('resume', 'one', '--owner', 'agent-c', '--note', 'takeover', code=2)
        self.run_tool('release', 'two', '--owner', 'agent-b', '--status', 'completed', '--note', 'done')
        data = self.run_tool('resume', 'one', '--owner', 'agent-c', '--note', 'read handoff')
        self.assertEqual(data['owner'], 'agent-c')
        self.assertEqual(data['history'][1]['job_ids'], ['123'])
        self.assertTrue((self.root / 'tasks/one/HANDOFF.md').is_file())
        self.run_tool('resume', 'two', '--owner', 'agent-b', '--note', 'completed cannot resume', code=2)

    def test_symlinks_and_normalized_paths_share_claims(self):
        (self.root / 'actual').mkdir()
        (self.root / 'alias').symlink_to(self.root / 'actual', target_is_directory=True)
        self.claim('one', 'alias')
        self.claim('two', 'actual/../actual/a.blend', code=2)

    def test_relocated_handoff_conflicts_with_canonical_path(self):
        self.claim('old', 'legacy/clip')
        self.run_tool('release', 'old', '--owner', 'agent-a', '--status', 'handoff', '--note', 'writers stopped')
        (self.root / 'configs').mkdir()
        (self.root / 'configs/path_migrations.json').write_text(json.dumps({
            'schema_version': 1, 'paths': {'legacy': 'scenes/one/blender'}}))
        self.claim('new', 'scenes/one/blender/clip', owner='agent-b')
        self.run_tool('resume', 'old', '--owner', 'agent-c', '--note', 'relocated resume', code=2)
        self.claim('alias', 'legacy/clip/scene.blend', code=2)
        stored = json.loads((self.root / 'tasks/old/task.json').read_text())
        self.assertIn('legacy/clip', stored['paths'])

    def test_rejects_escape_reserved_scope_and_task_traversal(self):
        for task, path in [('escape', '../outside'), ('root', '.'), ('registry', 'tasks'),
                           ('glob', 'scenes/*'), ('../bad', 'scenes/a')]:
            self.claim(task, path, code=2)
        (self.root / 'outside').symlink_to(self.root.parent, target_is_directory=True)
        self.claim('alias-escape', 'outside/elsewhere', code=2)
        self.assertEqual(self.run_tool('list'), [])

    def test_dependencies_must_be_completed(self):
        self.claim('base', 'scenes/a')
        args = ('claim', 'dependent', '--owner', 'agent-b', '--title', 'dependent',
                '--paths', 'scenes/b', '--depends-on', 'base')
        self.run_tool(*args, code=2)
        self.run_tool('release', 'base', '--owner', 'agent-a', '--status', 'completed', '--note', 'verified')
        self.assertEqual(self.run_tool(*args)['depends_on'], ['base'])

    def test_incomplete_or_corrupt_registry_fails_closed(self):
        self.claim('base', 'scenes/a')
        (self.root / 'tasks/base/task.json').write_text('{broken')
        self.claim('other', 'scenes/b', code=2)
        self.assertFalse((self.root / 'tasks/other').exists())

    def test_existing_lock_is_not_expired_or_deleted(self):
        lock = self.root / 'tasks' / '.registry.lock'
        lock.mkdir(parents=True)
        owner = lock / 'owner.json'
        original = '{"host": "some-host", "pid": 1, "created_at": "2000-01-01"}'
        owner.write_text(original)
        self.run_tool('list', code=2)
        self.assertEqual(owner.read_text(), original)

    def test_compact_listing_preserves_ownership_without_cache_payload(self):
        self.run_tool('claim', 'cleanup', '--owner', 'agent-a', '--title', 'cleanup',
                      '--paths', 'code/module.py', 'code/__pycache__')
        result = self.run_tool('list', '--compact')[0]
        self.assertEqual(result['owner'], 'agent-a')
        self.assertEqual(result['path_count'], 3)
        self.assertIn('code/module.py', result['paths'])
        self.assertNotIn('code/__pycache__', result['paths'])
        self.assertNotIn('history', result)
        self.assertIn('code/__pycache__', self.run_tool('show', 'cleanup')['paths'])

    def test_scene_completion_rejects_missing_scope_but_allows_handoff(self):
        self.run_tool('claim', 'scene-work', '--owner', 'agent-a', '--title', 'room',
                      '--scene', 'room', '--paths', 'scenes/room')
        self.run_tool('release', 'scene-work', '--owner', 'agent-a', '--status',
                      'completed', '--note', 'claims done without evidence', code=2)
        self.assertEqual(self.run_tool('show', 'scene-work')['status'], 'active')
        self.run_tool('release', 'scene-work', '--owner', 'agent-a', '--status',
                      'handoff', '--note', 'writers stopped, scope still needed')

    def test_explicit_preparation_is_not_scene_delivery(self):
        result = self.run_tool('claim', 'reference', '--owner', 'agent-a', '--title',
                              'extract reference', '--scene', 'room', '--kind',
                              'preparation', '--paths', 'scenes/room/reference')
        self.assertEqual(result['kind'], 'preparation')
        self.run_tool('release', 'reference', '--owner', 'agent-a', '--status',
                      'completed', '--note', 'reference extraction checked')
        self.run_tool('claim', 'bad', '--owner', 'agent-a', '--title', 'bad',
                      '--kind', 'reconstruction', '--paths', 'scenes/room', code=2)


if __name__ == '__main__':
    unittest.main()
