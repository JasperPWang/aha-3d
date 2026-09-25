"""Direct correction selection must retain its limited evidence scope."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.results import registry, gallery


class CorrectionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = 'test_room'
        self.correction = 'vase-correction-v1'
        self.run = self.root / 'runs' / self.scene / self.correction
        delivery = self.run / 'delivery'
        delivery.mkdir(parents=True)
        (self.root / 'scenes' / self.scene).mkdir(parents=True)
        artifacts = []
        for role, name in [('scene', 'room.blend'), ('whitebox_scene', 'white.blend'),
                           ('material_video', 'material.mp4'), ('whitebox_video', 'white.mp4'),
                           ('comparison', 'comparison.mp4')]:
            path = delivery / name
            path.write_bytes(b'actual output')
            artifacts.append(dict(role=role, path=path.relative_to(self.root).as_posix(), size=path.stat().st_size))
        evidence = []
        for path, data in [
            (self.run / 'visual_review.json', dict(targeted_correction='verified', automatic_acceptance=False)),
            (delivery / 'video_validation.json', {k: dict(full_decode=True, pts_checked=True, frames=899)
                                                 for k in ('source', 'materials', 'whitebox', 'comparison')}),
            (delivery / 'saved_blends_validation.json', {k: dict(camera=dict(frames_checked=899))
                                                        for k in ('materials', 'whitebox')})]:
            path.write_text(json.dumps(data))
            evidence.append(path.relative_to(self.root).as_posix())
        corrections = self.root / 'deliveries' / self.scene / 'corrections'
        corrections.mkdir(parents=True)
        self.record = corrections / (self.correction + '.json')
        self.record.write_text(json.dumps(dict(scene=self.scene, id=self.correction,
                                               status='targeted_correction_verified',
                                               automatic_acceptance=False, artifacts=artifacts, evidence=evidence)))

    def test_select_and_build_without_sha(self):
        with patch('aha3d.results.registry.digest', side_effect=AssertionError('SHA called')), \
             patch('aha3d.results.gallery.exporter_fingerprint', side_effect=AssertionError('SHA called')), \
             patch('aha3d.results.gallery.signature', side_effect=AssertionError('SHA called')):
            result = registry.select_correction(self.root, self.scene, self.correction)
            self.assertEqual(result['status'], 'targeted_correction_selected')
            gallery.build(self.root, hash_free=True)
        row = next(s for s in json.loads((self.root / 'gallery/index.json').read_text())['scenes']
                   if s['id'] == self.scene)
        self.assertEqual(row['delivery_id'], self.correction)
        self.assertEqual(row['certification'], 'targeted_correction_verified')
        self.assertEqual(row['selection_status'], 'selected')
        self.assertEqual(registry.selected(self.root, self.scene)['id'], self.correction)

    def test_changed_artifact_blocks_selection(self):
        (self.run / 'delivery/room.blend').write_bytes(b'different size')
        with self.assertRaisesRegex(ValueError, 'artifact missing or size changed'):
            registry.select_correction(self.root, self.scene, self.correction)

    def test_changed_evidence_breaks_selection(self):
        registry.select_correction(self.root, self.scene, self.correction)
        (self.run / 'visual_review.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'artifact or evidence changed'):
            registry.selected(self.root, self.scene)

    def test_missing_decode_blocks_selection(self):
        path = self.run / 'delivery/video_validation.json'
        data = json.loads(path.read_text())
        data['materials']['full_decode'] = False
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Full video decoding'):
            registry.select_correction(self.root, self.scene, self.correction)

    def test_hash_free_gallery_reads_legacy_pointer_without_digest(self):
        other = 'legacy_room'
        (self.root / 'scenes' / other).mkdir()
        folder = self.root / 'deliveries' / other
        versions = folder / 'versions'
        versions.mkdir(parents=True)
        scene_file = self.root / 'scenes' / other / 'room.blend'
        scene_file.write_bytes(b'legacy')
        manifest = versions / 'v1.json'
        manifest.write_text(json.dumps(dict(schema_version=1, scene=other, id='v1',
                                            status='recorded_delivery',
                                            artifacts=[dict(role='scene', path='scenes/legacy_room/room.blend')],
                                            evidence=[dict(path='scenes/legacy_room/room.blend')],
                                            review=dict(by='tester', note='Existing review'))))
        (folder / 'selected.json').write_text(json.dumps(dict(schema_version=2,
            delivery='deliveries/legacy_room/versions/v1.json', delivery_sha256='unused')))
        with patch('aha3d.results.registry.digest', side_effect=AssertionError('SHA called')):
            index = registry.build_index(self.root, hash_free=True)
        row = next(s for s in index['scenes'] if s['id'] == other)
        self.assertEqual(row['certification'], 'historical_unverified')


if __name__ == '__main__':
    unittest.main()
