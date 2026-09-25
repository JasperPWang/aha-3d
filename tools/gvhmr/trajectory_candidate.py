"""Proposal-only smooth world-XY offsets from observed COCO image coordinates.

No body cache is mutated, no candidate is accepted, and no floor/ray snapping is
performed. Apply offsets equally to every joint/vertex or convert world offsets
through the fixed native-to-world rotation before adding to native translation.
Contact, reprojection, identity and rendered whole-clip review remain downstream.
"""
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import least_squares
try:
    from .placement_diagnostics import SMPL, observed_samples, project
except ImportError:
    from placement_diagnostics import SMPL, observed_samples, project

DEFAULTS = dict(knot_seconds=.5, confidence_threshold=.5, min_joints_per_frame=4,
                min_supported_seconds=.5, min_frame_coverage=.3,
                pixel_sigma_diagonal=.01, robust_delta=1.5,
                offset_sigma_m=2., velocity_sigma_mps=1., acceleration_sigma_mps2=3.,
                max_knot_axis_offset_m=1., max_nfev=200,
                foot_height_band_m=.08, stationary_foot_speed_mps=.15)


def evaluate_offsets(knot_times, knot_xy, sample_times):
    """Evaluate clamped cubic XY curve; constant hold outside observed support."""
    kt=np.asarray(knot_times,float);xy=np.asarray(knot_xy,float);t=np.asarray(sample_times,float)
    if kt.ndim!=1 or len(kt)<2 or not np.all(np.diff(kt)>0) or xy.shape!=(len(kt),2) or not all(np.isfinite(x).all() for x in (kt,xy,t)):
        raise ValueError('Invalid finite knot curve or sample times')
    if t.ndim!=1:raise ValueError('Sample times must be one dimensional')
    values=CubicSpline(kt,xy,axis=0,bc_type='clamped')(np.clip(t,kt[0],kt[-1]))
    return np.column_stack([values,np.zeros(len(t))])


def propose_trajectory(joints,times,camera,K,keypoints_coco17,observation_times,image_size,*,valid=None,config=None):
    """Return offsets_world, knot_times, knot_xy and an unaccepted proposal report.

    Inputs use one fixed metric world basis and matching full-image camera raster.
    `valid` declares the reviewed visible/evaluable scope, not a fit-time outlier
    selector. Never exclude a failed interval merely to obtain a passing proposal.
    """
    cfg=dict(DEFAULTS)
    if config:
        if set(config)-set(cfg):raise ValueError('Unknown trajectory configuration')
        cfg.update(config)
    if not all(np.isscalar(x) and np.isfinite(x) and x>0 for x in cfg.values()):raise ValueError('Configuration values must be finite and positive')
    if cfg['min_joints_per_frame'] not in range(1,13) or not 0<cfg['min_frame_coverage']<=1 or cfg['max_nfev']!=int(cfg['max_nfev']):raise ValueError('Invalid coverage/count configuration')
    j=np.asarray(joints,float);t=np.asarray(times,float);C=np.asarray(camera,float);intr=np.asarray(K,float);size=np.asarray(image_size,float)
    if j.shape!=(len(t),22,3) or C.shape!=(len(t),4,4) or intr.shape!=(len(t),3,3) or len(t)<3:raise ValueError('Body/camera/time shapes differ')
    if not all(np.isfinite(x).all() for x in (j,t,C,intr,size)) or size.shape!=(2,) or np.any(size<=0):raise ValueError('Nonfinite inputs or invalid raster')
    dt=np.diff(t)
    if not (dt>0).all() or not np.allclose(dt,np.median(dt),atol=1e-6):raise ValueError('Motion timestamps must be uniformly increasing')
    if not np.allclose(C[:,3,:],[0,0,0,1],atol=1e-6) or not np.allclose(C[:,:3,:3].transpose(0,2,1)@C[:,:3,:3],np.eye(3),atol=1e-5) or np.any(np.linalg.det(C[:,:3,:3])<.999):raise ValueError('Camera poses must be proper rigid')
    if not np.allclose(intr[:,2,:],[0,0,1],atol=1e-6) or np.any(intr[:,0,0]<=0) or np.any(intr[:,1,1]<=0):raise ValueError('Invalid camera intrinsics')
    scope=np.ones(len(t),bool) if valid is None else np.asarray(valid,bool)
    if scope.shape!=(len(t),) or not scope.any():raise ValueError('No valid reviewed scope')
    obs,mask,sampling=observed_samples(keypoints_coco17,observation_times,t,size,cfg['confidence_threshold'])
    mask &= scope[:,None]
    supported=mask.sum(1)>=cfg['min_joints_per_frame'];mask &= supported[:,None]
    cadence=float(np.median(dt));coverage=float(supported.sum()/scope.sum())
    if supported.sum()*cadence<cfg['min_supported_seconds'] or coverage<cfg['min_frame_coverage'] or supported.sum()<3:raise ValueError('Insufficient observed support for trajectory proposal')
    support_times=t[supported];lo,hi=float(support_times[0]),float(support_times[-1])
    if hi-lo<cfg['min_supported_seconds']-cadence:raise ValueError('Insufficient supported time span')
    intervals=max(1,int(np.ceil((hi-lo)/cfg['knot_seconds'])));kt=np.linspace(lo,hi,intervals+1)
    # This fixed basis makes optimization low dimensional. Both boundary slopes
    # are zero, so constant extrapolation joins continuously in position/velocity.
    spline=CubicSpline(kt,np.eye(len(kt)),axis=0,bc_type='clamped')
    clipped=np.clip(t,lo,hi);B=spline(clipped);inside=(t>=lo)&(t<=hi)
    D=spline(clipped,1)*inside[:,None];A=spline(clipped,2)*inside[:,None]
    selected=j[:,SMPL];pixel_sigma=max(1.,float(np.linalg.norm(size))*cfg['pixel_sigma_diagonal'])
    n_obs=max(1,int(mask.sum()));n_frames=len(t)
    def residual(flat):
        xy=flat.reshape(-1,2);offset=B@xy
        uv,depth=project(selected+np.column_stack([offset,np.zeros(n_frames)])[:,None,:],C,intr)
        r=((uv-obs)[mask]/pixel_sigma).ravel();delta=cfg['robust_delta']
        robust=np.sign(r)*np.sqrt(2*delta**2*(np.sqrt(1+(r/delta)**2)-1))
        return np.concatenate([robust/np.sqrt(n_obs),
            np.minimum(depth[mask]-.05,0)*10/np.sqrt(n_obs),
            offset.ravel()/cfg['offset_sigma_m']/np.sqrt(n_frames),
            (D@xy).ravel()/cfg['velocity_sigma_mps']/np.sqrt(n_frames),
            (A@xy).ravel()/cfg['acceleration_sigma_mps2']/np.sqrt(n_frames)])
    fit=least_squares(residual,np.zeros(len(kt)*2),bounds=(-cfg['max_knot_axis_offset_m'],cfg['max_knot_axis_offset_m']),max_nfev=int(cfg['max_nfev']),loss='linear')
    xy=fit.x.reshape(-1,2);offset=evaluate_offsets(kt,xy,t)
    if not np.isfinite(offset).all():raise ValueError('Nonfinite optimizer proposal')
    before,bd=project(selected,C,intr);after,ad=project(selected+offset[:,None,:],C,intr)
    def stats(uv,depth):
        error=np.linalg.norm(uv-obs,axis=2)[mask]
        return dict(median_px=float(np.median(error)),p90_px=float(np.percentile(error,90)),behind_observed_samples=int((depth[mask]<=.05).sum()))
    feet=j[:,[7,8,10,11]]
    baseline_speed=np.linalg.norm(np.gradient(feet,t,axis=0),axis=2)
    moved_feet=feet+offset[:,None,:]
    candidate_speed=np.linalg.norm(np.gradient(moved_feet,t,axis=0),axis=2)
    # A fixed baseline cohort prevents a faster candidate from silently dropping
    # the very feet whose sliding worsened. This is joint-level screening only.
    low_reference=float(np.percentile(feet[scope,:,2],5))
    cohort=scope[:,None] & (feet[:,:,2]<=low_reference+cfg['foot_height_band_m']) & (baseline_speed<=cfg['stationary_foot_speed_mps'])
    def cohort_speeds(values):
        v=values[cohort]
        return dict(samples=int(len(v)),p50_mps=float(np.median(v)) if len(v) else None,p90_mps=float(np.percentile(v,90)) if len(v) else None,max_mps=float(v.max()) if len(v) else None)
    foot_report=dict(joint_indices=[7,8,10,11],cohort_source='immutable baseline slow/low joint samples',
        low_height_reference_z_m=low_reference,reference_is_floor_measurement=False,
        total_samples=int(cohort.sum()),per_joint_samples=cohort.sum(0).tolist(),baseline=cohort_speeds(baseline_speed),candidate=cohort_speeds(candidate_speed),
        status='unverified_empty_cohort' if not cohort.any() else 'diagnostic_only',
        candidate_exceeds_baseline_stationary_threshold=int((cohort & (candidate_speed>cfg['stationary_foot_speed_mps'])).sum()))
    report=dict(proposal_only=True,accepted=False,mutates_inputs=False,optimizer_success=bool(fit.success),optimizer_message=str(fit.message),evaluations=int(fit.nfev),
        config=cfg,scale=1.,changes='world XY translation only; Z, pose, shape, orientation unchanged',
        supported_frames=int(supported.sum()),scope_frames=int(scope.sum()),coverage=coverage,support_interval_seconds=[lo,hi],held_frames=int((~inside).sum()),resampling=sampling,
        baseline_stationary_foot_cohort=foot_report,
        knot_count=len(kt),parameter_count=2*len(kt),before=stats(before,bd),after=stats(after,ad),
        maximum_offset_m=float(np.linalg.norm(offset[:,:2],axis=1).max()),maximum_offset_speed_mps=float(np.linalg.norm(D@xy,axis=1).max()),
        maximum_offset_acceleration_mps2=float(np.linalg.norm(A@xy,axis=1).max()),
        caveats=['Observed projections do not uniquely determine 3D depth or correct actor identity.',
                 'Interior observation gaps are regularized interpolation, not measured motion.',
                 'Optimizer convergence is not acceptance. Re-skin and rerun placement, contact speed/penetration and whole-clip render checks.',
                 'Knot-axis bounds do not bound cubic inter-knot extrema; inspect reported maximum offsets.'])
    return dict(offsets_world=offset,knot_times=kt,knot_xy=xy,report=report)
