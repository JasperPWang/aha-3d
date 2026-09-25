"""G1 hinge-space contact fitting and mesh export, without human skinning.

Root orientation is retained as matrices. Physical hinge angles use continuous
bounded scalars and sin/cos matrices; no axis-angle pose optimization is used.
"""
import ast
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import torch
from scipy.spatial.transform import Rotation

ROOM = np.array([[-1,0,0],[0,0,1],[0,1,0]],dtype=np.float32)
MJ_TO_NATIVE = np.array([[0,1,0],[0,0,1],[1,0,0]],dtype=np.float32)


def validate_state_change(plan):
    """Reject gesture-only tasks and object changes outside planned hand contact."""
    from aha3d.motion.interaction import compile_plan
    c=compile_plan(plan)
    moves=np.linalg.norm(np.diff(c['object_translation'],axis=0),axis=-1)>1e-7
    light=plan.get('light_track')
    light_changes=False
    if light:
        keys=np.asarray(light['keys'],float)
        if keys.ndim!=2 or keys.shape[1]!=2 or not np.isfinite(keys).all() or np.any(np.diff(keys[:,0])<=0) or np.any((keys[:,1]<0)|(keys[:,1]>1)):
            raise ValueError('Invalid normalized lamp state keys')
        if keys[0,0]>0 or keys[-1,0]<c['times'][-1]:
            raise ValueError('Lamp keys must cover the complete sequence')
        level=np.interp(c['times'],keys[:,0],keys[:,1]);changes=np.abs(np.diff(level))>1e-7
        light_changes=bool(changes.any())
        if np.any(changes&~(c['hand_on'][1:]&c['hand_on'][:-1])):
            raise ValueError('Lamp changes outside planned hand contact')
    if not moves.any() and not light_changes:
        raise ValueError('Interaction must change an object pose or operational state')
    if np.any(moves&~(c['hand_on'][1:]&c['hand_on'][:-1])):
        raise ValueError('Object moves outside planned hand contact')
    return c


def load_mesh(skeleton):
    """Use the installed official mesh/joint map and MJCF mesh transforms."""
    import kimodo,trimesh
    source=Path(kimodo.__file__).parent/'viz/g1_rig.py'
    mapping=next(ast.literal_eval(n.value) for n in ast.parse(source.read_text()).body
                 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='G1_MESH_JOINT_MAP' for t in n.targets))
    folder=Path(skeleton.folder);xml=ET.parse(folder/'xml/g1.xml')
    file_names={m.get('file'):m.get('name') for m in xml.findall('.//asset/mesh')}
    transforms={}
    for g in xml.findall('.//geom'):
        if g.get('mesh'):
            p=np.fromstring(g.get('pos','0 0 0'),sep=' ')
            q=np.fromstring(g.get('quat','1 0 0 0'),sep=' ')
            transforms[g.get('mesh')]=(MJ_TO_NATIVE@p,MJ_TO_NATIVE@Rotation.from_quat(q[[1,2,3,0]]).as_matrix()@MJ_TO_NATIVE.T)
    vertices=[];faces=[];joints=[];parts=[];offset=0
    for name,files in mapping.items():
        for file in files:
            path=folder/'meshes/g1'/file
            if not path.exists():continue
            mesh=trimesh.load_mesh(path,process=True)
            if len(mesh.faces)>1200:
                mesh=mesh.simplify_quadric_decimation(face_count=1200)
            v=np.asarray(mesh.vertices)@MJ_TO_NATIVE.T
            p,r=transforms.get(file_names.get(file),(np.zeros(3),np.eye(3)))
            v=v@r.T+p;faces.append(np.asarray(mesh.faces)+offset);vertices.append(v)
            joints.extend([skeleton.bone_index[name]]*len(v));parts.append(dict(file=file,joint=name,start=offset,end=offset+len(v)));offset+=len(v)
    return dict(vertices=np.concatenate(vertices).astype(np.float32),faces=np.concatenate(faces),joint_ids=np.array(joints),parts=parts)


def skin(mesh,global_rotations,joints):
    ids=mesh['joint_ids'];v=mesh['vertices']
    return np.einsum('tvij,vj->tvi',global_rotations[:,ids],v)+joints[:,ids]


def fingertip_point(vertices, cap_depth=.003):
    """A real distal surface vertex of the official rubber hand (+local Z).

    Select the vertex nearest the distal cap's centre, not the volume centroid.
    This is a fixed rubber-hand contact, not an articulated finger grasp.
    """
    v=np.asarray(vertices)
    if v.ndim!=2 or v.shape[1]!=3 or not len(v) or not np.isfinite(v).all():
        raise ValueError('Expected finite hand mesh vertices')
    tip=v[v[:,2]>=v[:,2].max()-cap_depth]
    return tip[np.argmin(np.linalg.norm(tip-tip.mean(0),axis=1))].copy()


def patches(mesh, hand_contact='fingertip'):
    if hand_contact not in ('fingertip','legacy-centroid'):
        raise ValueError('Select fingertip contact or explicit legacy-centroid comparison')
    result={}
    for side in ('left','right'):
        part=next(p for p in mesh['parts'] if p['file']==side+'_rubber_hand.STL')
        ids=np.arange(part['start'],part['end']);v=mesh['vertices'][ids]
        result[side+'_hand_mesh']=(part['joint'],v)
        result[side+'_hand']=(part['joint'],fingertip_point(v) if hand_contact=='fingertip' else v.mean(0))
        part=next(p for p in mesh['parts'] if p['file']==side+'_ankle_roll_link.STL')
        ids=np.arange(part['start'],part['end']);v=mesh['vertices'][ids]
        result[side+'_sole']=(part['joint'],v)
        low=v[:,1]<v[:,1].min()+.012;v=v[low]
        for which,mask in [('heel',v[:,2]<np.median(v[:,2])),('toe',v[:,2]>=np.median(v[:,2]))]:
            sample=v[mask];result[side+'_'+which]=(part['joint'],sample[::max(1,len(sample)//12)])
    return result


class HingeRig:
    def __init__(self,sk):
        from kimodo.exports.mujoco import MujocoQposConverter
        self.sk=sk;self.device=sk.neutral_joints.device;self.converter=MujocoQposConverter(sk)
        c=self.converter;self.ids=c._mujoco_indices_to_kimodo_indices.long().to(self.device)
        self.offset=c._rot_offsets_f2q.to(self.device)[self.ids]
        self.axis=c._mujoco_joint_axis_values_f2q_space.to(self.device)
        self.rest=c._rest_dofs_axis_angle.to(self.device)
        self.lo=c._joint_limits_min.to(self.device);self.hi=c._joint_limits_max.to(self.device)
        x,y,z=self.axis.unbind(-1);zero=torch.zeros_like(x)
        self.K=torch.stack([zero,-z,y,z,zero,-x,-y,x,zero],-1).reshape(-1,3,3)
        self.K2=self.K@self.K
    def tensor(self,x):return torch.as_tensor(x,dtype=torch.float32,device=self.device)
    def encode(self,local):
        r=self.offset@local[:,self.ids]
        # Closest axis-preserving matrix angle; initialization only, unwrapped in time.
        sine=torch.stack([r[...,2,1]-r[...,1,2],r[...,0,2]-r[...,2,0],r[...,1,0]-r[...,0,1]],-1).mul(.5).mul(self.axis).sum(-1)
        cosine=(r.diagonal(dim1=-2,dim2=-1).sum(-1)-1)*.5
        raw=torch.atan2(sine,cosine).detach().cpu().numpy()
        q=self.tensor(np.unwrap(raw,axis=0))-self.rest
        return q.clamp(self.lo,self.hi)
    def decode(self,q,base):
        a=q+self.rest
        r=torch.eye(3,device=self.device)+a.sin()[...,None,None]*self.K+(1-a.cos())[...,None,None]*self.K2
        out=base.clone();out[:,self.ids]=self.offset.transpose(-1,-2)@r
        return out
    def project(self,motion):
        local=self.tensor(motion['local_rot_mats']);q=self.encode(local);local=self.decode(q,local)
        root=self.tensor(motion['root_positions']);gr,jp,_=self.sk.fk(local,root)
        return dict(local_rot_mats=local.detach().cpu().numpy(),root_positions=root.cpu().numpy(),posed_joints=jp.detach().cpu().numpy(),global_rot_mats=gr.detach().cpu().numpy(),foot_contacts=motion['foot_contacts'])


def ground_supported_root(root, joints, rotations, soles, heights=0., clearance=.001):
    """Enforce at least one actual foot on its support in each grounded frame.

    Native coordinates are Y-up. Heights may be scalar or [frames, 2] for the
    two authored support surfaces. This is for non-flight actions, independent
    of the model's sometimes all-zero contact predictions. Apply inside the
    solve so hand/seat objectives see the same grounded pose as the export.
    """
    low=torch.stack([(torch.einsum('tij,vj->tvi',rotations[:,jid],v)
                      +joints[:,jid,None])[:,:,1].amin(1) for jid,v in soles],-1)
    height=torch.as_tensor(heights,dtype=root.dtype,device=root.device)
    correction=clearance-(low-height).amin(-1)
    shift=torch.stack([torch.zeros_like(correction),correction,torch.zeros_like(correction)],-1)
    return root+shift,joints+shift[:,None],low


def support_report(motion, skeleton, mesh_patches, heights=0., fps=30):
    """Measure both-foot flight on every frame, without a contact-label gate."""
    lows=[]
    for side in ('left','right'):
        name,v=mesh_patches[side+'_sole'];j=skeleton.bone_index[name]
        points=np.einsum('tij,vj->tvi',motion['global_rot_mats'][:,j],v)+motion['posed_joints'][:,j,None]
        lows.append(points[:,:,1].min(1))
    gaps=np.stack(lows,-1)-np.asarray(heights)
    support=gaps.min(-1);air=support>.02
    boundaries=np.flatnonzero(np.diff(np.r_[False,air,False]))
    spans=boundaries.reshape(-1,2)
    return dict(frames=len(gaps),minimum_support_gap_m=float(support.min()),
        maximum_support_gap_m=float(support.max()),first_frame_foot_gaps_m=gaps[0].tolist(),
        both_feet_over_2cm_frames=np.flatnonzero(air).tolist(),
        airborne_intervals_seconds=(spans/fps).tolist(),
        maximum_airborne_seconds=float(np.diff(spans,axis=1).max()/fps) if len(spans) else 0.,
        native_no_contact_frames=int((np.asarray(motion['foot_contacts']).max(-1)<.5).sum()))


def scene_support_heights(scene, xy):
    """Query finite horizontal authored floor/rug triangles in room coordinates.

    Mesh matrices are column-major, as in the browser. These support meshes must
    be static with placement baked into their matrices (the RoomKit export).
    Missing floor coverage is a validation error, never an implicit zero plane.
    """
    xy=np.asarray(xy,float);shape=xy.shape[:-1];p=xy.reshape(-1,2)
    height=np.full(len(p),-np.inf)
    tracked={t['owner'] for t in scene.get('interaction',{}).get('object_tracks',[])}
    for mesh in scene['meshes']:
        if not re.search(r'\b(floor\w*|rug|carpet)\b',mesh['name'],re.I):continue
        if re.search(r'\bfloor\s+(lamp|light|vase)\b',mesh['name'],re.I):continue
        if mesh.get('owner') in tracked:raise ValueError('Animated support needs an explicit per-frame surface')
        mat=np.asarray(mesh['matrix']).reshape(4,4).T
        v=np.asarray(mesh['positions']).reshape(-1,3)@mat[:3,:3].T+mat[:3,3]
        ids=np.flatnonzero(np.all((p>=v[:,:2].min(0)-1e-6)&(p<=v[:,:2].max(0)+1e-6),axis=1))
        if not len(ids):continue
        points=p[ids]
        faces=np.concatenate([g['indices'] for g in mesh['groups']]).reshape(-1,3)
        for tri in v[faces]:
            if np.ptp(tri[:,2])>1e-5:continue
            a,b,c=tri[:,:2];u=b-a;w=c-a;det=u[0]*w[1]-u[1]*w[0]
            if abs(det)<1e-10:continue
            d=points-a;s=(d[:,0]*w[1]-d[:,1]*w[0])/det;t=(u[0]*d[:,1]-u[1]*d[:,0])/det
            inside=(s>=-1e-6)&(t>=-1e-6)&(s+t<=1+1e-6)
            height[ids[inside]]=np.maximum(height[ids[inside]],tri[:,2].mean())
    if not np.isfinite(height).all():raise ValueError(f'{int((~np.isfinite(height)).sum())} foot queries have no authored floor support')
    return height.reshape(shape)


def authored_support_heights(motion, skeleton, mesh_patches, scene, origin):
    """Equivalent native per-foot support planes from every actual mesh vertex.

    A single lowest vertex can fall in a floorboard seam while the rest of the
    sole is supported. Use the minimum vertex-to-surface gap over the whole foot.
    Re-evaluate after changing foot pose or horizontal placement.
    """
    heights=[]
    for side in ('left','right'):
        name,v=mesh_patches[side+'_sole'];j=skeleton.bone_index[name]
        native=np.einsum('tij,vj->tvi',motion['global_rot_mats'][:,j],v)+motion['posed_joints'][:,j,None]
        room=(native+np.asarray(origin))@ROOM.T
        floor=scene_support_heights(scene,room[:,:,:2])
        gap=(room[:,:,2]-floor).min(1)
        heights.append(native[:,:,1].min(1)-gap)
    return np.stack(heights,-1)


def fit(rig,motion,mesh_patches,hand_target,strength,*,iterations=250,root_xy=None,seat=None,grounded=True,ground_heights=0.,hand_normal=None,hand_clearance_strength=None):
    """Preserve native root rotation; fit valid robot hinges, hand and sole patches."""
    sk=rig.sk;t=rig.tensor;base=t(motion['local_rot_mats']);roots=t(motion['root_positions']);q0=rig.encode(base)
    q=torch.nn.Parameter(q0.clone());delta=torch.nn.Parameter(torch.zeros_like(roots))
    opt=torch.optim.Adam([q,delta],lr=.01);target=t(hand_target);on=t(strength)
    clearance_on=on if hand_clearance_strength is None else t(hand_clearance_strength)
    normal=None
    if hand_normal is not None:
        normal=t(hand_normal).expand_as(target)
        if not torch.isfinite(normal).all() or (normal.norm(dim=-1)<1e-6).any():
            raise ValueError('Hand surface normals must be finite and nonzero')
        normal=normal/normal.norm(dim=-1,keepdim=True)
    fc=t(motion['foot_contacts']);foot_keys=['left_heel','left_toe','right_heel','right_toe']
    point_defs={k:(sk.bone_index[j],t(v)) for k,(j,v) in mesh_patches.items()}
    soles=[point_defs[side+'_sole'] for side in ('left','right')] if grounded else []
    heights=t(ground_heights).expand(len(roots),2)
    def forward():
        local=rig.decode(q,base);root=roots+delta;gr,jp,_=sk.fk(local,root)
        if grounded:root,jp,_=ground_supported_root(root,jp,gr,soles,heights)
        return local,root,gr,jp
    def points(gr,jp,key):
        j,v=point_defs[key]
        return torch.einsum('tij,...j->t...i',gr[:,j],v)+jp[:,j].reshape((len(jp),)+(1,)*(v.ndim-1)+(3,))
    with torch.no_grad():
        gr0,jp0,_=sk.fk(rig.decode(q0,base),roots)
        if grounded:
            _,jp0,low=ground_supported_root(roots,jp0,gr0,soles,heights)
            # Repair missing contact evidence explicitly. Do not claim these
            # fallback weights came from Kimodo. A raised swing foot stays free.
            gap=low-heights;near=torch.exp(-(gap-gap.amin(-1,keepdim=True))/.025)
            fallback=near.repeat_interleave(2,-1)
            missing=fc.amax(-1)<.5
            fc=torch.where(missing[:,None],torch.maximum(fc,fallback),fc)
        anchors={}
        for k,key in enumerate(foot_keys):
            v=points(gr0,jp0,key).mean(1);a=v.clone();active=(fc[:,k]>.5).cpu().numpy()
            for i in range(len(a)):
                if active[i] and i and active[i-1]:a[i]=a[i-1]
            anchors[key]=a
    log=[]
    for step in range(iterations):
        opt.zero_grad();local,root,gr,jp=forward()
        hand=points(gr,jp,'right_hand');loss=700*((hand-target).square().sum(-1)*on).sum()/on.sum().clamp_min(1)
        if normal is not None:
            # The whole hand must approach from outside the reviewed contact
            # surface. Matching a single point alone allows the palm to enter it.
            whole=points(gr,jp,'right_hand_mesh')
            signed=((whole-target[:,None])*normal[:,None]).sum(-1)
            loss=loss+2000*(torch.relu(-signed.amin(-1)).square()*clearance_on).sum()/clearance_on.sum().clamp_min(1)
        loss=loss+.7*(q-q0).square().mean()+15*delta.square().mean()
        if root_xy is not None:loss=loss+80*(root[:,[0,2]]-t(root_xy)).square().mean()
        for k,key in enumerate(foot_keys):
            p=points(gr,jp,key);center=p.mean(1);support=fc[:,k];low=p[:,:,1].amin(1)
            gap=p[:,:,1]-heights[:,k//2,None]
            loss=loss+500*torch.relu(-gap).square().mean()+100*(gap.amin(1).square()*support).sum()/support.sum().clamp_min(1)
            loss=loss+50*((center[:,[0,2]]-anchors[key][:,[0,2]]).square().sum(-1)*support).sum()/support.sum().clamp_min(1)
            adjacent=support[1:]*support[:-1]
            loss=loss+180*((p[1:]-p[:-1]).square().mean((1,2))*adjacent).sum()/adjacent.sum().clamp_min(1)
        if seat is not None:
            goal,mask=seat;mask=t(mask);loss=loss+500*((root-t(goal)).square().sum(-1)*mask).sum()/mask.sum().clamp_min(1)
        if len(root)>2:
            loss=loss+4*torch.diff(q-q0,dim=0).square().mean()+40*torch.diff(delta,n=2,dim=0).square().mean()+800*torch.diff(jp,n=2,dim=0).square().mean()
        loss.backward();opt.step()
        with torch.no_grad():q.clamp_(rig.lo,rig.hi)
        for group in opt.param_groups:group['lr']=.01*(.15+.85*(1-step/iterations)**2)
        if step%50==0 or step==iterations-1:log.append(dict(iteration=step,loss=float(loss.detach())))
    with torch.no_grad():
        local,root,gr,jp=forward()
    out={k:v.detach().cpu().numpy() for k,v in dict(local_rot_mats=local,root_positions=root,global_rot_mats=gr,posed_joints=jp).items()};out['foot_contacts']=motion['foot_contacts'];out['support_weights']=fc.detach().cpu().numpy()
    return out,log


def fit_scene_support(rig,motion,mesh_patches,hand_target,strength,*,scene,origin,iterations=300,**kwargs):
    """Jointly fit grounded contacts, refreshing finite terrain after pose changes."""
    heights=lambda m:authored_support_heights(m,rig.sk,mesh_patches,scene,origin)
    out,log=fit(rig,motion,mesh_patches,hand_target,strength,iterations=iterations,
                grounded=True,ground_heights=heights(motion),**kwargs)
    for _ in range(3):
        report=support_report(out,rig.sk,mesh_patches,heights(out))
        if max(abs(report['minimum_support_gap_m']-.001),abs(report['maximum_support_gap_m']-.001))<.002:break
        out,extra=fit(rig,out,mesh_patches,hand_target,strength,iterations=180,
                      grounded=True,ground_heights=heights(out),**kwargs)
        log+=extra
    floor=heights(out);low=[]
    for side in ('left','right'):
        name,v=mesh_patches[side+'_sole'];j=rig.sk.bone_index[name]
        low.append((np.einsum('tij,vj->tvi',out['global_rot_mats'][:,j],v)+out['posed_joints'][:,j,None])[:,:,1].min(1))
    correction=.001-(np.stack(low,-1)-floor).min(-1)
    if abs(correction).max()>.04:raise ValueError('Ground support fitting did not converge against authored terrain')
    out['root_positions'][:,1]+=correction;out['posed_joints'][:,:,1]+=correction[:,None]
    log.append(dict(final_terrain_correction_max_m=float(abs(correction).max())))
    return out,log


def closed_mesh_point_depth(points,mesh,device="cpu"):
    """Inside depth from solid-angle winding and exact point/triangle distance.

    Caller must supply a consistently oriented watertight mesh; AABB is only
    a broad-phase filter, never treated as occupied object geometry.
    """
    points=np.asarray(points)
    if points.ndim!=2 or points.shape[-1]!=3 or not np.isfinite(points).all():
        raise ValueError('Expected finite [N,3] points')
    result=np.zeros(len(points));selected=np.flatnonzero(np.all((points>mesh.bounds[0])&(points<mesh.bounds[1]),axis=-1));tri=torch.tensor(mesh.triangles,dtype=torch.float32,device=device)[None];a,b,c=tri.unbind(-2);ab=b-a;ac=c-a;normal=torch.cross(ab,ac,dim=-1);norm2=normal.square().sum(-1).clamp_min(1e-20);valid=norm2>1e-16
    for start in range(0,len(selected),128):
     ids=selected[start:start+128];p=torch.tensor(points[ids],device=device,dtype=torch.float32)[:,None];u=a-p;w=b-p;z=c-p;lu=u.norm(dim=-1);lw=w.norm(dim=-1);lz=z.norm(dim=-1)
     numerator=(u*torch.cross(w,z,dim=-1)).sum(-1);denominator=lu*lw*lz+(u*w).sum(-1)*lz+(w*z).sum(-1)*lu+(z*u).sum(-1)*lw;inside=(2*torch.atan2(numerator,denominator)).sum(-1).abs()>2*np.pi
     ap=p-a;plane=(ap*normal).sum(-1);q=p-plane[...,None]/norm2[...,None]*normal;aq=q-a
     d00=(ab*ab).sum(-1);d01=(ab*ac).sum(-1);d11=(ac*ac).sum(-1);d20=(aq*ab).sum(-1);d21=(aq*ac).sum(-1);den=(d00*d11-d01*d01).clamp_min(1e-20);s=(d11*d20-d01*d21)/den;t=(d00*d21-d01*d20)/den
     dist=torch.where((s>=0)&(t>=0)&(s+t<=1)&valid,plane.square()/norm2,torch.inf)
     for x,y in [(a,b),(b,c),(c,a)]:
      edge=y-x;alpha=((p-x)*edge).sum(-1)/edge.square().sum(-1).clamp_min(1e-20);closest=x+alpha.clamp(0,1)[...,None]*edge;dist=torch.minimum(dist,(p-closest).square().sum(-1))
     depth=dist.amin(-1).sqrt()*inside;result[ids]=depth.cpu().numpy()
    return result


def hand_object_penetration(motion,skeleton,mesh_patches,scene,origin,object_id,translations,device='cpu'):
    """Audit every contact-hand vertex against each closed target-object part.

    Current interaction plans prescribe object translations only. Open parts
    are reported as unchecked, so passing the closed parts is not full acceptance.
    """
    import trimesh
    name,v=mesh_patches['right_hand_mesh'];j=skeleton.bone_index[name]
    hand=(np.einsum('tij,vj->tvi',motion['global_rot_mats'][:,j],v)
          +motion['posed_joints'][:,j,None]+np.asarray(origin))@ROOM.T-np.asarray(translations)[:,None]
    points=hand.reshape(-1,3);depth=np.zeros(len(points));closed=[];unchecked=[]
    for part in scene['meshes']:
        if part.get('owner')!=object_id:continue
        matrix=np.asarray(part['matrix']).reshape(4,4).T
        vertices=np.asarray(part['positions']).reshape(-1,3)@matrix[:3,:3].T+matrix[:3,3]
        faces=np.concatenate([group['indices'] for group in part['groups']]).reshape(-1,3)
        mesh=trimesh.Trimesh(vertices,faces,process=True);mesh.fix_normals()
        if not mesh.is_watertight:unchecked.append(part['name']);continue
        closed.append(part['name']);depth=np.maximum(depth,closed_mesh_point_depth(points,mesh,device))
    if not closed and not unchecked:raise ValueError('No mesh found for hand-contact object')
    per_frame=depth.reshape(hand.shape[:2]).max(-1)
    return dict(closed_parts=closed,unchecked_open_parts=unchecked,
        maximum_depth_m=float(per_frame.max()),frames_over_2mm=np.flatnonzero(per_frame>.002).tolist(),
        depth_per_frame_m=per_frame.tolist(),
        closed_part_check_passed=bool(closed and not (per_frame>.002).any()),
        scope='Right rubber hand vertices against translated target-object closed meshes; open parts unchecked; not whole-body collision or dynamics')
