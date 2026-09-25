"""Entrypoint ordering: missing layout cannot reach alignment, models or delivery."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def load(name):
    spec=importlib.util.spec_from_file_location('layout_consumer_'+name,ROOT/'tools/gvhmr'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class GVHMRLayoutGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'render':{'source_video':'source.mp4','camera_cache':'camera.npz'}}))
    def tearDown(self):self.tmp.cleanup()
    def test_alignment_missing_or_stale_review_blocks_before_geometry(self):
        module=load('align_group')
        args=['align','--manifest',str(self.manifest),'--camera-cache',str(self.root/'camera.npz'),'--output',str(self.root/'out')]
        for reason in ('missing layout review','stale layout evidence'):
            with patch('aha3d.workflow.layout_gate.validate_layout',side_effect=ValueError(reason)) as gate,patch.object(sys,'argv',args):
                with self.assertRaisesRegex(ValueError,reason):module.main()
                gate.assert_called_once();self.assertFalse((self.root/'out').exists())
    def test_alignment_explicit_camera_cannot_differ_from_reviewed_manifest(self):
        module=load('align_group')
        args=['align','--manifest',str(self.manifest),'--camera-cache',str(self.root/'other.npz'),'--output',str(self.root/'out')]
        with patch('aha3d.workflow.layout_gate.validate_layout') as gate,patch.object(sys,'argv',args):
            with self.assertRaisesRegex(ValueError,'Alignment camera differs'):module.main()
            gate.assert_not_called()
    def test_contact_blocks_before_loading_models_or_creating_output(self):
        module=load('contact_refine')
        args=['contact','--manifest',str(self.manifest),'--models',str(self.root/'missing_models'),'--output',str(self.root/'out')]
        with patch('aha3d.workflow.layout_gate.validate_layout',side_effect=ValueError('layout review required')) as gate,patch.object(sys,'argv',args):
            with self.assertRaisesRegex(ValueError,'layout review required'):module.main()
            gate.assert_called_once();self.assertFalse((self.root/'out').exists())
    def test_direct_renderer_requires_layout_even_for_legacy_reference(self):
        module=load('contact_render');args=SimpleNamespace(manifest=self.manifest,refinement=self.root/'missing',diagnostic_layout=False)
        with patch('aha3d.workflow.layout_gate.validate_layout',side_effect=ValueError('layout review required')) as gate:
            with self.assertRaisesRegex(ValueError,'layout review required'):module.inputs(args)
            self.assertFalse(gate.call_args.kwargs['diagnostic'])
    def test_diagnostic_layout_still_requires_body_placement(self):
        module=load('contact_render');args=SimpleNamespace(manifest=self.manifest,refinement=self.root/'missing',diagnostic_layout=True)
        fake_group=SimpleNamespace(validate_group=Mock(return_value={}))
        fake_placement=SimpleNamespace(validate_placement_report=Mock(side_effect=ValueError('body placement required')))
        with patch('aha3d.workflow.layout_gate.validate_layout',return_value={'accepted':False,'status':'diagnostic_unaccepted'}) as gate,patch.dict(sys.modules,{'group_scale_gate':fake_group,'placement_gate':fake_placement}):
            with self.assertRaisesRegex(ValueError,'body placement required'):module.inputs(args)
            self.assertTrue(gate.call_args.kwargs['diagnostic']);fake_placement.validate_placement_report.assert_called_once()
            self.assertFalse(args.layout_validation['accepted'])
        self.assertTrue(all(name.startswith('diagnostic_unaccepted_') for name in module.output_names(args)))
    def test_relative_layout_paths_survive_output_manifest_relocation(self):
        module=load('align_group');spec={'source_scene':'../room.blend','reference':'layers.npz','review_dir':'review','inputs_metadata':'inputs.json','reference_npz':'layers.npz','version':1}
        result=module.rebase_layout_gate({'layout_gate':spec},self.root)
        self.assertEqual(result['source_scene'],str((self.root/'../room.blend').resolve()))
        self.assertEqual(result['review_dir'],str(self.root/'review'));self.assertEqual(result['version'],1)
        self.assertEqual(result['inputs_metadata'],str(self.root/'inputs.json'));self.assertEqual(result['reference_npz'],str(self.root/'layers.npz'))
        self.assertEqual(spec['reference'],'layers.npz')
    def test_placement_only_wrapper_does_not_require_layout(self):
        fake=self.root/'python';fake.write_text('#!/bin/bash\nif [[ "$1" == -c ]]; then echo /unused/camera.npz; elif [[ "$1" == */placement_diagnostics.py ]]; then echo READ_ONLY_PLACEMENT; else echo UNEXPECTED_GATE >&2; exit 9; fi\n');fake.chmod(0o755)
        result=subprocess.run(['bash',str(ROOT/'tools/gvhmr/run_contact.sh'),'--manifest',str(self.manifest),'--output',str(self.root/'out'),'--placement-only'],capture_output=True,text=True,env={**os.environ,'CONTACT_PYTHON':str(fake)})
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('READ_ONLY_PLACEMENT',result.stdout)
    def test_wrapper_diagnostic_cannot_bypass_alignment_or_contact(self):
        result=subprocess.run(['bash',str(ROOT/'tools/gvhmr/run_contact.sh'),'--manifest',str(self.manifest),'--output',str(self.root/'out'),'--diagnostic-layout'],capture_output=True,text=True,env=dict(os.environ))
        self.assertNotEqual(result.returncode,0);self.assertIn('requires --render-only',result.stderr)

if __name__=='__main__':unittest.main()
