"""Fixed-world skeleton diagnostics; yaw/xz gauge alignment only, no fitted scale."""
from pathlib import Path
import json
import numpy as np


def yaw_xz_alignment(source, target):
    a, b = np.asarray(source, float), np.asarray(target, float)
    ca, cb = a.mean(0), b.mean(0)
    u, _, vh = np.linalg.svd((a[:, [0, 2]]-ca[[0, 2]]).T @ (b[:, [0, 2]]-cb[[0, 2]]))
    r2 = vh.T @ np.diag([1., np.linalg.det(vh.T @ u.T)]) @ u.T
    rotation = np.eye(3); rotation[np.ix_([0, 2], [0, 2])] = r2
    translation = cb - rotation @ ca; translation[1] = 0
    return rotation, translation


def render(out, upstream, model, baseline, candidate, fps):
    import cv2
    import imageio.v2 as imageio
    import joblib
    import smplx
    from PIL import Image
    try:
        from . import world_postopt as post
    except ImportError:
        import world_postopt as post
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    metric = post.module(Path(upstream)/'experiments/postopt_ab/metrics.py', 'world_review_metrics')
    body = smplx.SMPLX(str(model), use_pca=False, flat_hand_mean=True, num_betas=10).cuda()
    results = [joblib.load(path) for path in (baseline, candidate)]
    if any(len(result['people']) != 1 for result in results):
        raise ValueError('World diagnostic currently supports one actor per result')
    points=[];frames=[]
    for result in results:
        p=next(iter(result['people'].values()));sw=p['smplx_world']
        j,_=metric.forward(body,sw['pose'],sw['shape'],sw['trans'],'cuda')
        points.append(j[:,:22].cpu().numpy());frames.append(np.asarray(p['frames']))
    if results[0]['n_frames']!=results[1]['n_frames'] or not np.array_equal(frames[0],frames[1]):
        raise ValueError('World review requires identical source timelines')
    rotation,translation=yaw_xz_alignment(points[1][:,0],points[0][:,0])
    points[1]=points[1]@rotation.T+translation
    # Shared orthographic view; fixed bounds over both full trajectories.
    azimuth,elevation=np.deg2rad([35,20])
    basis=np.array([[np.cos(azimuth),0,-np.sin(azimuth)],
                    [-np.sin(elevation)*np.sin(azimuth),np.cos(elevation),-np.sin(elevation)*np.cos(azimuth)]])
    allpoints=np.concatenate(points).reshape(-1,3)
    lo,hi=allpoints.min(0),allpoints.max(0)
    lowxz,highxz=np.floor(lo[[0,2]])-1,np.ceil(hi[[0,2]])+1
    grid=[]
    for x in np.arange(lowxz[0],highxz[0]+.25,.5):grid.append([[x,0,lowxz[1]],[x,0,highxz[1]]])
    for z in np.arange(lowxz[1],highxz[1]+.25,.5):grid.append([[lowxz[0],0,z],[highxz[0],0,z]])
    uv=allpoints@basis.T;floor=(np.asarray(grid).reshape(-1,3)@basis.T)
    bounds=np.concatenate([uv,floor]);mn,mx=bounds.min(0),bounds.max(0)
    scale=min(580/max(mx[0]-mn[0],1),390/max(mx[1]-mn[1],1));center=(mn+mx)/2
    def project(p):
        v=(np.asarray(p)@basis.T-center)*scale
        v[...,1]*=-1
        return np.rint(v+[320,275]).astype(int)
    parents=[-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19]
    n=int(results[0]['n_frames']);active=set(frames[0].tolist());end=max(active)+1
    selected=sorted(set([0,n//4,n//2,3*n//4,n-1]+[f for f in (end-1,end,end+1) if 0<=f<n]))
    writer=imageio.get_writer(out/'world_comparison.mp4',fps=fps,codec='libx264',quality=7,macro_block_size=1)
    images=[]
    for frame in range(n):
        panels=[]
        for i,(name,color) in enumerate([('GVHMR global',(220,120,50)),('Corrected v2',(45,160,40))]):
            panel=np.full((500,640,3),245,np.uint8)
            for segment in grid:
                a,b=project(segment);cv2.line(panel,tuple(a),tuple(b),(215,215,215),1)
            idx=np.searchsorted(frames[i],frame)
            trail=points[i][:idx+1,0] if frame in active else points[i][:idx,0]
            if len(trail)>1:cv2.polylines(panel,[project(trail)],False,color,1,cv2.LINE_AA)
            if frame in active:
                xy=project(points[i][idx])
                for child,parent in enumerate(parents):
                    if parent>=0:cv2.line(panel,tuple(xy[child]),tuple(xy[parent]),color,3,cv2.LINE_AA)
                for point in xy:cv2.circle(panel,tuple(point),3,color,-1)
            cv2.putText(panel,name,(12,25),cv2.FONT_HERSHEY_SIMPLEX,.7,color,2)
            cv2.putText(panel,f'frame {frame}/{n-1} | '+('ACTIVE' if frame in active else 'INACTIVE'),(12,49),cv2.FONT_HERSHEY_SIMPLEX,.48,(40,40,40),1)
            cv2.putText(panel,'Fixed view; 0.5 m grid; yaw/xz alignment only',(12,480),cv2.FONT_HERSHEY_SIMPLEX,.45,(40,40,40),1)
            panels.append(panel)
        image=cv2.cvtColor(np.concatenate(panels,axis=1),cv2.COLOR_BGR2RGB);writer.append_data(image)
        if frame in selected:images.append(Image.fromarray(image))
    writer.close()
    cap=cv2.VideoCapture(str(out/'world_comparison.mp4'));decoded=0
    rate=cap.get(cv2.CAP_PROP_FPS)
    while cap.read()[0]:decoded+=1
    cap.release()
    if decoded!=n or abs(rate-fps)>1e-5:raise ValueError('World video timing mismatch')
    sheet=Image.new('RGB',(1280,500*len(images)))
    for i,im in enumerate(images):sheet.paste(im,(0,500*i))
    sheet.save(out/'world_frames.jpg',quality=90)
    record=dict(frames=n,decoded_frames=decoded,fps=rate,duration_seconds=n/rate,active_frames=len(active),
                representative_frames=selected,gauge_rotation=rotation.tolist(),gauge_translation=translation.tolist(),
                scale=1,scope='Fixed-world skeleton diagnostic; only yaw/xz display alignment. No authored-room mesh/contact validation.')
    (out/'world_validation.json').write_text(json.dumps(record,indent=2)+'\n')
    return record
