import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'tools/gvhmr/placement_gate.py'
spec = importlib.util.spec_from_file_location('placement_gate_tested', MODULE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class PlacementGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for name in ('motion.npz', 'cache.npz', 'alignment.json', 'pose.pt', 'camera.npz'):
            (self.base / name).write_bytes(name.encode())
        self.data = {'actors': [{'id': 'arbitrary_person_29', 'motion': 'motion.npz',
                      'cache': 'cache.npz', 'alignment': 'alignment.json',
                      'pose_confidence': 'pose.pt', 'exclude_seconds': []}],
                     'render': {'camera_cache': 'camera.npz'}}
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text(json.dumps(self.data))
        self.refined = self.base / 'refined'
        actor = self.refined / self.data['actors'][0]['id']
        actor.mkdir(parents=True)
        (actor / 'body_room.npz').write_bytes(b'selected-body')
        self.report = self.base / 'report.json'
        self.payload = {'schema_version': 1, 'scope': 'observed_projection_only',
                        'accepted': True, 'status': 'pass',
                        'input_binding': gate.input_binding(self.manifest, self.refined)}
        self.report.write_text(json.dumps(self.payload))

    def validate(self):
        return gate.validate_placement_report(self.report, self.manifest, self.refined)

    def test_accepts_exact_selected_evidence(self):
        self.assertEqual(self.validate()['scope'], 'observed_projection_only')

    def test_selected_cache_change_rejected(self):
        (self.refined / self.data['actors'][0]['id'] / 'body_room.npz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.validate()

    def test_observations_change_rejected(self):
        (self.base / 'pose.pt').write_bytes(b'other-detection')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.validate()

    def test_camera_change_rejected(self):
        (self.base / 'camera.npz').write_bytes(b'new-camera')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.validate()

    def test_posthoc_visibility_or_exclusions_rejected(self):
        for key, value in [('visible_until_seconds', 3), ('exclude_seconds', [[3, 9]])]:
            with self.subTest(key=key):
                self.data['actors'][0][key] = value
                self.manifest.write_text(json.dumps(self.data))
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    self.validate()

    def test_failed_and_unknown_cannot_be_contact_overridden(self):
        for status in ('fail', 'unverified'):
            with self.subTest(status=status):
                self.payload.update(status=status, accepted=False)
                self.report.write_text(json.dumps(self.payload))
                with self.assertRaisesRegex(ValueError, 'failed or is unverified'):
                    self.validate()

    def test_pseudo_projection_report_not_accepted(self):
        self.payload['scope'] = 'gvhmr_incam_projection'
        self.report.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, 'observed-source'):
            self.validate()

    def test_source_cache_report_cannot_validate_refined_cache(self):
        self.payload['input_binding'] = gate.input_binding(self.manifest)
        self.report.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
