"""Preserve aligned native-global SMPL-X motion; contact repair is explicit opt-in.

Inputs are explicit manifest paths (relative to manifest), native GVHMR parameters,
an unmodified global-aligned mesh cache, and its fixed rigid transform. Z-up room,
neutral SMPL-X with 12-component PCA hands. Optional repair requires flat support.
No camera-space root replacement. Outputs are separate and acceptance-gated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import importlib.metadata
import numpy as np


def smooth_targets(targets, strength=4.0):
    """Second-difference regularization, preserving affine trajectories."""
    x = np.asarray(targets, dtype=float)
    if x.ndim != 2 or not np.isfinite(x).all() or strength < 0:
        raise ValueError("Expected finite [T,D] targets and nonnegative strength")
    if len(x) < 3 or strength == 0:
        return x.copy()
    d = np.diff(np.eye(len(x)), n=2, axis=0)
    return np.linalg.solve(np.eye(len(x)) + strength * d.T @ d, x)


def contact_mask(heights, speed, valid, height_threshold=.04, speed_threshold=.15, min_frames=3):
    h, s, v = np.asarray(heights), np.asarray(speed), np.asarray(valid, dtype=bool)
    if h.ndim != 2 or h.shape[1] != 2 or h.shape != s.shape or v.shape != (len(h),):
        raise ValueError("Expected [T,2] heights/speeds and [T] validity")
    if not np.isfinite(h).all() or not np.isfinite(s).all() or min_frames < 1:
        raise ValueError("Nonfinite contact input or invalid duration")
    mask = (h < height_threshold) & (s < speed_threshold) & v[:, None]
    for side in range(2):
        for a, b in segments(mask[:, side]):
            if b - a < min_frames:
                mask[a:b, side] = False
    return mask


def segments(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int)))
    return list(zip(edges[::2], edges[1::2]))


def fixed_floor_shift(heights, valid, floor_z=0., clearance=.005, trigger=.03, max_shift=.5):
    """Robust constant support height from reviewed grounded frames, never clamp."""
    h, valid = np.asarray(heights), np.asarray(valid, dtype=bool)
    if h.ndim != 2 or h.shape[1] != 2 or valid.shape != (len(h),) or not valid.any():
        raise ValueError("No valid grounded frames or invalid height shape")
    if not np.isfinite(h).all():
        raise ValueError("Nonfinite heights")
    shift = float(floor_z + clearance - np.median(h[valid].min(axis=1)))
    if abs(shift) > max_shift:
        raise ValueError("Support offset exceeds max_shift; review room/scale")
    return shift if abs(shift) > trigger else 0.


def acceptance(before, after, root_xy_error):
    reasons = []
    if not np.isfinite(root_xy_error) or root_xy_error > 1e-5:
        reasons.append("root_xy_changed")
    for name in ("penetration_depth_max_m", "contact_speed_p90_m_s", "foot_acceleration_p90_m_s2"):
        if not np.isfinite(before[name]) or not np.isfinite(after[name]):
            reasons.append("nonfinite_metric")
    if after["penetration_depth_max_m"] > .005:
        reasons.append("remaining_penetration")
    if after["contact_speed_p90_m_s"] > before["contact_speed_p90_m_s"] + .025:
        reasons.append("contact_speed_regressed")
    if after["foot_acceleration_p90_m_s2"] > before["foot_acceleration_p90_m_s2"] * 1.25 + .5:
        reasons.append("acceleration_regressed")
    return not reasons, reasons


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resample(path, times):
    from scipy.spatial.transform import Rotation, Slerp
    with np.load(path) as z:
        nt = z["frame_times_seconds"]
        if len(nt) < 2 or not np.all(np.diff(nt) > 0) or times[0] < nt[0] - 1e-6 or times[-1] > nt[-1] + 1 / 30 + 1e-6:
            raise ValueError("Invalid native timing or excessive endpoint extrapolation")
        sample = np.clip(times, nt[0], nt[-1])
        out = {}
        for key in ("body_pose", "global_orient", "betas", "transl"):
            x = z["smpl_params_global__" + key]
            if key in ("body_pose", "global_orient"):
                x = x.reshape(len(nt), -1, 3)
                y = np.stack([Slerp(nt, Rotation.from_rotvec(x[:, j]))(sample).as_rotvec() for j in range(x.shape[1])], axis=1)
            else:
                y = np.stack([np.interp(sample, nt, row) for row in x.T], axis=1)
            out[key] = y.reshape(len(times), -1).astype("f4")
    return out


def measure(vertices, foot_ids, mask, valid, fps, floor_z):
    h = np.stack([vertices[:, ids, 2].min(1) - floor_z for ids in foot_ids], axis=1)
    center = np.stack([vertices[:, ids].mean(1) for ids in foot_ids], axis=1)
    velocity = np.diff(center, axis=0) * fps
    selected = mask[:-1] & mask[1:] & valid[:-1, None] & valid[1:, None]
    speeds = np.linalg.norm(velocity, axis=-1)[selected]
    av = valid[:-2] & valid[1:-1] & valid[2:]
    acceleration = np.linalg.norm(np.diff(velocity, axis=0) * fps, axis=-1)[av]
    return {
        "penetration_depth_max_m": float(max(0, -vertices[valid, :, 2].min() + floor_z)),
        "foot_height_min_m": float(h[valid].min()),
        "support_height_median_m": float(np.median(h[valid].min(1))),
        "contact_speed_p90_m_s": float(np.percentile(speeds, 90)) if len(speeds) else 0.,
        "contact_speed_samples": int(len(speeds)),
        "foot_acceleration_p90_m_s2": float(np.percentile(acceleration, 90)) if acceleration.size else 0.,
    }


def preserve_native_actor(actor, cache, output, params, alignment, input_hashes, reproduction_error):
    """Apply only this actor's constant room-Z translation; never infer contact."""
    value = actor.get("vertical_translation_m", 0.)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError("vertical_translation_m must be one finite scalar per actor")
    shift = float(value)
    selected = dict(cache)
    for key in ("vertices", "joints"):
        original = np.asarray(cache[key])
        if original.ndim != 3 or original.shape[-1] != 3 or not np.isfinite(original).all() or original.dtype.kind != 'f':
            raise ValueError("Expected finite floating-point [T,N,3] " + key)
        selected[key] = original.copy()
        selected[key][:, :, 2] += shift
        if not np.isfinite(selected[key]).all():
            raise ValueError("Nonfinite translated geometry")
    if shift == 0:
        shutil.copyfile(actor["cache"], output / "body_room.npz")
    else:
        np.savez(output / "body_room.npz", **selected)
    np.savez(output / "refined_parameters.npz", **params, refined_body_pose=params["body_pose"],
             rotation=alignment["rotation"],
             translation=np.asarray(alignment["translation"]) + [0., 0., shift],
             body_scale=1., time_seconds=cache["time_seconds"])
    report = dict(id=actor["id"], input_hashes=input_hashes, accepted=True,
                  acceptance_scope="native_motion_preservation_only; source placement checked separately",
                  selected="constant_vertical_translation" if shift else "unchanged",
                  method="native global motion + fixed rigid alignment + per-actor constant room-Z translation",
                  constant_vertical_shift_m=shift, ik_applied=False, optimization=[],
                  per_frame_root_correction=False, contact_refinement_applied=False,
                  cache_reproduction_error_m=reproduction_error, root_xy_max_error_m=0.,
                  before={"mesh_min_z_m":float(cache["vertices"][:, :, 2].min())},
                  after={"mesh_min_z_m":float(selected["vertices"][:, :, 2].min())},
                  contact_validated=False, rejection_reasons=[])
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def refine_actor(actor, manifest_dir, output, model, device, config, *, refine_contact=False):
    import torch
    from smplx.lbs import batch_rodrigues, batch_rigid_transform, blend_shapes, vertices2joints
    output.mkdir(parents=True, exist_ok=False)
    resolve = lambda key: (manifest_dir / actor[key]).resolve()
    cache_path, native_path, alignment_path = [resolve(k) for k in ("cache", "motion", "alignment")]
    with np.load(cache_path) as z:
        cache = {k: z[k] for k in z.files}
    vertices = cache["vertices"]
    times = cache["time_seconds"]
    n, fps = len(vertices), float(cache["fps"])
    if n < 3 or not np.isfinite(vertices).all() or not np.allclose(np.diff(times), 1/fps, atol=1e-5):
        raise ValueError("Invalid finite uniform-time cache")
    valid = np.ones(n, bool)
    for a, b in actor.get("exclude_seconds", []):
        valid &= ~((times >= a) & (times <= b))
    if valid.sum() < 3:
        raise ValueError("Insufficient visible/reliable frames")
    if refine_contact and not actor.get("grounded_motion", False):
        raise ValueError("Grounded motion must be reviewed; stairs/jumps/seated support need a different model")
    align = json.loads(alignment_path.read_text())
    R, t, scale = np.array(align["rotation"]), np.array(align["translation"]), float(align["body_scale"])
    if R.shape != (3,3) or t.shape != (3,) or not np.isfinite(t).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-5) or np.linalg.det(R) < .99 or not np.isclose(scale, 1., rtol=0, atol=1e-7):
        raise ValueError("Expected a finite rigid alignment with scale fixed to 1")
    tilt_degrees = float(np.degrees(np.arccos(np.clip((R @ np.array([0.,1.,0.]))[2],-1,1))))
    if tilt_degrees > 15:
        raise ValueError(f"Global-to-room up-axis tilt {tilt_degrees:.2f} exceeds 15 degrees; review alignment")
    params = resample(native_path, times)
    tensor = lambda x: torch.as_tensor(x, dtype=torch.float32, device=device)
    p = {k: tensor(v) for k, v in params.items()}
    def skin(body_pose):
        vs, js, full = [], [], []
        for a in range(0, n, 32):
            b = min(32, n-a)
            kw = {k: v[a:a+b] for k, v in p.items()}
            kw["body_pose"] = body_pose[a:a+b]
            kw.update({k: torch.zeros((b, d), device=device) for k, d in [
                ("left_hand_pose",12),("right_hand_pose",12),("jaw_pose",3),
                ("leye_pose",3),("reye_pose",3),("expression",10)]})
            o = model(**kw, return_full_pose=True)
            vs.append(o.vertices); js.append(o.joints[:, :22]); full.append(o.full_pose)
        return torch.cat(vs), torch.cat(js), torch.cat(full)
    with torch.no_grad():
        v0, j0, full_pose = skin(p["body_pose"])
    room = lambda v: scale * (v @ tensor(R).T) + tensor(t)
    reproduced = room(v0).cpu().numpy()
    reproduction_error = float(np.abs(reproduced - vertices).max())
    if reproduction_error > 5e-5:
        raise ValueError(f"Cache is not the supplied native-global similarity: {reproduction_error}")
    native_joints = room(j0).cpu().numpy()
    if native_joints.shape != cache["joints"].shape or not np.allclose(native_joints, cache["joints"], rtol=0, atol=5e-5):
        raise ValueError("Cache joints do not reproduce native-global motion")
    if not refine_contact:
        return preserve_native_actor(dict(actor, cache=str(cache_path)), cache, output, params, align,
                                     {k:sha(resolve(k)) for k in ("cache", "motion", "alignment")}, reproduction_error)
    if actor.get("vertical_translation_m", 0.) != 0.:
        raise ValueError("Explicit vertical_translation_m belongs to native mode; do not combine with automatic contact repair")
    dominant = model.lbs_weights.argmax(1).cpu().numpy()
    foot_ids = [np.flatnonzero(np.isin(dominant, side)) for side in ([7,10], [8,11])]
    if min(map(len, foot_ids)) < 20:
        raise ValueError("Missing SMPL-X foot skinning support")
    floor = float(config.get("floor_z", 0.))
    clearance = float(config.get("clearance", .005))
    heights = np.stack([vertices[:, ids, 2].min(1) for ids in foot_ids], axis=1)
    # Stable grounded samples only estimate the constant height offset.
    centers = np.stack([vertices[:, ids].mean(1) for ids in foot_ids], axis=1)
    speeds = np.zeros((n,2))
    speeds[1:] = np.linalg.norm(np.diff(centers, axis=0), axis=2) * fps
    speeds[0] = speeds[1]
    grounded = valid & (speeds.min(1) < .15)
    shift = fixed_floor_shift(heights, grounded, floor, clearance,
                              float(config.get("height_trigger", .03)), float(config.get("max_shift", .5)))
    base = vertices.copy(); base[:,:,2] += shift
    heights_rel = heights + shift - floor
    contact = contact_mask(heights_rel, speeds, valid, min_frames=max(3, round(fps*.12)))
    if int((contact[:-1] & contact[1:]).sum()) < 3:
        raise ValueError("Insufficient contact samples; review grounded-motion assumption")
    before = measure(vertices, foot_ids, contact, valid, fps, floor)
    shifted = measure(base, foot_ids, contact, valid, fps, floor)
    report = {"id":actor["id"], "input_hashes":{k:sha(resolve(k)) for k in ("cache","motion","alignment")},
              "config":config, "alignment_up_tilt_degrees":tilt_degrees, "excluded_seconds":actor.get("exclude_seconds", []),
              "cache_reproduction_error_m":reproduction_error, "constant_vertical_shift_m":shift,
              "before":before, "after_fixed_alignment":shifted,
              "contact_frames":contact.sum(0).tolist(), "contact_is_ground_truth":False}
    need_ik = shifted["penetration_depth_max_m"] > .003 or shifted["contact_speed_p90_m_s"] > .10
    final_pose = p["body_pose"].detach().clone()
    final_v, final_j = base, room(j0).cpu().numpy()
    final_j[:,:,2] += shift
    optimization = []
    if need_ik:
        # Differentiable exact SMPL-X LBS restricted to feet for efficient global-time IK.
        ids = np.concatenate(foot_ids)
        ni = len(foot_ids[0])
        with torch.no_grad():
            shaped = model.v_template[None] + blend_shapes(p["betas"], model.shapedirs[:,:,:10])
            rest_j = vertices2joints(model.J_regressor, shaped)
        shaped_sub = shaped[:, ids]
        posedirs = model.posedirs.reshape(486, -1, 3)[:, ids].reshape(486, -1)
        weights = model.lbs_weights[ids]
        base_pose = full_pose.reshape(n, -1, 3).detach()
        leg_ids = [1,2,4,5,7,8,10,11]
        original = base_pose[:,leg_ids].clone()
        bounds = tensor([.4,.4,.6,.6,.5,.5,.25,.25])[None,:,None].expand(n,8,3).clone()
        bounds[:,2:4,1:] = .10
        delta = torch.zeros_like(original, requires_grad=True)
        opt = torch.optim.Adam([delta], lr=.035)
        target = base[:, ids].copy()
        for side, subset in enumerate((slice(0,ni), slice(ni,len(ids)))):
            dz = np.maximum(clearance-heights_rel[:,side], 0)
            dz[contact[:,side]] = clearance-heights_rel[contact[:,side],side]
            target[:,subset,2] += dz[:,None]
            for a,b in segments(contact[:,side]):
                anchor = centers[a:b,side,:2].mean(0)
                target[a:b,subset,:2] += (anchor-centers[a:b,side,:2])[:,None,:]
        target_t = tensor(target)
        valid_t = tensor(valid)[:,None,None]
        contact_t = tensor(np.concatenate([np.repeat(contact[:,0,None],ni,axis=1),
                                           np.repeat(contact[:,1,None],len(ids)-ni,axis=1)], axis=1))[:,:,None]
        def evaluate(enforce_limits=True):
            change = torch.tanh(delta) * bounds
            # Knee flexion stays within broad anatomical range; retain small original twist.
            legs = original + change
            knee_x = legs[:,2:4,0].clamp(-.10, 2.75) if enforce_limits else legs[:,2:4,0]
            legs = legs.clone();legs[:,2:4,0] = knee_x
            pose = base_pose.clone();pose[:,leg_ids] = legs
            rot = batch_rodrigues(pose.reshape(-1,3)).reshape(n,-1,3,3)
            feat = (rot[:,1:] - torch.eye(3,device=device)).reshape(n,-1)
            posed = shaped_sub + (feat @ posedirs).reshape(n,len(ids),3)
            joints, A = batch_rigid_transform(rot, rest_j, model.parents, dtype=torch.float32)
            transforms = torch.einsum("vj,tjkl->tvkl", weights, A)
            homogeneous = torch.cat([posed, torch.ones((n,len(ids),1),device=device)],dim=2)
            native = torch.einsum("tvkl,tvl->tvk",transforms,homogeneous)[:,:,:3]+p["transl"][:,None]
            world = room(native) + tensor([0,0,shift])
            return world, pose, change
        with torch.no_grad():
            w, _, _ = evaluate(enforce_limits=False)
            if float((w-tensor(base[:,ids])).abs().max()) > 1e-4:
                raise ValueError(f"Subset LBS baseline mismatch: {float((w-tensor(base[:,ids])).abs().max())}")
        for step in range(int(config.get("iterations",180))):
            opt.param_groups[0]["lr"] = .002 + .023 * (1 - step / int(config.get("iterations", 180))) ** 2
            opt.zero_grad()
            w, pose, change = evaluate()
            loss_target = (((w-target_t)**2) * valid_t * (1+3*contact_t)).mean()
            loss_floor = ((torch.relu(floor+clearance-w[:,:,2])**2) * valid_t[:,:,0]).mean()
            # Smooth correction, not original gestures; preserves unedited upper body/root.
            loss_smooth = ((change[2:]-2*change[1:-1]+change[:-2])**2).mean()
            loss_pose = (change**2).mean()
            reliable_triplet = valid_t[2:] * valid_t[1:-1] * valid_t[:-2]
            loss_accel = (((w[2:]-2*w[1:-1]+w[:-2])**2) * reliable_triplet).mean()
            contact_pair = contact_t[1:] * contact_t[:-1] * valid_t[1:] * valid_t[:-1]
            loss_slip = (((w[1:]-w[:-1])**2) * contact_pair).mean()
            loss_floor_worst = ((torch.relu(floor+clearance-w[:,:,2].amin(1))**2) * valid_t[:,0,0]).mean()
            loss = 100*loss_target + 2000*loss_floor + 4000*loss_floor_worst + .025*loss_pose + 4*loss_smooth + 300*loss_accel + 1500*loss_slip
            loss.backward();opt.step()
            if step % 30 == 0:
                optimization.append({"step":step,"loss":float(loss.detach())})
        with torch.no_grad():
            _, pose, change = evaluate()
            final_pose = pose[:,1:22].reshape(n,63)
            v1,j1,_ = skin(final_pose)
            final_v = room(v1).cpu().numpy();final_v[:,:,2] += shift
            final_j = room(j1).cpu().numpy();final_j[:,:,2] += shift
        report["max_leg_rotation_component_change_rad"] = float(change.abs().max())
    after = measure(final_v, foot_ids, contact, valid, fps, floor)
    xy_error = float(np.abs(final_j[:,0,:2]-cache["joints"][:,0,:2]).max())
    accepted, reasons = acceptance(before, after, xy_error)
    report.update(after=after,root_xy_max_error_m=xy_error,accepted=accepted,rejection_reasons=reasons,
                  optimization=optimization,ik_applied=need_ik,
                  method="constant support alignment + bounded whole-clip SMPL-X leg IK with correction acceleration penalty")
    candidate = dict(cache, vertices=final_v.astype("f4"), joints=final_j.astype("f4"))
    np.savez(output/"candidate.npz", **candidate)
    np.savez(output/"refined_parameters.npz", **params, refined_body_pose=final_pose.cpu().numpy(),
             rotation=R,translation=t+np.array([0,0,shift]),body_scale=scale,time_seconds=times)
    if accepted:
        if shift == 0 and not need_ik:
            shutil.copyfile(cache_path,output/"body_room.npz")
        else:
            np.savez(output/"body_room.npz", **candidate)
        report["selected"]="refined" if shift or need_ik else "unchanged"
    else:
        shutil.copyfile(cache_path,output/"body_room.npz"); report["selected"]="original_rejected_candidate"
    (output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--models",type=Path,required=True)
    parser.add_argument("--device",default="cuda")
    parser.add_argument("--refine-contact",action="store_true",help="Opt in to automatic support-height repair and leg IK; default preserves native motion")
    a=parser.parse_args()
    manifest=json.loads(a.manifest.read_text())
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from aha3d.workflow.layout_gate import validate_layout
    layout_validation=validate_layout(manifest,a.manifest)
    import torch,smplx
    if manifest.get("schema_version") != 1 or not manifest.get("actors"):
        raise ValueError("Expected manifest schema_version 1 with actors")
    ids=[x["id"] for x in manifest["actors"]]
    if len(set(ids)) != len(ids) or any(not isinstance(x,str) or not x or Path(x).name!=x or x in (".","..") for x in ids):
        raise ValueError("Actor IDs must be unique safe path components")
    from group_scale_gate import validate_group
    group_validation = validate_group(manifest, a.manifest.parent)
    a.output.mkdir(parents=True,exist_ok=False)
    from placement_gate import check_and_record
    check_and_record(a.manifest, a.output/'placement_before')
    (a.output/"layout_validation.json").write_text(json.dumps(layout_validation,indent=2))
    (a.output/"group_validation.json").write_text(json.dumps(group_validation,indent=2))
    (a.output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    model_path = a.models / "smplx" / "SMPLX_NEUTRAL.npz"
    provenance = {"implementation_sha256":sha(Path(__file__)), "manifest_sha256":sha(a.manifest),
                  "model_sha256":sha(model_path), "python":sys.version,
                  "torch":torch.__version__, "smplx":importlib.metadata.version("smplx"),
                  "device":a.device,"job_id":os.environ.get("INDOOR_RUN_ID"),
                  "mode":"contact_refinement" if a.refine_contact else "native_fixed_alignment"}
    (a.output/"provenance.json").write_text(json.dumps(provenance,indent=2))
    model=smplx.create(str(a.models),model_type="smplx",gender="neutral",num_pca_comps=12,flat_hand_mean=False).to(a.device).eval()
    for p in model.parameters():p.requires_grad_(False)
    reports=[]
    for actor in manifest["actors"]:
        result=refine_actor(actor,a.manifest.parent,a.output/actor["id"],model,a.device,manifest.get("config",{}),refine_contact=a.refine_contact)
        reports.append(result)
        print(json.dumps({k:result[k] for k in ("id","selected","constant_vertical_shift_m","before","after","rejection_reasons")}),flush=True)
    (a.output/"summary.json").write_text(json.dumps({"actors":reports,"all_accepted":all(x["accepted"] for x in reports)},indent=2))
    if not all(x["accepted"] for x in reports):
        raise SystemExit(2)
    check_and_record(a.manifest, a.output/'placement_after', refinement=a.output)
if __name__=="__main__":
    main()
