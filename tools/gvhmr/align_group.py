"""Fit constant rigid gravity-preserving actor transforms in locked native units.

Projection targets are GVHMR incam estimates, not observed ground-truth joints.
Native global trajectories are retained; this never uses frame-dependent roots.
"""
from pathlib import Path
import argparse, hashlib, json, sys
import numpy as np
from scipy.optimize import least_squares


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def gravity_rotation(yaw, up):
    c,s=np.cos(yaw),np.sin(yaw)
    return np.array([[c,-s,0],[s,c,0],[0,0,1.]])@up


def project(joints, camera, K):
    q=np.einsum('tji,tkj->tki',camera[:,:3,:3],joints-camera[:,None,:3,3])
    h=q@K.transpose(0,2,1)
    return h[...,:2]/np.maximum(h[...,2:],.05),q[...,2]


def apparent_height_ratios(target, projected, joint_valid):
    """Head-to-mean-foot image extent on frames with all three target joints visible."""
    selected=np.asarray(joint_valid)[:,[15,10,11]].all(1)
    source_height=target[:,[10,11],1].mean(1)-target[:,15,1]
    rendered_height=projected[:,[10,11],1].mean(1)-projected[:,15,1]
    selected &= source_height>50
    return rendered_height[selected]/source_height[selected],selected


COCO_SUPPORT = ((11,12),(11,),(12,),(5,6,11,12),(13,),(14,),
                (5,6,11,12),(15,),(16,),(5,6,11,12),(15,),(16,),
                (5,6),(5,),(6,),(0,),(5,),(6,),(7,),(8,),(9,),(10,))


def pose_evidence_mask(keypoints, native_times, sample_times, image_size, threshold=.5):
    """Map COCO heatmap support to SMPL22; nearest time with half-step tolerance."""
    kp=np.asarray(keypoints);nt=np.asarray(native_times);times=np.asarray(sample_times)
    if kp.shape!=(len(nt),17,3) or len(nt)<2 or not np.isfinite(kp).all() or not np.isfinite(nt).all() or not np.all(np.diff(nt)>0):
        raise ValueError('Invalid COCO17 confidence samples or native timestamps')
    if len(times)<1 or not np.isfinite(times).all() or not np.all(np.diff(times)>0):raise ValueError('Invalid requested confidence timestamps')
    cadence=float(np.median(np.diff(nt)))
    if not np.allclose(np.diff(nt),cadence,atol=1e-6):raise ValueError('Confidence timestamps must have uniform cadence')
    index=np.abs(nt[:,None]-times[None,:]).argmin(0);error=np.abs(nt[index]-times)
    tolerance=cadence/2+1e-6
    if (error>tolerance).any():raise ValueError('Confidence timestamps do not cover requested motion')
    sampled=kp[index]
    observed=(sampled[:,:,2]>.5)&(sampled[:,:,0]>=0)&(sampled[:,:,0]<image_size[0])&(sampled[:,:,1]>=0)&(sampled[:,:,1]<image_size[1])
    if threshold!=.5:raise ValueError('Reviewed evidence threshold is fixed at upstream 0.5')
    mask=np.stack([observed[:,list(ids)].all(1) for ids in COCO_SUPPORT],axis=1)
    return mask,dict(threshold=.5,source_layout='COCO17 x,y,heatmap maxval',mapping_smpl22_to_coco17=[list(x) for x in COCO_SUPPORT],
        resampling='nearest native timestamp',native_cadence_seconds=cadence,maximum_time_error_seconds=float(error.max()),time_tolerance_seconds=tolerance,
        confidence_joint_frames=mask.sum(0).tolist(),native_frames=len(nt),output_frames=len(times))


def fit_group(actors, camera, K, cfg):
    up=np.asarray(cfg['up_rotation'],float)
    if up.shape!=(3,3) or not np.allclose(up.T@up,np.eye(3),atol=1e-6) or np.linalg.det(up)<.999 or not np.allclose(up@[0,1,0],[0,0,1],atol=1e-6):
        raise ValueError('Reviewed up_rotation must map native Y up to room Z up')
    floor=float(cfg.get('floor_z',0));clearance=float(cfg.get('clearance',.005))
    forbidden={'scale_anchor','scale_bounds','scale_prior_sigma','body_scale','shared_scale','optimize_scale'} & cfg.keys()
    if forbidden:raise ValueError('Scale-fitting configuration is prohibited: '+', '.join(sorted(forbidden)))
    initial=[]
    for actor in actors:
        old=actor['old'];relative=np.asarray(old['rotation'])@up.T
        yaw=np.arctan2(relative[1,0]-relative[0,1],relative[0,0]+relative[1,1])
        R=gravity_rotation(yaw,up)
        oldroot=actor['native_joints'][:,0]@np.asarray(old['rotation']).T*old['body_scale']+old['translation']
        xy=np.median(oldroot[:,:2]-(actor['native_joints'][:,0]@R.T)[:,:2],axis=0)
        initial.extend([yaw,*xy])
        actor['support']=float(np.median((actor['native_vertices'][actor.get('support_valid',actor['valid'])]@up.T)[:,:,2].min(1)))
    def world(x,idx):
        yaw,tx,ty=x[3*idx:3+3*idx]
        R=gravity_rotation(yaw,up);t=np.array([tx,ty,floor+clearance-actors[idx]['support']])
        return (actors[idx]['native_joints']@R.T)+t,R,t
    weights=np.ones(22);weights[[16,17,18,19,20,21]]=.35
    weights[[0,7,8,10,11,12,15]]=1.5
    def residual(x):
        pieces=[]
        for i,actor in enumerate(actors):
            j,_,_=world(x,i);uv,depth=project(j,camera,K)
            mask=actor['joint_valid']
            # Every actor contributes comparable weight despite visibility duration.
            norm=np.sqrt(max(mask.sum(),1)/500)
            pieces.extend([((uv-actor['target'])*weights[None,:,None])[mask].ravel()/10/norm,
                           np.minimum(depth[mask]-.1,0).ravel()*100/norm])
        return np.concatenate(pieces)
    fit=least_squares(residual,initial,loss='soft_l1',f_scale=2,max_nfev=400)
    return fit,world,residual


def rebase_layout_gate(manifest,base):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from aha3d.workflow.layout_gate import PATH_FIELDS,ALIASES
    result=dict(manifest['layout_gate'])
    for key in (*PATH_FIELDS,*ALIASES,'review_dir'):
        if result.get(key):result[key]=str((Path(base)/result[key]).resolve())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--camera-cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    m=json.loads(a.manifest.read_text())
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from aha3d.workflow.layout_gate import validate_layout
    if m.get('render',{}).get('source_video') and m['render'].get('camera_cache'):
        if (a.manifest.parent/m['render']['camera_cache']).resolve()!=a.camera_cache.resolve():
            raise ValueError('Alignment camera differs from layout-reviewed render camera_cache')
    layout_validation=validate_layout(m,a.manifest)
    if m.get('task_scope'):m['task_scope']=str((a.manifest.parent/m['task_scope']).resolve())
    from aha3d.workflow.acceptance import consumer_prerequisite
    consumer_prerequisite(m,a.manifest,'people')
    cfg=m['group_alignment'];actors=[]
    ids=[x['id'] for x in m['actors']]
    if not ids or len(set(ids))!=len(ids) or any(not isinstance(x,str) or not x or Path(x).name!=x or x in ('.','..') for x in ids):raise ValueError('Actor IDs must be unique safe path components')
    if a.output.exists():raise FileExistsError(a.output)
    with np.load(a.camera_cache) as z:camera=z['c2w'];K=z['K'];times=z['time_seconds'];size=z['image_size']
    for actor in m['actors']:
        resolve=lambda key:(a.manifest.parent/actor[key]).resolve()
        old=json.loads(resolve('alignment').read_text())
        diag=(a.manifest.parent/actor['diagnostics']).resolve() if actor.get('diagnostics') else resolve('alignment').parent/'alignment_diagnostics.npz'
        with np.load(resolve('cache')) as z:cache={k:z[k] for k in z.files}
        with np.load(diag) as z:verts=z['global_vertices'];target=z['target_uv']
        if not np.array_equal(cache['time_seconds'],times) or len(target)!=len(times):raise ValueError('Timing differs from reviewed camera')
        R=np.asarray(old['rotation']);t=np.asarray(old['translation']);s=old['body_scale']
        reconstructed=s*(verts@R.T)+t
        error=float(np.max(np.abs(reconstructed-cache['vertices'])))
        if error>5e-5:raise ValueError('Native diagnostic vertices do not reproduce input cache')
        joints=(cache['joints']-t)@R/s
        valid=np.ones(len(times),bool)
        for lo,hi in actor.get('exclude_seconds',[]):valid &= ~((times>=lo)&(times<=hi))
        joint_valid=valid[:,None]&np.isfinite(target).all(2)&(target[:,:,0]>=0)&(target[:,:,0]<size[0])&(target[:,:,1]>=0)&(target[:,:,1]<size[1])
        evidence_report=None;support_valid=valid.copy()
        default_confidence=resolve('motion').parent/'preprocess'/'vitpose.pt'
        if not actor.get('pose_confidence') and default_confidence.is_file():actor['pose_confidence']=str(default_confidence)
        if actor.get('pose_confidence'):
            import torch
            confidence_path=resolve('pose_confidence')
            keypoints=torch.load(confidence_path,map_location='cpu',weights_only=True).numpy()
            with np.load(resolve('motion')) as native: native_times=native['frame_times_seconds']
            evidence,evidence_report=pose_evidence_mask(keypoints,native_times,times,size)
            evidence_report.update(sha256=digest(confidence_path),path=str(confidence_path),before_joint_frames=joint_valid.sum(0).tolist())
            joint_valid &= evidence
            support_valid &= evidence[:,[7,8]].all(1)
            evidence_report.update(after_joint_frames=joint_valid.sum(0).tolist(),support_frames=int(support_valid.sum()))
        if support_valid.sum()<3:raise ValueError('Insufficient confident grounded ankle frames')
        if joint_valid.sum()<100:raise ValueError('Insufficient valid projection evidence')
        if not np.isfinite(verts).all() or not np.isfinite(joints).all():raise ValueError('Nonfinite native body geometry')
        actors.append(dict(spec=actor,old=old,cache=cache,native_vertices=verts,native_joints=joints,target=target,valid=valid,support_valid=support_valid,evidence_report=evidence_report,joint_valid=joint_valid,reproduction_error=error,paths={k:resolve(k) for k in ('cache','motion','alignment')},diagnostics=diag))
    fit,world,residual=fit_group(actors,camera,K,cfg)
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    scale=1.;results=[];contact_actors=[]
    for idx,actor in enumerate(actors):
        spec=actor['spec'];out=a.output/spec['id'];out.mkdir()
        j,R,t=world(fit.x,idx);vertices=scale*(actor['native_vertices']@R.T)+t
        uv,depth=project(j,camera,K);mask=actor['joint_valid'];valid=actor['valid']
        err=np.linalg.norm(uv-actor['target'],axis=2)
        target_height=np.ptp(actor['target'][:,:,1],axis=1);render_height=np.ptp(uv[:,:,1],axis=1)
        normalized=err/np.maximum(target_height[:,None],50)
        p90=float(np.percentile(normalized[mask],90));behind=bool((depth[valid]<=.1).any())
        ratios,fullbody=apparent_height_ratios(actor['target'],uv,mask)
        ratio=float(np.median(ratios)) if len(ratios) else None
        ratio_bounds=cfg.get('apparent_height_ratio_bounds',[.85,1.15])
        height_ok=len(ratios)>=3 and ratio_bounds[0]<=ratio<=ratio_bounds[1]
        accepted=bool(fit.success and not behind and height_ok and p90<=float(cfg.get('max_projection_p90_body_fraction',.15)))
        report=dict(id=spec['id'],method='native_units_rigid_grounded',rotation=R.tolist(),translation=t.tolist(),body_scale=scale,
            shared_scale=scale,scale_policy='native_units_locked',scale_optimized=False,frames=len(times),fps=float(actor['cache']['fps']),native_up_mapping=cfg['up_rotation'],
            reprojection_px_median=float(np.median(err[mask])),reprojection_px_p90=float(np.percentile(err[mask],90)),
            reprojection_p90_body_fraction=p90,behind_camera=behind,behind_camera_frames=np.flatnonzero((depth<=.1).any(1)&valid).tolist(),accepted=accepted,
            apparent_height_ratio_median=ratio,apparent_height_fullbody_frames=int(fullbody.sum()),
            apparent_height_ratio_p10_p50_p90=np.percentile(ratios,[10,50,90]).tolist() if len(ratios) else [],
            apparent_height_frame_indices=np.flatnonzero(fullbody).tolist(),height_gate_passed=bool(height_ok),
            raw_alljoint_height_ratio_median=float(np.median((render_height/np.maximum(target_height,1))[valid])),
            body_mesh_height_native_m_median=float(np.median(np.ptp(actor['native_vertices'][valid,:,1],axis=1))),
            body_mesh_height_room_m_median=float(np.median(np.ptp(vertices[valid,:,2],axis=1))),
            pose_confidence_sha256=actor['evidence_report']['sha256'] if actor['evidence_report'] else None,pose_evidence=actor['evidence_report'],per_joint_reprojection_px_median=[float(np.median(err[:,k][mask[:,k]])) if mask[:,k].any() else None for k in range(22)],native_cache_reproduction_error_m=actor['reproduction_error'],excluded_seconds=spec.get('exclude_seconds',[]),
            source_targets='GVHMR incam joint projections; estimates, not ground truth',absolute_scale_validated=False,
            input_hashes={k:digest(v) for k,v in actor['paths'].items()},diagnostics_sha256=digest(actor['diagnostics']))
        (out/'alignment.json').write_text(json.dumps(report,indent=2))
        np.savez(out/'body_room.npz',**dict(actor['cache'],vertices=vertices.astype('f4'),joints=j.astype('f4')))
        np.savez(out/'projection_diagnostics.npz',target_uv=actor['target'],aligned_uv=uv,depth=depth,valid=valid,joint_valid=mask,time_seconds=times)
        report.update(alignment_sha256=digest(out/'alignment.json'),cache_sha256=digest(out/'body_room.npz'))
        results.append(report)
        clean={k:v for k,v in spec.items() if k!='diagnostics'};clean.update(cache=str(out/'body_room.npz'),alignment=str(out/'alignment.json'),motion=str(actor['paths']['motion']))
        if spec.get('pose_confidence'):clean['pose_confidence']=str((a.manifest.parent/spec['pose_confidence']).resolve())
        contact_actors.append(clean)
    report=dict(schema_version=1,shared_scale=scale,scale_policy='native_units_locked',scale_optimized=False,optimizer_variable_count=len(fit.x),accepted=all(x['accepted'] for x in results),camera_sha256=digest(a.camera_cache),actors=results,
        solver_config=cfg,code_sha256=digest(__file__),input_manifest_sha256=digest(a.manifest),optimizer_success=bool(fit.success),optimizer_message=fit.message,
        projection_targets_are_ground_truth=False,absolute_scale_validated=False,
        scale_uncertainty='Native SMPL-X dimensions are unchanged. Room/camera metric calibration must be established upstream; this solver cannot compensate by resizing people.',
        method='Native units locked; per-actor constant yaw and XY, constant grounded Z; no fitted scale or time-dependent root correction')
    report['layout_validation']=layout_validation
    (a.output/'group_report.json').write_text(json.dumps(report,indent=2))
    result=dict(m,actors=contact_actors,group_alignment={'report':str(a.output/'group_report.json')})
    if m.get('layout_gate'):
        result['layout_gate']=rebase_layout_gate(m,a.manifest.parent)
    if m.get('render'):
        result['render']=dict(m['render'])
        for key in ('scene','camera_cache','source_video','output_blend'):
            if result['render'].get(key):result['render'][key]=str((a.manifest.parent/result['render'][key]).resolve())
    (a.output/'manifest.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:report[k] for k in ('shared_scale','accepted','optimizer_success','scale_policy')},indent=2))
    print(json.dumps([{k:x[k] for k in ('id','reprojection_px_median','reprojection_p90_body_fraction','apparent_height_ratio_median','accepted')} for x in results],indent=2))
    if not report['accepted']:raise SystemExit(2)

if __name__=='__main__':main()
