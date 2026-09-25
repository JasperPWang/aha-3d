"""Geometric floor hypothesis; confidence is not physical accuracy."""
import numpy as np

def stats(a):
    a=np.asarray(a); a=a[np.isfinite(a)]
    return {'count':int(a.size),'median':float(np.median(a)),'p90':float(np.percentile(a,90))} if a.size else {'count':0}

def world_alignment(points,valid,cameras):
    up=-cameras[:,:3,1].mean(0);up/=np.linalg.norm(up)
    normals=np.cross(points[:,1:-1,2:]-points[:,1:-1,:-2],points[:,2:,1:-1]-points[:,:-2,1:-1])
    norms=np.linalg.norm(normals,axis=-1)
    horizontal=(np.abs(normals@up)/np.maximum(norms,1e-12)>0.9)&valid[:,1:-1,1:-1]
    candidate=points[:,1:-1,1:-1][horizontal]
    rng=np.random.default_rng(42)
    if len(candidate)>20000:candidate=candidate[rng.choice(len(candidate),20000,replace=False)]
    camera_height=np.median(cameras[:,:3,3]@up)
    candidate=candidate[candidate@up<camera_height-0.5]
    info={'status':'camera-up only; no floor accepted','floor_plane_is_measured_ground_truth':False}
    origin=cameras[0,:3,3].copy()
    if len(candidate)>100:
        heights=candidate@up
        lo,hi=np.percentile(heights,[2,98]);edges=np.arange(lo,hi+0.05,0.05)
        if len(edges)>3:
            counts,_=np.histogram(heights,edges)
            # Choose the lowest substantial height mode; a floor hypothesis, not semantics.
            peaks=[i for i in range(1,len(counts)-1) if counts[i]>=max(50,0.2*counts.max()) and counts[i]>=counts[i-1] and counts[i]>=counts[i+1]]
            if peaks:
                floor_h=(edges[peaks[0]]+edges[peaks[0]+1])/2
                low=candidate[np.abs(heights-floor_h)<0.12]
                best=None;best_count=0
                for _ in range(180):
                    a,b,c=low[rng.choice(len(low),3,replace=False)]
                    n=np.cross(b-a,c-a);length=np.linalg.norm(n)
                    if length<1e-8:continue
                    n/=length
                    if n@up<0:n=-n
                    if n@up<0.94:continue
                    d=-n@a;inside=np.abs(low@n+d)<0.025
                    if inside.sum()>best_count:best=(n,d,inside);best_count=int(inside.sum())
                if best is not None and best_count>=100:
                    fit=low[best[2]];center=fit.mean(0)
                    _,_,v=np.linalg.svd(fit-center,full_matrices=False)
                    n=v[-1];n=n if n@up>0 else -n;d=-n@center
                    origin=cameras[0,:3,3]-(n@cameras[0,:3,3]+d)*n
                    up=n
                    info={'status':'automatic floor hypothesis; visual confirmation required',
                          'plane_normal_raw':n.tolist(),'plane_offset_raw':float(d),
                          'sampled_inliers':best_count,'plane_residual_predicted_m':stats(np.abs(fit@n+d)),
                          'camera_height_predicted_m':stats(cameras[:,:3,3]@n+d),
                          'floor_plane_is_measured_ground_truth':False}
    right=cameras[0,:3,0].copy();right-=up*(right@up);right/=np.linalg.norm(right)
    forward=np.cross(up,right)
    basis=np.stack([right,forward,up])
    transform=np.eye(4);transform[:3,:3]=basis;transform[:3,3]=-basis@origin
    info['world_transform_raw_to_aligned']=transform.tolist()
    return transform,info
