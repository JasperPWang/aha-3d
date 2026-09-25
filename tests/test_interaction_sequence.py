import unittest
import numpy as np
from aha3d.motion.interaction import compile_plan, KIMODO_TO_ROOM


class InteractionPlanTests(unittest.TestCase):
    def test_sitting_height_reaches_decoded_pelvis_without_other_joint_keys(self):
        import torch
        from kimodo.skeleton import SMPLXSkeleton22
        from kimodo.motion_rep.conditioning import build_condition_dicts
        from kimodo.motion_rep.reps.kimodo_motionrep import KimodoMotionRep
        from aha3d.motion.interaction import pelvis_position_constraint
        rep=KimodoMotionRep(SMPLXSkeleton22(),30)
        ids=torch.tensor([180,255]);xz=torch.tensor([[1.2,.5],[1.2,.5]])
        heights=torch.tensor([.69,.69])
        indices,data=build_condition_dicts([pelvis_position_constraint(ids,xz,heights)])
        obs,mask=rep.create_conditions(indices,data,300,False,'cpu')
        decoded=rep.inverse(obs[None],False,posed_joints_from='positions')
        np.testing.assert_allclose(decoded['root_positions'][0,ids,1],heights)
        np.testing.assert_allclose(decoded['root_positions'][0,ids][:,[0,2]],xz)
        local_mask=mask[:,rep.slice_dict['local_joints_positions']].reshape(300,22,3)
        self.assertFalse(local_mask[:,1:].any())
        self.assertEqual(int(local_mask.sum()),6)
        self.assertFalse(mask[:,rep.slice_dict['global_rot_data']].any())
        self.assertFalse(mask[:180].any())

    def test_optional_contacts_do_not_create_fake_constraints(self):
        p=self.plan()
        for key in ('hand_contact_seconds','hand_surface_point','seat_point'):
            p.pop(key)
        c=compile_plan(p)
        self.assertFalse(c['hand_on'].any())
        self.assertEqual(c['hand'].shape,(120,3))
        p['root_hand_coupling']={'root_from_hand_xy':[0,0]}
        with self.assertRaises(ValueError):compile_plan(p)

    def test_seat_releases_for_standup(self):
        from aha3d.motion.interaction import contact_envelope
        t=np.arange(390)/30
        strength=contact_envelope(t,[6,9],ramp=.5,lead=.5)
        self.assertTrue(np.all(strength[t>=9]==0))
        self.assertTrue(np.all(strength[(t>=6)&(t<=8.5)]==1))
        np.testing.assert_array_equal(contact_envelope(t,None),np.zeros(len(t)))
        with self.assertRaises(ValueError):contact_envelope(t,[9,6])

    def test_hand_can_slide_on_stationary_object_without_moving_root(self):
        p=self.plan();p['object_translation_keys']=[[0,0,0,0],[4,0,0,0]]
        p['root_xy_keys']=[[0,0,0],[4,0,0]]
        p['hand_surface_keys']=[[0,.4,.1,1],[1,.4,.1,1],[3,.4,.4,1],[4,.4,.4,1]]
        c=compile_plan(p)
        np.testing.assert_array_equal(c['root_xy'],np.zeros((120,2)))
        self.assertAlmostEqual(c['hand'][90,1]-c['hand'][30,1],.3)

    def test_historical_control_does_not_silently_add_boundary_conditioning(self):
        from aha3d.motion.interaction import constraint_schedule
        p=self.plan();p.update(generation_profile='1c9de0b_control',root_path_sample_stride=10,heading_sample_stride=10)
        schedule=constraint_schedule(p)
        expected=np.r_[np.arange(0,120,10),119]
        np.testing.assert_array_equal(schedule['root_frames'],expected)
        np.testing.assert_array_equal(schedule['heading_frames'],expected)
        p['segment_endpoint_keys']=True
        self.assertIn(59,constraint_schedule(p)['root_frames'])

    def test_splitting_equivalent_foot_terms_preserves_total_weight(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(1,3)
            def fk(self,r,p):return r,p[:,None],None
        class Skin:
            def skin(self,r,j):return j.expand(-1,3,-1)
        local=np.tile(np.eye(3),(4,1,1,1)).astype(np.float32)
        root=np.tile([0,.1,0],(4,1)).astype(np.float32)
        def fit(parts,scale):
            cd=dict(hand_target=np.tile([.1,.2,0],(4,1)),hand_strength=np.ones(4),
                    foot_parts=parts,foot_loss_scale=scale,foot_strength=np.ones((4,len(parts))),
                    foot_anchors={k:np.zeros((4,1,3)) for k in parts},floor_y=0.,fps=30)
            return optimize_motion(Skeleton(),local,root,iterations=10,contact_skin=Skin(),
                patch_layout=dict(palm=[0],**{k:[1] for k in parts}),contact_data=cd)[1]
        np.testing.assert_allclose(fit(('left','right'),1.),
                                   fit(('lh','lt','rh','rt'),.5),atol=1e-6)

    def test_each_native_segment_has_start_and_end_route_keys(self):
        from aha3d.motion.interaction import constraint_schedule
        p=self.plan();p['root_path_sample_stride']=10;p['heading_sample_stride']=10
        schedule=constraint_schedule(p)
        for field in ('root_frames','heading_frames'):
            self.assertTrue({0,59,60,119}.issubset(set(schedule[field])))

    def test_floor_exclusion_is_independent_of_support_labels_and_patch_weight(self):
        import torch
        from aha3d.motion.interaction import optimize_motion, FOOT_PATCHES
        class Skeleton:
            neutral_joints=torch.zeros(1,3)
            def fk(self,r,p):return r,p[:,None],None
        class Skin:
            def skin(self,r,j):return j.expand(-1,3,-1)
        local=np.tile(np.eye(3),(4,1,1,1)).astype(np.float32)
        root=np.tile([0,-.1,0],(4,1)).astype(np.float32)
        layout=dict(palm=[0],left_sole=[1],right_sole=[2],**{k:[1] for k in FOOT_PATCHES})
        cd=dict(hand_target=np.tile([0,-.2,0],(4,1)),hand_strength=np.ones(4),
                foot_strength=np.zeros((4,4)),foot_anchors={k:np.zeros((4,1,3)) for k in FOOT_PATCHES},
                floor_parts=('left_sole','right_sole'),floor_y=0.,fps=30)
        def fit(scale):
            return optimize_motion(Skeleton(),local,root,iterations=12,contact_skin=Skin(),
                patch_layout=layout,contact_data=dict(cd,foot_loss_scale=scale))[1]
        a,b=fit(.01),fit(1.)
        np.testing.assert_allclose(a,b,atol=1e-7)
        self.assertGreater(float(a[:,1].mean()),-.1)

    def test_generation_frame_translates_all_targets_and_restores_once(self):
        from aha3d.motion.interaction import generation_origin, room_to_generation, restore_scene_horizontal
        origin=generation_origin([.32,.05],.029)
        scene=np.array([[.32,.05,1.02],[.81,1.13,1.09]])
        canonical=room_to_generation(scene,origin)
        np.testing.assert_allclose(canonical[0,[0,2]],0,atol=1e-12)
        self.assertAlmostEqual(canonical[0,1],.991)
        rotations=np.tile(np.eye(3),(2,1,1));contacts=np.ones((2,4),bool)
        motion=dict(root_positions=canonical,posed_joints=canonical[:,None],
                    smooth_root_pos=canonical,local_rot_mats=rotations,foot_contacts=contacts)
        restored=restore_scene_horizontal(motion,origin)
        for key in ('root_positions','smooth_root_pos'):
            np.testing.assert_allclose((restored[key]+[0,.029,0])@KIMODO_TO_ROOM.T,scene)
        np.testing.assert_allclose(restored['posed_joints'][:,0],restored['root_positions'])
        np.testing.assert_array_equal(restored['local_rot_mats'],rotations)
        np.testing.assert_array_equal(restored['foot_contacts'],contacts)
        # Translating the entire room must not change model-space inputs.
        delta=np.array([4.,-2.,.3])
        moved=room_to_generation(scene+delta,generation_origin(scene[0,:2]+delta[:2],.029+delta[2]))
        np.testing.assert_allclose(moved,canonical,atol=1e-12)

    def test_single_heel_or_toe_support_is_not_discarded(self):
        from aha3d.motion.interaction import foot_contact_strength
        contacts=np.array([[True,False,False,True],[False,True,True,False],[True,True,False,False]])
        np.testing.assert_array_equal(foot_contact_strength(contacts),contacts.astype(float))
        with self.assertRaises(ValueError):foot_contact_strength(np.ones((3,2)))

    def test_sole_partition_follows_foot_axis_not_world_heading(self):
        from aha3d.motion.interaction import split_sole_patch
        rest=np.array([[0,0,-.06],[.01,0,.03],[0,0,.14],[0,0,.22]])
        ids=np.arange(4);ankle=np.array([0,.08,0]);toe=np.array([0,.03,.16])
        heel,forefoot=split_sole_patch(rest,ids,ankle,toe)
        np.testing.assert_array_equal(heel,[0,1]);np.testing.assert_array_equal(forefoot,[2,3])
        rotation=np.array([[0,0,1],[0,1,0],[-1,0,0]])
        moved=split_sole_patch(rest@rotation.T,ids,ankle@rotation.T,toe@rotation.T)
        np.testing.assert_array_equal(moved[0],heel);np.testing.assert_array_equal(moved[1],forefoot)

    def plan(self):
        return dict(fps=30,segments=[dict(seconds=2,prompt='walk'),dict(seconds=2,prompt='pull')],
            root_xy_keys=[[0,0,0],[4,1,0]],heading_keys=[[0,0],[4,0]],
            object_translation_keys=[[0,0,0,0],[1,0,0,0],[3,1,0,0],[4,1,0,0]],
            hand_contact_seconds=[1,3],hand_surface_point=[.4,.1,1],seat_point=[.3,0,.5])
    def test_moving_contact_is_object_relative_on_complete_timeline(self):
        p=self.plan();c=compile_plan(p)
        self.assertEqual(c['frames'],[60,60]);self.assertEqual(len(c['times']),120)
        np.testing.assert_allclose(c['hand']-c['object_translation'],np.tile(p['hand_surface_point'],(120,1)))
        np.testing.assert_array_equal(np.flatnonzero(c['hand_on'])[[0,-1]],[30,90])
        np.testing.assert_allclose(c['object_translation'][90:],np.tile([1,0,0],(30,1)))
    def test_coordinate_transform_preserves_distance_and_upright(self):
        np.testing.assert_array_equal(KIMODO_TO_ROOM@np.array([0,1,0]),[0,0,1])
        np.testing.assert_array_equal(KIMODO_TO_ROOM.T@KIMODO_TO_ROOM,np.eye(3))
        self.assertAlmostEqual(np.linalg.det(KIMODO_TO_ROOM),1)

    def test_pull_root_uses_hand_clock_and_fixed_offset(self):
        p=self.plan();old=compile_plan(p)
        p['root_hand_coupling']=dict(root_from_hand_xy=[-.35,.1],transition_seconds=.2)
        c=compile_plan(p);on=c['hand_on']
        np.testing.assert_allclose(c['root_xy'][on]-c['hand'][on,:2],np.tile([-.35,.1],(on.sum(),1)),atol=1e-12)
        np.testing.assert_allclose(np.diff(c['root_xy'][on],axis=0),np.diff(c['object_translation'][on,:2],axis=0),atol=1e-12)
        np.testing.assert_array_equal(c['root_xy'][c['root_binding']==0],old['root_xy'][c['root_binding']==0])
        self.assertTrue(np.all(c['root_binding'][on]==1))

    def test_coupled_root_cannot_drift_under_conflicting_contact_targets(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(2,3)
            def fk(self,r,p):return r,p[:,None].expand(-1,2,-1),None
        local=np.tile(np.eye(3),(4,2,1,1)).astype(np.float32)
        route=np.array([[0,0],[.1,0],[.2,0],[.3,0]],np.float32)
        _,root,_=optimize_motion(Skeleton(),local,np.zeros((4,3)),iterations=8,
            root_trajectory=dict(positions=route,binding=np.ones(4)),
            joint_targets=(np.tile([4.,1.,2.],(4,2,1)),np.ones((4,2))))
        np.testing.assert_array_equal(root[:,[0,2]],route)
        self.assertGreater(float(root[:,1].mean()),0)
    def test_soft_root_prior_limits_drift_but_allows_contact_tradeoff(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(2,3)
            def fk(self,r,p):return r,p[:,None].expand(-1,2,-1),None
        local=np.tile(np.eye(3),(4,2,1,1)).astype(np.float32)
        args=dict(joint_targets=(np.tile([.2,0,0],(4,2,1)),np.ones((4,2))),iterations=80)
        _,free,_=optimize_motion(Skeleton(),local,np.zeros((4,3)),**args)
        _,soft,_=optimize_motion(Skeleton(),local,np.zeros((4,3)),root_path_prior=dict(positions=np.zeros((4,2)),strength=np.ones(4),weight=200.),**args)
        self.assertGreater(float(soft[:,0].mean()),.04)
        self.assertLess(float(soft[:,0].mean()),float(free[:,0].mean())*.75)

    def test_minimal_schedule_leaves_walking_height_free(self):
        from aha3d.motion.interaction import constraint_schedule
        p=self.plan();p['pelvis_height_targets']=[[3,.61],[4,.61]]
        schedule=constraint_schedule(p)
        np.testing.assert_array_equal(schedule['height_frames'],[90,119])
        np.testing.assert_array_equal(schedule['root_frames'],[0,59,60,119])
        p['root_path_sample_stride']=10
        sampled=constraint_schedule(p)
        self.assertEqual(len(sampled['root_frames']),14)
        np.testing.assert_array_equal(sampled['height_frames'],[90,119])
        p['pelvis_height_targets']=[[3,.61],[3.001,.61]]
        with self.assertRaises(ValueError):constraint_schedule(p)

    def test_feature_constraint_crops_without_adding_root_channels(self):
        import torch
        from collections import defaultdict
        from aha3d.motion.interaction import FeatureConstraint
        c=FeatureConstraint(dict(global_joints_positions=(torch.tensor([[90,21],[120,21],[210,21]]),torch.zeros(3,3))))
        cropped=c.crop_move(100,200).to(device='cpu',dtype=torch.float64)
        data,indices=defaultdict(list),defaultdict(list);cropped.update_constraints(data,indices)
        self.assertEqual(set(data),{'global_joints_positions'})
        np.testing.assert_array_equal(cropped.frame_indices,[20])
        self.assertEqual(cropped.name,'selected-features')
        np.testing.assert_array_equal(indices['global_joints_positions'][0],[[20,21]])
        self.assertEqual(data['global_joints_positions'][0].dtype,torch.float64)
        data,indices=defaultdict(list),defaultdict(list);c.crop_move(220,300).update_constraints(data,indices)
        self.assertEqual(dict(data),{})

    def test_scalar_smooth_root_height_does_not_constrain_hips(self):
        import torch
        from collections import defaultdict
        from kimodo.skeleton import SMPLXSkeleton22
        from kimodo.motion_rep.reps.kimodo_motionrep import KimodoMotionRep
        from aha3d.motion.interaction import FeatureConstraint
        rep=KimodoMotionRep(SMPLXSkeleton22(),30)
        c=FeatureConstraint(dict(
            smooth_root_2d=(torch.tensor([90,120]),torch.zeros(2,2)),
            root_y_pos=(torch.tensor([435,479]),torch.tensor([.61,.61])),
            global_joints_positions=(torch.tensor([[90,21],[120,21]]),torch.ones(2,3)),
            global_joints_rots=(torch.tensor([[90,21],[120,21]]),torch.eye(3).repeat(2,1,1))))
        data,indices=defaultdict(list),defaultdict(list);c.update_constraints(data,indices)
        _,mask=rep.create_conditions(indices,data,480,False,'cpu')
        height=mask[:,rep.slice_dict['smooth_root_pos']][:,1]
        np.testing.assert_array_equal(torch.where(height)[0],[435,479])
        positions=mask[:,rep.slice_dict['local_joints_positions']].reshape(480,22,3)
        self.assertFalse(positions[:,0].any())
        self.assertEqual(int(positions[:,21].sum()),6)
        self.assertFalse(mask[:,rep.slice_dict['global_root_heading']].any())

    def test_native_hand_height_context_is_confined_to_contact(self):
        import torch
        from kimodo.skeleton import SMPLXSkeleton22
        from kimodo.constraints import RightHandConstraintSet
        from kimodo.motion_rep.conditioning import build_condition_dicts
        from kimodo.motion_rep.reps.kimodo_motionrep import KimodoMotionRep
        from aha3d.motion.interaction import FeatureConstraint
        sk=SMPLXSkeleton22();frames=torch.arange(90,211,15)
        root=torch.zeros(9,3);root[:,1]=torch.linspace(.91,1.05,9)
        gr,j,_=sk.fk(torch.eye(3).repeat(9,22,1,1),root)
        hand=RightHandConstraintSet(sk,frames,j,gr,root[:,[0,2]])
        from aha3d.motion.interaction import pelvis_position_constraint
        sitting=pelvis_position_constraint(torch.tensor([435,479]),torch.zeros(2,2),torch.tensor([.61,.61]))
        indices,data=build_condition_dicts([hand,sitting]);rep=KimodoMotionRep(sk,30)
        obs,mask=rep.create_conditions(indices,data,480,False,'cpu')
        height=mask[:,rep.slice_dict['smooth_root_pos']][:,1]
        np.testing.assert_array_equal(torch.where(height)[0],list(range(90,211,15))+[435,479])
        np.testing.assert_allclose(obs[frames,rep.slice_dict['smooth_root_pos']][:,1],root[:,1])
        self.assertFalse(height[:90].any());self.assertFalse(height[211:360].any())

    def test_rejects_overlong_prompts_and_uncovered_or_duplicate_keys(self):
        p=self.plan();p['segments'][0]['seconds']=11
        with self.assertRaises(ValueError):compile_plan(p)
        p=self.plan();p['root_xy_keys'][-1][0]=2
        with self.assertRaises(ValueError):compile_plan(p)
        p=self.plan();p['heading_keys'][1][0]=0
        with self.assertRaises(ValueError):compile_plan(p)

    def test_six_d_is_continuous_across_pi_with_finite_gradients(self):
        import torch
        from aha3d.motion.interaction import rotation_6d_to_matrix
        angle=torch.linspace(np.pi-.04,np.pi+.04,9)
        c,sn=angle.cos(),angle.sin();z=torch.zeros_like(c);one=torch.ones_like(c)
        expected=torch.stack([c,-sn,z,sn,c,z,z,z,one],-1).reshape(-1,3,3)
        six=expected[...,:2].transpose(-1,-2).reshape(-1,6).clone().requires_grad_()
        r=rotation_6d_to_matrix(six)
        np.testing.assert_allclose(r.detach(),expected,atol=1e-6)
        self.assertLess(float(torch.diff(r,dim=0).abs().max()),.011)
        torch.diff(r,dim=0).square().sum().backward()
        self.assertTrue(torch.isfinite(six.grad).all())

    def test_right_palm_chirality_and_room_down_goal(self):
        from aha3d.motion.interaction import right_palm_frame, hand_orientation_target
        frame=right_palm_frame(np.zeros(3),[-1,0,.2],[-1,0,0],[-1,0,-.2])
        np.testing.assert_allclose(frame[:,2],[0,-1,0])
        target=hand_orientation_target(frame,[0,0,-1],[1,0,0])
        np.testing.assert_allclose(KIMODO_TO_ROOM@target@frame[:,2],[0,0,-1],atol=1e-7)
        np.testing.assert_allclose(KIMODO_TO_ROOM@target@frame[:,0],[1,0,0],atol=1e-7)
        self.assertAlmostEqual(np.linalg.det(target),1.)

    def test_orientation_goal_is_optimized_without_position_goal(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(2,3)
            def fk(self,rot,root):return rot,root[:,None].expand(-1,2,-1),None
        base=np.tile(np.eye(3),(4,2,1,1)).astype(np.float32)
        angle=.5;goal=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
        r,_,_=optimize_motion(Skeleton(),base,np.zeros((4,3)),iterations=120,
            orientation_targets=dict(joint=1,rotations=np.tile(goal,(4,1,1)),strength=np.ones(4)))
        np.testing.assert_allclose(r[:,1],np.tile(goal,(4,1,1)),atol=.015)

    def test_fixed_neck_and_head_remain_exact_under_conflicting_targets(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(22,3)
            def fk(self,rot,root):
                return rot,root[:,None]+rot[...,0],None
        local=np.tile(np.eye(3),(4,22,1,1)).astype(np.float32)
        targets=np.tile([0.,1,0],(4,22,1));weights=np.zeros((4,22));weights[:,[0,3,6,9,12,15]]=1
        r,_,_=optimize_motion(Skeleton(),local,np.zeros((4,3)),joint_targets=(targets,weights),iterations=5,fixed_joints=(0,3,6,9,12,15))
        np.testing.assert_array_equal(r[:,[0,3,6,9,12,15]],local[:,[0,3,6,9,12,15]])

    def test_rotation_refinement_can_leave_zero_initial_delta(self):
        import torch
        from aha3d.motion.interaction import optimize_motion
        class Skeleton:
            neutral_joints=torch.zeros(2,3)
            def fk(self,rot,root):
                tip=root+rot[:,0,:,0]
                return rot,torch.stack([root,tip],1),None
        n=4
        local=np.tile(np.eye(3),(n,2,1,1)).astype(np.float32)
        root=np.zeros((n,3),np.float32)
        target=np.tile([[0.,0,0],[.98,.2,0]],(n,1,1))
        weights=np.tile([10.,1.],(n,1))
        rotations,positions,_=optimize_motion(Skeleton(),local,root,joint_targets=(target,weights),iterations=65)
        end=positions+rotations[:,0,:,0]
        self.assertLess(np.linalg.norm(end-target[:,1],axis=-1).max(),.03)
        self.assertGreater(np.abs(rotations-local).max(),.1)
        np.testing.assert_allclose(rotations.swapaxes(-1,-2)@rotations,np.tile(np.eye(3),(n,2,1,1)),atol=1e-5)

if __name__=='__main__':unittest.main()
