"""CPU contract checks for contact editing, not learned-model quality evidence."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from tools.kimodo.contact_edit import (
    ContactSettings, CompletionRejected, encode_for_contact, finalize_contact,
    forward_kinematics, known_source_rotations, load_projector, sample_with_feature_evidence, validate_inputs,
)

# Reuse the independent normalized 6D/FK codec, not neural weights, to verify
# what the new adapter actually sends to the existing denoising API.
_spec=importlib.util.spec_from_file_location('completion_contract_fixture',Path(__file__).with_name('test_motion_completion.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)


def fixture():
    source,_,interval=_fixture.fixture()
    source.update(source_video_sha256=np.asarray('a'*64),source_actor_id=np.asarray('woman'))
    count=len(source['time_seconds'])
    globals_,positions=forward_kinematics(source['local_rot_mats'],source['root_positions'],source['rest_joints'])
    constraints=dict(
        joint_names=source['joint_names'].copy(),time_seconds=source['time_seconds'].copy(),
        source_sha256=np.asarray('b'*64),source_video_sha256=np.asarray('a'*64),source_actor_id=np.asarray('woman'),
        coordinate_convention=np.asarray('gvhmr-native-y-up'),constraint_evidence=np.asarray('Synthetic fixture preserving source gestures'),
        target_evidence=np.asarray('Synthetic fixture root target; no scene measurement'),
        source_position_mask=np.zeros((count,22),bool),source_global_rotation_mask=np.zeros((count,22),bool),
        source_local_rotation_mask=np.ones((count,22),bool),
        target_position_mask=np.zeros((count,22),bool),target_positions=positions.copy())
    # Smooth tiny displacement to exercise translation separately from rotation.
    start,end=interval
    offset=.004*np.sin(np.linspace(0,np.pi,end-start))**2
    constraints['target_position_mask'][start:end,0]=True
    constraints['target_positions'][start:end,0,0]+=offset
    return source,constraints,interval


class ContactConstraintTests(unittest.TestCase):
    def validated(self):
        source,constraints,interval=fixture();settings=ContactSettings()
        return source,validate_inputs(source,constraints,interval,settings,source_hash='b'*64),interval,settings

    def test_source_and_target_bindings_cannot_be_replaced_by_same_length(self):
        source,constraints,interval=fixture()
        for key,value in [('source_actor_id','other'),('source_video_sha256','c'*64),('source_sha256','c'*64)]:
            other=deepcopy(constraints);other[key]=np.asarray(value)
            with self.assertRaises(ValueError):validate_inputs(source,other,interval,ContactSettings(),source_hash='b'*64)
        constraints['time_seconds']=constraints['time_seconds']+.001
        with self.assertRaisesRegex(ValueError,'timestamps'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_direct_source_position_collision_rejected_before_model(self):
        source,constraints,interval=fixture()
        constraints['source_position_mask'][:,0]=True
        with self.assertRaisesRegex(ValueError,'collides.*position'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_immutable_endpoints_cannot_be_moved_by_contact_target(self):
        source,constraints,interval=fixture()
        constraints['target_positions'][interval[0],0,1]+=.01
        with self.assertRaisesRegex(ValueError,'endpoint'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_implied_world_rotation_collision_from_local_chain_is_rejected(self):
        source,constraints,interval=fixture();count=len(source['time_seconds'])
        globals_,_=forward_kinematics(source['local_rot_mats'],source['root_positions'],source['rest_joints'])
        constraints['target_rotation_mask']=np.zeros((count,22),bool)
        constraints['target_rotation_mask'][10,20]=True
        constraints['target_global_rot_mats']=globals_.copy()
        constraints['target_global_rot_mats'][10,20]=Rotation.from_rotvec([0,0,.5]).as_matrix()
        with self.assertRaisesRegex(ValueError,'implied hard'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_isolated_local_rotation_is_not_mislabeled_world_condition(self):
        source,constraints,interval=fixture()
        constraints['source_local_rotation_mask'][:]=False
        constraints['source_local_rotation_mask'][:,20]=True
        known=known_source_rotations(source,constraints)
        self.assertFalse(known.any())
        # Pelvis targets remove automatic source root positions, so no frame has
        # a source world condition in the editable segment.
        with self.assertRaisesRegex(ValueError,'encodable source'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_source_shaped_bone_length_infeasibility_is_not_silently_sampled(self):
        source,constraints,interval=fixture()
        constraints['target_position_mask'][10,[1,4]]=True
        constraints['target_positions'][10,4]=constraints['target_positions'][10,1]+[0,-2,0]
        with self.assertRaisesRegex(ValueError,'bone length'):validate_inputs(source,constraints,interval,ContactSettings())

    def test_guide_only_initializes_and_requires_exact_shape_basis_time(self):
        source,constraints,interval=fixture();guide=deepcopy(source)
        guide['root_positions'][:,1]-=.1
        validate_inputs(source,constraints,interval,ContactSettings(),initial=guide)
        for key in ('betas','rest_joints','source_to_kimodo'):
            invalid=deepcopy(guide);invalid[key].flat[-1]+=.001
            with self.assertRaises(ValueError):validate_inputs(source,constraints,interval,ContactSettings(),initial=invalid)

    def test_root_edit_preserves_source_pose_shape_time_and_original_reference(self):
        source,constraints,interval,settings=self.validated();original=deepcopy(source)
        start,end=interval
        roots=constraints['target_positions'][start:end,0].copy()
        result,report=finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end].copy(),roots,settings)
        np.testing.assert_array_equal(result['local_rot_mats'],original['local_rot_mats'])
        np.testing.assert_array_equal(result['source_estimate_root_positions'],original['root_positions'])
        for key in ('betas','time_seconds','rest_joints','source_to_kimodo'):np.testing.assert_array_equal(result[key],original[key])
        np.testing.assert_array_equal(source['root_positions'],original['root_positions'])
        self.assertGreater(report['generated_root_frames'],0)
        self.assertEqual(report['generated_joint_samples'],0)
        self.assertTrue(report['gates']['source_preservation']['passed'])
        self.assertFalse(report['contact_validated'])
        np.testing.assert_array_equal(result['root_positions'][:start+1],source['root_positions'][:start+1])
        np.testing.assert_array_equal(result['root_positions'][end-1:],source['root_positions'][end-1:])

    def test_raw_bad_source_pose_or_contact_is_not_hidden_by_hard_merge(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        local=source['local_rot_mats'][start:end].copy();roots=source['root_positions'][start:end].copy()
        local[:,20]=Rotation.from_rotvec([0,0,1.5]).as_matrix()
        with self.assertRaisesRegex(CompletionRejected,'Raw sampled'):finalize_contact(source,constraints,interval,local,roots,settings)
        local=source['local_rot_mats'][start:end].copy();roots[:,0]+=.3
        with self.assertRaisesRegex(CompletionRejected,'Raw sampled'):finalize_contact(source,constraints,interval,local,roots,settings)

    def test_fast_root_return_rejected_by_distal_boundary_gate_even_without_rotation_change(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        settings=replace(settings,blend_frames=1)
        roots=source['root_positions'][start:end].copy();roots[1:-1,1]-=.12
        constraints['target_positions'][start+1:end-1,0,1]-=.12
        with self.assertRaisesRegex(CompletionRejected,'failed gates') as caught:
            finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end],roots,settings)
        gates=caught.exception.report['gates']
        self.assertTrue(gates['local_rotation_steps']['passed'])
        self.assertFalse(gates['boundary_distal_kinematics']['passed'])

    def test_target_auxiliary_xyz_is_not_accepted_without_final_shaped_fk(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        constraints['target_position_mask'][10:20,20]=True
        constraints['target_positions'][10:20,20,1]+=.05
        # FK wrist remains at source; root edit alone cannot reach this key.
        with self.assertRaisesRegex(CompletionRejected,'target_fk'):
            finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end],constraints['target_positions'][start:end,0],settings)

    def test_zero_effect_is_not_reported_as_contact_improvement(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        with self.assertRaisesRegex(CompletionRejected,'No effective'):
            finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end],source['root_positions'][start:end],settings)

    def test_rejected_merged_candidate_is_retained_as_diagnostic_not_accepted(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        roots=constraints['target_positions'][start:end,0].copy();roots[:,1]-=.3
        stored=[]
        with self.assertRaises(CompletionRejected):
            finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end],roots,settings,
                diagnostic_callback=lambda candidate,report:stored.append((candidate,report)))
        self.assertEqual(len(stored),1)
        self.assertFalse(stored[0][0]['contact_edit_parameter_candidate_accepted'])
        self.assertFalse(stored[0][1]['parameter_candidate_accepted'])
        self.assertFalse(stored[0][1]['gates']['raw_source_and_target']['passed'])

    def test_root_only_edit_exports_actual_native_translation_without_changing_pose(self):
        source,constraints,interval,settings=self.validated();start,end=interval
        prefix='source_gvhmr__smpl_params_global__'
        source[prefix+'body_pose']=Rotation.from_matrix(source['local_rot_mats'][:,1:].reshape(-1,3,3)).as_rotvec().reshape(len(source['time_seconds']),63).astype(np.float32)
        source[prefix+'global_orient']=Rotation.from_matrix(source['local_rot_mats'][:,0]).as_rotvec().astype(np.float32)
        source[prefix+'transl']=(source['root_positions']-source['rest_joints'][0]).astype(np.float32)
        source[prefix+'betas']=np.zeros((len(source['time_seconds']),10),np.float32)
        candidate,_=finalize_contact(source,constraints,interval,source['local_rot_mats'][start:end],constraints['target_positions'][start:end,0],settings)
        np.testing.assert_array_equal(candidate['smpl_params_global__body_pose'],source[prefix+'body_pose'])
        np.testing.assert_array_equal(candidate['smpl_params_global__global_orient'],source[prefix+'global_orient'])
        edited=candidate['generated_root_mask']
        np.testing.assert_allclose(candidate['smpl_params_global__transl'][edited],(candidate['root_positions']-source['rest_joints'][0])[edited],atol=2e-7)
        np.testing.assert_array_equal(candidate['smpl_params_global__transl'][~edited],source[prefix+'transl'][~edited])


@unittest.skipIf(_fixture.torch is None,'Torch optional for geometry-only tests')
class ContactEncodingTests(unittest.TestCase):
    def setup_encoding(self,guide=False):
        source,constraints,interval=fixture();settings=ContactSettings()
        model=_fixture.ContractModel(source['rest_joints'])
        model.motion_rep.unnormalize=lambda encoded:encoded*model.motion_rep.std+model.motion_rep.mean
        initial=deepcopy(source) if guide else None
        if guide:initial['root_positions'][:,2]+=.12
        constraints=validate_inputs(source,constraints,interval,settings,initial=initial)
        conditions=encode_for_contact(model,source,constraints,interval,settings,initial=initial)
        return source,constraints,interval,model,conditions,initial

    def test_normalized_full_root_and_body_conditions_decode_to_native_targets(self):
        source,constraints,interval,model,conditions,_=self.setup_encoding()
        raw=model.motion_rep.unnormalize(conditions['observed_motion']).numpy()[0]
        mask=conditions['motion_mask'].numpy()[0]
        start,end=interval
        native_positions=(raw[:,5:71].reshape(-1,22,3)+raw[:,:3][:,None]*[1,0,1]+conditions['canonical_origin']-source['source_to_kimodo'][:3,3])@source['source_to_kimodo'][:3,:3]
        np.testing.assert_allclose(native_positions[:,0],constraints['target_positions'][start:end,0],atol=1e-6)
        self.assertTrue(mask[:,:3].all())
        self.assertTrue(mask[:,5:8].all())
        self.assertTrue(mask[:,71:203].all())

    def test_distinct_guide_feature_origin_is_rebased_without_replacing_source_keys(self):
        source,constraints,interval,model,conditions,guide=self.setup_encoding(guide=True)
        start,end=interval
        decoded=model.motion_rep.inverse(conditions['encoded'])
        roots=(decoded['root_positions'].numpy()[0]+conditions['canonical_origin']-source['source_to_kimodo'][:3,3])@source['source_to_kimodo'][:3,:3]
        np.testing.assert_allclose(roots,guide['root_positions'][start:end],atol=1e-6)
        self.assertTrue(conditions['initial_is_distinct_guide'])
        self.assertFalse(np.allclose(roots,source['root_positions'][start:end]))
        raw=model.motion_rep.unnormalize(conditions['observed_motion']).numpy()[0]
        target_root=(raw[:,5:8]+raw[:,:3]*[1,0,1]+conditions['canonical_origin']-source['source_to_kimodo'][:3,3])@source['source_to_kimodo'][:3,:3]
        np.testing.assert_allclose(target_root,constraints['target_positions'][start:end,0],atol=1e-6)

    def test_final_feature_capture_does_not_change_decoder_or_sampling_result(self):
        source,constraints,interval,model,conditions,_=self.setup_encoding()
        model.target=conditions['encoded'].clone()
        inverse=model.motion_rep.inverse
        decoded,sampling,features=sample_with_feature_evidence(model,conditions,'A person sits.',7,ContactSettings())
        _fixture.torch.testing.assert_close(features,model.target)
        expected=inverse(model.target,is_normalized=True)
        for key in decoded:_fixture.torch.testing.assert_close(decoded[key],expected[key])
        self.assertEqual(model.motion_rep.inverse,inverse)
        self.assertEqual(sampling['reverse_steps_executed'],9)

    def setup_projected_sampling(self):
        source,constraints,interval,model,conditions,_=self.setup_encoding()
        torch=_fixture.torch
        class RecordingSampler(torch.nn.Module):
            def __init__(self):super().__init__();self.seen=[]
            # Exact upstream integration quirk: it bypasses forward hooks.
            def __call__(self,use_timesteps,noisy,clean,t):
                self.seen.append((noisy.clone(),clean.clone(),int(t.item())))
                return clean
        model.sampler=RecordingSampler();model.target=conditions['encoded'].clone();model.before_sampler=[]
        def denoise(current,pad,text,text_pad,t,heading,mask,observed,steps,cfg,**kwargs):
            use,_=model.diffusion.space_timesteps(settings.denoising_steps)
            model.before_sampler.append(current.clone())
            return model.sampler(use,current,model.target.clone(),t)
        settings=replace(ContactSettings(),denoising_steps=5,warm_start_step=2)
        model.denoising_step=denoise
        return source,constraints,interval,model,conditions,settings

    def test_projector_changes_clean_prediction_at_every_step_without_changing_noisy_argument(self):
        source,constraints,interval,model,conditions,settings=self.setup_projected_sampling()
        original=deepcopy(source);calls=[];start,end=interval
        def project(local,roots,**kwargs):
            self.assertEqual(local.shape,(end-start,22,3,3));self.assertEqual(roots.shape,(end-start,3))
            calls.append((kwargs['schedule_index'],kwargs['training_timestep']))
            # Attempting to mutate callback copies must not mutate original.
            kwargs['source']['betas'][:]=99
            kwargs['constraints']['source_local_rotation_mask'][:]=False
            return {'local_rot_mats':original['local_rot_mats'][start:end].copy(),
                    'root_positions':constraints['target_positions'][start:end,0].copy(),'report':{'synthetic':True}}
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'steps.json'
            decoded,sampling,features=sample_with_feature_evidence(model,conditions,'A person sits.',7,settings,
                projector=project,source=source,constraints=constraints,interval=interval,projection_log=log)
            self.assertTrue(log.exists())
        self.assertEqual(calls,[(2,50),(1,25),(0,0)])
        self.assertEqual(sampling['clean_projection_steps'],3)
        self.assertEqual(len(model.sampler._forward_pre_hooks),0)
        for before,seen in zip(model.before_sampler,model.sampler.seen):_fixture.torch.testing.assert_close(before,seen[0])
        np.testing.assert_array_equal(source['betas'],original['betas'])
        self.assertTrue(constraints['source_local_rotation_mask'].all())
        roots=(decoded['root_positions'].numpy()[0]+conditions['canonical_origin']-source['source_to_kimodo'][:3,3])@source['source_to_kimodo'][:3,:3]
        np.testing.assert_allclose(roots,constraints['target_positions'][start:end,0],atol=1e-6)

    def test_invalid_projector_output_rejects_and_restores_hooks(self):
        for invalid in ('shape','rotation','nan','report'):
            source,constraints,interval,model,conditions,settings=self.setup_projected_sampling()
            inverse=model.motion_rep.inverse
            def project(local,roots,**kwargs):
                result={'local_rot_mats':local,'root_positions':roots,'report':{}}
                if invalid=='shape':result['root_positions']=roots[:-1]
                if invalid=='rotation':result['local_rot_mats']=local*.9
                if invalid=='nan':result['root_positions'][0,0]=np.nan
                if invalid=='report':result['report']={'nonfinite':np.nan}
                return result
            with self.assertRaises(ValueError):
                sample_with_feature_evidence(model,conditions,'A person sits.',7,settings,
                    projector=project,source=source,constraints=constraints,interval=interval)
            self.assertEqual(model.motion_rep.inverse,inverse)
            self.assertEqual(len(model.sampler._forward_pre_hooks),0)
            self.assertEqual(len(model.sampler.seen),0)

    def test_explicit_projector_and_dependency_files_are_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'projector.py';dependency=Path(tmp)/'helper.py';dependency.write_text('VALUE=3\n')
            path.write_text("PROJECTOR_DEPENDENCY_PATHS=['helper.py']\ndef project_clean_motion(local_rot_mats,root_positions,**kwargs):\n return dict(local_rot_mats=local_rot_mats,root_positions=root_positions,report={})\n")
            function,info=load_projector(path)
            self.assertTrue(callable(function));self.assertEqual(len(info['sha256']),64)
            self.assertEqual(info['dependencies'][0]['path'],str(dependency.resolve()))

    def test_geometric_callback_can_differentiate_fresh_pose_inside_inference_sampler(self):
        source,constraints,interval,model,conditions,settings=self.setup_projected_sampling()
        torch=_fixture.torch;gradients=[];start,end=interval
        def project(local,roots,**kwargs):
            self.assertFalse(torch.is_inference_mode_enabled());self.assertTrue(torch.is_grad_enabled())
            pose=torch.tensor(roots,dtype=torch.float64,requires_grad=True)
            target=torch.tensor(constraints['target_positions'][start:end,0],dtype=torch.float64)
            loss=((pose-target)**2).sum();loss.backward()
            self.assertTrue(torch.isfinite(pose.grad).all());gradients.append(float(pose.grad.norm()))
            fixed=(pose-.5*pose.grad).detach().numpy()
            return dict(local_rot_mats=local,root_positions=fixed,report={'gradient_norm':gradients[-1]})
        _,sampling,_=sample_with_feature_evidence(model,conditions,'A person sits.',7,settings,
            projector=project,source=source,constraints=constraints,interval=interval)
        self.assertEqual(len(gradients),3);self.assertEqual(sampling['clean_projection_steps'],3)


if __name__=='__main__':unittest.main()
