"""Task-local root-translation ablations. Outputs are proposals, never accepted motion."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import least_squares

NAMES=['left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle','left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist']
SMPL=np.array([1,2,4,5,7,8,16,17,18,19,20,21])
DEFAULTS=dict(shared_xy_max=.5,shared_z_max=.1,deformation_max=.3,knot_seconds=1.5,
 pixel_sigma=15.,robust_delta=1.5,shared_prior_sigma=.5,deformation_prior_sigma=.3,
 velocity_sigma=.3,acceleration_sigma=1.,contact_speed_sigma=.03,plant_sigma=.025,
 weak3d_sigma=.3,floor_sigma=.01,max_nfev=200,floor_z=0.,min_joints_per_sample=4)


def project(joints,C,K):
    q=np.einsum('tji,tkj->tki',C[:,:3,:3],joints-C[:,None,:3,3])
    h=np.einsum('tij,tkj->tki',K,q)
    return h[...,:2]/np.maximum(q[...,2:],.05),q[...,2]


def bounded_ball(x,radius):
    norm=np.linalg.norm(x,axis=-1,keepdims=True)
    factor=np.ones_like(norm)
    np.divide(np.tanh(norm),norm,out=factor,where=norm>1e-9)
    return radius*x*factor


def cubic_basis(times,knot_seconds):
    lo,hi=times[0],times[-1]
    interior=np.arange(lo+knot_seconds,hi-1e-10,knot_seconds)
    knots=np.r_[np.repeat(lo,4),interior,np.repeat(hi,4)]
    count=len(knots)-4
    B=BSpline(knots,np.eye(count),3,extrapolate=False)(times)
    if not np.allclose(B.sum(1),1) or np.min(B)<-1e-12:raise ValueError('Invalid convex spline basis')
    return B,knots


def stats(x):
    x=np.asarray(x)
    return dict(n=int(x.size),median=float(np.median(x)) if x.size else None,p90=float(np.percentile(x,90)) if x.size else None,max=float(x.max()) if x.size else None)


def fit_variants(joints,vertices,times,camera_to_world,K,observations,config=None,*,contact_centers=None,observed_contact=None,scope=None):
    cfg=dict(DEFAULTS)
    if config:
        if set(config)-set(cfg):raise ValueError('Unknown configuration')
        cfg.update(config)
    if any(not np.isfinite(v) or (v<=0 and k!='floor_z') for k,v in cfg.items()):raise ValueError('Invalid configuration')
    t=np.asarray(times,float);j=np.asarray(joints,float);v=np.asarray(vertices);C=np.asarray(camera_to_world,float);K=np.asarray(K,float)
    T=len(t)
    if T<4 or j.ndim!=3 or j.shape[0]!=T or j.shape[1]<22 or j.shape[2]!=3 or v.ndim!=3 or v.shape[0]!=T or v.shape[2]!=3 or C.shape!=(T,4,4) or K.shape!=(T,3,3):raise ValueError('Input shapes differ')
    if not all(np.isfinite(a).all() for a in (t,j,v,C,K)) or not (np.diff(t)>0).all():raise ValueError('Nonfinite or invalid timing')
    if not np.allclose(np.diff(t),np.median(np.diff(t)),atol=1e-6):raise ValueError('Uniform output timeline required')
    if not np.allclose(C[:,3],[0,0,0,1]) or not np.allclose(C[:,:3,:3].transpose(0,2,1)@C[:,:3,:3],np.eye(3),atol=1e-5) or np.any(np.linalg.det(C[:,:3,:3])<.999):raise ValueError('Invalid rigid camera')
    if not np.allclose(K[:,2],[0,0,1]) or np.any(K[:,0,0]<=0) or np.any(K[:,1,1]<=0):raise ValueError('Invalid camera intrinsics')
    scope=np.ones(T,bool) if scope is None else np.asarray(scope,bool)
    if scope.shape!=(T,) or not scope.any():raise ValueError('Invalid scope')
    ot=np.asarray(observations['time_seconds'],float);uv=np.asarray(observations['uv'],float);mask=np.asarray(observations['valid'],bool).copy()
    if list(observations['joint_names'])!=NAMES:raise ValueError('Explicit anatomical joint order mismatch')
    if ot.ndim!=1 or len(ot)<4 or not np.isfinite(ot).all() or not (np.diff(ot)>0).all() or uv.shape!=(len(ot),12,2) or mask.shape!=(len(ot),12):raise ValueError('Invalid observations')
    ids=np.abs(t[:,None]-ot[None,:]).argmin(0)
    if np.max(np.abs(t[ids]-ot))>np.median(np.diff(t))/2+1e-6 or len(np.unique(ids))!=len(ids):raise ValueError('Observation times mismatch output timeline')
    if not np.isfinite(uv[mask]).all():raise ValueError('Nonfinite valid UV')
    uv=np.where(mask[:,:,None],uv,0.)
    mask &= scope[ids,None]
    mask &= (mask.sum(1)>=cfg['min_joints_per_sample'])[:,None]
    train=np.arange(len(ot))%2==0;heldout=~train
    trainmask=mask&train[:,None]
    if (trainmask.sum(1)>0).sum()<2:raise ValueError('Insufficient training timestamps')
    # Fixed split includes invalid rows, so review exclusions cannot alter parity.
    if contact_centers is None:
        feet=np.stack([j[:,[7,10]].mean(1),j[:,[8,11]].mean(1)],axis=1)
        foot_source='baseline ankle/toe joint mean; not mesh-contact points'
    else:
        feet=np.asarray(contact_centers,float);foot_source='caller supplied immutable baseline foot mesh centers'
    if feet.shape!=(T,2,3) or not np.isfinite(feet).all():raise ValueError('Invalid contact centers')
    dt=np.diff(t);base_speed=np.linalg.norm(np.diff(feet,axis=0)/dt[:,None,None],axis=2)
    if observed_contact is None:
        speed=np.r_[base_speed[:1],base_speed]
        low=np.percentile(feet[scope,:,2],5)
        contact=(feet[:,:,2]<=low+.08)&(speed<=.15)
        contact_source='model-derived immutable baseline low/slow mask'
    else:
        contact=np.asarray(observed_contact,bool).copy();contact_source='caller supplied immutable observed contact mask'
    if contact.shape!=(T,2):raise ValueError('Invalid contact mask')
    contact &= scope[:,None]
    edge_contact=contact[1:]&contact[:-1]
    all_edges=scope[1:]&scope[:-1]
    # Each fixed contact interval has one baseline plant anchor; global shared
    # relocation moves that anchor too. Root deformation must respect its plant.
    anchors=feet.copy()
    for foot in range(2):
        ids_c=np.flatnonzero(contact[:,foot]);groups=np.split(ids_c,np.flatnonzero(np.diff(ids_c)>1)+1)
        for group in groups:
            if len(group):anchors[group,foot]=np.median(feet[group,foot],axis=0)
    B,knots=cubic_basis(t,cfg['knot_seconds']);tau=(t-t.mean())/((t[-1]-t[0])/2)
    floor_min=v[:,:,2].min(1)
    weak=None
    if 'sam_camera_joints' in observations and 'weak3d_valid' in observations and bool(observations.get('sam_camera_opencv_confirmed',False)):
        sam=np.asarray(observations['sam_camera_joints'],float)
        if sam.ndim!=3 or sam.shape[0]!=len(ot) or sam.shape[1]<15 or sam.shape[2]!=3:raise ValueError('Invalid SAM camera joints')
        hip=sam[:,[9,10]].mean(1)
        world=np.einsum('tij,tj->ti',C[ids,:3,:3],hip)+C[ids,:3,3]
        weak_scope=np.asarray(observations['weak3d_valid'],bool)
        if weak_scope.shape!=(len(ot),):raise ValueError('Invalid weak3d validity shape')
        wm=train&mask[:,0]&mask[:,1]&np.isfinite(world).all(1)&(hip[:,2]>.05)&weak_scope
        if wm.sum()>=2:weak=(world,wm)
    variants=['baseline','shared_xyz','affine_drift','spline','spline_contact']
    if weak is not None:variants+=['spline_contact_weak3d']
    results={}
    for variant in variants:
        controls=0 if variant in ('baseline','shared_xyz') else 1 if variant=='affine_drift' else B.shape[1]
        def unpack(x):
            shared=np.r_[bounded_ball(x[:2],cfg['shared_xy_max']),np.tanh(x[2])*cfg['shared_z_max']]
            if controls==0:deform=np.zeros((T,3))
            else:
                points=bounded_ball(x[3:].reshape(controls,3),cfg['deformation_max'])
                deform=tau[:,None]*points[0] if variant=='affine_drift' else B@points
            return shared,deform
        def residual(x):
            shared,deform=unpack(x);offset=shared+deform
            puv,depth=project(j[ids][:,SMPL]+offset[ids,None,:],C[ids],K[ids])
            r=((puv-uv)[trainmask]/cfg['pixel_sigma']).ravel();delta=cfg['robust_delta']
            robust=np.sign(r)*np.sqrt(2*delta**2*(np.sqrt(1+(r/delta)**2)-1))
            chunks=[robust/np.sqrt(trainmask.sum()),np.minimum(depth[trainmask]-.05,0)*10/np.sqrt(trainmask.sum()),shared/cfg['shared_prior_sigma'],
                np.minimum(floor_min[scope]+offset[scope,2]-cfg['floor_z'],0)/cfg['floor_sigma']/np.sqrt(scope.sum())]
            if controls:
                chunks.extend([deform.ravel()/cfg['deformation_prior_sigma']/np.sqrt(T),
                    (np.diff(deform,axis=0)/dt[:,None]).ravel()/cfg['velocity_sigma']/np.sqrt(T-1),
                    (np.diff(deform,n=2,axis=0)/np.median(dt)**2).ravel()/cfg['acceleration_sigma']/np.sqrt(T-2)])
            if 'contact' in variant:
                moved=feet+offset[:,None,:]
                velocity=np.diff(moved,axis=0)/dt[:,None,None]
                if edge_contact.any():chunks.append(velocity[edge_contact].ravel()/cfg['contact_speed_sigma']/np.sqrt(edge_contact.sum()))
                if contact.any():chunks.append((moved-anchors-shared)[contact].ravel()/cfg['plant_sigma']/np.sqrt(contact.sum()))
            if variant=='spline_contact_weak3d':
                world,wm=weak;pred=j[ids][:,[1,2]].mean(1)+offset[ids]
                displacement=(pred[wm]-pred[wm].mean(0))-(world[wm]-world[wm].mean(0))
                chunks.append(displacement.ravel()/cfg['weak3d_sigma']/np.sqrt(wm.sum()))
            return np.concatenate(chunks)
        if variant=='baseline':
            shared=np.zeros(3);deform=np.zeros((T,3));fit=None
        else:
            fit=least_squares(residual,np.zeros(3+3*controls),max_nfev=int(cfg['max_nfev']),loss='linear')
            shared,deform=unpack(fit.x)
        offset=shared+deform
        before,bdepth=project(j[ids][:,SMPL],C[ids],K[ids]);after,adepth=project(j[ids][:,SMPL]+offset[ids,None,:],C[ids],K[ids])
        err_before=np.linalg.norm(before-uv,axis=2);err_after=np.linalg.norm(after-uv,axis=2)
        moved=feet+offset[:,None,:];speed=np.linalg.norm(np.diff(moved,axis=0)/dt[:,None,None],axis=2)
        correction_speed=np.linalg.norm(np.diff(offset,axis=0)/dt[:,None],axis=1)
        correction_accel=np.linalg.norm(np.diff(offset,n=2,axis=0)/np.median(dt)**2,axis=1)
        report=dict(variant=variant,proposal_only=True,accepted=False,scale=1.,pose_shape_orientation_unchanged=True,
            config=cfg,optimizer_success=bool(fit.success) if fit else True,optimizer_evaluations=int(fit.nfev) if fit else 0,
            optimizer_message=str(fit.message) if fit else 'unchanged baseline',optimizer_cost=float(fit.cost) if fit else None,
            observations=len(ot),train_rows=np.flatnonzero(train).tolist(),heldout_rows=np.flatnonzero(heldout).tolist(),observation_frame_indices=ids.tolist(),
            anatomy=NAMES,smpl_joint_indices=SMPL.tolist(),shared_offset_m=shared.tolist(),
            max_deformation_m=float(np.linalg.norm(deform,axis=1).max()),max_total_offset_m=float(np.linalg.norm(offset,axis=1).max()),
            correction_speed_mps=stats(correction_speed),correction_acceleration_mps2=stats(correction_accel),
            contact_source=contact_source,foot_center_source=foot_source,contact_samples=int(contact.sum()),contact_edge_samples=int(edge_contact.sum()),
            contact_status='fixed_cohort_available' if edge_contact.any() else 'unverified_empty_cohort',
            contact_speed_before_mps=stats(base_speed[edge_contact]),contact_speed_after_mps=stats(speed[edge_contact]),
            all_scope_foot_speed_before_mps=stats(base_speed[all_edges]),all_scope_foot_speed_after_mps=stats(speed[all_edges]),
            penetration_before_m=stats(np.maximum(cfg['floor_z']-floor_min[scope],0)),penetration_after_m=stats(np.maximum(cfg['floor_z']-floor_min[scope]-offset[scope,2],0)),
            training_uv_before_px=stats(err_before[trainmask]),training_uv_after_px=stats(err_after[trainmask]),
            heldout_uv_before_px=stats(err_before[mask&heldout[:,None]]),heldout_uv_after_px=stats(err_after[mask&heldout[:,None]]),
            training_behind_before=int((bdepth[trainmask]<=.05).sum()),training_behind_after=int((adepth[trainmask]<=.05).sum()),
            heldout_behind_before=int((bdepth[mask&heldout[:,None]]<=.05).sum()),heldout_behind_after=int((adepth[mask&heldout[:,None]]<=.05).sum()),
            weak3d_training_rows=np.flatnonzero(weak[1]).tolist() if variant=='spline_contact_weak3d' else [],
            spline_degree=3 if controls>1 else None,spline_knots=knots.tolist() if controls>1 else None,
            weak3d_enabled=variant=='spline_contact_weak3d',weak3d_note='SAM camera hip temporal displacement, train-only mean subtraction; absolute depth is not ground truth',
            caveats=['Only training timestamp UV enters optimization; heldout UV is reporting only.','Root translation proposals require independent detector, immutable contact and visual evaluation.','Spline decomposition is regularized; shared/deformation split is not independently identifiable.','No native shape, pose, scale, orientation, camera or baseline arrays are changed.'])
        results[variant]=dict(offsets=offset,offsets_world=offset,shared_offset=shared,deformation=deform,report=report)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('cache','camera','observations','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--contacts',type=Path);p.add_argument('--config',type=Path);p.add_argument('--sam-opencv-confirmed',action='store_true')
    a=p.parse_args()
    with np.load(a.cache,allow_pickle=False) as z:cache={k:z[k] for k in z.files}
    with np.load(a.camera,allow_pickle=False) as z:camera={k:z[k] for k in z.files}
    with np.load(a.observations,allow_pickle=False) as z:obs={k:z[k] for k in z.files}
    obs['sam_camera_opencv_confirmed']=a.sam_opencv_confirmed
    extra={}
    if a.contacts:
        with np.load(a.contacts,allow_pickle=False) as z:
            if 'time_seconds' not in z or not np.array_equal(z['time_seconds'],cache['time_seconds']):raise ValueError('Contact/cache time_seconds missing or mismatched')
            for key in ('contact_centers','observed_contact','scope'):
                if key in z:extra[key]=z[key]
    cfg=json.loads(a.config.read_text()) if a.config else None
    # Camera field aliases are explicit; never infer a camera inverse.
    C=camera['c2w'] if 'c2w' in camera else camera['camera_to_world'] if 'camera_to_world' in camera else camera['camera_to_world_cv']
    if 'time_seconds' not in camera or not np.array_equal(camera['time_seconds'],cache['time_seconds']):raise ValueError('Camera/cache time_seconds missing or mismatched')
    K=camera['K'] if 'K' in camera else camera['intrinsics']
    if K.shape==(3,3):K=np.repeat(K[None],len(cache['time_seconds']),axis=0)
    results=fit_variants(cache['joints'],cache['vertices'],cache['time_seconds'],C,K,obs,cfg,**extra)
    a.output.mkdir(parents=True,exist_ok=False)
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        return h.hexdigest()
    provenance={str(path.resolve()):digest(path) for path in [a.cache,a.camera,a.observations,Path(__file__),*([a.contacts] if a.contacts else []),*([a.config] if a.config else [])]}
    for name,result in results.items():
        out=a.output/name;out.mkdir()
        np.savez(out/'offsets.npz',time_seconds=cache['time_seconds'],offsets_world=result['offsets'],shared_offset=result['shared_offset'],deformation=result['deformation'])
        (out/'report.json').write_text(json.dumps(result['report'],indent=2)+'\n')
    (a.output/'summary.json').write_text(json.dumps(dict(proposal_only=True,variants=list(results),inputs=provenance),indent=2)+'\n')

if __name__=='__main__':main()
