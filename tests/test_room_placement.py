import tempfile
from pathlib import Path
import unittest
from aha3d.placement.config import normalize
from aha3d.placement.report import summarize,write_report
from aha3d.placement.runner import infer_scene


class PlacementTests(unittest.TestCase):
    def test_bad_config_does_not_silently_disable_checks(self):
        for bad in ([],{'penetration_m':float('nan')},{'max_samples':0},{'physics':'skip'},{'typo':1},{'objects':{'chair':{'fixed':'yes'}}}):
            with self.assertRaises(ValueError):normalize(bad)
    def test_incomplete_is_not_pass(self):
        report={'objects':[],'issues':[{'severity':'unverified'}]}
        self.assertEqual(summarize(report)['status'],'incomplete')
        self.assertFalse(summarize(report)['accepted'])
    def test_scene_inference_is_structural(self):
        root=Path('/project')
        self.assertEqual(infer_scene(root,root/'scenes/room/blender/source.blend'),'room')
        self.assertEqual(infer_scene(root,root/'runs/room/run/scene.blend'),'room')
        with self.assertRaises(ValueError):infer_scene(root,root/'runs/_tools/example.blend')
    def test_html_escapes_object_evidence(self):
        report=dict(objects=[],issues=[dict(severity='warning',code='overlap',objects=['<script>'],message='<script>alert(1)</script>',next_action='review')],coverage={},limits=['no acceptance'])
        with tempfile.TemporaryDirectory() as td:
            write_report(td,report)
            text=(Path(td)/'report.html').read_text()
            self.assertNotIn('<script>',text);self.assertIn('&lt;script&gt;',text)
            self.assertTrue((Path(td)/'report.json').is_file())


if __name__=='__main__':unittest.main()
