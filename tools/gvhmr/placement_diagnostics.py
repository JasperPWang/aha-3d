"""Observed-2D placement checks; diagnostic XY probes never alter body caches.

COCO/SMPL joint definitions and detector identity/confidence remain imperfect.
Passing this module establishes an observed-projection gate, not correct 3D motion.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from scipy.optimize import least_squares

SMPL = np.array([1,2,4,5,7,8,16,17,18,19,20,21])
COCO = np.array([11,12,13,14,15,16,5,6,7,8,9,10])
NAMES = ['left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle',
         'left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist']
DEFAULTS = dict(window_seconds=2., confidence_threshold=.5, min_supported_seconds=.4,
                min_frame_coverage=.5, min_joints_per_frame=4,
                max_p90_image_diagonal_fraction=.05, probe_disagreement_m=.10)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def configuration(given=None):
    cfg=dict(DEFAULTS)
    if given:
        if set(given)-set(cfg):raise ValueError('Unknown placement diagnostic configuration')
        cfg.update(given)
    if not all(np.isfinite(v) for v in cfg.values()):raise ValueError('Nonfinite configuration')
    if cfg['window_seconds']<=0 or cfg['min_supported_seconds']<=0 or not 0<cfg['min_frame_coverage']<=1 or not 1<=cfg['min_joints_per_frame']<=12 or cfg['confidence_threshold']<0 or cfg['max_p90_image_diagonal_fraction']<=0 or cfg['probe_disagreement_m']<=0:
        raise ValueError('Invalid diagnostic configuration')
    return cfg


def observed_samples(keypoints, observation_times, times, image_size, threshold=.5):
    kp=np.asarray(keypoints);ot=np.asarray(observation_times);times=np.asarray(times)
    if kp.shape!=(len(ot),17,3) or len(ot)<2 or not np.isfinite(kp).all() or not np.isfinite(ot).all() or not np.all(np.diff(ot)>0):raise ValueError('Invalid COCO17 observations/timing')
    if len(times)<2 or not np.isfinite(times).all() or not np.all(np.diff(times)>0):raise ValueError('Invalid motion timing')
    dt=float(np.median(np.diff(ot)))
    if not np.allclose(np.diff(ot),dt,atol=1e-6):raise ValueError('Observation timestamps must be uniform')
    idx=np.abs(ot[:,None]-times[None,:]).argmin(0);error=np.abs(ot[idx]-times);tol=dt/2+1e-6
    if (error>tol).any():raise ValueError('Observation timestamps do not cover motion')
    sample=kp[idx][:,COCO];uv=sample[:,:,:2]
    mask=(sample[:,:,2]>threshold)&(uv[:,:,0]>=0)&(uv[:,:,0]<image_size[0])&(uv[:,:,1]>=0)&(uv[:,:,1]<image_size[1])
    return uv,mask,dict(method='nearest native timestamp',maximum_error_seconds=float(error.max()),tolerance_seconds=tol,native_cadence_seconds=dt,source_frames=len(ot),output_frames=len(times))


def project(joints,camera,K):
    q=np.einsum('tji,tkj->tki',camera[:,:3,:3],joints-camera[:,None,:3,3])
    h=q@K.transpose(0,2,1)
    return h[...,:2]/np.maximum(h[...,2:],.05),q[...,2]


def window_masks(times, valid, seconds, minimum_seconds):
    dt=float(np.median(np.diff(times)));end=float(times[-1]+dt)
    edges=list(np.arange(times[0],end,seconds))+[end]
    if len(edges)>2 and edges[-1]-edges[-2]<minimum_seconds:edges.pop(-2)
    return [(float(lo),float(hi),(times>=lo)&(times<hi)&valid) for lo,hi in zip(edges[:-1],edges[1:])]


def projection_stats(predicted,observed,mask,diagonal):
    error=np.linalg.norm(predicted-observed,axis=2)[mask]
    return dict(samples=int(mask.sum()),median_px=float(np.median(error)) if len(error) else None,
                p90_px=float(np.percentile(error,90)) if len(error) else None,
                p90_image_diagonal_fraction=float(np.percentile(error,90)/diagonal) if len(error) else None)


def diagnose_arrays(joints,times,camera,K,keypoints,observation_times,image_size,valid=None,config=None):
    cfg=configuration(config);j=np.asarray(joints);times=np.asarray(times);C=np.asarray(camera);K=np.asarray(K)
    if j.ndim!=3 or j.shape[1:]!=(22,3) or len(j)!=len(times) or C.shape!=(len(j),4,4) or K.shape!=(len(j),3,3):raise ValueError('Body/camera/timing shapes differ')
    if not all(np.isfinite(x).all() for x in (j,C,K,times)):raise ValueError('Nonfinite body/camera')
    if len(times)<2 or not np.all(np.diff(times)>0) or not np.allclose(np.diff(times),np.median(np.diff(times)),atol=1e-6):raise ValueError('Motion timing must be finite uniform increasing')
    image_size=np.asarray(image_size)
    if image_size.shape!=(2,) or not np.isfinite(image_size).all() or min(image_size)<=0:raise ValueError('Invalid camera raster')
    if not np.allclose(C[:,3,:],[0,0,0,1],atol=1e-6):raise ValueError('Invalid homogeneous camera poses')
    if not np.allclose(K[:,2,:],[0,0,1],atol=1e-6) or np.any(K[:,0,0]<=0) or np.any(K[:,1,1]<=0):raise ValueError('Invalid camera intrinsics')
    if not np.allclose(C[:,:3,:3].transpose(0,2,1)@C[:,:3,:3],np.eye(3),atol=1e-5) or np.any(np.linalg.det(C[:,:3,:3])<.999):raise ValueError('Camera rotations are not proper rigid rotations')
    valid=np.ones(len(j),bool) if valid is None else np.asarray(valid,dtype=bool)
    if valid.shape!=(len(j),):raise ValueError('Invalid frame validity')
    observed,mask,resampling=observed_samples(keypoints,observation_times,times,image_size,cfg['confidence_threshold'])
    mask &= valid[:,None]
    predicted,depth=project(j[:,SMPL],C,K);diagonal=float(np.linalg.norm(image_size));dt=float(np.median(np.diff(times)))
    supported=mask.sum(1)>=cfg['min_joints_per_frame']
    # All statistics and probes use the same sufficiently supported frames.
    mask &= supported[:,None]
    def probe(frame_mask):
        cohort=mask&frame_mask[:,None]
        if cohort.sum()<cfg['min_joints_per_frame']*2:return None
        def residual(x):
            uv,_=project(j[:,SMPL]+np.r_[x,0.][None,None,:],C,K)
            return ((uv-observed)[cohort]/max(1.,diagonal*.01)).ravel()
        fit=least_squares(residual,[0.,0.],loss='soft_l1',f_scale=1.,max_nfev=100)
        uv,_=project(j[:,SMPL]+np.r_[fit.x,0.][None,None,:],C,K)
        return dict(xy_delta_m=fit.x.tolist(),optimizer_success=bool(fit.success),projection=projection_stats(uv,observed,cohort,diagonal))
    all_probe=probe(valid)
    constant_uv=None
    if all_probe:constant_uv=project(j[:,SMPL]+np.r_[all_probe['xy_delta_m'],0.][None,None,:],C,K)[0]
    windows=[]
    for lo,hi,frames in window_masks(times,valid,cfg['window_seconds'],cfg['min_supported_seconds']):
        expected=int(frames.sum());actual=int((frames&supported).sum());cohort=mask&frames[:,None]
        coverage=actual/expected if expected else None
        total=int(((times>=lo)&(times<hi)).sum())
        sufficient=expected>0 and actual*dt+1e-8>=min(cfg['min_supported_seconds'],len(times)*dt) and coverage>=cfg['min_frame_coverage']
        stats=projection_stats(predicted,observed,cohort,diagonal)
        behind=bool((depth[cohort]<=.05).any())
        status='excluded' if expected==0 else ('unverified' if not sufficient else ('pass' if not behind and stats['p90_image_diagonal_fraction']<=cfg['max_p90_image_diagonal_fraction'] else 'fail'))
        windows.append(dict(start_seconds=lo,end_seconds=hi,total_frames=total,excluded_frames=total-expected,expected_frames=expected,supported_frames=actual,coverage=coverage,status=status,projection=stats,behind_camera=behind,
            common_constant_probe_projection=projection_stats(constant_uv,observed,cohort,diagonal) if constant_uv is not None else None,
            window_constant_xy_probe=probe(frames) if sufficient else None))
    informative=[w for w in windows if w['status']!='excluded']
    status='fail' if any(w['status']=='fail' for w in informative) else ('pass' if informative and all(w['status']=='pass' for w in informative) else 'unverified')
    reliable=[w for w in informative if w['status'] in ('pass','fail')]
    classification='observations_insufficient' if status=='unverified' else 'observed_consistent'
    delta_spread=None
    if status=='fail':
        rigid_pass=bool(reliable and all(w['common_constant_probe_projection'] and w['common_constant_probe_projection']['p90_image_diagonal_fraction']<=cfg['max_p90_image_diagonal_fraction'] for w in reliable))
        deltas=[w['window_constant_xy_probe']['xy_delta_m'] for w in reliable if w['window_constant_xy_probe']]
        if len(deltas)>=2:delta_spread=float(np.max(np.linalg.norm(np.asarray(deltas)[:,None]-np.asarray(deltas)[None,:],axis=2)))
        classification='observations_insufficient' if any(w['status']=='unverified' for w in informative) else ('rigid_placement_candidate' if rigid_pass else ('temporal_mismatch' if delta_spread is not None and delta_spread>cfg['probe_disagreement_m'] else 'unresolved_geometric_mismatch'))
    extent={}
    for name,top,bottom in [('torso',[6,7],[0,1]),('legs',[0,1],[4,5])]:
        cohort=mask[:,top+bottom].all(1)
        source_extent=observed[:,bottom,1].mean(1)-observed[:,top,1].mean(1)
        pred_extent=predicted[:,bottom,1].mean(1)-predicted[:,top,1].mean(1)
        cohort &= source_extent>diagonal*.015
        ratios=pred_extent[cohort]/source_extent[cohort]
        extent[name]=dict(frames=int(cohort.sum()),ratio_p10_p50_p90=np.percentile(ratios,[10,50,90]).tolist() if len(ratios) else [],frame_indices=np.flatnonzero(cohort).tolist())
    return dict(status=status,accepted=status=='pass',classification=classification,evaluated_scope='reviewed_valid_frames_only' if not valid.all() else 'full_clip_observation_windows',total_frames=len(times),excluded_frames=int((~valid).sum()),excluded_time_seconds=times[~valid].tolist(),scale_policy='native_units_locked',scale_optimized=False,
        resampling=resampling,all_clip=projection_stats(predicted,observed,mask,diagonal),windows=windows,
        constant_xy_probe=all_probe,window_probe_disagreement_m=delta_spread,extent_diagnostics=extent,
        joint_observation_counts=mask.sum(0).tolist(),matched_joint_names=NAMES,smpl_indices=SMPL.tolist(),coco_indices=COCO.tolist(),
        caveats=['COCO/SMPL joint definitions differ; detector confidence does not establish identity or ground truth.',
                 'Apparent extent cannot uniquely distinguish depth, camera calibration, body morphology and pose.',
                 'Window probes are diagnosis only; no trajectory or cache modification is authorized by this result.'])


def evaluate_manifest(manifest_path,camera_cache,refinement=None):
    from types import SimpleNamespace
    a=SimpleNamespace(manifest=Path(manifest_path),camera_cache=Path(camera_cache),refinement=Path(refinement) if refinement is not None else None)
    m=json.loads(a.manifest.read_text());cfg=configuration(m.get('placement_diagnostics'))
    ids=[x['id'] for x in m['actors']]
    if not ids or len(set(ids))!=len(ids) or any(not isinstance(x,str) or not x or Path(x).name!=x or x in ('.','..') for x in ids):raise ValueError('Actor IDs must be unique safe path components')
    with np.load(a.camera_cache) as z:C=z['c2w'];K=z['K'];ct=z['time_seconds'];size=z['image_size']
    rows=[]
    for actor in m['actors']:
        resolve=lambda key:(a.manifest.parent/actor[key]).resolve()
        cache=(a.refinement/actor['id']/'body_room.npz').resolve() if a.refinement else resolve('cache')
        row=dict(id=actor['id'],selected_cache=str(cache))
        try:
            alignment=resolve('alignment');motion=resolve('motion')
            row['hashes']={k:digest(v) for k,v in [('cache',cache),('alignment',alignment),('motion',motion)]}
            scale=float(json.loads(alignment.read_text())['body_scale'])
            if not np.isfinite(scale) or abs(scale-1.)>1e-6:raise ValueError('Native body units are not locked to scale 1')
            pose=resolve('pose_confidence') if actor.get('pose_confidence') else motion.parent/'preprocess/vitpose.pt'
            if not pose.is_file():raise ValueError('Missing detector observations; projection remains unverified')
            import torch
            keypoints=torch.load(pose,map_location='cpu',weights_only=True).numpy()
            with np.load(motion) as z:ot=z['frame_times_seconds']
            with np.load(cache) as z:joints=z['joints'];times=z['time_seconds']
            if ct.shape!=times.shape or not np.allclose(ct,times,atol=1e-6):raise ValueError('Camera timestamps differ from body')
            valid=np.ones(len(times),bool)
            for lo,hi in actor.get('exclude_seconds',[]):valid &= ~((times>=lo)&(times<=hi))
            if actor.get('visible_until_seconds') is not None:valid &= times<=actor['visible_until_seconds']
            row.update(diagnose_arrays(joints,times,C,K,keypoints,ot,size,valid,cfg))
            row['pose_confidence']=str(pose);row['hashes']['pose_confidence']=digest(pose)
        except (ValueError,KeyError,FileNotFoundError) as e:
            row.update(status='unverified',accepted=False,classification='observations_insufficient',reason=str(e))
        rows.append(row)
    status='fail' if any(x['status']=='fail' for x in rows) else ('pass' if all(x['accepted'] for x in rows) else 'unverified')
    report=dict(schema_version=1,status=status,accepted=status=='pass',scope='observed_projection_only',config=cfg,
        camera_sha256=digest(a.camera_cache),manifest_sha256=digest(a.manifest),implementation_sha256=digest(__file__),
        actors=rows,mutates_inputs=False,probes_adopted=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--camera-cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--refinement',type=Path)
    parser.add_argument('--require-accepted',action='store_true');a=parser.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    report=evaluate_manifest(a.manifest,a.camera_cache,a.refinement)
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps(dict(status=report['status'],actors=[{k:x[k] for k in ('id','status','classification')} for x in report['actors']]),indent=2))
    if a.require_accepted and not report['accepted']:raise SystemExit(2)

if __name__=='__main__':main()
