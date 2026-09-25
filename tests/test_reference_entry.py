import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from tools.layout_inspection.build_reference import parser, run
from tools.layout_inspection.semantic import validate_cache
from tools.layout_inspection.prepare import require_full_coverage


class ReferenceEntry(unittest.TestCase):
    def test_portable_runtime_environment_and_explicit_overrides(self):
        env = {'PI3X_PY': '/configured/core/python',
               'PI3X_UPSTREAM': '/configured/Pi3',
               'PI3X_MESH_PY': '/configured/mesh/python'}
        with patch.dict(os.environ, env):
            args = parser().parse_args(['--bundle', 'bundle', '--out', 'out'])
            self.assertEqual(args.pi3x_python, Path(env['PI3X_PY']))
            self.assertEqual(args.upstream, Path(env['PI3X_UPSTREAM']))
            self.assertEqual(args.mesh_python, Path(env['PI3X_MESH_PY']))
            args = parser().parse_args(['--bundle', 'bundle', '--out', 'out',
                '--pi3x-python', '/override/core', '--upstream', '/override/Pi3',
                '--mesh-python', '/override/mesh'])
            self.assertEqual(args.pi3x_python, Path('/override/core'))
            self.assertEqual(args.upstream, Path('/override/Pi3'))
            self.assertEqual(args.mesh_python, Path('/override/mesh'))

    def test_new_video_builds_full_geometry_then_five_source_overlays(self):
        for count in (32, 64):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)/'result'
                a = parser().parse_args(['--video', str(Path(tmp)/'video.mp4'), '--checkpoint', 'weights',
                                         '--out', str(out), '--num-frames', str(count)])
                ids = np.linspace(0, 251, count).round().astype(int).tolist()
                calls = []
                def runner(command, **kwargs):
                    calls.append(command)
                    self.assertNotIn('--frames', command)
                    if len(calls) == 1:
                        (out/'pi3x').mkdir()
                        (out/'pi3x/inputs.json').write_text(json.dumps(dict(frame_indices=ids, source_frame_count=252)))
                    elif len(calls) == 4:
                        (out/'mesh').mkdir()
                        (out/'mesh/manifest.json').write_text(json.dumps(dict(frame_indices=ids,geometry_representation={'method':'tsdf-context'})))
                    elif len(calls) == 5:
                        (out/'source_views').mkdir()
                        (out/'source_views/reference_views.json').write_text(json.dumps(dict(source_frame_indices=[ids[i] for i in (0,7,15,23,len(ids)-1)])))
                result = run(a, runner=runner)
                self.assertEqual(len(calls), 5)
                self.assertEqual(result['frame_indices'], ids)
                self.assertEqual(calls[1][2], 'tools.layout_inspection.semantic')
                self.assertIn('--structure', calls[1])
                self.assertEqual(calls[2][2], 'tools.layout_inspection.structural_alignment')
                self.assertEqual(calls[3][2], 'tools.layout_inspection.prepare')
                self.assertEqual(calls[3][calls[3].index('--cameras')+1], str(out/'alignment/cameras.json'))
                self.assertEqual(result['mesh_method'], 'tsdf-context')
                self.assertEqual(calls[3][0], str(a.mesh_python))
                self.assertEqual(calls[3][calls[3].index('--confidence')+1], '0.5')
                self.assertEqual(calls[3][calls[3].index('--fusion-confidence')+1], '0.1')
                self.assertEqual(calls[3][calls[3].index('--human-mask-radius')+1], '3')
                self.assertEqual(calls[4][2], 'tools.layout_inspection.reference_views')
                self.assertEqual(calls[4][calls[4].index('--view-count')+1], '5')
                self.assertEqual(len(result['source_view_frames']), 5)

    def test_cached_masks_skip_gpu_semantics_and_grid_is_explicit(self):
        for method in ('tsdf-context','grid'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);bundle=root/'bundle';bundle.mkdir();out=root/'result'
                ids=list(range(32));(bundle/'inputs.json').write_text(json.dumps(dict(frame_indices=ids,source_frame_count=32)))
                a=parser().parse_args(['--bundle',str(bundle),'--semantic-cache',str(root/'masks'),
                    '--out',str(out),'--mesh-method',method,'--reference-views','3',
                    '--human-mask-radius','5','--fusion-confidence','0.3','--cameras',str(bundle/'cameras.json')])
                calls=[]
                def runner(command,**kwargs):
                    calls.append(command)
                    if len(calls) == 1:
                        (out/'mesh').mkdir()
                        (out/'mesh/manifest.json').write_text(json.dumps(dict(frame_indices=ids,geometry_representation={'method':method})))
                    else:
                        (out/'source_views').mkdir()
                        (out/'source_views/reference_views.json').write_text(json.dumps(dict(source_frame_indices=[0,15,31])))
                result=run(a,runner)
                self.assertEqual(len(calls),2)
                self.assertEqual(result['mesh_method'],method)
                self.assertEqual(calls[0][0],str(a.mesh_python if method=='tsdf-context' else a.pi3x_python))
                self.assertEqual(calls[0][calls[0].index('--human-mask-radius')+1], '5')
                self.assertEqual(calls[0][calls[0].index('--fusion-confidence')+1], '0.3')
                self.assertEqual(calls[1][calls[1].index('--view-count')+1], '3')
                self.assertEqual(result['source_view_frames'], [0,15,31])

    def test_negative_margin_fails_before_creating_outputs_or_launching_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            args=parser().parse_args(['--bundle',str(Path(tmp)/'missing'),'--out',str(out),
                                     '--human-mask-radius','-1'])
            with self.assertRaisesRegex(ValueError,'nonnegative'):run(args)
            self.assertFalse(out.exists())

    def test_explicit_camera_basis_cannot_be_silently_realigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            args=parser().parse_args(['--bundle',tmp,'--out',str(out),'--cameras',str(Path(tmp)/'cameras.json'),
                                     '--alignment','structural'])
            with self.assertRaisesRegex(ValueError,'preserves an established basis'):run(args)
            self.assertFalse(out.exists())

    def test_zero_detections_are_processed_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bundle=root/'bundle'; cache=root/'cache'
            bundle.mkdir(); cache.mkdir()
            ids=np.arange(32)
            np.savez(bundle/'inputs.npz',frame_indices=ids)
            np.savez(cache/'masks.npz',frame_indices=ids,
                     **{k:np.zeros((32,2,2),bool) for k in ('person','glass','mirror')})
            (cache/'manifest.json').write_text(json.dumps(dict(status='complete',
                bundle=str(bundle.resolve()))))
            masks, known, _ = validate_cache(cache,bundle,ids,(2,2))
            require_full_coverage(ids,None,known)
            self.assertTrue(known.all())
            self.assertFalse(any(v.any() for v in masks.values()))


if __name__ == '__main__':
    unittest.main()
