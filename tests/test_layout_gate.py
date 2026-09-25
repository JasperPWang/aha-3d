import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from aha3d.workflow import layout_gate as gate
from aha3d.workflow.camera import interpolate


class LayoutGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        from test_object_review import object_fixture
        generation=patch('aha3d.workflow.object_review.generate',side_effect=object_fixture)
        generation.start();self.addCleanup(generation.stop)
        self.spec={k:str(self.root/name) for k,name in [('source_scene','room.blend'),('source_video','source.mp4'),('reference','reference.npz'),('inputs','inputs.npz'),('cameras','cameras.json'),('config','config.json'),('camera_cache','camera.npz')]}
        Path(self.spec['source_scene']).write_bytes(b'BLENDER fake room fixture');Path(self.spec['source_video']).write_bytes(b'original video fixture')
        self.rgb=np.stack([np.full((8,8,3),x,np.uint8) for x in (30,80,160)])
        np.savez(self.spec['inputs'],rgb=self.rgb,frame_indices=[0,5,10],timestamps_seconds=[0.,1.,2.])
        self.meta={'frame_indices':[0,5,10],'timestamps_seconds':[0.,1.,2.],'processed_size_wh':[8,8],'source_sha256':gate.digest(self.spec['source_video'])}
        self.dump('inputs.json',self.meta)
        self.cam={'world_transform':np.eye(4).tolist(),'units':'predicted metres, uncalibrated','processed_size_wh':[8,8],'frames':[{'source_frame':f,'timestamp_seconds':t,'c2w':np.eye(4).tolist(),'intrinsics':[[5,0,3.5],[0,5,3.5],[0,0,1]]} for f,t in zip([0,5,10],[0.,1.,2.])]}
        self.dump('cameras.json',self.cam);np.savez(self.spec['reference'],world_transform=np.eye(4),frame_indices=[0,5,10])
        self.manifest={'frame_indices':[0,5,10],'world_transform':np.eye(4).tolist(),'inputs_sha256':gate.digest(self.spec['inputs']),'cameras_sha256':gate.digest(self.spec['cameras']),'layers_sha256':gate.digest(self.spec['reference'])};self.dump('manifest.json',self.manifest)
        self.config={'model_to_world':np.eye(4).tolist(),'model_transform_reason':'Authored directly in reviewed reference basis','resolution':8,'source_frames':[0,5,10],'views':{n:{'location':[0,0,10],'target':[0,0,0],'ortho_scale':8,'crop_xyz_m':[[-4,4],[-4,4],[-1,4]]} for n in ('top','front','side')}}
        self.dump('config.json',self.config)
        values,_=interpolate(self.cam,np.array([0.,.5,1.,1.5,2.]),[8,8],[16,16]);np.savez(self.spec['camera_cache'],**values)
        self.evidence=self.root/'evidence'
        from aha3d.workflow.acceptance import init
        self.task_scope=init(self.root,dict(scene='room',task='layout',kind='reconstruction',reference_reconstruction=True,human_motion=False,render='none',required_artifacts=['scene'],subjects=['bed'],source_video=self.spec['source_video']))['scope']
    def dump(self,path,value): (self.root/path).write_text(json.dumps(value))
    def runner(self,spec,out):
        out.mkdir();technical=gate._technical_inputs(spec);views={}
        for name in technical['expected_views']:
            if name.startswith('source_'):
                f=int(name.split('_')[1]);record=next(r for r in self.cam['frames'] if r['source_frame']==f);settings={'source_record':record,'crop_xyz_m':[[-1000,1000]]*3};matrix=np.diag([1,-1,-1,1]);Image.fromarray(self.rgb[[0,5,10].index(f)]).save(out/f'{name}_source.png')
            else:
                settings=self.config['views'][name];matrix=np.eye(4);matrix[:3,3]=settings['location']
            outputs=[]
            for mode in gate.MODES:
                p=out/f'{name}_{mode}.png';Image.fromarray(self.rgb[0]).save(p);outputs.append(str(p))
            views[name]={'camera_matrix_world':matrix.tolist(),'settings':settings,'outputs':outputs}
        meta={'source_scene_sha256':gate.digest(spec['source_scene']),'reference_sha256':gate.digest(spec['reference']),'cameras_sha256':gate.digest(spec['cameras']),'config':self.config,'world_transform':np.eye(4).tolist(),'views':views}
        (out/'inspection.json').write_text(json.dumps(meta));(out/'inspection.blend').write_bytes(b'BLENDER inspection fixture');return out
    def prepare(self):return gate.prepare(self.spec,self.evidence,runner=self.runner)
    def review(self,verdict='accepted'):
        from test_acceptance import visual_fixture
        e=self.prepare();request=gate.review_request(self.spec,self.evidence)
        visual=visual_fixture(request['candidate_revision'],request['images']);visual['verdict']=verdict
        for identity, images in request['object_views'].items():
            visual['observations'].append(dict(aspect='placement',subjects=[identity],views=images,
                observation='Fixture: object extent and supporting plane agree in the supplied focused views.'))
        return gate.record_review(self.spec,self.evidence,reviewer='agent-fixture',notes='Inspected source comparisons, footprint alignment and uncertain regions.',verdict=verdict,expected_views=e['expected_views'],visual_review=visual)
    def test_partial_mesh_coverage_rejected(self):
        np.savez(self.spec['reference'],world_transform=np.eye(4),frame_indices=[0,10])
        self.manifest['frame_indices']=[0,10]
        self.manifest['layers_sha256']=gate.digest(self.spec['reference'])
        self.dump('manifest.json',self.manifest)
        with self.assertRaisesRegex(ValueError,'all cached inference frames'):self.prepare()

    def test_placement_report_is_bound_to_review(self):
        base=self.runner
        def with_placement(spec,out):
            base(spec,out)
            meta=json.loads((out/'inspection.json').read_text());meta['placement_report']='placement/report.json'
            (out/'inspection.json').write_text(json.dumps(meta));(out/'placement').mkdir()
            (out/'placement/report.json').write_text(json.dumps({'schema_version':1,'summary':{'accepted':False}}))
            (out/'placement/report.html').write_text('diagnostic html')
            (out/'placement/REPORT.md').write_text('diagnostic summary')
            return out
        self.runner=with_placement
        self.review()
        self.assertEqual(gate.require_current(self.spec,self.evidence)['status'],'accepted')
        (self.evidence/'inspection/placement/report.json').write_text('{}')
        with self.assertRaises(ValueError):gate.require_current(self.spec,self.evidence)

    def test_generation_does_not_accept_geometry(self):
        e=self.prepare();self.assertEqual(e['status'],'awaiting_agent_review')
        with self.assertRaises((ValueError,FileNotFoundError)):gate.require_current(self.spec,self.evidence)
    def test_consumer_requires_no_scientific_runtime(self):
        import builtins
        from unittest.mock import patch
        self.review();original=builtins.__import__
        def limited(name,*args,**kwargs):
            if name.split('.')[0] in ('numpy','scipy','PIL'):raise ImportError('Unavailable in Blender')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=limited):
            self.assertEqual(gate.require_current(self.spec,self.evidence)['status'],'accepted')
    def test_explicit_review_and_motion_only_reuse(self):
        self.review();s=dict(self.spec,motion_cache='actor-updated.npz')
        self.assertEqual(gate.require_current(s,self.evidence)['status'],'accepted')
    def test_scene_edit_invalidates_review(self):
        self.review();Path(self.spec['source_scene']).write_bytes(b'room moved')
        with self.assertRaises(ValueError):gate.require_current(self.spec,self.evidence)
    def xray_runner(self,spec,out):
        result=self.runner(spec,out)
        path=out/'inspection.json';metadata=json.loads(path.read_text())
        for name,row in metadata['views'].items():
            for mode in gate.XRAY_MODES:
                image=out/f'{name}_{mode}.png'
                Image.fromarray(self.rgb[0]).save(image)
                row['outputs'].append(str(image))
        path.write_text(json.dumps(metadata))
        return result
    def test_current_renderer_xray_images_are_bound_and_reviewed(self):
        gate.prepare(self.spec,self.evidence,runner=self.xray_runner)
        request=gate.review_request(self.spec,self.evidence)
        self.assertIn('top:overlay_xray',request['images'])
        self.assertIn('source_000010:edges',request['images'])
        gate._current_evidence(self.spec,self.evidence,recheck_technical=False)
        Image.fromarray(self.rgb[2]).save(self.evidence/'inspection/top_overlay_xray.png')
        with self.assertRaisesRegex(ValueError,'changed'):
            gate._current_evidence(self.spec,self.evidence,recheck_technical=False)
    def test_partial_xray_output_set_rejected(self):
        def incomplete(spec,out):
            result=self.xray_runner(spec,out)
            path=out/'inspection.json';metadata=json.loads(path.read_text())
            metadata['views']['top']['outputs'].pop()
            path.write_text(json.dumps(metadata));return result
        with self.assertRaisesRegex(ValueError,'comparison modes'):
            gate.prepare(self.spec,self.evidence,runner=incomplete)
    def test_config_transform_edit_invalidates(self):
        self.review();self.config['model_to_world'][0][3]=1;self.dump('config.json',self.config)
        with self.assertRaises(ValueError):gate.require_current(self.spec,self.evidence)
    def test_missing_or_modified_artifact_invalidates(self):
        self.review();(self.evidence/'inspection/top_overlay.png').unlink()
        with self.assertRaises(ValueError):gate.require_current(self.spec,self.evidence)
    def test_review_requires_every_expected_view(self):
        e=self.prepare()
        with self.assertRaises(ValueError):gate.record_review(self.spec,self.evidence,reviewer='agent',notes='Reviewed only one view',verdict='accepted',expected_views=e['expected_views'][:-1])
    def test_rejection_cannot_be_consumed(self):
        self.review('rejected')
        with self.assertRaises(ValueError):gate.require_current(self.spec,self.evidence)
    def test_camera_cache_calibration_mismatch_rejected(self):
        with np.load(self.spec['camera_cache']) as z:data={k:z[k] for k in z.files}
        data['K'][:,0,0]+=1;np.savez(self.spec['camera_cache'],**data)
        with self.assertRaisesRegex(ValueError,'camera cache'):self.prepare()
    def test_source_identity_mismatch_rejected(self):
        Path(self.spec['source_video']).write_bytes(b'different source')
        with self.assertRaisesRegex(ValueError,'source identity'):self.prepare()
    def test_early_only_views_rejected(self):
        self.config['source_frames']=[0,5];self.dump('config.json',self.config)
        with self.assertRaises(ValueError):self.prepare()
    def test_wrong_source_frame_pixels_rejected(self):
        def bad_runner(spec,out):
            result=self.runner(spec,out);Image.fromarray(self.rgb[2]).save(out/'source_000000_source.png');return result
        with self.assertRaisesRegex(ValueError,'source RGB'):gate.prepare(self.spec,self.evidence,runner=bad_runner)
    def test_input_mutation_during_generation_rejected(self):
        def bad_runner(spec,out):
            result=self.runner(spec,out);Path(spec['source_scene']).write_bytes(b'concurrent room edit');return result
        with self.assertRaisesRegex(ValueError,'changed during'):gate.prepare(self.spec,self.evidence,runner=bad_runner)
    def test_synthetic_skip_reference_missing_gate_fails(self):
        with self.assertRaisesRegex(ValueError,'task_scope'):gate.validate_layout({'render':{}},self.root/'manifest.json')
        with self.assertRaises(ValueError):gate.validate_layout({'render':{'source_video':'source.mp4'}},self.root/'manifest.json')
        result=gate.validate_layout({'render':{'source_video':'source.mp4'}},self.root/'manifest.json',diagnostic=True)
        self.assertFalse(result['accepted'])
    def test_consumer_cannot_switch_room_or_camera(self):
        self.review();spec=dict(self.spec,review_dir=str(self.evidence));m={'task_scope':self.task_scope,'layout_gate':spec,'render':{'source_video':self.spec['source_video'],'scene':self.spec['source_scene'],'camera_cache':self.spec['camera_cache']}}
        self.assertEqual(gate.validate_layout(m,self.root/'consumer.json')['status'],'accepted')
        m['render']['scene']='unreviewed.blend'
        with self.assertRaises(ValueError):gate.validate_layout(m,self.root/'consumer.json')
if __name__=='__main__':unittest.main()
