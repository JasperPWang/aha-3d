"""Dense Pi3X persistence and camera/depth coordinate consistency."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

p=Path(__file__).resolve().parents[1]/'tools/gvhmr/world_backend/experiments/postopt_ab/run_pi3x_dense.py'
s=importlib.util.spec_from_file_location('dense_pi3x_export',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class DenseExport(unittest.TestCase):
    def test_dense_camera_replaces_every_sparse_representation(self):
        poses=np.tile(np.eye(4),(3,1,1));poses[:,:3,:3]=Rotation.from_euler('y',np.array([0,10,30])[:,None],degrees=True).as_matrix();poses[:,0,3]=[0,1,3]
        k=np.tile(np.diag([100.,100.,1.]),(3,1,1))
        result=m.dense_track_payload(dict(time_seconds=np.arange(3)/30,slam=np.zeros((3,7)),cam_angvel_6d=np.zeros((3,6))),poses,k,[8,6])
        np.testing.assert_allclose(Rotation.from_quat(result['slam'][:,3:]).as_matrix(),poses[:,:3,:3],atol=1e-14)
        np.testing.assert_array_equal(result['slam'][:,:3],poses[:,:3,3])
        np.testing.assert_allclose(result['relative_rotation'],Rotation.from_euler('y',np.array([-10,-20])[:,None],degrees=True).as_matrix(),atol=1e-14)
        np.testing.assert_array_equal(result['cam_angvel_6d'][-1],result['cam_angvel_6d'][-2])
        self.assertGreater(np.abs(result['cam_angvel_6d']).sum(),0)
        with self.assertRaises(ValueError):m.dense_track_payload(dict(time_seconds=np.arange(2)),poses,k,[8,6])

    def test_saved_depth_uses_same_scale_and_frame_as_aligned_camera(self):
        lp=np.array([[[[1.,2.,4.],[2.,1.,5.]]],[[[2.,3.,6.],[3.,2.,7.]]]],dtype=np.float32)
        raw_camera=np.tile(np.eye(4),(2,1,1));raw_camera[:,0,3]=[1,2]
        r=Rotation.from_euler('z',30,degrees=True).as_matrix();t=np.array([10.,20.,30.]);scale=1.2
        aligned=raw_camera.copy();aligned[:,:3,:3]=r;aligned[:,:3,3]=scale*raw_camera[:,:3,3]@r.T+t
        predictions=dict(local_points=lp,camera_poses=raw_camera,conf=np.ones((2,1,2,1),dtype=np.float32),metric=np.asarray(2.))
        k=np.tile(np.eye(3),(2,1,1))
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'predictions'
            m.save_dense_predictions(folder,predictions,intrinsics=k,non_edge=np.ones((2,1,2),bool),c2w=aligned,scale=scale,rotation=r,translation=t,times=np.arange(2)/30,image_size=[4,2])
            z=np.load(folder/'depth_m.npy',mmap_mode='r');raw=np.load(folder/'local_points.npy',mmap_mode='r')
            np.testing.assert_array_equal(raw,lp)
            np.testing.assert_allclose(z,lp[...,2]*scale)
            raw_world=lp+raw_camera[:,:3,3][:,None,None]
            aligned_world=(lp*(z/lp[...,2])[...,None])@r.T+aligned[:,:3,3][:,None,None]
            np.testing.assert_allclose(aligned_world,scale*raw_world@r.T+t,atol=1e-6)
            np.testing.assert_array_equal(np.load(folder/'source_frame_indices.npy'),[0,1])
            self.assertTrue((folder/'metric.npy').is_file())

if __name__=='__main__':unittest.main()
