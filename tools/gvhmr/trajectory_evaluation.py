"""Independent proposal diagnostics. No result authorizes reconstruction acceptance.

Caller supplies the same baseline-derived contacts and detector cohort to every
variant. Projection arrays must use actual anatomical detector correspondences,
not SAM targets. SAM train/heldout residuals belong in a separate report.
"""
import hashlib
import numpy as np


def split_sparse_indices(indices):
    raw=np.asarray(indices)
    if raw.ndim!=1 or not np.issubdtype(raw.dtype,np.integer) or len(raw)<2 or (raw<0).any():
        raise ValueError('Need at least two nonnegative integer sparse indices')
    idx=np.sort(raw)
    if len(np.unique(idx))!=len(idx):raise ValueError('Duplicate sparse frame')
    return idx[::2],idx[1::2]


def stats(values):
    v=np.asarray(values,float).reshape(-1)
    if not np.isfinite(v).all():raise ValueError('Nonfinite evaluated values')
    return dict(samples=len(v),median=float(np.median(v)) if len(v) else None,
                p90=float(np.percentile(v,90)) if len(v) else None,
                maximum=float(v.max()) if len(v) else None)


def fingerprint(array):
    x=np.ascontiguousarray(array)
    return hashlib.sha256(str((x.shape,x.dtype.str)).encode()+x.tobytes()).hexdigest()


def evaluate_arrays(baseline_vertices,candidate_vertices,baseline_joints,candidate_joints,
                    times,foot_ids,contact_masks,valid,root_offsets,bounds_xyz,sparse_indices,
                    floor_z=0.,root_only=True,observed_uv=None,predicted_before_uv=None,
                    predicted_after_uv=None,observed_mask=None):
    times=np.asarray(times,float);n=len(times);valid=np.asarray(valid,bool)
    if n<3 or valid.shape!=(n,) or not valid.any() or not np.isfinite(times).all() or not np.all(np.diff(times)>0):raise ValueError('Invalid timeline/validity')
    dt=np.diff(times)
    if not np.allclose(dt,dt[0],atol=1e-6,rtol=1e-5):raise ValueError('Uniform evaluated timeline required')
    v0,v1,j0,j1=[np.asarray(x,float) for x in (baseline_vertices,candidate_vertices,baseline_joints,candidate_joints)]
    if v0.shape!=v1.shape or j0.shape!=j1.shape or any(x.ndim!=3 or x.shape[0]!=n or x.shape[2]!=3 or not np.isfinite(x).all() for x in (v0,v1,j0,j1)):raise ValueError('Invalid geometry')
    offsets=np.asarray(root_offsets,float);bounds=np.asarray(bounds_xyz,float)
    if offsets.shape!=(n,3) or bounds.shape!=(3,) or (bounds<0).any() or not np.isfinite(offsets).all() or not np.isfinite(bounds).all():raise ValueError('Invalid offsets/bounds')
    train,heldout=split_sparse_indices(sparse_indices)
    if max(train.max(),heldout.max())>=n:raise ValueError('Sparse index outside clip')
    if len(foot_ids)!=2 or any(len(x)==0 or np.min(x)<0 or np.max(x)>=v0.shape[1] for x in foot_ids):raise ValueError('Invalid foot vertex IDs')
    if set(contact_masks)!={'observed','model'}:raise ValueError('Both immutable observed and model contacts required')
    pairs=valid[:-1]&valid[1:];triples=valid[:-2]&valid[1:-1]&valid[2:]
    def feet(v):
        centers=np.stack([v[:,ids].mean(1) for ids in foot_ids],1)
        velocity=np.diff(centers,axis=0)/dt[:,None,None]
        acceleration=np.diff(velocity,axis=0)/((dt[:-1]+dt[1:])/2)[:,None,None]
        return velocity,acceleration
    f0,a0=feet(v0);f1,a1=feet(v1)
    contacts={}
    for name,mask in contact_masks.items():
        mask=np.asarray(mask,bool)
        if mask.shape!=(n,2):raise ValueError('Invalid contact mask')
        cohort=mask[:-1]&mask[1:]&pairs[:,None]
        contacts[name]=dict(mask_sha256=fingerprint(mask),pair_mask_sha256=fingerprint(cohort),status='measured' if cohort.any() else 'unverified',
                           before_speed_m_s=stats(np.linalg.norm(f0,axis=2)[cohort]),after_speed_m_s=stats(np.linalg.norm(f1,axis=2)[cohort]))
    root_velocity=np.diff(offsets,axis=0)/dt[:,None]
    root_acc=np.diff(root_velocity,axis=0)/((dt[:-1]+dt[1:])/2)[:,None]
    invariant=max(float(np.abs(v1-v0-offsets[:,None]).max()),float(np.abs(j1-j0-offsets[:,None]).max()))
    report=dict(proposal_only=True,accepted=False,scope='candidate_comparison_only',scale_policy='native_units_locked',
        split=dict(train_indices=train.tolist(),heldout_indices=heldout.tolist(),sparse_indices_sha256=fingerprint(np.sort(np.asarray(sparse_indices))),policy='sorted sparse samples alternating even train / odd heldout'),
        valid_mask_sha256=fingerprint(valid),excluded_frames=int((~valid).sum()),contact=contacts,
        before_penetration_max_m=float(max(0,floor_z-v0[valid,:,2].min())),after_penetration_max_m=float(max(0,floor_z-v1[valid,:,2].min())),
        before_foot_acceleration_m_s2=stats(np.linalg.norm(a0,axis=2)[triples]),after_foot_acceleration_m_s2=stats(np.linalg.norm(a1,axis=2)[triples]),
        root_only_requested=bool(root_only),root_only_geometry_error_max_m=invariant,root_only_geometry_verified=bool(root_only and invariant<=5e-5),
        realized_root_axis_max_m=np.abs(offsets).max(0).tolist(),bounds_xyz_m=bounds.tolist(),bounds_verified=bool((np.abs(offsets)<=bounds+1e-6).all()),
        root_offset_norm_m=stats(np.linalg.norm(offsets,axis=1)),root_correction_speed_m_s=stats(np.linalg.norm(root_velocity,axis=1)[pairs]),root_correction_acceleration_m_s2=stats(np.linalg.norm(root_acc,axis=1)[triples]))
    uv_args=(observed_uv,predicted_before_uv,predicted_after_uv,observed_mask)
    if any(x is not None for x in uv_args):
        if any(x is None for x in uv_args):raise ValueError('All observed projection arrays required')
        obs,p0,p1=[np.asarray(x,float) for x in uv_args[:3]];mask=np.asarray(observed_mask,bool)
        if obs.shape!=p0.shape or obs.shape!=p1.shape or obs.ndim!=3 or obs.shape[0]!=n or obs.shape[2]!=2 or mask.shape!=obs.shape[:2]:raise ValueError('Invalid observed projection shape')
        cohort=mask&valid[:,None]
        # Invalid predicted projection on observed support is a failure, never dropped.
        if any(not np.isfinite(x[cohort]).all() for x in (obs,p0,p1)):raise ValueError('Nonfinite observed/support projection')
        def projection(frame_mask):
            select=cohort&frame_mask[:,None]
            return dict(frames=int((select.sum(1)>0).sum()),joints=int(select.sum()),status='measured' if select.any() else 'unverified',before_error_px=stats(np.linalg.norm(p0[select]-obs[select],axis=1)),after_error_px=stats(np.linalg.norm(p1[select]-obs[select],axis=1)))
        windows=[]
        for label in np.unique(np.floor((times-times[0])/2).astype(int)):
            select=np.floor((times-times[0])/2).astype(int)==label
            windows.append(dict(start_seconds=float(times[0]+label*2),**projection(select)))
        report['independent_detector_projection']=dict(observation_cohort_sha256=fingerprint(cohort),all_clip=projection(np.ones(n,bool)),train_times=projection(np.isin(np.arange(n),train)),heldout_times=projection(np.isin(np.arange(n),heldout)),windows=windows,note='Residual summaries only; shared placement gate remains mandatory with its original coverage thresholds.')
    else:report['independent_detector_projection']=dict(status='unverified',reason='not supplied')
    return report
