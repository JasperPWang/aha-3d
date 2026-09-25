import unittest
import tempfile
import subprocess
import sys
from pathlib import Path
import numpy as np
from tools.gvhmr.trajectory_methods import fit_variants,project,NAMES,cubic_basis,bounded_ball

class MethodsTests(unittest.TestCase):
    def fixture(self):
        t=np.linspace(0,3,31);j=np.zeros((31,22,3));j[:,:,2]=4
        j[:,:,0]=np.linspace(-.4,.4,22);j[:,:,1]=np.linspace(-.7,.7,22)
        C=np.repeat(np.eye(4)[None],31,axis=0);K=np.repeat(np.array([[500.,0,320],[0,500,240],[0,0,1]])[None],31,axis=0)
        ids=np.arange(0,31,5);uv,_=project(j[ids][:,[1,2,4,5,7,8,16,17,18,19,20,21]]+np.array([.12,0,0]),C[ids],K[ids])
        obs=dict(time_seconds=t[ids],uv=uv,valid=np.ones((len(ids),12),bool),joint_names=NAMES)
        return j,j[:,:8].copy(),t,C,K,obs
    def test_cli_rejects_missing_or_same_length_shifted_timestamps(self):
        j,v,t,C,K,obs=self.fixture()
        module=Path(__file__).resolve().parents[1]/'tools/gvhmr/trajectory_methods.py'
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);np.savez(d/'cache.npz',joints=j,vertices=v,time_seconds=t)
            np.savez(d/'observations.npz',**obs)
            for source in ('Contact','Camera'):
                for supplied in (None,t+.01):
                    np.savez(d/'camera.npz',c2w=C,K=K,**({'time_seconds':t} if source!='Camera' else {} if supplied is None else {'time_seconds':supplied}))
                    np.savez(d/'contacts.npz',observed_contact=np.ones((len(t),2),bool),**({'time_seconds':t} if source!='Contact' else {} if supplied is None else {'time_seconds':supplied}))
                    result=subprocess.run([sys.executable,str(module),'--cache',str(d/'cache.npz'),'--camera',str(d/'camera.npz'),'--observations',str(d/'observations.npz'),'--contacts',str(d/'contacts.npz'),'--output',str(d/'output')],capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn(source+'/cache time_seconds missing or mismatched',result.stderr)
                    self.assertFalse((d/'output').exists())
    def test_convex_cubic_realized_bounds(self):
        t=np.linspace(0,10,1001);B,k=cubic_basis(t,1.5)
        controls=bounded_ball(np.random.default_rng(2).normal(size=(B.shape[1],3))*100,.3)
        self.assertLessEqual(np.linalg.norm(B@controls,axis=1).max(),.3+1e-12)
        np.testing.assert_allclose(B.sum(1),1)
        np.testing.assert_allclose(bounded_ball(np.zeros((2,3)),.3),0)
    def test_variants_improve_training_preserve_inputs_and_bounds(self):
        args=self.fixture();original=args[0].copy()
        r=fit_variants(*args,config={'max_nfev':45})
        self.assertEqual(list(r),['baseline','shared_xyz','affine_drift','spline','spline_contact'])
        np.testing.assert_array_equal(args[0],original);np.testing.assert_array_equal(r['baseline']['offsets'],0)
        for name,item in r.items():
            self.assertEqual(item['offsets'].shape,(31,3))
            self.assertLessEqual(np.linalg.norm(item['shared_offset'][:2]),.5+1e-10)
            self.assertLessEqual(abs(item['shared_offset'][2]),.1+1e-10)
            self.assertLessEqual(np.linalg.norm(item['deformation'],axis=1).max(),.3+1e-10)
            self.assertFalse(item['report']['accepted'])
        self.assertLess(r['shared_xyz']['report']['training_uv_after_px']['median'],r['baseline']['report']['training_uv_before_px']['median'])
    def test_heldout_uv_does_not_change_fits(self):
        args=self.fixture();a=fit_variants(*args,config={'max_nfev':25})
        args[-1]['uv'][1::2]+=400
        b=fit_variants(*args,config={'max_nfev':25})
        for name in a:np.testing.assert_array_equal(a[name]['offsets'],b[name]['offsets'])
        self.assertGreater(b['shared_xyz']['report']['heldout_uv_after_px']['median'],a['shared_xyz']['report']['heldout_uv_after_px']['median'])
    def test_common_floor_penalty_reduces_penetration_all_fit_arms(self):
        args=self.fixture();args[1][:,:,2]=-.05
        result=fit_variants(*args,config={'max_nfev':40})
        for name,item in result.items():
            if name!='baseline':self.assertLess(item['report']['penetration_after_m']['max'],.02)
    def test_empty_observed_contact_is_explicitly_unverified(self):
        args=self.fixture()
        result=fit_variants(*args,config={'max_nfev':15},observed_contact=np.zeros((31,2),bool))
        self.assertEqual(result['spline_contact']['report']['contact_status'],'unverified_empty_cohort')
        self.assertEqual(result['spline_contact']['report']['contact_speed_after_mps']['n'],0)
    def test_reviewed_weak3d_exclusions_are_honored(self):
        args=self.fixture();S=len(args[-1]['time_seconds'])
        args[-1].update(sam_camera_joints=np.ones((S,70,3)),sam_camera_opencv_confirmed=True,weak3d_valid=np.zeros(S,bool))
        self.assertNotIn('spline_contact_weak3d',fit_variants(*args,config={'max_nfev':15}))
    def test_wrong_anatomy_and_foreign_timestamps_rejected(self):
        args=self.fixture();args[-1]['joint_names']=NAMES[::-1]
        with self.assertRaises(ValueError):fit_variants(*args)
        args=self.fixture();args[-1]['time_seconds'][-1]=10
        with self.assertRaises(ValueError):fit_variants(*args)
    def test_fixed_contact_cohort_does_not_drop_candidate_motion(self):
        args=self.fixture();feet=np.stack([args[0][:,7],args[0][:,8]],1);contact=np.ones((31,2),bool)
        r=fit_variants(*args,config={'max_nfev':25},contact_centers=feet,observed_contact=contact)
        for item in r.values():
            self.assertEqual(item['report']['contact_edge_samples'],60)
            self.assertEqual(item['report']['contact_speed_after_mps']['n'],60)
    def test_weak3d_requires_confirmation_and_heldout3d_does_not_fit(self):
        args=self.fixture();S=len(args[-1]['time_seconds']);sam=np.zeros((S,70,3));sam[:,:,2]=4
        args[-1]['sam_camera_joints']=sam
        self.assertNotIn('spline_contact_weak3d',fit_variants(*args,config={'max_nfev':15}))
        args[-1]['sam_camera_opencv_confirmed']=True
        args[-1]['weak3d_valid']=np.ones(S,bool)
        a=fit_variants(*args,config={'max_nfev':15})
        args[-1]['sam_camera_joints'][1::2]+=10
        b=fit_variants(*args,config={'max_nfev':15})
        np.testing.assert_array_equal(a['spline_contact_weak3d']['offsets'],b['spline_contact_weak3d']['offsets'])

if __name__=='__main__':unittest.main()
