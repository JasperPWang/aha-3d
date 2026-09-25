"""Align a native GVHMR sequence to a same-video Pi3X room."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from aha3d.workflow.camera import interpolate

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--motion',type=Path,required=True);p.add_argument('--room',type=Path,required=True)
 p.add_argument('--models',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 import torch,smplx
 a.output.mkdir(parents=True,exist_ok=True)
 z=np.load(a.motion);n=len(z['smpl_params_global__transl']);times=z['frame_times_seconds']
 camera_path=a.room/('cameras_reviewed.json' if (a.room/'cameras_reviewed.json').exists() else 'cameras.json')
 cam=json.loads(camera_path.read_text());inputs=json.loads((a.room/'inputs.json').read_text())
 provenance=json.loads((a.motion.parent/'provenance.json').read_text())
 if provenance['source_sha256']!=inputs['source_sha256']:raise ValueError('Motion and room must come from the identical source video')
 if inputs['original_size_wh']!=[1280,720]:raise ValueError('This pilot adapter currently requires a 1280x720 source')
 camera,held=interpolate(cam,times,inputs['processed_size_wh'],[1280,720],endpoint='error')
 C,K=camera['c2w'],camera['K'];np.savez(a.output/'camera.npz',**camera)
 model=smplx.create(str(a.models),model_type='smplx',gender='neutral',num_pca_comps=12,flat_hand_mean=False).cuda().eval()
 def skin(kind):
  chunks=[];joints=[]
  for start in range(0,n,32):
   d={key:torch.tensor(z[f'smpl_params_{kind}__{key}'][start:start+32],device='cuda') for key in ['body_pose','betas','global_orient','transl']}
   b=len(d['betas'])
   d.update({k:torch.zeros((b,m),device='cuda') for k,m in [('left_hand_pose',12),('right_hand_pose',12),('jaw_pose',3),('leye_pose',3),('reye_pose',3),('expression',10)]})
   with torch.inference_mode():o=model(**d)
   chunks.append(o.vertices.cpu().numpy());joints.append(o.joints[:,:22].cpu().numpy())
  return np.concatenate(chunks),np.concatenate(joints)
 vg,jg=skin('global');vi,ji=skin('incam')
 kg=z['K_fullimg'];h=ji@kg.transpose(0,2,1);target=h[...,:2]/h[...,2:]
 # Global orientation relationship supplies a physically proper initial rotation.
 rg=Rotation.from_rotvec(z['smpl_params_global__global_orient']).as_matrix()
 ri=Rotation.from_rotvec(z['smpl_params_incam__global_orient']).as_matrix()
 r0=Rotation.from_matrix(C[:,:3,:3]@ri@rg.transpose(0,2,1)).mean().as_matrix()
 # Adapt root depth to Pi3X focal length for initialization only.
 roots=ji[:,0].copy(); roots[:,2]*=K[:,0,0]/kg[:,0,0]
 roots[:,:2]=(target[:,0]-K[:,:2,2])*roots[:,2,None]/K[:,[0,1],[0,1]]
 rw=np.einsum('nij,nj->ni',C[:,:3,:3],roots)+C[:,:3,3]
 t0=np.median(rw-jg[:,0]@r0.T,axis=0)
 def unpack(x):return Rotation.from_rotvec(x[:3]).as_matrix(),x[3:6],np.exp(x[6])
 def project(x):
  r,t,s=unpack(x);world=s*(jg@r.T)+t
  q=np.einsum('nji,nkj->nki',C[:,:3,:3],world-C[:,None,:3,3]);q=q@K.transpose(0,2,1)
  return q[...,:2]/np.maximum(q[...,2:],.1)
 def residual(x):
  # Weak size prior prevents degenerate similarity on near-stationary camera paths.
  return np.r_[((project(x)-target)/10).ravel(),x[6]/.10]
 x0=np.r_[Rotation.from_matrix(r0).as_rotvec(),t0,0.]
 fit=least_squares(residual,x0,loss='soft_l1',max_nfev=180,bounds=(np.r_[[-np.inf]*6,np.log(.7)],np.r_[[np.inf]*6,np.log(1.3)]))
 r,t,s=unpack(fit.x);v=s*(vg@r.T)+t;j=s*(jg@r.T)+t
 err=np.linalg.norm(project(fit.x)-target,axis=-1)
 np.savez(a.output/'body_room.npz',schema_version=1,vertices=v.astype('f4'),joints=j.astype('f4'),faces=model.faces.astype('i4'),vertex_ids=np.arange(v.shape[1]),fps=30.,time_seconds=times,surface_model_type='SMPL-X neutral; GVHMR estimate',joint_names=np.array([str(i) for i in range(22)]))
 np.savez(a.output/'alignment_diagnostics.npz',target_uv=target,aligned_uv=project(fit.x),root_world=j[:,0],global_vertices=vg)
 report=dict(method='One similarity fitted across all frames to GVHMR camera-space joint projections using same-video Pi3X cameras; weak log-scale prior sigma 0.10. No per-frame root edits.',rotation=r.tolist(),translation=t.tolist(),body_scale=float(s),reprojection_px_median=float(np.median(err)),reprojection_px_p90=float(np.percentile(err,90)),reprojection_px_max=float(err.max()),frame_median_px=np.median(err,axis=1).tolist(),floor_min_z_percentiles=np.percentile(v[:,:,2].min(1),[0,50,100]).tolist(),root_path_m=float(np.linalg.norm(np.diff(j[:,0],axis=0),axis=1).sum()),frames=n,fps=30,camera_held_frames=held,optimizer_success=bool(fit.success),absolute_scale_validated=False,contact_optimization=False,floor_alignment=cam['floor_alignment'],motion_source=str(a.motion.resolve()))
 (a.output/'alignment.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
