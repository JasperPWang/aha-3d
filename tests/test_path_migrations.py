"""Verify relocation boundaries and compatibility with existing scene recipes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.config import path
from aha3d.paths import migrated_path


class PathMigrations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'configs').mkdir()
        self.registry = self.root / 'configs/path_migrations.json'
        self.registry.write_text(json.dumps({'schema_version':1, 'paths':{'legacy':'scenes/one/blender'}}))

    def tearDown(self):
        self.temp.cleanup()

    def test_descendants_resolve_and_sibling_names_are_unchanged(self):
        self.assertEqual(path(self.root, 'legacy/scene.blend'), self.root / 'scenes/one/blender/scene.blend')
        self.assertEqual(path(self.root, self.root / 'legacy'), self.root / 'scenes/one/blender')
        self.assertEqual(path(self.root, 'legacy_other/scene.blend'), self.root / 'legacy_other/scene.blend')
        self.assertEqual(path(self.root, '../external.blend'), self.root.parent / 'external.blend')

    def test_registry_cannot_escape_project_or_map_empty_prefix(self):
        for old,new in [('legacy','../outside'), ('','scenes/a'), ('/absolute','scenes/a')]:
            self.registry.write_text(json.dumps({'schema_version':1,'paths':{old:new}}))
            with self.assertRaises(ValueError): migrated_path(self.root, 'legacy/scene.blend')

    def test_no_registry_preserves_existing_behavior(self):
        self.registry.unlink()
        self.assertEqual(path(self.root, 'legacy/scene.blend'), self.root / 'legacy/scene.blend')


if __name__ == '__main__': unittest.main()
