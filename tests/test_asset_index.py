"""Discovery must distinguish portable assets from source candidates and stale data."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('asset_index', ROOT / 'tools/asset_index.py')
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class AssetIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = catalog.build(ROOT)

    def test_search_distinguishes_geometry_materials_and_candidates(self):
        collections = catalog.search(self.index, 'sofa', kind='collection')
        self.assertIn('roomkit-v1/sofa-linen-three-seat', [e['id'] for e in collections])
        self.assertTrue(all(e['kind'] == 'collection' and e['status'] == 'registered'
                            for e in collections))
        materials = catalog.search(self.index, 'sofa', kind='material')
        self.assertTrue(materials)
        self.assertTrue(all(e['reuse']['method'] == 'append_material' for e in materials))
        fruit = catalog.search(self.index, 'fruit bowl', status='needs_extraction')
        self.assertEqual(fruit, [])

    def test_aliases_and_absent_water_cup(self):
        for query in ['sofa', 'couch', '\u6c99\u53d1']:
            self.assertIn('roomkit-v1/sofa-linen-three-seat',
                          [e['id'] for e in catalog.search(self.index, query, kind='collection')])
        self.assertEqual(catalog.search(self.index, '\u6c34\u676f', kind='scene_object'), [])
        self.assertEqual(catalog.search(self.index, '\u9ad8\u811a\u676f', kind='scene_object'), [])

    def test_excluded_scenes_have_no_catalog_entries(self):
        self.assertEqual(catalog.search(self.index, 'sofa', scene='pool_lounge_0a8d46c9'), [])
        self.assertFalse(any(e['status'] == 'needs_extraction' for e in self.index['entries']))

    def test_library_inventory_is_not_duplicated_by_historical_copies(self):
        registry = catalog.read(ROOT / 'assets/registry.json')
        manifests = [catalog.read(ROOT / item['metadata']) for item in registry['assets'].values()]
        registered = catalog.search(self.index, status='registered')
        self.assertEqual(len(registered), sum(len(m['furniture']) + len(m['materials']) for m in manifests))
        self.assertEqual(len({e['id'] for e in self.index['entries']}), len(self.index['entries']))

    def test_articulated_reuse_keeps_independent_controls(self):
        entries = [e for e in self.index['entries'] if e.get('articulation')]
        for entry in entries:
            self.assertEqual(entry['reuse']['method'], 'append_articulated')
            self.assertIn('place_asset', entry['reuse']['python'])
            self.assertTrue(entry['controls'])

    def test_direction_is_item_specific_and_symmetric_assets_have_no_front(self):
        entries = {entry['id']: entry for entry in self.index['entries']}
        chair = entries['roomkit-v1/chair-walnut-lounge']
        self.assertEqual(chair['orientation']['semantic_front'], 'seating')
        self.assertEqual(chair['orientation']['status'], 'reviewed')
        self.assertIn('place_asset', chair['reuse']['python'])
        vase = entries['ceramic-vase-v1/vase-rounded-ceramic']
        self.assertIsNone(vase['forward'])
        self.assertEqual(vase['orientation']['symmetry'], 'continuous_z')

    def test_cached_query_needs_no_blender_or_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'assets/index.json').write_text(json.dumps(self.index), encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/asset_index.py'),
                '--root', str(root), 'search', 'sofa', '--kind', 'collection', '--json'],
                cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['total'],
                             len(catalog.search(self.index, 'sofa', kind='collection')))

    def test_maintenance_rejects_stale_or_ambiguous_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in self.index['input_sha256']:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            for entry in self.index['entries']:
                # Existence placeholders: index validation must not load or hash these files.
                for key in ('library_path', 'scene_state'):
                    if entry.get(key):
                        target = root / entry[key]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.touch()
            original = catalog.build(root)
            self.assertEqual(original, self.index)
            reviews_path = root / 'assets/orientation_reviews.json'
            reviews_text = reviews_path.read_text()
            reviews = json.loads(reviews_text)
            chair_id = 'roomkit-v1/chair-walnut-lounge'
            reviews['reviews'][chair_id]['library_sha256'] = '0' * 64
            reviews_path.write_text(json.dumps(reviews))
            with self.assertRaisesRegex(ValueError, 'review does not match immutable asset'):
                catalog.build(root)
            reviews_path.write_text(json.dumps({'schema_version': 1, 'reviews': {}}))
            unknown = next(e for e in catalog.build(root)['entries'] if e['id'] == chair_id)
            self.assertEqual(unknown['orientation']['status'], 'unknown')
            self.assertIsNone(unknown['forward'])
            reviews_path.write_text(reviews_text)
            (root / 'assets/index.json').write_text(json.dumps(original, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            (root / 'assets/INDEX.md').write_text(catalog.markdown(original), encoding='utf-8')
            path = root / 'src/aha3d/blender/roomkit.py'
            path.write_text('# New source revision\n' + path.read_text(), encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/asset_index.py'),
                '--root', str(root), 'check'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Stale index', result.stderr)
            path.write_text(path.read_text() + "\n# def cabinet(\n", encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'anchor must match once'):
                catalog.build(root)


if __name__ == '__main__':
    unittest.main()
