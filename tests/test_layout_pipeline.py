"""Pipeline wiring checks using tiny immutable inputs and an explicit fake reviewer."""
import copy
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_pipeline
from aha3d.pipeline import runner
from aha3d.io import read,write

class LayoutPipeline(unittest.TestCase):
    def setUp(self):
        self.fixture=test_pipeline.Pipeline();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root
        (self.root/'tools/layout_inspection').mkdir(parents=True)
        (self.root/'tools/layout_inspection/render_blender.py').write_text('# frozen renderer')
        self.layout={k:k+ext for k,ext in [('reference','.npz'),('cameras','.json'),('inputs','.npz'),('config','.json'),('camera_cache','.npz'),('source_video','.mp4')]}
        for filename in [*self.layout.values(),'manifest.json','inputs.json']:(self.root/filename).write_bytes(b'fixture')
        self.recipe=copy.deepcopy(self.fixture.recipe);self.recipe['layout_inspection']=self.layout
        write(self.root/'scenes/one/recipes/replay.json',self.recipe)
    def test_frozen_tools_inputs_and_stage_order(self):
        run=runner.prepare(self.root,'one','replay',run_id='layout')
        data,recipe,_=runner.load(run)
        self.assertEqual(runner.stages(recipe)[0],'layout_inspection')
        self.assertEqual(Path(data['layout_inspection']['spec']['source_scene']),run/'inputs/source.blend')
        self.assertEqual((run/'snapshot/tools/layout_inspection/render_blender.py').read_text(),'# frozen renderer')
        (run/'snapshot/tools/layout_inspection/render_blender.py').write_text('changed')
        with self.assertRaises(ValueError):runner.load(run)
    def test_registered_reference_cannot_omit_gate(self):
        write(self.root/'scenes/one/scene.json',dict(schema_version=1,id='one',reference=self.layout['source_video']))
        write(self.root/'scenes/one/recipes/replay.json',self.fixture.recipe)
        with self.assertRaisesRegex(ValueError,'layout_inspection'):runner.prepare(self.root,'one','replay',run_id='bad')
        self.assertFalse((self.root/'runs/one/bad').exists())
    def test_required_object_ids_survive_snapshot_and_cannot_be_dropped(self):
        self.recipe['layout_inspection']['required_object_ids'] = ['bed', 'headwall']
        write(self.root/'scenes/one/recipes/replay.json', self.recipe)
        run = runner.prepare(self.root,'one','replay',run_id='object-ids')
        data, _, _ = runner.load(run)
        self.assertEqual(data['layout_inspection']['spec']['required_object_ids'], ['bed', 'headwall'])
        data['layout_inspection']['spec']['required_object_ids'] = ['bed']
        write(run/'run.json',data)
        with self.assertRaisesRegex(ValueError,'immutable recipe'):runner.load(run)

    def test_object_stage_uses_configured_mesh_interpreter(self):
        run = runner.prepare(self.root,'one','replay',run_id='mesh-runtime')
        manifest, _, runtime = runner.load(run)
        def prepare(spec, out, *, runner, object_runner):
            object_runner(spec, out)
        with patch.dict(os.environ, {'PI3X_MESH_PY': '/configured/mesh/python'}), \
                patch('aha3d.workflow.layout_gate.prepare', side_effect=prepare), \
                patch('aha3d.workflow.object_review.generate') as generate:
            self.assertFalse(runner.ensure_layout(run, manifest, runtime))
        self.assertEqual(generate.call_args.kwargs['python'], '/configured/mesh/python')
        self.assertEqual(generate.call_args.kwargs['tools_root'], run/'snapshot/tools/layout_inspection')
    def test_manifest_cannot_switch_evidence_inputs(self):
        run=runner.prepare(self.root,'one','replay',run_id='tamper')
        data=read(run/'run.json');data['layout_inspection']['spec']['source_scene']='unreviewed.blend';write(run/'run.json',data)
        with self.assertRaisesRegex(ValueError,'immutable'):runner.load(run)
    def test_wrong_review_room_rejected(self):
        self.recipe['layout_inspection']['source_scene']='other.blend';write(self.root/'scenes/one/recipes/replay.json',self.recipe)
        with self.assertRaisesRegex(ValueError,'exact recipe'):runner.prepare(self.root,'one','replay',run_id='bad')
    def test_review_blocks_assembly_and_resume(self):
        run=runner.prepare(self.root,'one','replay',run_id='layout')
        def prepare(spec,out,runner,object_runner):
            self.assertTrue(callable(object_runner));Path(out).mkdir();return {}
        def require(spec,out):
            if not (Path(out)/'reviewed').exists():raise ValueError('Unreviewed')
            return {}
        fake=types.SimpleNamespace(prepare=prepare,require_current=require)
        with patch.dict(sys.modules,{'aha3d.workflow.layout_gate':fake}):
            result=runner.execute(run);self.assertEqual(result['status'],'awaiting_review');self.assertNotIn('assemble',result['stages'])
            (run/'layout_evidence/reviewed').write_text('actual agent record fixture')
            result=runner.execute(run,until='layout_inspection');self.assertEqual(result['status'],'staged')
    def test_real_core_missing_review_stays_review_required(self):
        from aha3d.workflow import layout_gate
        run=runner.prepare(self.root,'one','replay',run_id='missing-review')
        evidence=run/'layout_evidence';evidence.mkdir()
        # Technical evidence is a separate core test; exercise its real missing-review IO path.
        with patch.object(layout_gate,'_current_evidence',return_value=({},{})):
            result=runner.execute(run)
        self.assertEqual(result['status'],'awaiting_review')
        self.assertNotIn('assemble',result['stages'])
    def test_body_change_preserves_layout_context(self):
        a=runner.prepare(self.root,'one','replay',run_id='a')
        self.recipe['body']['object_name']='new-motion-person';write(self.root/'scenes/one/recipes/replay.json',self.recipe)
        b=runner.prepare(self.root,'one','replay',run_id='b')
        self.assertEqual(read(a/'run.json')['layout_inspection']['spec']['pipeline_context'],read(b/'run.json')['layout_inspection']['spec']['pipeline_context'])
        self.recipe['assembly']={'camera':{'lens':40}};write(self.root/'scenes/one/recipes/replay.json',self.recipe)
        with self.assertRaisesRegex(ValueError,'authored room'):runner.prepare(self.root,'one','replay',run_id='c')

if __name__=='__main__':unittest.main()
