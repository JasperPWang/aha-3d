import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.human_experiments.inspection_bundle import bundle_artifacts
from tools.human_experiments.serve_portal import artifact_allowlist


class InspectionBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.artifacts = {'index.html': b'<img src="source.png">', 'source.png': b'frame evidence'}
        for name, content in self.artifacts.items():
            (self.package / name).write_bytes(content)
        (self.package / 'unlisted.txt').write_text('not an inspection artifact')
        self.manifest = self.package / 'bundle_manifest.json'
        self.data = dict(schema_version=1, entry='index.html', artifacts={
            name: hashlib.sha256(content).hexdigest() for name, content in self.artifacts.items()})
        self.write()

    def write(self):
        self.manifest.write_text(json.dumps(self.data))

    def test_server_exposes_only_inventoried_package_files(self):
        portal = self.root / 'portal.html'
        portal.write_text('<script id="caseData" type="application/json">' + json.dumps([
            {'evidence': [{'report': 'package/index.html', 'bundle': 'package/bundle_manifest.json'}]}]) + '</script>')
        with patch('tools.human_experiments.serve_portal.ROOT', self.root):
            allowed = artifact_allowlist(portal)
        self.assertEqual(allowed, {portal, self.manifest, self.package / 'index.html', self.package / 'source.png'})

    def test_changed_frame_rejects_package(self):
        (self.package / 'source.png').write_bytes(b'different source frame')
        with self.assertRaisesRegex(ValueError, 'changed'):
            bundle_artifacts(self.manifest, root=self.root)

    def test_report_must_match_entry(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            bundle_artifacts(self.manifest, root=self.root, entry=self.package / 'source.png')

    def test_traversal_and_symlinks_rejected(self):
        other = self.root / 'private.txt'
        other.write_bytes(b'private')
        self.data['artifacts']['../private.txt'] = hashlib.sha256(b'private').hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, 'relative'):
            bundle_artifacts(self.manifest, root=self.root)
        del self.data['artifacts']['../private.txt']
        (self.package / 'linked.txt').symlink_to(other)
        self.data['artifacts']['linked.txt'] = hashlib.sha256(b'private').hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            bundle_artifacts(self.manifest, root=self.root)


if __name__ == '__main__':
    unittest.main()
