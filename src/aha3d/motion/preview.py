"""Render native SMPL-X joint motion and optional comparisons with Pillow/FFmpeg."""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import time

import imageio_ffmpeg as ff
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = (1280, 720)
S = 2
PARENTS = [-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19]
LEFT = {1,4,7,10,13,16,18,20}
RIGHT = {2,5,8,11,14,17,19,21}
BACKGROUND = (247,249,251)
COLORS = {'left': (27,147,153), 'right': (215,119,60), 'core': (65,83,106)}
FONT_PATH = next((p for p in [Path('/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf'),
                             Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
                  if p.exists()), None)
FONTS = {n:ImageFont.truetype(str(FONT_PATH), n*S) if FONT_PATH else ImageFont.load_default(size=n*S)
         for n in [14,16,18,20,24,28]}


def label(draw, xy, text, size=18, color=(48,62,78)):
    draw.text(tuple(v*S for v in xy), text, font=FONTS[size], fill=color)


def project(points, alternative=False):
    right = np.array([.70710678,0,.70710678 if alternative else -.70710678])
    depth = np.array([-.70710678 if alternative else .70710678,0,.70710678])
    return np.stack([points@right, points[...,1]-.26*(points@depth)],axis=-1)


def view_params(joints, rect, alternative=False):
    uv=project(joints, alternative)
    lo,hi=uv.min(axis=(0,1)),uv.max(axis=(0,1))
    center=(lo+hi)/2
    scale=min((rect[2]-rect[0]-80)/(hi[0]-lo[0]+.25),
              (rect[3]-rect[1]-60)/(hi[1]-lo[1]+.25))
    return center,scale


def draw_view(im, joints, rect, center, scale, follow=False, path=None, goal=None, active=False):
    x0,y0,x1,y1=rect
    middle=np.array([(x0+x1)/2,(y0+y1)/2+10])
    offset=np.array([joints[0,0],0,joints[0,2]]) if follow else np.zeros(3)
    def screen(points):
        uv=project(np.asarray(points)-offset, alternative=follow)-center
        return (middle+uv*np.array([scale,-scale]))*S
    layer=Image.new('RGB',im.size,BACKGROUND)
    draw=ImageDraw.Draw(layer)
    if follow:
        lo=np.floor(joints[0,[0,2]]-2).astype(int)
        hi=np.ceil(joints[0,[0,2]]+2).astype(int)
    else:
        lo=np.floor(path[:,[0,2]].min(axis=0)-1).astype(int)
        hi=np.ceil(path[:,[0,2]].max(axis=0)+1).astype(int)
    for x in np.arange(lo[0],hi[0]+.01,.5):
        a,b=screen([[x,0,lo[1]],[x,0,hi[1]]])
        draw.line([tuple(a),tuple(b)],fill=(224,231,237),width=S)
    for z in np.arange(lo[1],hi[1]+.01,.5):
        a,b=screen([[lo[0],0,z],[hi[0],0,z]])
        draw.line([tuple(a),tuple(b)],fill=(224,231,237),width=S)
    if path is not None and not follow:
        draw.line([tuple(p) for p in screen(path)],fill=(185,200,213),width=2*S)
    xy=screen(joints)
    depth=np.array([-.70710678 if follow else .70710678,0,.70710678])
    for index in np.argsort(joints@depth)[::-1]:
        parent=PARENTS[index]
        color=COLORS['left' if index in LEFT else 'right' if index in RIGHT else 'core']
        if parent>=0:
            width=max(3,int((.072 if index in {4,5,7,8} else .054)*scale*S))
            draw.line([tuple(xy[parent]),tuple(xy[index])],fill=color,width=width)
        radius=(.09 if index==15 else .042 if index==0 else .032)*scale*S
        point=xy[index]
        draw.ellipse((point[0]-radius,point[1]-radius,point[0]+radius,point[1]+radius),fill=color)
    if goal is not None:
        point=screen(goal)
        radius=10*S
        color=(39,137,93) if active else (105,153,128)
        draw.ellipse((point[0]-radius,point[1]-radius,point[0]+radius,point[1]+radius),outline=color,width=3*S)
        draw.line([(point[0]-radius-4*S,point[1]),(point[0]+radius+4*S,point[1])],fill=color,width=S)
        draw.line([(point[0],point[1]-radius-4*S),(point[0],point[1]+radius+4*S)],fill=color,width=S)
    crop=tuple(int(v*S) for v in rect)
    im.paste(layer.crop(crop),crop[:2])


def load_motion(path):
    with np.load(path, allow_pickle=False) as source:
        joints=source['posed_joints'].copy()
    if joints.ndim!=3 or joints.shape[1:]!=(22,3) or not np.isfinite(joints).all():
        raise ValueError('Expected finite single-clip posed_joints [T,22,3] in Kimodo Y-up coordinates')
    return joints


def render_reference(motion, reference, out, config, targets, fps='30000/1001'):
    """Compare a source clip with the skeleton using a saved approximate camera.

    Uses only constant coordinate registration for display. It does not modify
    generated motion, recover a new camera, or render Blender geometry.
    """
    from scipy.interpolate import CubicHermiteSpline
    out=Path(out)
    if out.exists():
        raise FileExistsError(out)
    out.parent.mkdir(parents=True,exist_ok=True)
    settings=json.loads(Path(config).read_text())
    camera=settings['preview_camera']
    fit=json.loads(Path(camera['fit_file']).read_text())
    keys=np.array(fit['keys'])
    curve=CubicHermiteSpline(keys[:,0],keys[:,1:],np.gradient(keys[:,1:],keys[:,0],axis=0))
    joints=load_motion(motion)
    transform=np.array([[-1.,0.,0.],[0.,0.,1.],[0.,1.,0.]])
    offset=np.array(camera['body_offset_blender_m'])
    world=joints@transform.T+offset
    target_data=json.loads(Path(targets).read_text())
    marks=np.array(target_data['frame_indices_zero_based'])
    goals=np.array(target_data['wrist_targets_y_up_m'])@transform.T+offset
    rate=float(Fraction(fps))
    frames=len(joints)
    resolution=(2560,720)
    exe=ff.get_ffmpeg_exe()
    reader=ff.read_frames(str(reference),pix_fmt='rgb24')
    metadata=next(reader)
    if tuple(metadata['size'])!=(1280,720) or abs(metadata['fps']-rate)>.02:
        raise ValueError('Reference comparison currently expects a 1280x720 clip at the output FPS')
    command=[exe,'-nostdin','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
             '-s','2560x720','-r',fps,'-i','pipe:0','-an','-c:v','libx264','-threads','8',
             '-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(out)]
    path=world[:,0].copy()
    path[:,2]=0
    visible=[]
    selected={0,149,294,299,304,frames-1,*marks.tolist()}
    started=time.perf_counter()
    with out.with_suffix('.log').open('w') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for frame in range(frames):
                source=Image.frombytes('RGB',(1280,720),next(reader))
                im=Image.new('RGB',(1280*S,720*S),BACKGROUND)
                draw=ImageDraw.Draw(im)
                pose=curve(frame)
                position=pose[:3]*camera['room_scale']
                yaw,pitch,roll=pose[3:]
                forward=np.array([np.sin(yaw)*np.cos(pitch),np.cos(yaw)*np.cos(pitch),np.sin(pitch)])
                right=np.array([np.cos(yaw),-np.sin(yaw),0.])
                up=np.cross(right,forward)
                basis=np.array([right*np.cos(roll)+up*np.sin(roll),up*np.cos(roll)-right*np.sin(roll),forward])

                def screen(points):
                    q=(np.asarray(points)-position)@basis.T
                    depth=q[...,2]
                    uv=np.stack([640+fit['focal_pixels']*q[...,0]/np.maximum(depth,.01),
                                 360-fit['focal_pixels']*q[...,1]/np.maximum(depth,.01)],axis=-1)
                    return uv*S,depth

                for x in np.arange(-1,6.01,.5):
                    xy,depth=screen([[x,0,0],[x,7,0]])
                    if (depth>.15).all():
                        draw.line([tuple(p) for p in xy],fill=(223,230,236),width=S)
                for y in np.arange(0,7.01,.5):
                    xy,depth=screen([[-1,y,0],[6,y,0]])
                    if (depth>.15).all():
                        draw.line([tuple(p) for p in xy],fill=(223,230,236),width=S)
                xy,depth=screen(path)
                if (depth>.15).all():
                    draw.line([tuple(p) for p in xy],fill=(185,200,213),width=2*S)
                xy,depth=screen(world[frame])
                visible.append(float(((depth>.15)&(xy[:,0]>=0)&(xy[:,0]<1280*S)&(xy[:,1]>=0)&(xy[:,1]<720*S)).mean()))
                for j in np.argsort(depth)[::-1]:
                    parent=PARENTS[j]
                    color=COLORS['left' if j in LEFT else 'right' if j in RIGHT else 'core']
                    if depth[j]<=.15:
                        continue
                    scale=fit['focal_pixels']/depth[j]*S
                    if parent>=0 and depth[parent]>.15:
                        draw.line([tuple(xy[parent]),tuple(xy[j])],fill=color,width=max(2,int(.055*scale)))
                    radius=(.09 if j==15 else .032)*scale
                    point=xy[j]
                    draw.ellipse((point[0]-radius,point[1]-radius,point[0]+radius,point[1]+radius),fill=color)
                key=int(np.argmin(np.abs(marks-frame)))
                if abs(int(marks[key])-frame)<=20:
                    xy,depth=screen(goals[key])
                    if depth>.15:
                        radius=9*S
                        draw.ellipse((xy[0]-radius,xy[1]-radius,xy[0]+radius,xy[1]+radius),outline=(39,137,93),width=2*S)
                label(draw,(25,20),'Generated / reused approximate camera',24)
                label(draw,(25,660),f'{frame/rate:05.2f} s  |  Five native right-hand keys',20)
                label(draw,(25,694),'Approximate actions and route. Hand articulation and objects are omitted.',14)
                final=Image.new('RGB',resolution,BACKGROUND)
                final.paste(source,(0,0))
                final.paste(im.resize((1280,720),Image.Resampling.LANCZOS),(1280,0))
                # Source label is intentionally a small overlay; source frames
                # retain their original framing and exact frame correspondence.
                overlay=Image.new('RGB',(360*S,48*S),BACKGROUND)
                label(ImageDraw.Draw(overlay),(15,10),'Original reference',20)
                final.paste(overlay.resize((360,48)),(0,0))
                process.stdin.write(final.tobytes())
                if frame in selected:
                    preview=out.parent/'previews'
                    preview.mkdir(exist_ok=True)
                    final.save(preview/f'{out.stem}_{frame+1:04d}.jpg',quality=92)
                if (frame+1)%150==0:
                    print('REFERENCE_PREVIEW_PROGRESS',frame+1,frames,flush=True)
            if next(reader,None) is not None:
                raise ValueError('Reference has more frames than the generated motion')
        finally:
            process.stdin.close()
            reader.close()
        if process.wait()!=0:
            raise RuntimeError('Reference preview encoding failed')
    subprocess.run([exe,'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',str(out),'-f','null','-'],check=True)
    decoded=ff.read_frames(str(out),pix_fmt='rgb24')
    meta=next(decoded)
    count=sum(1 for _ in decoded)
    if count!=frames or tuple(meta['size'])!=resolution or abs(meta['duration']-frames/rate)>.02:
        raise ValueError('Reference comparison timing or resolution mismatch')
    report=dict(file=out.name,frames=frames,decoded_frames=count,full_decode_pass=True,
                fps=fps,duration_seconds=frames/rate,width=resolution[0],height=resolution[1],
                render_and_encode_seconds=time.perf_counter()-started,
                source_frame_alignment='Same frame index at 30000/1001 fps',
                camera='Saved manual fit with original Hermite interpolation and constant room scale',
                minimum_joint_in_frame_fraction=min(visible),visual_review='pending')
    out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print('REFERENCE_PREVIEW_COMPLETE',json.dumps(report),flush=True)
    return report


def render_skeleton(motion, out, fps='30000/1001', baseline=None, targets=None, config=None):
    out=Path(out)
    if out.exists():
        raise FileExistsError('Choose a new output video: '+str(out))
    out.parent.mkdir(parents=True,exist_ok=True)
    rate=float(Fraction(str(fps)))
    joints=load_motion(motion)
    count=len(joints)
    old=load_motion(baseline) if baseline else None
    if old is not None and old.shape!=joints.shape:
        raise ValueError('Comparison motions must have matching duration and topology')
    target_data=json.loads(Path(targets).read_text()) if targets else None
    goal_points=np.array(target_data['wrist_targets_y_up_m']) if targets else None
    keyframes=target_data['frame_indices_zero_based'] if targets else []
    settings=json.loads(Path(config).read_text()) if config else {}
    actions=settings.get('action_segments', [[0,'WALK'],[300,'RAISE / REACH / LOWER']])
    rects=[(20,108,630,643),(650,108,1260,643)]
    paths=[joints[:,0].copy(),joints[:,0].copy()]
    for path in paths:
        path[:,1]=0
    if old is None:
        sources=[joints,joints]
        following=[False,True]
        titles=['Fixed world view','Following view / second angle']
    else:
        sources=[old,joints]
        following=[True,True]
        titles=['Text + root route',f'Native: + {len(keyframes)} right-hand keyframes']
    params=[]
    for points,follow,rect in zip(sources,following,rects):
        framing=points.copy()
        if follow:
            framing[...,0]-=points[:,None,0,0]
            framing[...,2]-=points[:,None,0,2]
        params.append(view_params(framing,rect,alternative=follow))
    if old is not None:
        shared=np.concatenate([source-np.stack([source[:,0,0],np.zeros(count),source[:,0,2]],axis=-1)[:,None]
                               for source in sources])
        params=[view_params(shared,rects[0],alternative=True)]*2
    samples={0,149,299,304,count-1}
    samples.update(keyframes)
    exe=ff.get_ffmpeg_exe()
    command=[exe,'-nostdin','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
             '-s','1280x720','-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-threads','8',
             '-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(out)]
    started=time.perf_counter()
    with out.with_suffix('.log').open('w') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for frame in range(count):
                im=Image.new('RGB',(SIZE[0]*S,SIZE[1]*S),BACKGROUND)
                draw=ImageDraw.Draw(im)
                label(draw,(25,20),settings.get('preview_title', 'Native right-hand target test' if old is None else 'Same prompts and seed: sparse native targets'),24)
                label(draw,(1035,25),f'{frame/rate:05.2f} / {count/rate:.2f} s',18)
                goal=None
                if keyframes:
                    key=int(np.argmin(np.abs(np.asarray(keyframes)-frame)))
                    if abs(keyframes[key]-frame)<=20:
                        goal=goal_points[key]
                for index,(points,follow,rect,param,title) in enumerate(zip(sources,following,rects,params,titles)):
                    label(draw,(rect[0]+12,76),title,18)
                    draw_view(im,points[frame],rect,*param,follow=follow,path=paths[index],
                              goal=goal,active=frame in keyframes)
                draw=ImageDraw.Draw(im)
                draw.line([(640*S,105*S),(640*S,643*S)],fill=(213,222,231),width=S)
                label(draw,(25,659),next(text for start,text in reversed(actions) if start<=frame),16)
                label(draw,(670,659),'Green cross: target   Orange: right arm',16)
                for index,mark in enumerate(keyframes):
                    x=(270+350*mark/count)*S
                    draw.line([(x,654*S),(x,676*S)],fill=(39,137,93),width=2*S)
                draw.line([(270*S,669*S),(620*S,669*S)],fill=(191,207,216),width=3*S)
                draw.line([(270*S,669*S),((270+350*(frame+1)/count)*S,669*S)],fill=(38,130,157),width=3*S)
                label(draw,(25,692),'22-joint skeleton. No Blender, skinning, or external IK.',14)
                image=im.resize(SIZE,Image.Resampling.LANCZOS)
                process.stdin.write(image.tobytes())
                if frame in samples:
                    preview=out.parent/'previews'
                    preview.mkdir(exist_ok=True)
                    image.save(preview/f'{out.stem}_{frame+1:04d}.png')
                if (frame+1)%150==0:
                    print('PREVIEW_PROGRESS',out.name,frame+1,count,flush=True)
        finally:
            process.stdin.close()
        if process.wait()!=0:
            raise RuntimeError('FFmpeg failed; see '+str(out.with_suffix('.log')))
    elapsed=time.perf_counter()-started
    subprocess.run([exe,'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',str(out),'-f','null','-'],check=True)
    stream=ff.read_frames(str(out),pix_fmt='rgb24')
    meta=next(stream)
    decoded=sum(1 for _ in stream)
    if decoded!=count or tuple(meta['size'])!=SIZE or abs(meta['duration']-count/rate)>.02:
        raise ValueError('Encoded video timing, shape or frame count does not match input')
    report=dict(file=out.name,frames=count,fps=str(fps),duration_seconds=count/rate,
                decoded_frames=decoded,width=SIZE[0],height=SIZE[1],full_decode_pass=True,
                render_and_encode_seconds=elapsed,representation='22-joint skeleton',
                visual_review='pending',bytes=out.stat().st_size)
    out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PREVIEW_COMPLETE',json.dumps(report),flush=True)
    return report


def render(motion, out, fps='30000/1001', baseline=None, targets=None, config=None,
           representation='mesh'):
    """User-facing previews default to SMPL-X; skeleton remains explicit diagnostics."""
    if representation == 'skeleton':
        return render_skeleton(motion, out, fps, baseline, targets, config)
    if representation != 'mesh':
        raise ValueError('Choose mesh or skeleton')
    from .mesh_preview import render as render_mesh
    return render_mesh(motion, out, fps, baseline, targets, config)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--representation',choices=['mesh','skeleton'],default='mesh')
    parser.add_argument('--motion',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--fps',default='30000/1001')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--targets',type=Path)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    render(args.motion,args.out,args.fps,args.baseline,args.targets,args.config,args.representation)


if __name__=='__main__':
    main()
