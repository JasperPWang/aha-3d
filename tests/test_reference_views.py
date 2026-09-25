import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from tools.layout_inspection.reference_views import select_views, overlay, run, CORE_COLOR
from tools.layout_inspection.reference_geometry import human_exclusion_mask


class ReferenceViews(unittest.TestCase):
    def test_native_selection_keeps_endpoints_and_unique_times(self):
        ids=np.array([0,10,11,12,50,75,100]); times=np.array([0,.05,.07,.1,5,7.5,10])
        slots=select_views(ids,times,5)
        self.assertEqual(len(slots),5)
        self.assertEqual(slots,sorted(set(slots)))
        self.assertEqual((slots[0],slots[-1]),(0,6))
        self.assertIn(4,slots)
        self.assertEqual(select_views(np.array([0,3]),[0,1],5),[0,1])
        self.assertEqual(select_views(np.array([0]),[0],5),[0])

    def test_requested_views_must_be_native_and_cover_the_clip(self):
        ids=np.arange(10); times=ids*.1
        self.assertEqual(select_views(ids,times,5,[0,4,9]),[0,4,9])
        for frames in ([0,1,2],[0,4,10],[0,4,4],[0,9]):
            with self.assertRaises(ValueError):select_views(ids,times,5,frames)
        with self.assertRaises(ValueError):select_views(ids,times[::-1])

    def test_overlay_preserves_people_and_missing_geometry(self):
        rgb=np.full((5,6,3),100,np.uint8); depth=np.full((5,6),4.,np.float32)
        role=np.zeros((5,6),np.uint8); person=np.zeros((5,6),bool)
        depth[:,0]=np.inf; person[:,5]=True
        result,hit,edges=overlay(rgb,depth,role,person,1.)
        np.testing.assert_array_equal(result[:,0],rgb[:,0])
        np.testing.assert_array_equal(result[:,5],rgb[:,5])
        np.testing.assert_array_equal(result[hit],np.broadcast_to(CORE_COLOR,result[hit].shape))
        self.assertFalse(hit[:,0].any());self.assertFalse(hit[:,5].any())
        self.assertTrue(edges.any())

    @unittest.skipUnless(importlib.util.find_spec('open3d') is not None,'Optional Open3D runtime required')
    def test_real_projection_uses_native_rgb_camera_z_and_basis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ids=np.array([0,10,20]); times=np.array([0.,1.,2.]); h,w=24,32
            rgb=np.full((3,h,w,3),110,np.uint8); rgb[...,0]=np.arange(w)[None,None,:]
            np.savez(root/'inputs.npz',rgb=rgb,frame_indices=ids,timestamps_seconds=times)
            k=np.array([[30.,0,15.5],[0,30.,11.5],[0,0,1.]])
            poses=np.repeat(np.eye(4)[None],3,axis=0);poses[:,0,3]=[0,.1,.2]
            records=[dict(source_frame=int(f),timestamp_seconds=float(t),intrinsics=k.tolist(),c2w=pose.tolist()) for f,t,pose in zip(ids,times,poses)]
            camera=dict(world_transform=np.eye(4).tolist(),processed_size_wh=[w,h],frames=records)
            (root/'cameras.json').write_text(json.dumps(camera))
            layer=np.zeros((3,h,w),np.uint8);layer[:,:8,:8]=1
            exclusion=human_exclusion_mask(layer==1,3)
            np.savez(root/'layers.npz',frame_indices=ids,world_transform=np.eye(4),layer=layer.ravel(),
                human_exclusion=exclusion.ravel(),
                display_vertices=np.array([[-1,-1,4],[1,-1,4],[-1,1,4],[1,1,4]],np.float32),
                display_faces=np.array([[0,1,2],[1,3,2]],np.int32),display_colors=np.full((4,3),128,np.uint8),
                display_face_layer=np.array([0,0],np.uint8),display_face_role=np.array([0,1],np.uint8))
            meta=dict(frame_indices=ids.tolist(),geometry_representation={'method':'tsdf-context'})
            (root/'manifest.json').write_text(json.dumps(meta))
            result=run(root/'layers.npz',root/'cameras.json',root/'inputs.npz',root/'views')
            self.assertEqual(result['source_frame_indices'],ids.tolist())
            for i,f in enumerate(ids):
                stem=f'source_{f:06d}'
                with Image.open(root/f'views/{stem}_source.png') as im:np.testing.assert_array_equal(np.asarray(im),rgb[i])
                with Image.open(root/f'views/{stem}_overlay.png') as im:combined=np.asarray(im)
                with np.load(root/f'views/{stem}_projection.npz') as z:
                    np.testing.assert_array_equal(z['person_mask'],layer[i]==1)
                    np.testing.assert_array_equal(z['human_exclusion'],exclusion[i])
                    self.assertFalse(z['overlay_visible'][exclusion[i]].any())
                    self.assertTrue((np.isfinite(z['depth_camera_z']) & exclusion[i] & (layer[i]!=1)).any())
                    depth=z['depth_camera_z']; hit=np.isfinite(depth)
                    np.testing.assert_allclose(depth[hit],4.,rtol=0,atol=1e-5)
                    self.assertTrue(hit.any());self.assertFalse(hit.all())
                    self.assertEqual(set(z['role'][hit].tolist()),{0,1})
                    np.testing.assert_array_equal(combined[~z['overlay_visible']],rgb[i][~z['overlay_visible']])
            for name in result['artifacts']:self.assertTrue((root/'views'/name).is_file())
            camera['world_transform'][0][3] = 1
            (root/'cameras.json').write_text(json.dumps(camera))
            with self.assertRaisesRegex(ValueError,'world basis'):
                run(root/'layers.npz',root/'cameras.json',root/'inputs.npz',root/'bad')


if __name__=='__main__':unittest.main()
