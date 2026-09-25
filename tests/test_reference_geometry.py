"""Contract tests for background-preserving references and trusted measurements."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import numpy as np
from tools.layout_inspection.prepare import build, parser
from tools.layout_inspection.reference_geometry import build_display, context_triangles, rays, validate_cameras, human_exclusion_mask


def fixture(root):
    bundle=root/'bundle';cache=root/'masks';bundle.mkdir();cache.mkdir()
    n,h,w=3,48,64;ids=np.arange(n);y,x=np.mgrid[:h,:w]
    k=np.array([[60.,0,(w-1)/2],[0,60.,(h-1)/2],[0,0,1]])
    depth=np.where(x<w//2,4.,9.)
    local=np.stack([(x-k[0,2])/k[0,0]*depth,(y-k[1,2])/k[1,1]*depth,depth],-1)
    local=np.repeat(local[None],n,axis=0).astype(np.float32)
    poses=np.repeat(np.eye(4)[None],n,axis=0);poses[:,0,3]=np.arange(n)*.05
    world=np.repeat(np.eye(4)[None],1,axis=0)[0];world[:3,3]=[1,2,-.5]
    points=local+poses[:,:3,3,None,None].transpose(0,2,3,1)
    rgb=np.full((n,h,w,3),128,np.uint8)
    confidence=np.where(x<w//2,.8,.01);logits=np.log(confidence/(1-confidence))
    logits=np.broadcast_to(logits[None,...,None],(n,h,w,1)).copy()
    edges=np.ones((n,h,w),bool);edges[:,:,w//2:]=False
    np.savez(bundle/'inputs.npz',rgb=rgb,frame_indices=ids,timestamps_seconds=ids.astype(float))
    np.savez(bundle/'predictions.npz',points=points,local_points=local,conf=logits,non_edge=edges,
        camera_poses=poses,intrinsics=np.repeat(k[None],n,axis=0))
    masks={key:np.zeros((n,h,w),bool) for key in ('person','glass','mirror')}
    masks['person'][:,:8,:8]=True;masks['glass'][:,:,48:]=True
    np.savez(cache/'masks.npz',frame_indices=ids,**masks)
    (cache/'manifest.json').write_text(json.dumps(dict(status='complete',bundle=str(bundle.resolve()))))
    camera=dict(world_transform=world.tolist(),processed_size_wh=[w,h],frames=[dict(source_frame=int(i),
        c2w=(world@poses[i]).tolist(),intrinsics=k.tolist(),timestamp_seconds=float(i)) for i in ids])
    (bundle/'cameras.json').write_text(json.dumps(camera))
    return bundle,cache


class ReferenceGeometryTests(unittest.TestCase):
    def test_human_margin_is_a_spatial_disk_and_zero_does_not_fill(self):
        person=np.zeros((3,11,11),bool);person[1,5,5]=True;person[2,0,0]=True
        original=person.copy()
        excluded=human_exclusion_mask(person,3)
        y,x=np.mgrid[:11,:11]
        np.testing.assert_array_equal(excluded[1],(x-5)**2+(y-5)**2<=9)
        np.testing.assert_array_equal(excluded[2],x*x+y*y<=9)
        self.assertFalse(excluded[0].any())
        np.testing.assert_array_equal(person,original)
        np.testing.assert_array_equal(human_exclusion_mask(person,0),person)
        self.assertFalse(human_exclusion_mask(np.zeros_like(person),5).any())
        for radius in (-1,1.5,True):
            with self.assertRaises(ValueError):human_exclusion_mask(person,radius)

    @unittest.skipUnless(importlib.util.find_spec('open3d') is not None,'Optional Open3D runtime required')
    def test_margin_blocks_context_triangles_and_isolated_fallback_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,_=fixture(Path(tmp));camera=json.loads((bundle/'cameras.json').read_text())
            with np.load(bundle/'predictions.npz') as z:
                local=z['local_points'];poses=z['camera_poses'];k=z['intrinsics']
                transform=np.array(camera['world_transform'])
                points=z['points'] @ transform[:3,:3].T + transform[:3,3]
            shape=local.shape[:-1];layer=np.full(shape,5,np.uint8)
            layer[1,20,20]=1
            confidence=np.full(shape,.8)
            # An isolated valid point inside the margin and one outside it.
            confidence[:,16:25,16:25]=0
            confidence[1,20,22]=.8;confidence[1,17,17]=.8
            args=(points,np.full(local.shape,128,np.uint8),local,confidence,
                  np.ones(shape,bool),layer,np.arange(3),camera,poses,k,transform)
            baseline,_=build_display(*args,human_mask_radius=0)
            arrays,meta=build_display(*args,human_mask_radius=3)
            excluded=human_exclusion_mask(layer==1,3).ravel()
            inside=np.ravel_multi_index((1,20,22),shape)
            outside=np.ravel_multi_index((1,17,17),shape)
            self.assertIn(inside,baseline['context_point_indices'])
            self.assertNotIn(inside,arrays['context_point_indices'])
            self.assertIn(outside,arrays['context_point_indices'])
            self.assertFalse(arrays['context_eligible'][excluded].any())
            source=arrays['display_source_flat_indices'];source=source[source>=0]
            self.assertGreater(len(source),0)
            self.assertFalse(excluded[source].any())
            np.testing.assert_array_equal(arrays['background_valid'],baseline['background_valid'])
            self.assertEqual(meta['human_exclusion_pixels_per_frame'],[0,29,0])

    @unittest.skipUnless(importlib.util.find_spec('open3d') is not None,'Optional Open3D runtime required')
    def test_strict_threshold_masks_fusion_and_all_context_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,_=fixture(Path(tmp))
            camera=json.loads((bundle/'cameras.json').read_text())
            with np.load(bundle/'predictions.npz') as z:
                local=z['local_points'];poses=z['camera_poses'];k=z['intrinsics']
                transform=np.array(camera['world_transform'])
                points=z['points'] @ transform[:3,:3].T + transform[:3,3]
            shape=local.shape[:-1]
            conf=np.full(shape,.8)
            # Rejected pixels span both planes; dilation must not revive them.
            conf[:,:,:6]=.1;conf[:,:,6:12]=np.nan;conf[:,:,12:18]=np.inf
            conf[:,:,18:24]=.01
            accepted=np.isfinite(conf)&(conf>.1)
            arrays,meta=build_display(points,np.full(local.shape,128,np.uint8),local,conf,
                np.ones(shape,bool),np.zeros(shape,np.uint8),np.arange(3),camera,poses,k,transform)
            np.testing.assert_array_equal(arrays['fusion_eligible'],accepted.ravel())
            np.testing.assert_array_equal(arrays['context_eligible'],accepted.ravel())
            src=arrays['display_source_flat_indices'];src=src[src>=0]
            self.assertTrue(accepted.ravel()[src].all())
            self.assertTrue(accepted.ravel()[arrays['context_point_indices']].all())
            self.assertGreater(meta['core_faces'],0)
            # An entirely rejected image stack must produce no fused or context geometry.
            arrays,_=build_display(points,np.full(local.shape,128,np.uint8),local,np.full(shape,.1),
                np.ones(shape,bool),np.zeros(shape,np.uint8),np.arange(3),camera,poses,k,transform)
            self.assertEqual(len(arrays['display_vertices']),0)
            self.assertEqual(len(arrays['context_point_indices']),0)
            self.assertTrue(arrays['background_valid'].all())

    def test_context_discontinuity_does_not_bridge_depth_layers(self):
        y,x=np.mgrid[:8,:8];z=np.where(x<4,4.,9.)
        p=np.stack([x*.02,y*.02,z],-1)
        used,faces=context_triangles(p,z,np.ones((8,8),bool))
        self.assertGreater(len(faces),0)
        self.assertTrue(np.all(np.ptp(p.reshape(-1,3)[used][faces,2],axis=1)==0))

    @unittest.skipUnless(importlib.util.find_spec('open3d') is not None,'Optional Open3D runtime required')
    def test_embedded_geometry_filters_display_but_retains_raw_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,cache=fixture(root);out=root/'mesh'
            args=parser().parse_args(['--bundle',str(bundle),'--cameras',str(bundle/'cameras.json'),
                '--semantic-cache',str(cache),'--out',str(out)])
            meta=build(args)
            self.assertEqual(meta['geometry_representation']['processed_frame_indices'],[0,1,2])
            self.assertGreater(meta['geometry_representation']['core_faces'],0)
            with np.load(out/'layers.npz') as z:
                person=z['layer']==1;glass=z['layer']==2;low=z['confidence']<.1
                excluded=z['human_exclusion'];guard=excluded & ~person
                self.assertTrue(guard.any())
                self.assertTrue(z['background_valid'][guard].all())
                self.assertFalse(z['fusion_eligible'][excluded].any())
                self.assertFalse(z['context_eligible'][excluded].any())
                self.assertFalse(z['measurement_valid'][excluded].any())
                self.assertFalse(guard[z['faces']].any())
                self.assertEqual(int(person.sum()),3*8*8)
                self.assertFalse(z['fusion_eligible'][person|glass|low].any())
                self.assertTrue(z['background_valid'][low & ~person].all())
                self.assertFalse(z['measurement_valid'][low|person|glass].any())
                self.assertFalse((z['display_face_layer']==1).any())
                source=z['display_source_flat_indices'];src=source[source>=0]
                self.assertFalse(person[src].any());self.assertFalse(low[src].any())
                self.assertFalse(z['context_eligible'][low|person].any())
                self.assertFalse(low[z['context_point_indices']].any())
                self.assertTrue(np.isfinite(z['display_vertices']).all())
                world=z['vertices'];np.testing.assert_allclose(z['display_vertices'][source>=0],world[src])
                expected_bg=int(z['background_valid'].sum())
            import open3d as o3d
            cloud=o3d.io.read_point_cloud(str(out/'background_all_finite.ply'))
            self.assertEqual(len(cloud.points),expected_bg)
            self.assertGreater(np.asarray(cloud.points)[:,2].max(),8.)
            self.assertEqual(meta['geometry_representation']['human_mask_radius_pixels'],3)
            # Pipeline snapshot contract: only primary NPZ and manifest need to
            # be copied for display and measurements; no external display file.
            snap=root/'snapshot';snap.mkdir()
            for file in ('layers.npz','manifest.json'):shutil.copyfile(out/file,snap/file)
            shutil.rmtree(out)
            with np.load(snap/'layers.npz') as z:self.assertGreater(len(z['display_faces']),0)

    def test_wrong_camera_basis_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,_=fixture(Path(tmp));camera=json.loads((bundle/'cameras.json').read_text())
            camera['frames'][1]['c2w'][0][3]+=1
            with np.load(bundle/'predictions.npz') as z:
                with self.assertRaisesRegex(ValueError,'coordinate basis'):
                    validate_cameras(camera,np.arange(3),z['camera_poses'],z['intrinsics'],np.array(camera['world_transform']),(48,64))


if __name__=='__main__':unittest.main()
