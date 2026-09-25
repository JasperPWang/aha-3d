import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from aha3d.io import digest, read, write
from aha3d.results import batch, gallery, registry
from aha3d.results.cli import main


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        repo = Path(__file__).resolve().parents[1]
        (self.root / 'scenes/alpha').mkdir(parents=True)
        (self.root / 'tools/roomkit_browser').mkdir(parents=True)
        (self.root / 'scenes/alpha/STATE.md').write_text('Historical reviewed delivery.\n')
        (self.root / 'tools/roomkit_browser/demo.py').write_text('# exporter\n')
        shutil.copy(repo / 'tools/task_claim.py', self.root / 'tools/task_claim.py')
        self.source = self.root / 'scenes/alpha/scene.blend'; self.source.write_bytes(b'scene-v1')
        self.spec = dict(schema_version=1, scene='alpha', id='delivery-v1', status='recorded_delivery',
                         artifacts=[dict(role='scene', path='scenes/alpha/scene.blend')],
                         evidence=[dict(path='scenes/alpha/STATE.md')],
                         review=dict(by='historical-import', note='Existing delivery; no fresh visual review.'))
        self.runtime = dict(blender='/fake/blender', python='fixture', node='fixture')

    def select(self):
        # Existing Gallery/batch tests read an explicitly historical selection.
        # Fresh selection policy is exercised in test_acceptance.
        registry.register(self.root, self.spec)
        path=self.root/'deliveries/alpha/versions/delivery-v1.json'
        write(self.root/'deliveries/alpha/selected.json',dict(schema_version=2,delivery='deliveries/alpha/versions/delivery-v1.json',delivery_sha256=digest(path)))

    def plan(self, scenes=None, retry=None):
        with patch.object(batch, 'runtime_identity', return_value=self.runtime):
            return batch.plan(self.root, scenes, '/fake/blender', retry=retry)

    def test_discovery_never_selects_latest_or_final(self):
        (self.source.parent / 'final-v99.blend').write_bytes(b'newer')
        row = registry.build_index(self.root)['scenes'][0]
        self.assertEqual(row['selection_status'], 'unselected')
        self.assertEqual(len(row['candidates']), 2); self.assertEqual(row['artifacts'], [])
        self.assertTrue(row['warnings'])
        self.assertEqual(self.plan()['rows'][0]['action'], 'blocked')

    def test_registration_immutable_and_selection_hash_bound(self):
        self.select()
        with self.assertRaisesRegex(ValueError, 'immutable'):
            registry.register(self.root, self.spec)
        path = self.root / 'deliveries/alpha/versions/delivery-v1.json'
        path.write_text(path.read_text() + ' ')
        self.assertEqual(registry.build_index(self.root)['scenes'][0]['selection_status'], 'broken_selection')

    def test_modified_source_cannot_be_selected_or_exported(self):
        self.select(); self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SCOPE_REQUIRED'):
            registry.select(self.root, 'alpha', 'delivery-v1')
        self.assertEqual(self.plan()['counts']['blocked'], 1)
        self.assertEqual(registry.build_index(self.root, verify=True)['scenes'][0]['artifacts'][0]['availability'], 'changed')

    def test_outside_symlink_rejected(self):
        self.source.unlink(); self.source.symlink_to('/etc/hosts')
        with self.assertRaises(ValueError): registry.register(self.root, self.spec)

    def test_duplicate_default_input_and_missing_evidence_rejected(self):
        data = dict(self.spec, artifacts=self.spec['artifacts'] + [dict(role='scene', variant='whitebox', path='scenes/alpha/scene.blend')])
        with self.assertRaisesRegex(ValueError, 'default'): registry.validate_manifest(data)
        with self.assertRaisesRegex(ValueError, 'evidence'): registry.validate_manifest(dict(self.spec, evidence=[]))

    def test_candidate_cannot_be_selected(self):
        registry.register(self.root, dict(self.spec, status='candidate'))
        with self.assertRaisesRegex(ValueError, 'recorded delivery'): registry.select(self.root, 'alpha', 'delivery-v1')

    def test_legacy_promotion_adapter(self):
        run = self.root / 'runs/alpha/legacy'
        p = run / 'stages/assemble/scene.blend'; p.parent.mkdir(parents=True); p.write_bytes(b'legacy')
        write(run / 'run.json', dict(scene='alpha', status='validated', stages={'assemble': {'status': 'completed', 'outputs': {'scene.blend': digest(p)}}}))
        write(self.root / 'deliveries/alpha/selected.json', dict(run=str(run), visual_review={'status': 'reviewed', 'reviewer': 'old', 'note': 'Old evidence'}))
        self.assertEqual(registry.build_index(self.root, verify=True)['scenes'][0]['selection_status'], 'selected')
        p.unlink(); self.assertEqual(self.plan()['rows'][0]['action'], 'blocked')

    def test_incremental_reuse_checks_demo_bytes_and_exporter(self):
        self.select(); plan = self.plan(); out = self.root / 'runs/alpha/demo-old'
        html = out / 'stages/demo/demo.html'; html.parent.mkdir(parents=True); html.write_text('demo')
        write(out / 'run.json', dict(results_kind='demo', status='validated', run_id='demo-old',
                                    source_fingerprint=plan['rows'][0]['source_fingerprint'], tool_signature=plan['tool_signature'],
                                    exporter_fingerprint=plan['exporter_fingerprint'],
                                    artifacts=[dict(role='demo', path=registry.relative(self.root, html), fingerprint=registry.fingerprint(html))]))
        self.assertEqual(self.plan()['counts']['skip'], 1)
        index = registry.build_index(self.root, verify=True); gallery.attach_demos(self.root, index, True)
        self.assertEqual(index['scenes'][0]['demo_status'], 'current')
        resource = html.with_name('segment.bin.gz'); resource.write_bytes(b'animation')
        record = read(out / 'run.json')
        record['artifacts'].append(dict(role='demo_resource', path=registry.relative(self.root, resource), fingerprint=registry.fingerprint(resource)))
        write(out / 'run.json', record)
        resource.unlink()
        self.assertEqual(self.plan()['counts']['build'], 1)
        index = registry.build_index(self.root, verify=True); gallery.attach_demos(self.root, index, True)
        self.assertEqual(index['scenes'][0]['demo_status'], 'stale')
        resource.write_bytes(b'animation')
        self.source.write_bytes(b'changed source')
        index = registry.build_index(self.root, verify=True); gallery.attach_demos(self.root, index, True)
        self.assertEqual(index['scenes'][0]['demo_status'], 'stale')
        self.source.write_bytes(b'scene-v1')
        html.write_text('corrupt'); self.assertEqual(self.plan()['counts']['build'], 1)
        (self.root / 'tools/roomkit_browser/demo.py').write_text('# changed exporter')
        self.assertNotEqual(self.plan()['tool_signature'], plan['tool_signature'])

    def test_selected_fast_demo_requires_all_resources(self):
        html = self.source.parent / 'demo-fast.html'; html.write_text('fast entry')
        resource = self.source.parent / 'segment.bin.gz'; resource.write_bytes(b'model')
        self.spec['artifacts'] += [dict(role='demo', path=registry.relative(self.root, html)),
                                   dict(role='demo_resource', path=registry.relative(self.root, resource))]
        self.select()
        index = registry.build_index(self.root, verify=True); gallery.attach_demos(self.root, index, True)
        self.assertEqual(index['scenes'][0]['demo_status'], 'selected')
        resource.unlink()
        index = registry.build_index(self.root, verify=True); gallery.attach_demos(self.root, index, True)
        self.assertNotEqual(index['scenes'][0]['demo_status'], 'selected')

    def test_chair_option_is_pinned_and_changes_reuse_identity(self):
        self.select()
        with patch.object(batch, 'runtime_identity', return_value=self.runtime):
            plain = batch.plan(self.root, ['alpha'], '/fake/blender')
            chairs = batch.plan(self.root, ['alpha'], '/fake/blender', chairs=True)
        batch.validate_plan(chairs)
        self.assertTrue(chairs['options']['chairs'])
        self.assertNotEqual(plain['tool_signature'], chairs['tool_signature'])
        with contextlib.redirect_stdout(io.StringIO()), patch.object(batch, 'runtime_identity', return_value=self.runtime):
            target = self.root / 'chair-plan.json'
            self.assertEqual(main(['demo-plan', '--scene', 'alpha', '--chairs', '--tabletop', '--out', str(target)], self.root), 0)
        self.assertEqual(read(target)['options'], dict(tabletop=True, chairs=True))

    def test_retry_empty_stays_empty(self):
        self.select(); report = self.root / 'old-batch.json'
        write(report, {'rows': [{'scene': 'alpha', 'status': 'validated'}]})
        self.assertEqual(self.plan(retry=report)['rows'], [])

    def test_new_run_has_real_claim_and_unique_path(self):
        first = batch.new_run(self.root, 'alpha', 'render', 'test-owner')
        second = batch.new_run(self.root, 'alpha', 'render', 'test-owner')
        self.assertNotEqual(first['path'], second['path'])
        task = read(self.root / 'tasks' / first['task'] / 'task.json')
        self.assertIn(first['path'], task['paths']); self.assertEqual(task['status'], 'active')

    def test_gallery_json_escape_and_integrity_check(self):
        self.select()
        write(self.root / 'scenes/alpha/scene.json', {'description': '</script><script>bad()</script>'})
        gallery.build(self.root, verify=True)
        self.assertNotIn('</script><script>bad()', (self.root / 'gallery/index.html').read_text())
        self.assertEqual(gallery.check(self.root, verify=True)['status'], 'passed')
        self.source.unlink(); self.assertEqual(gallery.check(self.root, verify=True)['status'], 'needs_attention')

    def test_cli_build_and_failure_exit(self):
        self.select()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['build', '--verify'], self.root), 0)
            self.source.unlink(); self.assertEqual(main(['check', '--verify'], self.root), 1)

    def test_parent_cli_delegates_help(self):
        from aha3d.cli import main as parent_main
        with patch.object(sys, 'argv', ['indoor', 'results', '--help']), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught: parent_main()
        self.assertEqual(caught.exception.code, 0)

    def test_server_range_and_private_file_exclusion(self):
        resource = self.source.parent / ('a' * 64 + '.props.json.gz')
        resource.write_bytes(b'compressed-model')
        self.spec['artifacts'].append(dict(role='demo_resource', variant='model', path=registry.relative(self.root, resource)))
        self.select(); gallery.build(self.root, verify=True)
        (self.root / 'private.txt').write_text('not indexed')
        tool = Path(__file__).resolve().parents[1] / 'tools/scene_results.py'
        proc = subprocess.Popen([sys.executable, str(tool), '--root', str(self.root), 'serve', '--port', '0'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            address = proc.stdout.readline().strip().split('Gallery: ')[1].split('/gallery')[0]
            with urlopen(address + '/', timeout=5) as response:
                self.assertEqual(response.geturl(), address + '/gallery/index.html')
                relative_resource = urljoin(response.geturl(), '../scenes/alpha/' + resource.name)
            with urlopen(relative_resource, timeout=5) as response:
                self.assertEqual(response.read(), b'compressed-model')
            with urlopen(address + '/gallery/index.html', timeout=5) as response:
                self.assertEqual(response.status, 200)
            with urlopen(address + '/scenes/alpha/' + resource.name, timeout=5) as response:
                self.assertEqual(response.read(), b'compressed-model')
                self.assertIn('immutable', response.headers['Cache-Control'])
                self.assertIsNone(response.headers.get('Content-Encoding'))
            req = Request(address + '/scenes/alpha/scene.blend', headers={'Range': 'bytes=2-5'})
            with urlopen(req, timeout=5) as response:
                self.assertEqual(response.status, 206); self.assertEqual(response.read(), b'ene-')
            with self.assertRaises(HTTPError) as caught: urlopen(address + '/private.txt', timeout=5)
            self.assertEqual(caught.exception.code, 404)
            with self.assertRaises(HTTPError) as missing:
                urlopen(address + '/scenes/alpha/' + 'b' * 64 + '.bin.gz', timeout=5)
            self.assertIsNone(missing.exception.headers.get('Cache-Control'))
        finally:
            proc.terminate(); proc.wait(timeout=5); proc.stdout.close()

    def test_batch_failure_isolated_and_claim_released(self):
        self.select(); (self.root / 'scenes/beta').mkdir()
        (self.root / 'scenes/beta/scene.blend').write_bytes(b'beta')
        spec = dict(self.spec, scene='beta', artifacts=[dict(role='scene', path='scenes/beta/scene.blend')])
        registry.register(self.root, spec)
        path=self.root/'deliveries/beta/versions'/(spec['id']+'.json')
        write(self.root/'deliveries/beta/selected.json',dict(schema_version=2,delivery=registry.relative(self.root,path),delivery_sha256=digest(path)))
        script = '''import argparse, pathlib, json, hashlib
p=argparse.ArgumentParser();p.add_argument('--source');p.add_argument('--out');p.add_argument('--blender');a=p.parse_args()
if 'beta' in a.source: raise RuntimeError('unsupported geometry fixture')
out=pathlib.Path(a.out);out.mkdir(parents=True)
(out/'demo-fast.html').write_text('fixture fast demo');(out/'demo-fast.html.json').write_text('{"files": []}');(out/'demo.html').write_text('fixture demo');(out/'orbit.png').write_bytes(b'fixture')
(out/'validation.json').write_text('{}')
(out/'run.json').write_text(json.dumps({'status':'validated','source_sha256':hashlib.sha256(pathlib.Path(a.source).read_bytes()).hexdigest()}))
'''
        (self.root / 'tools/roomkit_browser/demo.py').write_text(script)
        folder = batch.create_batch(self.root, self.plan(), 'test-owner')
        with patch.object(batch, 'runtime_identity', return_value=self.runtime):
            result = batch.execute(self.root, folder)
            with self.assertRaisesRegex(ValueError, 'new batch'): batch.execute(self.root, folder)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual([r['status'] for r in result['rows']], ['validated', 'failed'])
        self.assertEqual(read(self.root / 'tasks' / result['task'] / 'task.json')['status'], 'handoff')
        self.assertEqual([r['scene'] for r in self.plan(retry=folder / 'batch.json')['rows']], ['beta'])


if __name__ == '__main__': unittest.main()
