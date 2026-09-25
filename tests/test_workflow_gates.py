"""Input regressions and integrated preview-gate lifecycle tests."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.io import digest, inventory, read, write
from aha3d.workflow.submission_preflight import constraints_report, sam_report, check, device_check
from aha3d.workflow.preview_gate import applicable, binding
import test_pipeline


class Inputs(unittest.TestCase):
    def test_cpu_and_gpu_device_visibility(self):
        with patch.dict(os.environ, {'CUDA_VISIBLE_DEVICES':'-1'}, clear=True):
            device_check('cpu','preview')
            with self.assertRaisesRegex(ValueError,'needs a GPU'): device_check('gpu','assemble')
        for visible in ({}, {'CUDA_VISIBLE_DEVICES':'0'}):
            with patch.dict(os.environ, visible, clear=True): device_check('gpu','preview')
        with self.assertRaisesRegex(ValueError,'cpu or gpu'): device_check('tpu','preview')

    def test_constraints_bounds_and_conflicts(self):
        route = [dict(type='root2d', frame_indices=[0,416], smooth_root_2d=[[0,0],[1,0]], global_root_heading=[[1,0],[1,0]])]
        constraints_report(route,417)
        for bad in [418,417,-1,False]:
            value=copy.deepcopy(route);value[0]['frame_indices'][-1]=bad
            with self.assertRaises(ValueError):constraints_report(value,417)
        with self.assertRaises(ValueError):constraints_report(route+[dict(type='right-hand',frame_indices=[416],smooth_root_2d=[[2,0]])],417)
        constraints_report(route+[dict(type='right-hand',frame_indices=[416],smooth_root_2d=[[1,0]])],417)
        value=copy.deepcopy(route);value[0]['global_root_heading'][0]=[2,0]
        with self.assertRaises(ValueError):constraints_report(value,417)

    def test_sam_exact_raster_and_last_frame_rounding(self):
        cameras=dict(processed_size_wh=[672,378],frames=[dict(source_frame=899,timestamp_seconds=899/60)])
        selection=dict(native_fps=30,native_frames=450,events=[dict(source_frame=899,bbox_xyxy=[1,2,45,120])])
        with self.assertRaisesRegex(ValueError,'rounds outside'):sam_report(selection,cameras)
        for bad in [-.001,449.5/30]:
            selection['events'][0]['target_time_seconds']=bad
            with self.assertRaises(ValueError):sam_report(selection,cameras)
        selection['native_fps']=24
        with self.assertRaises(ValueError):sam_report(selection,cameras)
        selection['native_fps']=30
        selection['events'][0]['target_time_seconds']=449/30
        sam_report(selection,cameras)
        compatible=copy.deepcopy(selection);compatible.pop('native_fps');compatible['events'][0].pop('bbox_xyxy');compatible['events'][0]['facing_xz']=[2,0]
        sam_report(compatible,cameras)  # Compiler accepts a nonunit direction and default native fps.
        selection['events'][0]['bbox_xyxy']=[1,2,800,700]
        with self.assertRaisesRegex(ValueError,'raster'):sam_report(selection,cameras)

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'scenes/formal_dining_platter_g0065/recipes/final.json').is_file(), 'Optional private scene fixtures are not distributed')
    def test_real_recipes_and_sam(self):
        root=Path(__file__).resolve().parents[1]
        pairs = [('formal_dining_platter_g0065','final'),
                 ('formal_dining_platter_g0065','presenter_contact_v2'),
                 ('formal_dining_platter_g0065','companion_guided'),
                 ('desert_view_lounge_g0061','delivery'),
                 ('desert_view_lounge_g0061','actor1_final_v2'),
                 ('desert_view_lounge_g0061','actor2_final'),
                 ('desert_view_lounge_g0061','actor3_final'),
                 ('four_poster_bedroom_g0063','final_whitebox_v2'),
                 ('four_poster_bedroom_g0063','man_guided_v2'),
                 ('four_poster_bedroom_g0063','woman_guided_v2')]
        results=[]
        for scene, name in pairs:
            value=read(root/'scenes'/scene/'recipes'/f'{name}.json')
            results.append(check(root,scene,name,value.get('body',{}).get('mode') in ('generate','native')))
        self.assertEqual(results[1]['native_segment_frames'], [180,237])
        self.assertGreaterEqual(len(results),3)
        selection=root/'scenes/desert_view_lounge_g0061/workflow/sam_2_reviewed.json'
        cameras=root/'runs/desert_view_lounge_g0061/reconstruction-20260911/pi3x/cameras.json'
        sam_report(read(selection),read(cameras))
        sam_report(read(selection.with_name('sam_3_reviewed.json')),read(cameras))


class Lifecycle(test_pipeline.Pipeline):
    def test_new_video_policy_and_still_scope(self):
        run=test_pipeline.runner.prepare(self.root,'one','replay',run_id='new-video')
        self.assertEqual(read(run/'run.json')['preview_policy'],'full_clip_v1')
        recipe=copy.deepcopy(self.recipe);recipe['render']={'kind':'stills'}
        write(self.root/'scenes/one/recipes/replay.json',recipe)
        still=test_pipeline.runner.prepare(self.root,'one','replay',run_id='new-still')
        self.assertNotIn('preview_policy',read(still/'run.json'))

    def test_new_gate_stops_before_render_and_reuses_assembly(self):
        run=super().prepare('gate');data=read(run/'run.json');data['preview_policy']='full_clip_v1';write(run/'run.json',data)
        stopped=self.run_stages(run)
        self.assertEqual(stopped['status'],'awaiting_review');self.assertNotIn('render',stopped['stages'])
        evidence=run/'evidence.json';write(evidence,{'reviewed':True})
        stopped['preview_acceptance']=dict(status='accepted',implementation_sha256=digest(__import__('aha3d.workflow.preview_gate',fromlist=['x']).__file__),binding=binding(run,stopped),evidence_hashes={str(evidence):digest(evidence)})
        write(run/'run.json',stopped)
        final=self.run_stages(run);self.assertEqual(final['status'],'validated')
        self.assertEqual(final['stages']['assemble']['attempts'],1)
        write(evidence,{'reviewed':'changed'})
        self.assertFalse(applicable(run,read(run/'run.json')))
        # Even a previously rendered new run cannot silently reuse stale acceptance.
        self.assertEqual(self.run_stages(run)['status'],'awaiting_review')

    def test_gpu_guard_only_for_actual_gpu_commands(self):
        run=super().prepare('gpu-guard')
        def command(run, recipe, runtime, stage, budget):
            return [sys.executable, str(self.fixture), str(run), stage]
        with patch.object(test_pipeline.runner,'command',side_effect=command), patch('aha3d.workflow.submission_preflight.device_check') as guard:
            test_pipeline.runner.execute(run,until='verify')
            guard.assert_called_once_with('gpu','assemble')
            guard.reset_mock()
            test_pipeline.runner.execute(run,until='verify')
            guard.assert_not_called()
            test_pipeline.runner.execute(run,until='render')
            guard.assert_called_once_with('gpu','render')

    def test_missing_input_before_prepare_or_submit(self):
        (self.root/'source.blend').unlink()
        with self.assertRaisesRegex(ValueError,'Missing source'):check(self.root,'one','replay')

if __name__=='__main__':unittest.main()
