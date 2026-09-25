"""Export a generic image-only Pi3X reference bundle from a continuous video shot."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

def digest(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--num-frames',type=int,choices=(32,64),default=32)
    parser.add_argument('--frame-indices',type=Path,help='Ordered native frame IDs matching the selected 32/64 frame tier; include both endpoints')
    parser.add_argument('--pixel-limit',type=int,default=255000)
    parser.add_argument('--confidence',type=float,default=0.5)
    args=parser.parse_args()
    if args.num_frames<2 or args.pixel_limit<196 or not 0<args.confidence<1:parser.error('Invalid frame count, resolution or confidence')
    for path in [args.video,args.checkpoint,args.upstream/'pi3/models/pi3x.py']:
        if not path.is_file():parser.error(f'Missing input: {path}')
    import cv2
    import numpy as np
    from PIL import Image
    import torch
    from safetensors.torch import load_file
    from geometry import world_alignment
    if not torch.cuda.is_available():parser.error('Reconstruction requires a visible CUDA GPU')
    sys.path.insert(0,str(args.upstream.resolve()))
    from pi3.models.pi3x import Pi3X
    from pi3.utils.geometry import recover_intrinsic_from_rays_d,depth_normal_edge
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'frames').mkdir()
    dump=lambda name,value:(out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    started=time.perf_counter()
    cap=cv2.VideoCapture(str(args.video))
    if not cap.isOpened():raise ValueError('Cannot open input video')
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=float(cap.get(cv2.CAP_PROP_FPS))
    ow,oh=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if total<2 or min(ow,oh)<=0 or not math.isfinite(fps) or fps<=0:raise ValueError('Invalid video metadata')
    ids=json.loads(args.frame_indices.read_text()) if args.frame_indices else np.linspace(0,total-1,min(args.num_frames,total)).round().astype(int).tolist()
    if not isinstance(ids,list) or len(ids)<2 or any(type(i) is not int or i<0 or i>=total for i in ids) or ids!=sorted(set(ids)):
        raise ValueError('Frame IDs must be unique, ascending, in-range integers')
    if len(ids)!=min(args.num_frames,total) or ids[0]!=0 or ids[-1]!=total-1:
        raise ValueError('Frame selection must match the 32/64 tier (all frames for shorter videos) and include both endpoints')
    ratio=math.sqrt(args.pixel_limit/(ow*oh));tw,th=ow*ratio,oh*ratio
    kw,kh=max(1,round(tw/14)),max(1,round(th/14))
    while kw*kh*196>args.pixel_limit:
        if kw/kh>tw/th and kw>1:kw-=1
        elif kh>1:kh-=1
        else:kw-=1
    width,height=kw*14,kh*14
    wanted=set(ids);frames=[];timestamps=[];decoded=0
    while True:
        ok,bgr=cap.read()
        if not ok:break
        if decoded in wanted:
            timestamps.append(float(cap.get(cv2.CAP_PROP_POS_MSEC)/1000))
            im=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)).resize((width,height),Image.Resampling.LANCZOS)
            frames.append(np.asarray(im));im.save(out/'frames'/f'{decoded:06d}.jpg',quality=90)
        decoded+=1
    cap.release()
    if decoded!=total or len(frames)!=len(ids):raise ValueError('Incomplete video decoding or selected frames missing')
    if not np.isfinite(timestamps).all() or np.any(np.diff(timestamps)<=0):raise ValueError('Decoder did not provide valid presentation timestamps; use an explicit PTS-aware decoder')
    rgb=np.stack(frames)
    manifest={'schema_version':1,'source':str(args.video.resolve()),'source_sha256':digest(args.video),
              'source_frame_count':decoded,'source_fps':fps,'frame_indices':ids,'timestamps_seconds':timestamps,
              'timestamp_source':'OpenCV decoder presentation timestamp, seconds; not inferred from selected-frame cadence',
              'original_size_wh':[ow,oh],'processed_size_wh':[width,height],'resize':'Whole frame PIL LANCZOS; no crop',
              'conditions_used':[],'shot_policy':'Caller selected one continuous shot; automatic cut detection not implemented',
              'pixel_coordinate_convention':'Recovered K uses integer-index centers and ((W-1)/2,(H-1)/2).',
              'job_id':os.environ.get('INDOOR_RUN_ID')}
    dump('inputs.json',manifest)
    np.savez(out/'inputs.npz',rgb=rgb,frame_indices=np.array(ids),timestamps_seconds=np.array(timestamps))
    t=time.perf_counter();model=Pi3X(use_multimodal=False).eval()
    weights=load_file(str(args.checkpoint));mismatch=model.load_state_dict(weights,strict=False);del weights
    allowed=('depth_encoder.','depth_emb','ray_embed.','pose_inject_blk.')
    if mismatch.missing_keys or any(not key.startswith(allowed) for key in mismatch.unexpected_keys):raise ValueError('Checkpoint does not match the image-only Pi3X model')
    model=model.cuda();imgs=torch.from_numpy(rgb.copy()).permute(0,3,1,2).float().div_(255)[None].cuda()
    torch.cuda.synchronize();load_seconds=time.perf_counter()-t;torch.cuda.reset_peak_memory_stats();t=time.perf_counter()
    dtype=torch.bfloat16 if torch.cuda.get_device_capability()[0]>=8 else torch.float16
    with torch.inference_mode(),torch.autocast('cuda',dtype=dtype):res=model(imgs)
    torch.cuda.synchronize();inference_seconds=time.perf_counter()-t
    with torch.inference_mode():
        k=recover_intrinsic_from_rays_d(res['rays'],force_center_principal_point=True)
        conf=torch.sigmoid(res['conf'][...,0]);non_edge=~depth_normal_edge(res['local_points'],rtol=0.03,mask=conf>0.1)
    pred={key:value.detach().float().cpu().numpy()[0] for key,value in res.items()}
    pred['intrinsics']=k.detach().float().cpu().numpy()[0];pred['non_edge']=non_edge.cpu().numpy()[0]
    if not all(np.isfinite(value).all() for value in pred.values()):raise ValueError('Nonfinite reconstruction')
    np.savez(out/'predictions.npz',**pred)
    valid=(conf.cpu().numpy()[0]>args.confidence)&pred['non_edge']
    if valid.sum()<100:raise ValueError('Too few reliable points; raw outputs retained')
    transform,floor=world_alignment(pred['points'],valid,pred['camera_poses'])
    selected=np.flatnonzero(valid.reshape(-1));rng=np.random.default_rng(42)
    if len(selected)>350000:selected=rng.choice(selected,350000,replace=False)
    cloud=pred['points'].reshape(-1,3)[selected]@transform[:3,:3].T+transform[:3,3]
    cameras=transform@pred['camera_poses']
    np.savez(out/'reference_samples.npz',points=cloud,colors=rgb.reshape(-1,3)[selected],source_flat_indices=selected,camera_c2w=cameras)
    dump('cameras.json',{'schema_version':1,'convention':'camera-to-world OpenCV camera axes (right,down,forward); aligned world Z up',
        'units':'predicted metres; uncalibrated','world_transform':transform.tolist(),'floor_alignment':floor,
        'processed_size_wh':[width,height],'frames':[{'source_frame':i,'timestamp_seconds':ts,'c2w':pose.tolist(),'intrinsics':ki.tolist()}
          for i,ts,pose,ki in zip(ids,timestamps,cameras,pred['intrinsics'])]})
    rotation_error=float(np.max(np.abs(cameras[:,:3,:3]@cameras[:,:3,:3].transpose(0,2,1)-np.eye(3))))
    if rotation_error>1e-4 or np.any(np.linalg.det(cameras[:,:3,:3])<0.999):raise ValueError('Invalid camera rotations')
    commit=subprocess.run(['git','-C',str(args.upstream),'rev-parse','HEAD'],capture_output=True,text=True,check=False)
    dump('run_report.json',{'status':'raw reference exported; visual/geometric review required',
        'upstream_commit':commit.stdout.strip() if commit.returncode==0 else None,
        'upstream_model_sha256':digest(args.upstream/'pi3/models/pi3x.py'),'checkpoint_sha256':digest(args.checkpoint),
        'script_sha256':digest(__file__),'checkpoint_path':str(args.checkpoint.resolve()),
        'torch':torch.__version__,'gpu':torch.cuda.get_device_name(),'peak_gpu_allocated_gib':torch.cuda.max_memory_allocated()/2**30,
        'model_load_seconds':load_seconds,'inference_seconds':inference_seconds,'total_seconds':time.perf_counter()-started,
        'confidence_threshold':args.confidence,'retained_fraction':float(valid.mean()),'floor_alignment':floor,
        'metric_factor_already_applied':True,'absolute_scale_validated':False,'rotation_orthonormal_error':rotation_error,
        'dynamic_mask_applied':False,'independent_correspondence_validation':'not performed by this helper'})
    print(out)

if __name__=='__main__':main()
