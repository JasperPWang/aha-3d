"""Run a prompt-planned interaction on an existing exported RoomKit scene.

Explicit stages preserve raw generation separately from contact refinement.
"""
import argparse
import gzip
import json
from pathlib import Path
import numpy as np
from aha3d.motion.interaction import compile_plan, constraint_schedule, FeatureConstraint, KIMODO_TO_ROOM, optimize_motion, subset_skin, right_palm_frame, hand_orientation_target
from aha3d.motion.interaction import FOOT_PATCHES, foot_contact_strength, split_sole_patch
from aha3d.motion.interaction import generation_origin, room_to_generation, restore_scene_horizontal, contact_envelope
from aha3d.motion.interaction import pelvis_position_constraint
from aha3d.motion.kimodo_frame import sample_in_local_frame


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def load_skin(sk, out, body_model=None):
    # Load the offline skin module without importing optional Viser UI modules.
    import importlib.util
    import kimodo
    module_path=Path(kimodo.__file__).parent/'viz/smplx_skin.py'
    spec=importlib.util.spec_from_file_location('interaction_smplx_skin',module_path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    SMPLXSkin=module.SMPLXSkin
    if body_model is not None:
        assets=out/'skinning-assets';assets.mkdir(exist_ok=True)
        for name,source in [('SMPLX_NEUTRAL.npz',body_model),('beta.npy',Path(sk.folder)/'beta.npy'),('mean_hands.npy',Path(sk.folder)/'mean_hands.npy')]:
            target=assets/name
            if not target.exists():target.symlink_to(source.resolve(strict=True))
            elif target.resolve()!=source.resolve():raise ValueError('Skin asset binding changed')
        sk.folder=str(assets)
    skin=SMPLXSkin(sk,use_mean_hands=True)
    return skin


def hand_goal(plan, sk, skin):
    spec=plan.get('hand_orientation')
    if spec is None:return None
    rest=skin.joint_rest.detach().cpu().numpy()
    frame=right_palm_frame(rest[skin.body_joint_indices[21]],
        rest[skin.hand_joint_indices[15]],rest[skin.hand_joint_indices[18]],rest[skin.hand_joint_indices[21]])
    desired=hand_orientation_target(frame,spec['palm_normal_room'],spec['fingers_direction_room'])
    return dict(local_frame=frame,rotation=desired,palm_normal_room=np.asarray(spec['palm_normal_room']))


def project_grasp(plan, scene):
    # Project the planned grasp onto the actual exported chair triangle surface.
    import trimesh
    triangles=[]
    for m in scene['meshes']:
        if m['owner']!=plan['target_object']:continue
        v=np.asarray(m['positions']).reshape(-1,3);M=np.asarray(m['matrix']).reshape(4,4).T
        v=v@M[:3,:3].T+M[:3,3]
        faces=np.asarray([i for g in m['groups'] for i in g['indices']]).reshape(-1,3)
        triangles.append(v[faces])
    triangles=np.concatenate(triangles)
    target=np.asarray(plan['hand_surface_point'])
    nearest=trimesh.triangles.closest_point(triangles,np.broadcast_to(target,(len(triangles),3)))
    surface=nearest[np.linalg.norm(nearest-target,axis=1).argmin()]
    return surface


def generate(plan, out, body_model=None, scene_path=None):
    if (out/'generated.npz').exists():raise FileExistsError('Choose a new output for a new generation')
    write_json(out/'input_plan.json',plan)
    if scene_path is not None and plan.get('hand_contact_seconds') is not None:
        raw_scene=scene_path.read_bytes()
        scene=json.loads(gzip.decompress(raw_scene) if scene_path.suffix=='.gz' else raw_scene)
        plan=dict(plan,hand_surface_point=project_grasp(plan,scene).tolist())
        if 'hand_surface_keys' in plan:
            plan['hand_surface_keys']=[[key[0],*project_grasp(dict(plan,hand_surface_point=key[1:]),scene).tolist()] for key in plan['hand_surface_keys']]
    elif plan.get('root_hand_coupling'):
        raise ValueError('--scene is required to resolve the coupled contact before generation')
    write_json(out/'resolved_plan.json',plan)
    import torch
    from kimodo import load_model
    from kimodo.constraints import Root2DConstraintSet, RightHandConstraintSet, EndEffectorConstraintSet
    from kimodo.motion_rep.conditioning import build_condition_dicts
    from kimodo.tools import seed_everything
    c=compile_plan(plan)
    model=load_model('Kimodo-SMPLX-RP-v1',device='cuda:0')
    sk=model.skeleton; device=model.device
    direction=hand_goal(plan,sk,load_skin(sk,out,body_model)) if plan.get('hand_orientation') else None
    tensor=lambda a:torch.as_tensor(a,dtype=torch.float32,device=device)
    # Room XY maps to native (-X,Z); heading is authored in native Y-up.
    origin=generation_origin(c['root_xy'][0],plan['floor_height'])
    route=np.column_stack([-c['root_xy'][:,0],c['root_xy'][:,1]])-origin[[0,2]]
    write_json(out/'coordinate_frame.json',dict(scene_origin_native=origin.tolist(),
        model='Y-up, first smoothed root XZ = zero, heights above scene floor',
        archive='Native axes with scene XZ restored once; Y stays floor-relative until refinement',
        continuation='Native multiprompt restores scene XZ; each diffusion call additionally normalizes initial XZ/yaw, including all constraints and 12-frame context, then restores it before native continuation/postprocessing.'))
    schedule=constraint_schedule(plan)
    ids=schedule['root_frames']; headingids=schedule['heading_frames']
    route_constraint=Root2DConstraintSet(sk,torch.as_tensor(ids),tensor(route[ids]))
    heading_constraint=FeatureConstraint(dict(global_root_heading=(torch.as_tensor(headingids),tensor(np.column_stack([np.cos(c['heading'][headingids]),np.sin(c['heading'][headingids])])))))
    baseline_constraints=[route_constraint,heading_constraint]
    constraints=list(baseline_constraints)
    hipids=schedule['height_frames']
    historical=plan.get('generation_profile')=='1c9de0b_control'
    def hip_constraint(indices):
        from kimodo.geometry import angle_to_Y_rotation_matrix
        rootkeys=np.column_stack([route[indices,0],c['root_height'][indices],route[indices,1]])
        rots=torch.eye(3,device=device).repeat(len(indices),22,1,1)
        rots[:,0]=angle_to_Y_rotation_matrix(tensor(c['heading'][indices]))
        gr,jp,_=sk.fk(rots,tensor(rootkeys))
        return EndEffectorConstraintSet(sk,torch.as_tensor(indices),jp,gr,tensor(route[indices]),joint_names=['Hips'])
    if historical:
        if c['root_height'] is None or len(hipids):
            raise ValueError('Historical control requires original root_height_keys and no scalar height targets')
        hipids=np.unique(np.r_[np.arange(0,len(route),30),len(route)-1])
        baseline_constraints.append(hip_constraint(hipids))
        constraints=list(baseline_constraints)
    elif len(hipids):
        constraints.append(pelvis_position_constraint(hipids,tensor(route[hipids]),tensor(schedule['height_values'])))
    elif c['root_height'] is not None:
        raise ValueError('Replace full-clip root_height_keys with phase-specific pelvis_height_targets')
    prompts=[s['prompt'] for s in plan['segments']]
    kwargs=dict(num_denoising_steps=plan.get('steps',100),cfg_weight=[2.,2.],cfg_type='separated',num_samples=1,multi_prompt=True,
                num_transition_frames=12,post_processing=True,return_numpy=True,first_heading_angle=[float(c['heading'][0])])
    # Intercept actual native per-segment inputs/outputs without editing Kimodo.
    # Later segments contain 12 frames of preceding context, recorded explicitly.
    import kimodo.model.kimodo_model as native_module
    native_postprocess = native_module.post_process_motion
    capture = dict(pass_name='baseline', index=0)
    segment_records=[]
    text_records=[]
    alignment_records=[]
    native_generate=model._generate
    def record_generate(texts, max_frames, **kw):
        observed=model.motion_rep.unnormalize(kw['observed_motion'])
        smooth=model.motion_rep.get_root_pos(observed)[0,:, [0,2]]
        start=smooth[0].detach().cpu().numpy()
        if np.linalg.norm(start)>1e-5:
            raise ValueError(f'Noncanonical subsequence origin: {start}')
        context=0 if capture['index']==0 else kwargs['num_transition_frames']
        prefix=f"{capture['pass_name']}-segment-{capture['index']+1}"
        np.savez_compressed(out/(prefix+'-model-input.npz'),
            observed=observed[0].detach().cpu().numpy(),mask=kw['motion_mask'][0].detach().cpu().numpy())
        alignment_records.append(dict(pass_name=capture['pass_name'],step=capture['index']+1,
            context_frames=context,first_smooth_root_xz=start.tolist(),
            initial_heading_radians=kw['first_heading_angle'].detach().cpu().tolist(),
            context_smooth_root_xz=smooth[:context].detach().cpu().tolist()))
        return sample_in_local_frame(model,native_generate,texts,max_frames,
            receipt=alignment_records[-1],
            save_input=lambda obs,mask:np.savez_compressed(out/(prefix+'-local-input.npz'),
                observed=obs[0].detach().cpu().numpy(),mask=mask[0].detach().cpu().numpy()),**kw)
    text_encoder=model.text_encoder
    def record_text(texts, *args, **kwargs):
        text_records.append(dict(pass_name=capture['pass_name'],step=capture['index']+1,texts=list(texts)))
        return text_encoder(texts, *args, **kwargs)
    def record_native(local, root, contacts, skeleton, *args, **kw):
        index=capture['index'];capture['index']+=1
        prefix=f"{capture['pass_name']}-segment-{index+1}"
        context=0 if index==0 else kwargs['num_transition_frames']
        start=sum(c['frames'][:index])-context
        def save(name, rotations, roots, fc):
            with torch.no_grad():
                gr,jp,_=sk.fk(rotations,roots)
            values=dict(local_rot_mats=rotations,root_positions=roots,foot_contacts=fc,posed_joints=jp,global_rot_mats=gr)
            np.savez_compressed(out/(prefix+name+'.npz'),**restore_scene_horizontal({k:v[0].detach().cpu().numpy() for k,v in values.items()},origin))
        save('-raw',local,root,contacts)
        corrected=native_postprocess(local,root,contacts,skeleton,*args,**kw)
        if context:
            previous_root,previous_rot=capture['last_native']
            root_error=float((corrected['root_positions'][:,:context]-previous_root).abs().max())
            rotation_error=float((corrected['local_rot_mats'][:,:context]-previous_rot).abs().max())
            if root_error>1e-5 or rotation_error>1e-4:
                raise ValueError('Native continuation changed the preceding root/pose context')
            alignment_records[-1].update(context_root_max_abs_error_m=root_error,
                context_rotation_matrix_max_abs_error=rotation_error,
                seam_root_step_cm=float(torch.linalg.vector_norm(corrected['root_positions'][:,context]-corrected['root_positions'][:,context-1]))*100)
        capture['last_native']=(corrected['root_positions'][:,-12:].clone(),corrected['local_rot_mats'][:,-12:].clone())
        save('-native',corrected['local_rot_mats'],corrected['root_positions'],contacts)
        segment_records.append(dict(pass_name=capture['pass_name'],step=index+1,
            start_frame=start,context_frames=context,frames=int(root.shape[1]),
            raw_file=prefix+'-raw.npz',native_file=prefix+'-native.npz'))
        return corrected
    def sample(pass_name, condition):
        capture.update(pass_name=pass_name,index=0)
        native_module.post_process_motion=record_native
        model.text_encoder=record_text
        model._generate=record_generate
        try:return model(prompts,c['frames'],constraint_lst=condition,**kwargs)
        finally:
            native_module.post_process_motion=native_postprocess
            model.text_encoder=text_encoder
            model._generate=native_generate
            write_json(out/'text_encoder_receipt.json',dict(calls=text_records))
            write_json(out/'subsequence_alignment.json',dict(calls=alignment_records))
    seed_everything(plan['seed'])
    print('Generating route/text baseline',flush=True)
    # The phase-specific default leaves height free; the explicit historical
    # comparison retains its original Hips keys in both passes.
    raw=sample('baseline',baseline_constraints)
    raw={k:v[0] for k,v in raw.items() if isinstance(v,np.ndarray)}
    np.savez_compressed(out/'baseline.npz',**restore_scene_horizontal(raw,origin))
    handids=np.array([],dtype=int);log=[];hand_only=False;hand_constraints=[]
    if c['hand_on'].any():
        print('Authoring FK-consistent sparse hand constraint poses',flush=True)
        handids=np.flatnonzero(c['hand_on'])[::15]
        handids=np.unique(np.r_[handids,np.flatnonzero(c['hand_on'])[-1]])
        if plan.get('hand_pose_lead_seconds',0):
            handids=np.unique(np.r_[max(0,handids[0]-round(plan['hand_pose_lead_seconds']*30)),handids])
        positions=raw['posed_joints'][handids].copy()
        # Wrist sits behind the palm surface, towards the person. All targets use the
        # same native frame; final mesh refinement measures actual palm contact.
        targets=positions.copy()
        wrist_room=c['hand'][handids]+np.asarray(plan['wrist_from_surface'])
        targets[:,21]=room_to_generation(wrist_room,origin)
        if historical:targets[:,0,1]=c['root_height'][handids]
        weights=np.zeros(targets.shape[:2]);weights[:,21]=1;weights[:,[7,8,10,11]]=.2
        weights[:,0]=2
        key_root_bound=bool(plan.get('root_hand_coupling') or plan.get('hand_key_root_mode')=='planned_xy')
        if key_root_bound:targets[:,0,[0,2]]=route[handids]
        local,root,log=optimize_motion(sk,raw['local_rot_mats'][handids],raw['root_positions'][handids],joint_targets=(targets,weights),iterations=240 if direction is not None else 160,
            root_trajectory=None if not key_root_bound else dict(positions=route[handids],binding=np.ones(len(handids))),
            orientation_targets=None if direction is None else dict(joint=21,rotations=np.tile(direction['rotation'],(len(handids),1,1)),strength=np.ones(len(handids))))
        with torch.no_grad():
            global_rots,posed,_=sk.fk(tensor(local),tensor(root))
        native_hand=RightHandConstraintSet(sk,torch.as_tensor(handids),posed,global_rots,tensor(route[handids]))
        hand_only=plan.get('hand_condition_features')=='hand_only'
        if hand_only:
            # Experimental: drop the native EE root context. Retained for reproducing
            # the diagnosed crouching/turning trial, not the default interaction.
            index_dict,data_dict=build_condition_dicts([native_hand])
            native_hand=FeatureConstraint({name:(torch.cat(index_dict[name]),torch.cat(data_dict[name]))
                for name in ('global_joints_positions','global_joints_rots')})
            referenceids=np.setdiff1d(handids,ids)
            if len(referenceids):constraints.append(Root2DConstraintSet(sk,torch.as_tensor(referenceids),tensor(route[referenceids])))
        else:
            # Native hand keys include FK-derived facing. Do not submit a conflicting
            # authored heading at the same frame and rely on upstream duplicate order.
            facingids=np.setdiff1d(headingids,handids)
            constraints[1]=FeatureConstraint(dict(global_root_heading=(torch.as_tensor(facingids),tensor(np.column_stack([np.cos(c['heading'][facingids]),np.sin(c['heading'][facingids])])))))
            if historical:
                # Native hand keys already supply Hips context. Avoid conflicting
                # full-Hips observations/projections at those same frames.
                constraints[2]=hip_constraint(np.setdiff1d(hipids,handids))
        hand_constraints=[native_hand]
    # Native hand keys carry the fitted root context at contact frames. Only the
    # explicit historical control adds full-clip Hips; the default leaves walking
    # height free and handles seated height separately.
    def receipt(items):
        indices,data=build_condition_dicts(items)
        return {name:dict(indices=torch.cat(indices[name]).cpu().tolist(),values=torch.cat(data[name]).detach().cpu().tolist()) for name in indices}
    write_json(out/'constraint_receipt.json',dict(baseline=receipt(baseline_constraints),conditioned=receipt(constraints+hand_constraints),
        scope='Exact authored feature channels before native continuation context. Native 12-frame continuation still carries preceding generated full-body motion.'))
    if c['hand_on'].any():
        orientation_evidence={}
        if direction is not None:
            orientation_evidence=dict(requested_global_wrist_rotation=np.tile(direction['rotation'],(len(handids),1,1)),
                fk_global_wrist_rotation=global_rots[:,21].cpu().numpy(),local_palm_frame=direction['local_frame'])
            write_json(out/'hand_orientation.json',{k:v.tolist() for k,v in direction.items()})
        np.savez_compressed(out/'hand_constraints.npz',**orientation_evidence,frames=handids,requested_wrist=targets[:,21]+origin*[1,0,1],fk_wrist=posed[:,21].cpu().numpy()+origin*[1,0,1],local_rot_mats=local,root_positions=root+origin*[1,0,1],requested_root_xy=route[handids]+origin[[0,2]])
    seed_everything(plan['seed'])
    print('Generating sequence with route, hand keys, text and native transition conditioning',flush=True)
    raw=sample('conditioned',constraints+hand_constraints)
    raw={k:v[0] for k,v in raw.items() if isinstance(v,np.ndarray)}
    np.savez_compressed(out/'generated.npz',**restore_scene_horizontal(raw,origin))
    raw_segments=[]
    for record in segment_records:
        if record['pass_name']=='conditioned':
            motion=dict(np.load(out/record['raw_file']))
            raw_segments.append({k:v[record['context_frames']:] for k,v in motion.items()})
    np.savez_compressed(out/'raw_segments.npz',**{k:np.concatenate([r[k] for r in raw_segments]) for k in raw_segments[0]})
    write_json(out/'segments.json',dict(segments=segment_records,
        raw_display='Actual pre-native-postprocessing samples; later segments are continuation-conditioned, not independent draws. Context is saved in individual files and excluded in raw_segments.npz.',
        joined='generated.npz is the native continuation/postprocessing result.'))
    write_json(out/'generation.json',dict(model='Kimodo-SMPLX-RP-v1',fps=30,frames=len(c['times']),generated=True,
        generation_profile=plan.get('generation_profile','phase_specific'),
        pass_constraints=dict(baseline=['Root2DConstraintSet','SparseHeading']+(['HistoricalHips'] if historical else []),
            conditioned=(['Root2DConstraintSet','SparseHeading']+([('RightHandPositionRotationOnly' if hand_only else 'RightHandConstraintSet')] if len(handids) else []))+(['HistoricalHipsOutsideHandKeys' if historical else 'SparsePelvisPosition'] if len(hipids) else [])),
        constraints=(['Root2DConstraintSet','SparseHeading']+([('RightHandPositionRotationOnly' if hand_only else 'RightHandConstraintSet')] if len(handids) else []))+(['HistoricalHipsOutsideHandKeys' if historical else 'SparsePelvisPosition'] if len(hipids) else []),
        pelvis_height_frames=hipids.tolist(),root_path_frames=ids.tolist(),heading_frames=headingids.tolist(),native_transition_frames=12,native_postprocessing=True,
        hand_key_frames=handids.tolist(),pose_authoring_optimization=log,plan=plan))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['generate','preview','refine'])
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--scene',type=Path);p.add_argument('--body-model',type=Path);p.add_argument('--iterations',type=int,default=200)
    p.add_argument('--refinement-profile',choices=['current','1c9de0b_control','balanced_heel_toe','balanced_heel_toe_ground'],default='current')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    plan=json.loads(a.plan.read_text());compile_plan(plan)
    if a.stage=='generate':generate(plan,a.out,a.body_model,a.scene)
    else:
        if a.scene is None:p.error('--scene required for refinement')
        refine(plan,a.out,a.scene,0 if a.stage=='preview' else a.iterations,a.body_model,a.refinement_profile)




def refine(plan, out, scene_path, iterations, body_model=None, refinement_profile='current'):
    if (out/'scene.json').exists():raise FileExistsError('Choose a new output to preserve the existing refinement')
    import torch
    from kimodo.skeleton import SMPLXSkeleton22
    if (out/'resolved_plan.json').exists():
        if json.loads((out/'input_plan.json').read_text())!=plan:raise ValueError('Refinement plan differs from generation input')
        plan=json.loads((out/'resolved_plan.json').read_text())
    c=compile_plan(plan); device='cuda:0'
    sk=SMPLXSkeleton22().to(device)
    skin=load_skin(sk,out,body_model)
    direction=hand_goal(plan,sk,skin)
    raw=dict(np.load(out/'generated.npz'))
    local=raw['local_rot_mats'];root=raw['root_positions'].copy();root[:,1]+=plan['floor_height']
    tensor=lambda a:torch.as_tensor(a,dtype=torch.float32,device=device)
    def skin_all(local,root):
        vs=[];js=[]
        with torch.no_grad():
            for start in range(0,len(root),12):
                r=tensor(local[start:start+12]);_,j,_=sk.fk(r,tensor(root[start:start+12]))
                vs.append(skin.skin(r,j).cpu().numpy());js.append(j.cpu().numpy())
        return np.concatenate(vs),np.concatenate(js)
    before,joints=skin_all(local,root)
    source_bytes=scene_path.read_bytes()
    scene=json.loads(gzip.decompress(source_bytes) if scene_path.suffix=='.gz' else source_bytes)
    surface=project_grasp(plan,scene) if c['hand_on'].any() else None
    if surface is not None and 'hand_surface_keys' not in plan:c['hand']=surface+c['object_translation']
    rest=skin.v_shaped.cpu().numpy(); weights=skin.lbs_weights.cpu().numpy()
    body_indices=skin.body_joint_indices
    neutral=sk.neutral_joints.cpu().numpy()
    # Freeze a proximity-selected hand patch; this is not semantic palm segmentation.
    f=int(np.flatnonzero(c['hand_on'])[0]) if c['hand_on'].any() else 0
    wrist=joints[f,21]
    if direction is None:
        hand_ids=np.flatnonzero(np.linalg.norm(before[f]-wrist,axis=1)<.18)
        target_native=c['hand'][f]@KIMODO_TO_ROOM
        palm=hand_ids[np.argsort(np.linalg.norm(before[f,hand_ids]-target_native,axis=1))[:12]]
    else:
        # The palm faces outward along the anatomical palmar normal. Freeze
        # an interior palmar patch, not whichever finger/back happens to be close.
        handrest=rest-skin.joint_rest[skin.body_joint_indices[21]].cpu().numpy()
        coords=handrest@direction['local_frame']
        eligible=np.flatnonzero((coords[:,0]>.025)&(coords[:,0]<.10)&(np.abs(coords[:,1])<.035)&(weights[:,skin.body_joint_indices[21]]>.35))
        if len(eligible)<12:raise ValueError('Insufficient anatomical palm vertices')
        eligible=eligible[coords[eligible,2]>=np.percentile(coords[eligible,2],65)]
        palm=eligible[np.argsort(np.linalg.norm(coords[eligible,:2]-[.065,0],axis=1))[:12]]
    parts={'palm':palm}
    for name,js in [('left_sole',[7,10]),('right_sole',[8,11])]:
        ids=np.flatnonzero(weights[:,body_indices[js]].sum(1)>.5)
        ids=ids[rest[ids,1]<np.percentile(rest[ids,1],25)]
        parts[name]=ids[np.linspace(0,len(ids)-1,min(24,len(ids))).astype(int)]
        side=name.split('_')[0]
        parts[side+'_heel'],parts[side+'_toe']=split_sole_patch(rest,parts[name],neutral[js[0]],neutral[js[1]])
    butt=[]
    for side in [-1,1]:
        point=neutral[0]+[side*.085,-.105,-.09]
        eligible=np.flatnonzero(weights[:,body_indices[[0,1,2]]].sum(1)>.5)
        butt.extend(eligible[np.argsort(np.linalg.norm(rest[eligible]-point,axis=1))[:12]])
    parts['seat']=np.unique(butt)
    palm_faces=skin.faces.cpu().numpy()
    palm_faces=palm_faces[np.isin(palm_faces,palm).sum(1)>=2]
    selected=np.unique(np.concatenate(list(parts.values())+([palm_faces.reshape(-1)] if direction is not None else [])))
    layout={k:np.searchsorted(selected,v) for k,v in parts.items()}
    fc=raw['foot_contacts']
    if fc.shape!=(len(root),4):raise ValueError('Expected Kimodo [left ankle,left toe,right ankle,right toe] labels')
    strength=foot_contact_strength(fc)
    foot_parts=FOOT_PATCHES
    objective_strength=strength
    foot_scale=1.
    fixed_joints=(0,3,6,9,12,15,13,16,18,20)
    if refinement_profile in ('1c9de0b_control','balanced_heel_toe','balanced_heel_toe_ground'):
        fixed_joints=(0,3,6,9,12,15)
        if refinement_profile=='1c9de0b_control':
            foot_parts=('left_sole','right_sole')
            # Deliberately reproduce the old mask only for the matched control.
            objective_strength=np.column_stack([fc[:,:2].mean(1),fc[:,2:].mean(1)])
            objective_strength=np.where(objective_strength>.5,objective_strength,0.)
        else:
            # Two patches per foot: retain the old aggregate coefficient budget.
            foot_scale=.5
    if not c['hand_on'].any():
        # Foot/seat refinement has no reason to change generated arm gestures.
        fixed_joints=tuple(sorted(set(fixed_joints) | {13,14,16,17,18,19,20,21}))
    anchors={}
    for i,name in enumerate(foot_parts):
        positions=before[:,parts[name]].copy();on=objective_strength[:,i]>0
        changes=np.diff(np.r_[False,on,False].astype(int))
        for a,b in zip(np.flatnonzero(changes==1),np.flatnonzero(changes==-1)):
            reference=np.median(positions[a:b],axis=0)
            reference[:,1]+=plan['floor_height']+.002-reference[:,1].min()
            positions[a:b]=reference
        anchors[name]=positions
    hand_strength=c['hand_on'].astype(float)
    # Lower the endpoint contact weights during acquisition/release.
    t=c['times']
    if plan.get('hand_contact_seconds') is not None:
        a,b=plan['hand_contact_seconds']
        hand_strength*=np.clip((t-a+.15)/.3,0,1)*np.clip((b+.15-t)/.3,0,1)
    seat_interval=plan.get('seat_contact_seconds')
    seat_strength=contact_envelope(t,seat_interval,ramp=.5,lead=.5)
    # A seat held through clip end has no release inside the clip.
    if seat_interval is not None and seat_interval[1]>=len(t)/30:
        seat_strength=np.clip((t-seat_interval[0]+.5)/.5,0,1)
    cd=dict(hand_strength=hand_strength,hand_target=c['hand']@KIMODO_TO_ROOM,
        foot_anchors=anchors,foot_strength=objective_strength,foot_parts=foot_parts,foot_loss_scale=foot_scale,floor_y=plan['floor_height']+.002,fps=30,
        seat_strength=seat_strength,seat_target=c['seat']@KIMODO_TO_ROOM)
    if refinement_profile=='balanced_heel_toe_ground':
        cd['floor_parts']=('left_sole','right_sole')
    if direction is not None:
        cd.update(palm_triangles=np.searchsorted(selected,palm_faces),palm_normal_target=direction['palm_normal_room']@KIMODO_TO_ROOM)
    final_local,final_root,logs=(local.copy(),root.copy(),[]) if iterations==0 else optimize_motion(sk,local,root,iterations=iterations,
        contact_skin=subset_skin(skin,selected),patch_layout=layout,contact_data=cd,
        fixed_joints=fixed_joints,
        root_path_prior=None if not plan.get('root_path_prior_weight') else dict(positions=np.column_stack([-c['root_xy'][:,0],c['root_xy'][:,1]]),strength=hand_strength,weight=plan['root_path_prior_weight']),
        root_trajectory=None if not plan.get('root_hand_coupling') else dict(positions=np.column_stack([-c['root_xy'][:,0],c['root_xy'][:,1]]),binding=c['root_binding']),
        orientation_targets=None if direction is None else dict(joint=21,rotations=np.tile(direction['rotation'],(len(root),1,1)),strength=hand_strength,weight=2.))
    after,after_joints=skin_all(final_local,final_root)
    np.savez_compressed(out/'refined.npz',local_rot_mats=final_local,root_positions=final_root,
        foot_contacts=fc,posed_joints=after_joints)
    def direction_trace(rotations, roots, vertices):
        if direction is None:return None
        with torch.no_grad():
            gr,j,_=sk.fk(tensor(rotations),tensor(roots))
        palm_axes=gr[:,21].cpu().numpy()@direction['local_frame']
        normal=palm_axes[:,:,2]@KIMODO_TO_ROOM.T
        faces=skin.faces.cpu().numpy()
        patch_faces=faces[np.isin(faces,palm).sum(1)>=2]
        if not len(patch_faces):raise ValueError('Palm patch has no surface triangles')
        tri=vertices[:,patch_faces]
        mesh_normal=np.cross(tri[:,:,1]-tri[:,:,0],tri[:,:,2]-tri[:,:,0]).sum(1)
        mesh_normal/=np.maximum(np.linalg.norm(mesh_normal,axis=1,keepdims=True),1e-12)
        return dict(wrists=j[:,21].cpu().numpy()@KIMODO_TO_ROOM.T,palm_centers=vertices[:,palm].mean(1)@KIMODO_TO_ROOM.T,
            normal=normal,mesh_normal=mesh_normal@KIMODO_TO_ROOM.T,
            fingers=palm_axes[:,:,0]@KIMODO_TO_ROOM.T)
    def direction_metrics(trace):
        if trace is None:return None
        def angle(v,target):return np.rad2deg(np.arccos(np.clip(v@np.asarray(target),-1,1)))[c['hand_on']]
        result={}
        for name,vec,target in [('palm_normal',trace['normal'],plan['hand_orientation']['palm_normal_room']),
                                ('mesh_palm_normal',trace['mesh_normal'],plan['hand_orientation']['palm_normal_room']),
                                ('fingers',trace['fingers'],plan['hand_orientation']['fingers_direction_room'])]:
            a=angle(vec,target);result[name]=dict(mean_error_deg=float(a.mean()),max_error_deg=float(a.max()),p90_error_deg=float(np.percentile(a,90)))
        return result
    def root_metrics(roots):
        xy=(roots@KIMODO_TO_ROOM.T)[:,:2];on=c['hand_on'];pairs=on[1:]&on[:-1]
        if not pairs.any():return None
        error=np.linalg.norm(xy-c['root_xy'],axis=1)[on]*100
        velocity=np.linalg.norm(np.diff(xy-c['hand'][:,:2],axis=0),axis=1)[pairs]*30*100
        ids=np.flatnonzero(on)
        return dict(root_target_error_mean_cm=float(error.mean()),root_target_error_max_cm=float(error.max()),
            root_hand_relative_speed_mean_cm_s=float(velocity.mean()),root_hand_relative_speed_max_cm_s=float(velocity.max()),
            root_displacement_room_xy_cm=((xy[ids[-1]]-xy[ids[0]])*100).tolist(),
            hand_displacement_room_xy_cm=((c['hand'][ids[-1],:2]-c['hand'][ids[0],:2])*100).tolist())
    before_direction=direction_trace(local,root,before)
    after_direction=direction_trace(final_local,final_root,after)
    def metrics(v,j):
        hand=np.linalg.norm(v[:,palm].mean(1)-cd['hand_target'],axis=-1)[hand_strength>.9]
        feet=[]
        for i,k in enumerate(('left_sole','right_sole')):
            p=v[:,parts[k]];on=strength[:,2*i:2*i+2].max(1)>0;pairs=on[1:]&on[:-1]
            speed=np.linalg.norm(np.diff(p,axis=0),axis=-1).mean(1)*30
            feet.append(dict(contact_frames=int(on.sum()),contact_speed_mean_cm_s=float(speed[pairs].mean()*100) if pairs.any() else None,
                contact_speed_p90_cm_s=float(np.percentile(speed[pairs],90)*100) if pairs.any() else None,
                sole_height_mean_cm=float((p[:,:,1].min(1)[on]-plan['floor_height']).mean()*100) if on.any() else None))
        channels=[]
        for i,k in enumerate(FOOT_PATCHES):
            p=v[:,parts[k]];on=strength[:,i]>0;pairs=on[1:]&on[:-1]
            speed=np.linalg.norm(np.diff(p[:,:,[0,2]],axis=0),axis=-1).mean(1)*30
            phases=[];start=0
            for segment,n in zip(plan['segments'],c['frames']):
                mask=pairs.copy();mask[:start]=False;mask[start+n-1:]=False
                phases.append(dict(name=segment['name'],pairs=int(mask.sum()),
                    horizontal_speed_mean_cm_s=float(speed[mask].mean()*100) if mask.any() else None,
                    horizontal_speed_max_cm_s=float(speed[mask].max()*100) if mask.any() else None))
                start+=n
            channels.append(dict(patch=k,contact_frames=int(on.sum()),pairs=int(pairs.sum()),
                horizontal_speed_mean_cm_s=float(speed[pairs].mean()*100) if pairs.any() else None,
                horizontal_speed_p90_cm_s=float(np.percentile(speed[pairs],90)*100) if pairs.any() else None,
                phases=phases))
        seat=v[:,parts['seat'],1].min(1)-c['seat'][:,2]
        boundaries=np.cumsum(c['frames'])[:-1]
        return dict(hand_error_mean_cm=float(hand.mean()*100) if len(hand) else None,hand_error_p90_cm=float(np.percentile(hand,90)*100) if len(hand) else None,
            floor_penetration_max_cm=float(max(0,plan['floor_height']-v[:,:,1].min())*100),feet=feet,foot_contact_channels=channels,
            seat_gap_mean_cm=float(seat[seat_strength>.99].mean()*100) if (seat_strength>.99).any() else None,
            seam_root_steps_cm=(np.linalg.norm(j[boundaries,0]-j[boundaries-1,0],axis=1)*100).tolist(),
            max_joint_step_cm=float(np.linalg.norm(np.diff(j,axis=0),axis=-1).max()*100))
    fixed_names={0:'pelvis',3:'spine1',6:'spine2',9:'spine3',12:'neck',15:'head',13:'left_collar',16:'left_shoulder',18:'left_elbow',20:'left_wrist',14:'right_collar',17:'right_shoulder',19:'right_elbow',21:'right_wrist'}
    report=dict(rotation_representation='6D columns -> matrices; SO(3) matrix temporal losses; no axis-angle motion conversion',fixed_local_joints=[fixed_names[i] for i in fixed_joints],fixed_local_joint_indices=list(fixed_joints),refinement_profile=refinement_profile,foot_objective_parts=list(foot_parts),foot_loss_scale=foot_scale,floor_objective_parts=list(cd.get('floor_parts',foot_parts)),floor_loss_scale=1. if cd.get('floor_parts') else foot_scale,status='unrefined_preview' if iterations==0 else 'experimental_candidate',before=metrics(before,joints),after=metrics(after,after_joints),
        root_hand_coupling=plan.get('root_hand_coupling'),root_motion_before=root_metrics(root),root_motion_after=root_metrics(final_root),
        hand_orientation_before=direction_metrics(before_direction),hand_orientation_after=direction_metrics(after_direction),
        optimization=logs,grasp_surface_point_room=None if surface is None else surface.tolist(),patch_vertices={k:v.tolist() for k,v in parts.items()},
        foot_contact_source='Metrics always use unchanged independent Kimodo heel/toe labels; historical control objective alone reproduces side averaging.',frames=len(root),fps=30,
        limitations=['Prescribed object kinematics; no force or friction simulation.',
         'Fixed mean hand pose; palm patch contact does not establish articulated finger grasp.',
         'No full scene collision or balance guarantee; inspect rendered sequence.',
         'Generated action, not estimated source-video motion.'])
    write_json(out/'contact_report.json',report)
    faces=skin.faces.cpu().numpy()
    np.savez_compressed(out/'mesh.npz',vertices=after@KIMODO_TO_ROOM.T,joints=after_joints@KIMODO_TO_ROOM.T,
        baseline_vertices=before@KIMODO_TO_ROOM.T,faces=faces,time_seconds=t,fps=30)
    # Reuse exact static demo geometry/materials; replace its source actors only.
    old={a['owner'] for a in (scene.get('animation') or {}).get('actors',[])}
    scene['objects']=[o for o in scene['objects'] if o['instance_id'] not in old]
    scene['meshes']=[m for m in scene['meshes'] if m['owner'] not in old]
    for key in ('tabletop','chairs'):scene.pop(key,None)
    if not plan.get('light_track'):scene.pop('lighting',None)
    # The material-editor card hides the standard animation/stage controls.
    if scene.get('quick_actions',{}).get('editor_card'):
        scene['quick_actions']=dict(scene['quick_actions'])
        scene['quick_actions'].pop('editor_card')
    actor_records=[]
    direction_tracks={}
    root_tracks={'generated-person':final_root@KIMODO_TO_ROOM.T,'before-refinement':root@KIMODO_TO_ROOM.T}
    if direction is not None:
        direction_tracks={'generated-person':after_direction,'before-refinement':before_direction}
    variants=[('generated-person',after,[.12,.52,.46]),('before-refinement',before,[.7,.33,.13])]
    for file,name,color in [('raw_segments.npz','raw-segments',[.35,.42,.85]),('baseline.npz','route-baseline',[.65,.35,.7])]:
        if (out/file).exists():
            motion=dict(np.load(out/file));r=motion['root_positions'].copy();r[:,1]+=plan['floor_height']
            verts,_=skin_all(motion['local_rot_mats'],r);variants.append((name,verts,color))
            root_tracks[name]=r@KIMODO_TO_ROOM.T
            if direction is not None:direction_tracks[name]=direction_trace(motion['local_rot_mats'],r,verts)
    for name,verts,color in variants:
        vertices=(verts@KIMODO_TO_ROOM.T).astype('<f4')
        file=name+'.bin';vertices.tofile(out/file)
        mi=len(scene['materials']);scene['materials'].append(dict(name=name,color=color,roughness=.8,metalness=0))
        scene['objects'].append(dict(instance_id=name,semantic_class='animation/generated-human',movable=False))
        scene['meshes'].append(dict(name=name,owner=name,joint=None,surface='body',cutaway=False,
            matrix=np.eye(4).reshape(-1).tolist(),positions=vertices[0].reshape(-1).tolist(),
            groups=[dict(material=mi,indices=faces.reshape(-1).tolist())]))
        actor_records.append(dict(owner=name,mesh_name=name,vertex_count=vertices.shape[1],encoding='float32-le-world-xyz',
            positions_file=file,bounds=np.stack([vertices.min(1),vertices.max(1)],axis=1).tolist()))
    for o in scene['objects']:
        if o['instance_id']==plan['target_object']:o['movable']=False
    phases=[];start=0
    for seg,n in zip(plan['segments'],c['frames']):
        phases.append(dict(label=seg['name'],start_frame=start,end_frame=start+n));start+=n
    scene['interaction']=dict(object_tracks=[dict(owner=plan['target_object'],translations=c['object_translation'].tolist())],
        phases=phases,baseline_owner='before-refinement',hand_targets=c['hand'].tolist(),hand_contact_mask=c['hand_on'].tolist())
    if plan.get('light_track'):
        track=plan['light_track'];keys=np.asarray(track['keys'],dtype=float)
        scene['interaction']['light_tracks']=[dict(owner=track['owner'],values=np.interp(t,keys[:,0],keys[:,1]).tolist())]
    if plan.get('state_change'):scene['interaction']['state_change']=plan['state_change']
    for owner,offset in plan.get('scene_offsets',{}).items():
        scene['interaction']['object_tracks'].append(dict(owner=owner,translations=np.tile(offset,(len(root),1)).tolist()))
    scene['interaction']['variants']=[dict(owner=name,label=label) for name,label in [
        ('raw-segments','1 · Raw Kimodo segment samples'),('before-refinement','2 · Native joined / before optimization'),
        ('generated-person','3 · After 6D contact optimization'),('route-baseline','Optional · Route/text first pass')]
        if name in {v[0] for v in variants}]
    scene['interaction']['hand_direction_tracks']={name:{k:v.tolist() for k,v in trace.items()} for name,trace in direction_tracks.items()}
    scene['interaction']['hand_orientation_goal']=plan.get('hand_orientation')
    scene['interaction']['root_coupling']=dict(goal_xy=c['root_xy'].tolist(),tracks={k:v.tolist() for k,v in root_tracks.items()},floor_height=plan['floor_height']) if plan.get('root_hand_coupling') else None
    scene['interaction']['default_variant']='generated-person'
    if iterations==0:
        for variant in scene['interaction']['variants']:
            if variant['owner']=='generated-person':
                variant['label']='Native review / no scene optimization'
    scene['interaction']['provenance']='Raw segments are actual captured samples before native postprocessing. Later segments use previous-motion context; they are not independent draws.'
    scene['animation']=dict(frames=len(root),fps=30,start_frame=1,duration_seconds=len(root)/30,actors=actor_records,
        description='Kimodo generated interaction. Select a step and motion artifact to compare raw, joined and refined motion. The orange marker is the planned hand target.')
    scene['title']=plan.get('title','Generated interaction · pull out a chair and sit')
    scene['description']=f'{len(root)/30:g}-second experimental sequence · orbit, scrub, and compare before/after contact refinement'
    scene['capability_note']='Generated motion with prescribed object movement. Finger grasp, full-body collision and dynamic balance remain unverified.'
    scene['views']['orbit']=plan.get('orbit_view',dict(position=[.25,-2.8,2.5],target=[.6,1.2,.85],fov=48))
    center=np.mean(c['root_xy'],axis=0).tolist()
    scene['views']['plan']=plan.get('plan_view',dict(position=[*center,7],target=[*center,0],fov=48))
    write_json(out/'scene.json',scene)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
