"""Reviewed SAM leg directions -> sparse native Kimodo feet; no pose replacement."""
import argparse
from pathlib import Path
import numpy as np
from aha3d.io import read, write, digest
from .reference import UP, finite, unit, rotation, project, camera_to_world, unique_frames
from .sparse import align_vectors


def body_basis(points, left, right):
    lateral = points[right] - points[left]
    lateral[1] = 0
    lateral = unit(lateral)
    return np.column_stack([lateral, UP, unit(np.cross(UP, lateral))])


def build_guidance(obs, cameras, selection):
    if obs.get('schema_version') != 1 or selection.get('schema_version') != 1:
        raise ValueError('Unsupported schema')
    if obs.get('coordinate_convention') != 'opencv_camera_metres_with_translation':
        raise ValueError('Expected camera points with translation applied once')
    if not selection.get('person_id') or obs.get('person_id') != selection['person_id']:
        raise ValueError('Matching reviewed person identity required')
    if obs['processed_size_wh'] != cameras['processed_size_wh']:
        raise ValueError('Image dimensions differ')
    total = selection['native_frames']
    if type(total) is not int or total <= 0 or selection.get('native_fps') != 30:
        raise ValueError('Positive frame count and native 30 fps required')
    r = rotation(selection['world_to_kimodo_rotation'])
    if not np.allclose(r @ [0, 0, 1], UP, atol=1e-5):
        raise ValueError('World Z up must map to Kimodo Y up')
    names = obs['keypoint_names']
    if len(names) != len(set(names)):raise ValueError('Duplicate landmark names')
    samples = unique_frames(obs['frames']); cams = unique_frames(cameras['frames'])
    keys = []; seen = set()
    for event in selection['events']:
        allowed = {'source_frame', 'side', 'reviewed', 'review_note', 'visibility', 'target_time_seconds'}
        if set(event)-allowed:raise ValueError('Unsupported leg event fields')
        if event.get('reviewed') is not True or event.get('visibility') != 'visible' or not event.get('review_note', '').strip():
            raise ValueError('Visible reviewed leg and an actual review note required')
        side = event['side']; source = event['source_frame']
        if side not in ('left', 'right') or type(source) is not int or source not in samples or source not in cams:
            raise ValueError('Exact source frame and left/right leg required')
        sample = samples[source]; cam = cams[source]; ts = float(sample['timestamp_seconds'])
        if not np.isfinite(ts) or abs(ts-float(cam['timestamp_seconds'])) > 1e-6:
            raise ValueError('Observation/camera timestamps differ')
        target = float(event.get('target_time_seconds', ts-selection.get('source_start_seconds', 0)))
        frame = int(np.floor(target*30+.5)) if np.isfinite(target) else -1
        if not 0 <= target < total/30 or not 0 <= frame < total:raise ValueError('Event outside native duration')
        if (frame, side) in seen:raise ValueError('Duplicate native foot key')
        seen.add((frame, side))
        required = ['left-hip', 'right-hip', side+'-hip', side+'-knee', side+'-ankle']
        ids = [names.index(n) for n in required]
        points = finite(sample['keypoints_camera_m'], (len(names), 3), 'camera points')
        uv = finite(sample['keypoints_2d'], (len(names), 2), 'image points')
        err = float(np.linalg.norm(project(points[ids], cam['intrinsics'])-uv[ids], axis=1).max())
        if err > 2:raise ValueError('Projection mismatch over 2 pixels')
        width, height = cameras['processed_size_wh']
        if np.any(uv[ids] < 0) or np.any(uv[ids] > [width-1, height-1]):raise ValueError('Required landmarks outside image')
        p = camera_to_world(points, cam['c2w']) @ r.T
        basis = body_basis(p, ids[0], ids[1]); hip, knee, ankle = p[ids[2:]]
        keys.append(dict(frame=frame, side=side, source_frame=source, source_timestamp_seconds=ts,
                         target_time_seconds=target, quantization_error_seconds=frame/30-target,
                         thigh_direction=(basis.T @ unit(knee-hip)).tolist(),
                         shin_direction=(basis.T @ unit(ankle-knee)).tolist(),
                         projection_max_error_px=err, review_note=event['review_note']))
    if not keys:raise ValueError('No reviewed leg events')
    return sorted(keys, key=lambda k:(k['frame'], k['side']))


def compile_constraints(baseline, keys, native_frames, route=None):
    import torch
    from kimodo.constraints import LeftFootConstraintSet, RightFootConstraintSet, load_constraints_lst
    from kimodo.skeleton import SMPLXSkeleton22
    sk = SMPLXSkeleton22().cpu()
    local_all = finite(baseline['local_rot_mats'], (native_frames,22,3,3), 'baseline rotations')
    if not np.allclose(local_all.swapaxes(-1,-2)@local_all,np.eye(3),atol=1e-4) or not np.allclose(np.linalg.det(local_all),1,atol=1e-4):
        raise ValueError('Invalid baseline rotations')
    roots = finite(baseline['root_positions'], (native_frames,3), 'baseline roots')
    smooths = finite(baseline['smooth_root_pos'], (native_frames,3), 'smooth roots')
    route = [] if route is None else route
    occupied = set()
    for entry in route:
        if entry.get('type') != 'root2d':raise ValueError('Only root2d route may be merged')
        frames = entry['frame_indices']
        if frames != sorted(set(frames)) or any(type(f) is not int or not 0 <= f < native_frames for f in frames) or occupied.intersection(frames):
            raise ValueError('Invalid or duplicate route frames')
        occupied.update(frames)
        finite(entry['smooth_root_2d'], (len(frames),2), 'route')
    routes = load_constraints_lst(route, sk)
    def fk(local, root):
        with torch.inference_mode():rot, pos, _ = sk.fk(torch.tensor(local,dtype=torch.float32),torch.tensor(root,dtype=torch.float32))
        return rot.numpy(), pos.numpy()
    constraints = []; reports = []; seen = set()
    for frame in sorted({k['frame'] for k in keys}):
        if type(frame) is not int or not 0 <= frame < native_frames:raise ValueError('Invalid native key frame')
        local = local_all[[frame]].astype(np.float32).copy(); root = roots[[frame]].astype(np.float32).copy()
        smooth = smooths[[frame]][:,[0,2]].astype(np.float32).copy()
        original_rot, original_pos = fk(local, root)
        basis = body_basis(original_pos[0], 1, 2)
        events = [k for k in keys if k['frame']==frame]
        for key in events:
            side = key['side']
            if side not in ('left','right') or (frame,side) in seen:raise ValueError('Invalid or duplicate foot key')
            seen.add((frame,side))
            for bone_name, tip_name, parent_name, field in [
                (side+'_hip',side+'_knee','pelvis','thigh_direction'),
                (side+'_knee',side+'_ankle',side+'_hip','shin_direction')]:
                bone,tip,parent = [sk.bone_index[n] for n in (bone_name,tip_name,parent_name)]
                rot,pos = fk(local,root)
                desired = unit(basis @ finite(key[field], (3,), field))
                local[0,bone] = rot[0,parent].T @ align_vectors(pos[0,tip]-pos[0,bone],desired) @ rot[0,bone]
            # Retain baseline global ankle orientation: SAM toe twist is not used.
            ankle = sk.bone_index[side+'_ankle']; knee = sk.bone_index[side+'_knee']
            rot,_ = fk(local,root)
            local[0,ankle] = rot[0,knee].T @ original_rot[0,ankle]
        rot,pos = fk(local,root)
        for key in events:
            cls = LeftFootConstraintSet if key['side']=='left' else RightFootConstraintSet
            foot = cls(sk,torch.tensor([frame]),torch.from_numpy(pos),torch.from_numpy(rot),torch.from_numpy(smooth))
            saved = {k:v.detach().cpu().tolist() if torch.is_tensor(v) else v for k,v in foot.get_save_info().items()}
            restored = cls.from_dict(sk,saved)
            error = float(np.max(np.abs(restored.global_joints_positions.numpy()-pos)))
            if error > 1e-5:raise ValueError('Native foot FK round-trip failed')
            for route_set in routes:
                for i,f in enumerate(route_set.frame_indices.tolist()):
                    if f != frame:continue
                    if not np.allclose(route_set.smooth_root_2d[i].numpy(),smooth[0],atol=1e-4):raise ValueError('Foot key conflicts with route position')
                    if route_set.global_root_heading is not None and not np.allclose(route_set.global_root_heading[i].numpy(),foot.global_root_heading[0].numpy(),atol=1e-4):raise ValueError('Foot key conflicts with route heading')
            ankle = sk.bone_index[key['side']+'_ankle']; toe = sk.bone_index[key['side']+'_foot']
            reports.append(dict(event=key,ankle_target_m=pos[0,ankle].tolist(),foot_target_m=pos[0,toe].tolist(),
                                baseline_ankle_height_m=float(original_pos[0,ankle,1]),
                                ankle_height_delta_m=float(pos[0,ankle,1]-original_pos[0,ankle,1]),
                                root_position_m=root[0].tolist(),smooth_root_xz_m=smooth[0].tolist(),
                                heading=foot.global_root_heading.tolist(),fk_roundtrip_max_error_m=error))
            constraints.append(saved)
    return route+constraints,reports


def agreement(joints, keys):
    rows=[]
    for key in keys:
        p=joints[key['frame']]; basis=body_basis(p,1,2)
        hip,knee,ankle=(1,4,7) if key['side']=='left' else (2,5,8)
        angles=[]
        for v,field in [(p[knee]-p[hip],'thigh_direction'),(p[ankle]-p[knee],'shin_direction')]:
            angles.append(float(np.degrees(np.arccos(np.clip(np.dot(basis.T@unit(v),unit(key[field])),-1,1)))))
        rows.append(dict(source_frame=key['source_frame'],side=key['side'],thigh_angle_deg=angles[0],shin_angle_deg=angles[1]))
    return dict(mean_angle_deg=float(np.mean([[r['thigh_angle_deg'],r['shin_angle_deg']] for r in rows])),events=rows)


def motion_metrics(joints, fps=30):
    feet=joints[:,[7,8,10,11]]
    speed=np.linalg.norm(np.diff(feet[:,:,[0,2]],axis=0),axis=-1)*fps
    height=feet[:,:,1]; low=np.quantile(height,.05,axis=0)
    # Native ankle/toe proxy only; actual skinned sole diagnostics are separate.
    near=(height[:-1] < low+.04)&(height[1:] < low+.04)
    acceleration=np.diff(joints[:,[4,5,7,8]]-joints[:,[0]],n=2,axis=0)*fps**2
    return dict(near_low_foot_speed_mean_m_s=float(speed[near].mean()) if near.any() else None,
                near_low_foot_samples=int(near.sum()),foot_height_min_m=float(height.min()),
                knee_ankle_acceleration_p95_m_s2=float(np.quantile(np.linalg.norm(acceleration,axis=-1),.95)),
                proxy_definition='Ankle/toe within 4 cm of its own 5th-percentile native height; not detected physical contact')


def compare_motions(baseline, candidate, reviewed_keys, training_keys):
    """Report SAM agreement separately at keyed and withheld source times."""
    shape = np.asarray(baseline).shape
    if len(shape)!=3 or shape[1:]!=(22,3) or not np.isfinite(baseline).all():
        raise ValueError('Expected finite native SMPL-X joints [T,22,3]')
    candidate = finite(candidate, shape, 'candidate joints')
    used = {k['source_frame'] for k in training_keys}
    heldout = [k for k in reviewed_keys if k['source_frame'] not in used]
    if not heldout:raise ValueError('Include visually reviewed withheld source times')
    return dict(training_keys=len(training_keys), withheld_events=len(heldout),
                baseline=dict(keyed=agreement(baseline,training_keys),withheld=agreement(baseline,heldout),motion=motion_metrics(baseline)),
                candidate=dict(keyed=agreement(candidate,training_keys),withheld=agreement(candidate,heldout),motion=motion_metrics(candidate)),
                limits='Agreement with single-image SAM body-relative thigh/shin directions, not motion ground truth. Sparse held-out times are correlated. Root/floor/mesh validation remains separate.')


def compare_meshes(baseline, candidate, joints, fps, scale=1., floor_z=0.):
    """Fixed sole vertices and identical floor policy; no per-frame grounding."""
    shape=np.asarray(baseline).shape
    if len(shape)!=3 or shape[2]!=3 or not np.isfinite(baseline).all():raise ValueError('Expected finite [T,V,3] meshes')
    candidate=finite(candidate,shape,'candidate vertices')
    if not np.isfinite([fps,scale,floor_z]).all() or fps<=0 or scale<=0:raise ValueError('Invalid mesh metric units')
    # Select IDs once from baseline first-frame ankle neighborhoods. Keep exactly
    # those vertex IDs for both variants. This is a documented sole proxy.
    v=baseline[0];ankles=joints[0,[7,8]]
    distance=np.linalg.norm(v[:,None,:]-ankles[None,:,:],axis=-1)
    side=distance.argmin(1);ids=[]
    for i in range(2):
        near=np.flatnonzero((side==i)&(distance[:,i]<.25))
        if len(near)<8:raise ValueError('Cannot identify baseline ankle neighborhood')
        chosen=near[v[near,2]<=v[near,2].min()+.025]
        if len(chosen)<4:raise ValueError('Insufficient sole proxy vertices')
        ids.append(chosen)
    reports={}
    # One constant baseline-derived floor registration applied to both clips.
    offset=floor_z-float(baseline[:,:,2].min())*scale
    for name,vertices in [('baseline',baseline),('candidate',candidate)]:
        z=vertices[:,:,2]*scale+offset-floor_z
        foot={}
        for side,chosen in zip(('left','right'),ids):
            patch=vertices[:,chosen]*scale
            h=np.quantile(patch[:,:,2],.1,axis=1)+offset-floor_z
            xy=patch[:,:,:2].mean(1)
            near=(h[:-1]<.04)&(h[1:]<.04)
            speed=np.linalg.norm(np.diff(xy,axis=0),axis=-1)*fps
            foot[side]=dict(vertex_count=len(chosen),near_floor_intervals=int(near.sum()),
                            near_floor_speed_mean_m_s=float(speed[near].mean()) if near.any() else None,
                            sole_p10_height_min_m=float(h.min()),sole_p10_height_max_m=float(h.max()))
        reports[name]=dict(min_vertex_clearance_m=float(z.min()),penetrating_frames_5mm=int((z.min(1)<-.005).sum()),
                           airborne_frames_5cm=int((z.min(1)>.05).sum()),feet=foot)
    return dict(**reports,body_scale=scale,floor_z=floor_z,shared_constant_z_offset_m=offset,
                sole_vertex_ids=[x.tolist() for x in ids],
                limits='Sole vertex neighborhood is inferred once from baseline. Near-floor speed is a sliding proxy; toe roll and stance are not classified. Both clips share one constant floor offset; no per-frame grounding.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observations',type=Path,required=True);p.add_argument('--pi3x',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--route',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():p.error('Use a new claimed output directory')
    obs=read(a.observations);pi=read(a.pi3x/'inputs.json');cams=read(a.pi3x/'cameras.json');selection=read(a.selection)
    if obs['source_sha256']!=pi['source_sha256'] or obs['pi3x_inputs_sha256']!=digest(a.pi3x/'inputs.json') or obs['pi3x_cameras_sha256']!=digest(a.pi3x/'cameras.json'):
        raise ValueError('Original same-shot Pi3X hashes required')
    keys=build_guidance(obs,cams,selection)
    with np.load(a.baseline,allow_pickle=False) as z:baseline={k:z[k] for k in ('local_rot_mats','root_positions','smooth_root_pos')}
    constraints,report=compile_constraints(baseline,keys,selection['native_frames'],read(a.route) if a.route else None)
    a.out.mkdir(parents=True,exist_ok=False)
    write(a.out/'constraints.json',constraints);write(a.out/'guidance.json',dict(events=keys))
    inputs=[a.observations,a.selection,a.baseline,a.pi3x/'inputs.json',a.pi3x/'cameras.json']+([a.route] if a.route else [])
    write(a.out/'report.json',dict(status='experimental; generation and mesh validation pending',targets=report,
          inputs={str(x):digest(x) for x in inputs},
          root_policy='Baseline root position, smooth root and heading retained at keys; no SAM absolute depth or floor fit',
          orientation_policy='Baseline global ankle rotation retained; no SAM foot twist recovery',
          native_mask=['ankle and foot position','ankle rotation','smooth root XZ','root height','heading'],
          limits='Reviewed leg directions do not certify contact or gait phase; no post-generation edits'))

if __name__=='__main__':main()
