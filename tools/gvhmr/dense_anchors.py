"""Dense same-person depth anchors with visible-keypoint fallback.

Helpers consume full-image COCO17 observations and matching processed-raster
Pi3X predictions. Pair preference never prevents trying a remaining joint when
pair depth is unsupported. Each surface point constrains a posed body offset,
not an assumed pelvis depth. No model execution or body scaling occurs here.
"""
from __future__ import annotations
import numpy as np
from scipy.special import expit
from tools.gvhmr.depth_observations import ray_hit

NAMES=('nose','left_eye','right_eye','left_ear','right_ear','left_shoulder',
       'right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist',
       'left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle')


def anchor_candidates(keypoints, threshold=.5, *, allow_weak=False):
    """Prefer good pairs/joints, retaining low-score predictions in fallback.

    ``allow_weak`` is for a second whole-clip pass after strong anchors prove
    unavailable/insufficient. Low confidence lowers weight instead of removing
    the constraint. All-zero empty-mask sentinels are missing predictions.
    """
    kp=np.asarray(keypoints,float)
    if kp.shape != (17,3) or not 0 <= threshold <= 1:
        raise ValueError('Expected COCO17 [17,3] and a score threshold in [0,1]')
    present=np.isfinite(kp).all(1)&(kp[:,2]>=0)&(kp[:,2]<=1)&~np.all(kp==0,axis=1)
    valid=present & ((kp[:,2]>=threshold) | allow_weak)
    candidates=[]
    for name,ids in [('hips',[11,12]),('shoulders',[5,6])]+[(NAMES[i],[i]) for i in [11,12,5,6,7,8,9,10,13,14,15,16,0,1,2,3,4]]:
        if valid[ids].all():
            confidence=float(kp[ids,2].min())
            weak=confidence<threshold
            candidates.append(dict(name=name,joints=ids,uv=kp[ids,:2].mean(0),
                                   confidence=confidence,pair=len(ids)==2,
                                   evidence='weak_keypoint' if weak else 'strong_keypoint',
                                   weight=max(confidence,.01)**2*(.1 if weak else 1.)))
    # Strong singles are preferable to a weak pair; preserve anatomical order
    # within each tier and preserve all remaining candidates for depth failures.
    candidates.sort(key=lambda item:item['evidence']=='weak_keypoint')
    return candidates


def collect_clip_anchors(keypoints, collect, *, threshold=.5, required_frames=3):
    """Try every frame strongly, then explicitly retry weak evidence if needed.

    ``collect(frame, candidate)`` returns an accepted observation dict or None
    after actual mask/depth/posed-surface correspondence. Its rejection details
    should be retained by the caller. Never convert missing predictions to a
    fabricated anchor; an empty result remains a reconstruction repair failure.
    """
    if required_frames < 1:
        raise ValueError('Positive minimum anchor-frame count required')
    observations=[];supported=set()
    for allow_weak in (False,True):
        for frame,kp in enumerate(keypoints):
            if frame in supported:continue
            for candidate in anchor_candidates(kp,threshold,allow_weak=allow_weak):
                if allow_weak and candidate['evidence']!='weak_keypoint':continue
                result=collect(frame,candidate)
                if result is not None:
                    observations.append(dict(result,frame=frame,anchor=candidate['name'],
                        keypoint_evidence=candidate['evidence'],keypoint_weight=candidate['weight']))
                    supported.add(frame);break
        if len(supported)>=required_frames:break
    return sorted(observations,key=lambda row:row['frame'])


def sample_keypoint_surface(depth, logits, non_edge, mask, uv, K, c2w,
                            radius=5, confidence_threshold=0.):
    """Use a local same-person depth patch, including narrow visible limbs.

    A valid centre can be on a thin wrist/ankle; two-pixel mask erosion is not
    mandatory. A small mask-edge displacement is recorded and downweighted.
    Nearest supported depth cluster avoids averaging foreground and background.
    Confidence is a weight by default, not a 0.5 hard gate that can eliminate
    every pixel of a foreground person. Explicit experiment thresholds remain
    available; low-depth-confidence observations are labeled independently of
    keypoint confidence.
    """
    z=np.asarray(depth);mask=np.asarray(mask,bool);uv=np.asarray(uv,float)
    conf=expit(np.asarray(logits).squeeze());edge=np.asarray(non_edge,bool)
    if z.ndim!=2 or any(a.shape!=z.shape for a in (mask,conf,edge)):
        raise ValueError('Depth, confidence, edge and actor mask must share a raster')
    if uv.shape!=(2,) or not np.isfinite(uv).all():return None,dict(reason='invalid keypoint')
    h,w=z.shape;x,y=uv
    if not (0<=x<w and 0<=y<h):return None,dict(reason='keypoint outside source frame')
    y0,y1=max(0,int(y)-radius),min(h,int(y)+radius+2)
    x0,x1=max(0,int(x)-radius),min(w,int(x)+radius+2)
    yy,xx=np.mgrid[y0:y1,x0:x1];distance=(xx-x)**2+(yy-y)**2
    local=z[y0:y1,x0:x1]
    valid=(distance<=radius**2)&mask[y0:y1,x0:x1]&edge[y0:y1,x0:x1]
    valid&=np.isfinite(local)&(local>0)&(conf[y0:y1,x0:x1]>confidence_threshold)
    if not valid.any():return None,dict(reason='no supported depth in local person-mask patch')
    nearest=np.argmin(np.where(valid,distance,np.inf));iy,ix=np.unravel_index(nearest,valid.shape)
    centre=float(local[iy,ix]);cluster=valid&(np.abs(local-centre)<=max(.04,.02*centre))
    vals=local[cluster];depth_value=float(np.median(vals));mad=float(np.median(np.abs(vals-depth_value)))
    sample_uv=np.array([xx[iy,ix],yy[iy,ix]],float)
    ray=np.linalg.solve(K,np.r_[sample_uv,1.]);ray/=ray[2]
    world=c2w[:3,:3]@(ray*depth_value)+c2w[:3,3]
    offset=float(np.linalg.norm(sample_uv-uv))
    depth_confidence=float(np.median(conf[y0:y1,x0:x1][cluster]))
    weight=depth_confidence*min(1.,len(vals)/9)/(1+offset)/(1+mad/.02)
    return world,dict(valid=True,pixels=int(len(vals)),uv=sample_uv.tolist(),requested_uv=uv.tolist(),
                      pixel_offset=offset,depth_m=depth_value,depth_mad_m=mad,weight=weight,
                      depth_confidence=depth_confidence,weak_depth=depth_confidence<.5)


def root_target_from_surface(surface_world, vertices_world, root_world,
                             anchor_world, uv, K, c2w, anchor_depth):
    """Match the observed ray against the posed surface before locating pelvis.

    Translate the camera-space pose so its anatomical anchor projects onto the
    same sampled ray. Its initial depth affects only the surface/pelvis offset;
    the observed surface depth supplies absolute distance. No wrist-as-pelvis
    shortcut and no intersection along a different model-predicted pixel ray.
    """
    if not np.isfinite(anchor_depth) or anchor_depth<=0:return None
    vertices,faces=vertices_world
    ray=np.linalg.solve(K,np.r_[uv,1.]);ray/=ray[2]
    relative=(vertices-root_world)@c2w[:3,:3]
    offset=(anchor_world-root_world)@c2w[:3,:3]
    proposed_root=ray*anchor_depth-offset
    front=ray_hit(relative+proposed_root,faces,ray)
    if front is None:return None
    return surface_world+c2w[:3,:3]@(proposed_root-front)


def robust_translation(offsets, weights):
    """Confidence-weighted robust fixed translation, without trajectory scaling."""
    values=np.asarray(offsets,float);weights=np.asarray(weights,float)
    if values.ndim!=2 or values.shape[1]!=3 or weights.shape!=(len(values),):
        raise ValueError('Expected offsets[N,3] and weights[N]')
    valid=np.isfinite(values).all(1)&np.isfinite(weights)&(weights>0)
    values=values[valid];weights=weights[valid]
    if not len(values):raise ValueError('No supported anchor observations')
    delta=np.median(values,axis=0)
    for _ in range(20):
        residual=np.linalg.norm(values-delta,axis=1)
        scale=max(.03,1.4826*np.median(np.abs(residual-np.median(residual))))
        w=weights*np.minimum(1.,1.5*scale/np.maximum(residual,1e-9))
        updated=np.average(values,axis=0,weights=w)
        if np.linalg.norm(updated-delta)<1e-7:break
        delta=updated
    return updated
