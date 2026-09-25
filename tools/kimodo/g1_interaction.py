"""Generate native G1 state-changing interactions in reused RoomKit scenes.

Requires the deployed Kimodo G1 checkpoint, trimesh and fast-simplification.
Run with --batch JSON (actions: id, run, source_scene). One model/GPU is reused.
Outputs are review candidates, not robot control policies or physics simulations.
"""
import argparse,copy,json
from pathlib import Path
import numpy as np
import torch
from scipy.spatial.transform import Rotation
from aha3d.motion.kimodo_frame import sample_in_local_frame
from aha3d.motion.g1_interaction import ROOM,load_mesh,patches,HingeRig,fit,validate_state_change,support_report,fit_scene_support,authored_support_heights
from aha3d.motion.interaction import compile_plan,contact_envelope,FeatureConstraint,pelvis_position_constraint


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def numpy_motion(value):
    return {k:(v.detach().cpu().numpy() if isinstance(v,torch.Tensor) else v) for k,v in value.items() if isinstance(v,(torch.Tensor,np.ndarray))}


def curve(keys,t):
    keys=np.asarray(keys,float);return np.stack([np.interp(t,keys[:,0],keys[:,i]) for i in range(1,keys.shape[1])],-1)


def generate(model,rig,mesh,plan,out,source_scene):
    from kimodo.constraints import Root2DConstraintSet,RightHandConstraintSet,FullBodyConstraintSet
    from kimodo.motion_rep.conditioning import build_condition_dicts
    from kimodo.tools import seed_everything
    sk=model.skeleton;tensor=rig.tensor;c=validate_state_change(plan);times=c['times'];n=len(times)
    origin=np.array([-c['root_xy'][0,0],plan['floor_height'],c['root_xy'][0,1]])
    route=np.stack([-c['root_xy'][:,0],c['root_xy'][:,1]],-1)-origin[[0,2]]
    target=c['hand']@ROOM.T-origin
    contact_patch=plan.get('hand_contact_patch','fingertip')
    hand_normal=plan.get('hand_surface_normal')
    if c['hand_on'].any() and hand_normal is None and contact_patch!='legacy-centroid':
        raise ValueError('Review the contact surface and provide hand_surface_normal (room-space outward normal) before generating fingertip contact')
    if hand_normal is not None:
        hand_normal=np.asarray(hand_normal,float)
        if hand_normal.shape!=(3,) or not np.isfinite(hand_normal).all() or np.linalg.norm(hand_normal)<1e-6:
            raise ValueError('Expected finite nonzero room-space hand_surface_normal')
        hand_normal=hand_normal@ROOM.T
    stride=plan.get('root_path_stride',10)
    if type(stride) is not int or stride<1:raise ValueError('root_path_stride must be a positive integer')
    ids=np.unique(np.r_[np.arange(0,n,stride),np.cumsum([0]+c['frames'])[:-1],np.cumsum(c['frames'])-1])
    ids=ids[(ids>=0)&(ids<n)]
    initial=[]
    if plan.get('initial_pose_file'):
        pose=dict(np.load(plan['initial_pose_file'],allow_pickle=False))
        positions=pose['posed_joints'][:1];rotations=pose['global_rot_mats'][:1]
        if positions.shape!=(1,sk.nbjoints,3) or not np.isfinite(positions).all():
            raise ValueError('Initial pose must use the native G1 skeleton')
        if rotations.shape!=(1,sk.nbjoints,3,3) or not np.isfinite(rotations).all():
            raise ValueError('Initial pose must contain finite native G1 rotation matrices')
        if not np.allclose(rotations@rotations.swapaxes(-1,-2),np.eye(3),atol=1e-4) or not np.allclose(np.linalg.det(rotations),1.,atol=1e-4):
            raise ValueError('Initial pose rotations must be proper orthonormal matrices')
        initial=[FullBodyConstraintSet(sk,torch.tensor([0]),tensor(positions),tensor(rotations),tensor(route[:1]))]
        ids=ids[ids!=0]
    root_constraint=Root2DConstraintSet(sk,torch.as_tensor(ids),tensor(route[ids]))
    def heading(frames):return FeatureConstraint({'global_root_heading':(torch.as_tensor(frames),tensor(np.stack([np.cos(c['heading'][frames]),np.sin(c['heading'][frames])],-1)))})
    heading_ids=np.intersect1d(ids,np.unique(np.r_[np.arange(0,n,10),np.cumsum(c['frames'])-1]))
    if plan.get('heading_constraints',True) is False:heading_ids=np.array([],dtype=int)
    baseline_conditions=[root_constraint,*([heading(heading_ids)] if len(heading_ids) else []),*initial];conditions=list(baseline_conditions)
    prompts=[s['prompt'] for s in plan['segments']];records=[];text_calls=[]
    state={};native=model._generate;encoder=model.text_encoder
    def capture(texts,max_frames,**kw):
        index=state['index'];context=0 if index==0 else 12
        observed=model.motion_rep.unnormalize(kw['observed_motion']);first=model.motion_rep.get_root_pos(observed)[0,0,[0,2]].detach().cpu().numpy()
        if np.linalg.norm(first)>1e-4:raise ValueError('Noncanonical G1 continuation input')
        prefix=f"{state['pass']}-segment-{index+1}"
        np.savez_compressed(out/(prefix+'-input.npz'),observed=observed[0].detach().cpu().numpy(),mask=kw['motion_mask'][0].detach().cpu().numpy())
        frame_receipt={}
        result=sample_in_local_frame(model,native,texts,max_frames,receipt=frame_receipt,
            save_input=lambda obs,mask:np.savez_compressed(out/(prefix+'-local-input.npz'),
                observed=obs[0].detach().cpu().numpy(),mask=mask[0].detach().cpu().numpy()),**kw)
        unnormalized=model.motion_rep.unnormalize(result)
        shift=state.get('shift',np.zeros(2))
        positioned=model.motion_rep.translate_2d(unnormalized,tensor(shift)[None])
        motion=numpy_motion(model.motion_rep.inverse(positioned,is_normalized=False,return_numpy=False));motion={k:v[0] for k,v in motion.items()}
        np.savez_compressed(out/(prefix+'-raw.npz'),**motion)
        smooth=model.motion_rep.get_root_pos(positioned)[0,:, [0,2]].detach().cpu().numpy();state['shift']=smooth[-12]
        records.append(dict(pass_name=state['pass'],step=index+1,frames=len(motion['root_positions']),context_frames=context,raw_file=prefix+'-raw.npz',input_file=prefix+'-input.npz',raw_origin_xz=shift.tolist(),first_observed_root_xz=first.tolist(),local_frame=frame_receipt))
        state['index']+=1;return result
    def text_capture(texts,*args,**kwargs):text_calls.append(dict(pass_name=state['pass'],step=state['index']+1,texts=list(texts)));return encoder(texts,*args,**kwargs)
    def sample(name,constraints):
        state.clear();state.update(pass_name=name,**{'pass':name},index=0)
        seed_everything(plan['seed']);model._generate=capture;model.text_encoder=text_capture
        try:
            raw=model(prompts,c['frames'],constraint_lst=constraints,num_denoising_steps=plan['steps'],cfg_weight=[2.,2.],cfg_type='separated',num_samples=1,multi_prompt=True,num_transition_frames=12,post_processing=False,return_numpy=True,first_heading_angle=[float(c['heading'][0])])
        finally:model._generate=native;model.text_encoder=encoder
        return {k:v[0] for k,v in raw.items() if isinstance(v,np.ndarray)}
    print('G1 baseline',plan['title'],flush=True);baseline=sample('baseline',baseline_conditions);np.savez_compressed(out/'baseline.npz',**baseline)
    projected=rig.project(baseline);p=patches(mesh,contact_patch);strength=contact_envelope(times,plan['hand_contact_seconds'])
    contact_start,contact_end=plan['hand_contact_seconds']
    clearance_strength=contact_envelope(times,plan.get('hand_clearance_seconds',[max(0,contact_start-.5),contact_end+.5]))
    print('Author G1 hand poses in hinge space',flush=True)
    grounded=plan.get('require_ground_support',True)
    def refine(m,iterations,seat=None):
        if grounded:return fit_scene_support(rig,m,p,target,strength,iterations=iterations,root_xy=route,seat=seat,scene=source_scene,origin=origin,hand_normal=hand_normal,hand_clearance_strength=clearance_strength)
        return fit(rig,m,p,target,strength,iterations=iterations,root_xy=route,seat=seat,grounded=False,hand_normal=hand_normal,hand_clearance_strength=clearance_strength)
    authored,author_log=refine(projected,180)
    handids=np.unique(np.r_[np.flatnonzero(c['hand_on'])[::15],np.flatnonzero(c['hand_on'])[-1]])
    hands=RightHandConstraintSet(sk,torch.as_tensor(handids),tensor(authored['posed_joints'][handids]),tensor(authored['global_rot_mats'][handids]),tensor(route[handids]))
    remaining_heading_ids=np.setdiff1d(heading_ids,handids)
    conditions=[root_constraint,*([heading(remaining_heading_ids)] if len(remaining_heading_ids) else []),hands,*initial]
    if plan.get('pelvis_height_targets'):
        keys=np.asarray(plan['pelvis_height_targets']);hi=np.clip(np.rint(keys[:,0]*30).astype(int),0,n-1)
        conditions.append(pelvis_position_constraint(hi,tensor(route[hi]),tensor(keys[:,1]-plan['floor_height'])))
    def receipt(conditions):
        indices,values=build_condition_dicts(conditions)
        return {k:dict(indices=torch.cat(indices[k]).cpu().tolist(),values=torch.cat(values[k]).detach().cpu().tolist()) for k in indices}
    write(out/'constraint_receipt.json',dict(baseline=receipt(baseline_conditions),conditioned=receipt(conditions)))
    np.savez_compressed(out/'hand_constraints.npz',frames=handids,requested_points=target[handids],posed_joints=authored['posed_joints'][handids],global_rot_mats=authored['global_rot_mats'][handids])
    print('G1 conditioned generation',flush=True);joined=sample('conditioned',conditions);np.savez_compressed(out/'generated.npz',**joined)
    chunks=[(dict(np.load(out/r['raw_file'])),r['context_frames']) for r in records if r['pass_name']=='conditioned']
    raw_segments={k:np.concatenate([m[k][context:] for m,context in chunks]) for k in joined if all(k in m for m,_ in chunks)}
    np.savez_compressed(out/'raw_segments.npz',**raw_segments)
    before=rig.project(joined);np.savez_compressed(out/'projected.npz',**before)
    seat=None
    if plan.get('seat_contact_seconds'):
        goal=np.tile(np.asarray(plan['seat_point'])@ROOM.T-origin,(n,1));goal[:,1]=plan['pelvis_height_targets'][-1][1]-plan['floor_height']
        seat=(goal,contact_envelope(times,plan['seat_contact_seconds']))
    print('Refine G1 contact and support',flush=True);after,log=refine(before,300,seat)
    np.savez_compressed(out/'refined.npz',**after)
    write(out/'generation.json',dict(model='nvidia/Kimodo-G1-RP-v1',skeleton=sk.name,frames=n,fps=30,native_postprocessing=False,native_transition_frames=12,hand_key_frames=handids.tolist(),origin_native=origin.tolist(),plan=plan,hand_authoring_log=author_log))
    write(out/'text_encoder_receipt.json',text_calls);write(out/'segments.json',dict(segments=records,joined='Native multiprompt feature-space blending across 12-frame continuation; G1 human postprocessing disabled'))
    def metrics(m):
        gr=m['global_rot_mats'];jp=m['posed_joints'];j,v=p['right_hand'];hand=np.einsum('tij,j->ti',gr[:,sk.bone_index[j]],v)+jp[:,sk.bone_index[j]]
        on=c['hand_on'];report={'hand_proxy_mean_cm':float(np.linalg.norm(hand-target,axis=-1)[on].mean()*100),'hand_proxy_max_cm':float(np.linalg.norm(hand-target,axis=-1)[on].max()*100),'feet':{}}
        for i,key in enumerate(['left_heel','left_toe','right_heel','right_toe']):
            j,v=p[key];v=np.einsum('tij,vj->tvi',gr[:,sk.bone_index[j]],v)+jp[:,sk.bone_index[j],None];fc=m['foot_contacts'][:,i]>.5;adj=fc[1:]&fc[:-1]
            speed=np.linalg.norm(np.diff(v[:,:,[0,2]],axis=0),axis=-1).mean(-1)*3000
            report['feet'][key]=dict(contact_frames=int(fc.sum()),slip_cm_s=float(speed[adj].mean()) if adj.any() else None,max_penetration_cm=float(max(0,-v[:,:,1].min())*100))
        report['all_frame_support']=support_report(m,sk,p,authored_support_heights(m,sk,p,source_scene,origin))
        report['hand_contact_patch']=contact_patch
        # Object collision diagnostics were cancelled by the user. Contact and
        # foot-support metrics remain independent of this disabled audit.
        report['object_collision_detection']={'status':'disabled','reason':'user_request'}
        return report
    write(out/'contact_report.json',dict(before=metrics(before),after=metrics(after),rotation_representation='Bounded physical hinge angles reconstructed with sin/cos; unchanged native root orientation matrices; no axis-angle pose optimization',optimization=log,limitations=['Fixed rubber hands; hand proxy agreement does not establish finger grasp','Prescribed object tracks; no force/friction or dynamic balance simulation','No human postprocessing; native G1 may have foot skating and joint projection artifacts']))
    variants=[('raw-segments',raw_segments,'Raw G1 samples'),('native-joined',joined,'Native joined G1 (before hinge projection)'),('before-refinement',before,'Projected G1 / before contact fitting'),('generated-person',after,'G1 / after contact fitting'),('route-baseline',baseline,'Text and path baseline')]
    return c,origin,variants


def export_scene(sk,mesh,plan,source,out,c,origin,variants):
    scene=copy.deepcopy(source)
    for key in ('tabletop','chairs'):scene.pop(key,None)
    scene.get('quick_actions',{}).pop('editor_card',None)
    scene['animation']=dict(frames=len(c['times']),fps=30,start_frame=1,duration_seconds=len(c['times'])/30,actors=[],description='Native G1 rigid-link animation; choose motion stage')
    tracks=[dict(owner=plan['target_object'],translations=c['object_translation'].tolist())]
    robot_material=len(scene['materials']);scene['materials'].extend([dict(name='G1 light housing',color=[.62,.65,.67],roughness=.55,metalness=.3),dict(name='G1 dark joints and hands',color=[.045,.055,.065],roughness=.65,metalness=.2)])
    for owner,motion,label in variants:
        scene['objects'].append(dict(instance_id=owner,semantic_class='animation/generated-robot',movable=False))
        for name in dict.fromkeys(p['joint'] for p in mesh['parts']):
            jid=sk.bone_index[name];link=owner+'/'+name
            scene['objects'].append(dict(instance_id=link,support_id=owner,semantic_class='robot/link',movable=False))
            pos=(motion['posed_joints'][:,jid]+origin)@ROOM.T
            rot=ROOM@motion['global_rot_mats'][:,jid]@ROOM.T
            quats=Rotation.from_matrix(rot).as_quat();tracks.append(dict(owner=link,translations=pos.tolist(),quaternions=quats.tolist()))
        for p in mesh['parts']:
            v=mesh['vertices'][p['start']:p['end']]@ROOM.T;faces=mesh['faces'];faces=faces[(faces[:,0]>=p['start'])&(faces[:,0]<p['end'])]-p['start']
            dark=any(s in p['file'] for s in ('rubber','wrist','ankle','hip','waist'))
            scene['meshes'].append(dict(name=owner+'/'+p['file'],owner=owner+'/'+p['joint'],joint=None,surface='robot',cutaway=False,matrix=np.eye(4).reshape(-1).tolist(),positions=v.reshape(-1).tolist(),groups=[dict(material=robot_material+int(dark),indices=faces.reshape(-1).tolist())]))
    phases=[];f=0
    for seg,frames in zip(plan['segments'],c['frames']):phases.append(dict(label=seg['name'],start_frame=f,end_frame=f+frames));f+=frames
    light=[]
    if plan.get('light_track'):
        spec=plan['light_track'];light=[dict(owner=spec['owner'],values=curve(spec['keys'],c['times'])[:,0].tolist())]
    scene['interaction']=dict(object_tracks=tracks,light_tracks=light,phases=phases,hand_targets=c['hand'].tolist(),hand_contact_mask=c['hand_on'].tolist(),variants=[dict(owner=o,label=l) for o,m,l in variants],default_variant='generated-person',provenance='Native Kimodo G1 model. Gray robot uses official rigid-link meshes. Raw/joined motion retained; physical hinge projection and contact fitting are distinct stages. Object motion is prescribed, not simulated.',state_change=plan['state_change'])
    scene['title']=plan['title'];scene['views']['orbit']=plan['orbit_view'];scene['description']='G1 state-changing interaction candidate';scene['capability_note']='Fixed rubber hands; kinematic playback, not a real-robot controller.'
    write(out/'scene.json',scene)
    write(out/'state_report.json',dict(requested=plan['state_change'],initial_translation=c['object_translation'][0].tolist(),final_translation=c['object_translation'][-1].tolist(),max_translation_m=float(np.linalg.norm(c['object_translation']-c['object_translation'][0],axis=-1).max()),light_tracks=light))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path,required=True);p.add_argument('--actions',nargs='*');a=p.parse_args();batch=json.loads(a.batch.read_text())
    from kimodo import load_model
    model=load_model('Kimodo-G1-RP-v1',device='cuda:0');rig=HingeRig(model.skeleton);mesh=load_mesh(model.skeleton)
    if model.skeleton.name!='g1skel34':raise ValueError('Native G1 skeleton required')
    print('Robot mesh:',len(mesh['vertices']),'vertices;',len(mesh['faces']),'faces',flush=True)
    for action in batch['actions']:
        if a.actions and action['id'] not in a.actions:continue
        run=Path(action['run']);out=run/'stages';out.mkdir(exist_ok=True)
        if (out/'scene.json').exists():print('Preserving existing completed candidate',action['id'],flush=True);continue
        plan=json.loads((run/'snapshot/plan.json').read_text());plan['floor_height']=plan.get('floor_height_override',plan['floor_height'])
        if (out/'generated.npz').exists():raise FileExistsError('Incomplete generation exists; inspect and resume explicitly')
        write(run/'status.json',dict(status='generating',model='Kimodo-G1-RP-v1'))
        source_scene=json.loads(Path(action['source_scene']).read_text())
        c,origin,variants=generate(model,rig,mesh,plan,out,source_scene)
        export_scene(model.skeleton,mesh,plan,source_scene,out,c,origin,variants)
        write(run/'status.json',dict(status='candidate_generated',frames=len(c['times']),fps=30))
        print('Completed',action['id'],flush=True)


if __name__=='__main__':main()
