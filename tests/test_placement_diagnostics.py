"""Synthetic independent projection checks at different cadences and body placements."""
import unittest
import json
import tempfile
from pathlib import Path
import numpy as np
from tools.gvhmr.placement_diagnostics import diagnose_arrays,observed_samples,project,SMPL,COCO,window_masks,evaluate_manifest,digest


def scene(fps=25,seconds=6,offset=0.):
    t=np.arange(round(fps*seconds))/fps;n=len(t)
    j=np.zeros((n,22,3));j[:,:,0]=offset
    pairs=[(1,2,.12,.8),(4,5,.12,.4),(7,8,.12,0.),(16,17,.25,1.4),(18,19,.35,1.05),(20,21,.4,.85)]
    for left,right,x,z in pairs:j[:,left]=[offset-x,0,z];j[:,right]=[offset+x,0,z]
    camera=np.tile(np.eye(4),(n,1,1));camera[:,:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]];camera[:,:3,3]=[0,-3,1.]
    K=np.tile([[300.,0,320],[0,300,240],[0,0,1]],(n,1,1))
    uv,_=project(j[:,SMPL],camera,K);kp=np.zeros((n,17,3));kp[:,COCO,:2]=uv;kp[:,COCO,2]=.9
    return j,t,camera,K,kp


class PlacementChecks(unittest.TestCase):
    def test_correct_projection_passes_multiple_cadences_and_placements(self):
        for fps,offset in [(12.,-.4),(25.,0.),(30.,.3)]:
            with self.subTest(fps=fps):
                j,t,C,K,kp=scene(fps,2.16,offset)
                r=diagnose_arrays(j,t,C,K,kp,t,[640,480])
                self.assertTrue(r['accepted']);self.assertEqual(r['classification'],'observed_consistent')

    def test_constant_offset_is_only_a_diagnostic_candidate(self):
        j,t,C,K,kp=scene();j[:,:,0]+=.8;original=j.copy()
        r=diagnose_arrays(j,t,C,K,kp,t,[640,480])
        self.assertFalse(r['accepted']);self.assertEqual(r['classification'],'rigid_placement_candidate')
        np.testing.assert_allclose(r['constant_xy_probe']['xy_delta_m'],[-.8,0],atol=1e-5)
        np.testing.assert_array_equal(j,original)

    def test_time_varying_drift_is_not_hidden_by_all_clip_fit(self):
        j,t,C,K,kp=scene();j[:,:,0]+=np.where(t<2,-.8,np.where(t<4,0.,.8))[:,None]
        r=diagnose_arrays(j,t,C,K,kp,t,[640,480])
        self.assertFalse(r['accepted']);self.assertEqual(r['classification'],'temporal_mismatch')
        self.assertGreater(r['window_probe_disagreement_m'],1.)

    def test_occluded_visible_window_is_unverified(self):
        j,t,C,K,kp=scene();kp[(t>=2)&(t<4),:,2]=0.
        r=diagnose_arrays(j,t,C,K,kp,t,[640,480])
        self.assertFalse(r['accepted']);self.assertEqual(r['windows'][1]['status'],'unverified')

    def test_explicitly_excluded_window_is_reported(self):
        j,t,C,K,kp=scene();valid=~((t>=2)&(t<4))
        r=diagnose_arrays(j,t,C,K,kp,t,[640,480],valid)
        self.assertTrue(r['accepted']);self.assertEqual(r['windows'][1]['status'],'excluded')

    def test_low_confidence_and_out_of_image_points_are_not_observations(self):
        j,t,C,K,kp=scene();kp[:,15,2]=.1;kp[:,16,0]=-1
        _,mask,_=observed_samples(kp,t,t,[640,480])
        self.assertFalse(mask[:,4:6].any());self.assertTrue(mask[:,:4].all())

    def test_unmatched_time_is_rejected(self):
        j,t,C,K,kp=scene()
        with self.assertRaises(ValueError):observed_samples(kp,t,t+.5,[640,480])

    def test_missing_fullbody_extent_stays_unknown(self):
        j,t,C,K,kp=scene();kp[:,[11,12,15,16],2]=0.
        r=diagnose_arrays(j,t,C,K,kp,t,[640,480])
        self.assertEqual(r['extent_diagnostics']['legs']['frames'],0)
        self.assertEqual(r['extent_diagnostics']['legs']['ratio_p10_p50_p90'],[])

class ManifestChecks(unittest.TestCase):
    def test_arbitrary_id_auto_observations_and_selected_refinement_cache(self):
        import torch
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'preprocess').mkdir()
            j,t,C,K,kp=scene(12,2.2)
            np.savez(base/'motion.npz',frame_times_seconds=t)
            np.savez(base/'body.npz',joints=j,time_seconds=t)
            np.savez(base/'camera.npz',c2w=C,K=K,time_seconds=t,image_size=[640,480])
            (base/'alignment.json').write_text(json.dumps({'body_scale':1.}))
            torch.save(torch.tensor(kp),base/'preprocess/vitpose.pt')
            m={'actors':[{'id':'visitor-alpha','cache':'body.npz','motion':'motion.npz','alignment':'alignment.json'}]}
            (base/'manifest.json').write_text(json.dumps(m))
            report=evaluate_manifest(base/'manifest.json',base/'camera.npz')
            self.assertTrue(report['accepted']);self.assertEqual(report['actors'][0]['id'],'visitor-alpha')
            self.assertEqual(report['actors'][0]['hashes']['pose_confidence'],digest(base/'preprocess/vitpose.pt'))
            refined=base/'refined'/'visitor-alpha';refined.mkdir(parents=True)
            changed=j.copy();changed[:,:,0]+=.8
            np.savez(refined/'body_room.npz',joints=changed,time_seconds=t)
            report=evaluate_manifest(base/'manifest.json',base/'camera.npz',base/'refined')
            self.assertFalse(report['accepted']);self.assertEqual(report['actors'][0]['hashes']['cache'],digest(refined/'body_room.npz'))
            (base/'preprocess/vitpose.pt').unlink()
            report=evaluate_manifest(base/'manifest.json',base/'camera.npz')
            self.assertEqual(report['status'],'unverified')

    def test_invalid_camera_contracts_are_rejected(self):
        j,t,C,K,kp=scene()
        for which in ('raster','pose','intrinsics'):
            with self.subTest(which=which):
                c=C.copy();k=K.copy();size=[640,480]
                if which=='raster':size=[float('nan'),480]
                if which=='pose':c[:,3,0]=1.
                if which=='intrinsics':k[:,0,0]=-1.
                with self.assertRaises(ValueError):diagnose_arrays(j,t,c,k,kp,t,size)

    def test_one_retained_frame_does_not_validate_a_window(self):
        j,t,C,K,kp=scene();valid=np.zeros(len(t),bool);valid[0]=True
        report=diagnose_arrays(j,t,C,K,kp,t,[640,480],valid)
        self.assertFalse(report['accepted']);self.assertEqual(report['windows'][0]['status'],'unverified')
        self.assertEqual(report['windows'][0]['excluded_frames'],49)

if __name__=='__main__':unittest.main()
