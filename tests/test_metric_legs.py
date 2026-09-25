"""Meaningful geometry/identity/native-mask regressions."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'.agents/skills/pi3x-scene-reference/scripts'))
from drawing import Sheet
from measure import display_filter
from aha3d.motion.observations import merge_observations
from aha3d.motion.legs import build_guidance, compile_constraints, body_basis, compare_motions, compare_meshes
from aha3d.motion.reference import project
from test_reference_motion import baseline


def fixture():
    points=np.array([[-.15,0,4],[.15,0,4],[-.15,.4,4],[-.15,.8,4],[.15,.35,3.8],[.15,.7,3.6]])
    names=['left-hip','right-hip','left-knee','left-ankle','right-knee','right-ankle']
    K=np.array([[300,0,320],[0,300,240],[0,0,1.]])
    # Camera Y down to world Z up, proper rotation.
    pose=np.eye(4);pose[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
    obs=dict(schema_version=1,person_id='test',coordinate_convention='opencv_camera_metres_with_translation',
             processed_size_wh=[640,480],keypoint_names=names,frames=[dict(source_frame=60,timestamp_seconds=1.001,
             keypoints_camera_m=points.tolist(),keypoints_2d=project(points,K).tolist())])
    cams=dict(processed_size_wh=[640,480],frames=[dict(source_frame=60,timestamp_seconds=1.001,c2w=pose.tolist(),intrinsics=K.tolist())])
    sel=dict(schema_version=1,person_id='test',native_frames=90,native_fps=30,world_to_kimodo_rotation=[[1,0,0],[0,0,1],[0,-1,0]],
             events=[dict(source_frame=60,side='right',reviewed=True,visibility='visible',review_note='Analytic visible fixture')])
    return obs,cams,sel


class MetricLegs(unittest.TestCase):
    def test_rgb_nearest_depth_is_independent_of_input_order(self):
        cloud=np.array([[.233,.277,.2],[.233,.277,1.5]])
        colors=np.array([[255,0,0],[0,0,255]],dtype=np.uint8)
        a=Sheet('test',[0,1],[[0,1],[0,1]],cloud,1,colors=colors)
        b=Sheet('test',[0,1],[[0,1],[0,1]],cloud[::-1],1,colors=colors[::-1])
        x,y=np.rint(a.map(cloud)[0]).astype(int)
        self.assertEqual(a.im.getpixel((x,y)),(0,0,255))
        self.assertEqual(a.im.getpixel((x,y)),b.im.getpixel((x,y)))

    def test_display_slice_respects_uniform_calibration_without_mutation(self):
        cloud=np.array([[0,0,.5],[0,0,1.5],[0,0,3.]])*2; original=cloud.copy()
        np.testing.assert_array_equal(display_filter(cloud,{'clip_xyz_m':{'z':[.1,1.6]}},2),[True,True,False])
        np.testing.assert_array_equal(cloud,original)
        for cfg in ({'a':[0,1]},{'z':[2,1]},{'x':[0,float('nan')]}):
            with self.assertRaises(ValueError):display_filter(cloud,{'clip_xyz_m':cfg},1)

    def test_legacy_merge_requires_identity_and_rejects_conflicts(self):
        obs,_,_=fixture()
        obs.update(source_sha256='s',pi3x_inputs_sha256='i',pi3x_cameras_sha256='c')
        extra=deepcopy(obs);extra['frames'][0]['source_frame']=61
        with self.assertRaises(ValueError):merge_observations([obs,extra])
        self.assertEqual(len(merge_observations([obs,extra],'test')['frames']),2)
        for field,value in [('person_id','another'),('pi3x_cameras_sha256','changed'),('checkpoint_sha256','changed')]:
            bad=deepcopy(extra);bad[field]=value
            with self.assertRaises(ValueError):merge_observations([obs,bad],'test')
        with self.assertRaises(ValueError):merge_observations([obs,obs],'test')

    def test_camera_translation_and_pts_contract(self):
        obs,cams,sel=fixture();keys=build_guidance(obs,cams,sel)
        self.assertEqual(keys[0]['frame'],30)
        cams['frames'][0]['c2w'][0][3]=100
        moved=build_guidance(obs,cams,sel)
        np.testing.assert_allclose(keys[0]['thigh_direction'],moved[0]['thigh_direction'],atol=1e-12)
        for mutation in ('occluded','unreviewed','identity','projection','timestamp'):
            o,c,s=fixture()
            if mutation=='occluded':s['events'][0]['visibility']='occluded'
            if mutation=='unreviewed':s['events'][0]['reviewed']=False
            if mutation=='identity':s['person_id']='other'
            if mutation=='projection':o['frames'][0]['keypoints_2d'][4][0]+=20
            if mutation=='timestamp':c['frames'][0]['timestamp_seconds']+=.1
            with self.assertRaises(ValueError):build_guidance(o,c,s)

    def test_native_foot_target_keeps_root_heading_and_ankle_rotation(self):
        from kimodo.constraints import load_constraints_lst
        from kimodo.skeleton import SMPLXSkeleton22
        obs,cams,sel=fixture();keys=build_guidance(obs,cams,sel);base=baseline()
        original=deepcopy(base)
        values,report=compile_constraints(base,keys,90)
        self.assertEqual(values[0]['type'],'right-foot')
        foot=load_constraints_lst(values,SMPLXSkeleton22().cpu())[0]
        np.testing.assert_allclose(foot.global_joints_rots.numpy()[0,8],base['global_rot_mats'][30,8],atol=1e-5)
        np.testing.assert_allclose(report[0]['root_position_m'],base['root_positions'][30])
        np.testing.assert_allclose(foot.global_joints_positions.numpy()[0,0],base['posed_joints'][30,0],atol=1e-5)
        for name in base:np.testing.assert_array_equal(base[name],original[name])
        badroute=[dict(type='root2d',frame_indices=[30],smooth_root_2d=[[99,99]])]
        with self.assertRaises(ValueError):compile_constraints(base,keys,90,badroute)

    def test_comparison_withholds_entire_keyed_times(self):
        obs,cams,sel=fixture();key=build_guidance(obs,cams,sel)[0];base=baseline()['posed_joints']
        withheld={**key,'source_frame':70,'frame':35}
        result=compare_motions(base,base,[key,{**key,'side':'left'},withheld],[key])
        self.assertEqual(result['withheld_events'],1)
        self.assertEqual(result['baseline']['withheld'],result['candidate']['withheld'])
        with self.assertRaises(ValueError):compare_motions(base,base,[key],[key])

    def test_mesh_comparison_exposes_vertical_drop_with_shared_floor(self):
        left=np.array([[-.2+x,y,z] for x in [-.025,.025] for y in [-.04,.04] for z in [0,.01,.02]])
        right=left+np.array([.4,0,0]);v=np.tile(np.concatenate([left,right])[None],(3,1,1))
        j=np.zeros((3,22,3));j[:,7]=[-.2,0,.08];j[:,8]=[.2,0,.08]
        candidate=v-np.array([0,0,.02])
        result=compare_meshes(v,candidate,j,30,scale=.73)
        self.assertEqual(result['baseline']['penetrating_frames_5mm'],0)
        self.assertEqual(result['candidate']['penetrating_frames_5mm'],3)
        self.assertAlmostEqual(result['candidate']['min_vertex_clearance_m'],-.0146)

if __name__=='__main__':unittest.main()
