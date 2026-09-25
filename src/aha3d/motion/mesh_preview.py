"""Skin native motion with the deployed SMPL-X asset and render a mesh preview."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg as ff

from aha3d import runtime as host
from aha3d.config import load_runtime


def render(motion, out, fps='30000/1001', baseline=None, targets=None, config=None):
    out=Path(out).resolve()
    work=out.parent/(out.stem+'_assets')
    if out.exists() or work.exists():
        raise FileExistsError('Choose a new output and assets directory')
    root=Path(__file__).resolve().parents[3]
    runtime=load_runtime(root,'local')
    work.mkdir(parents=True)
    paths=[Path(baseline).resolve(),Path(motion).resolve()] if baseline else [Path(motion).resolve()]
    counts=[]
    for path in paths:
        with np.load(path,allow_pickle=False) as data:
            counts.append(len(data['root_positions']))
    if len(set(counts))!=1:
        raise ValueError('Comparison clips must have matching native frame counts')
    frames=counts[0]
    caches=[]
    for i,path in enumerate(paths):
        prepared=work/f'prepared_{i}.npz'; cache=work/f'body_{i}.npz'
        subprocess.run([sys.executable,'-m','aha3d.motion.prepare','--motion',str(path),
                        '--out',str(prepared),'--fps',fps,'--frames',str(frames)],check=True)
        with (work/f'skin_{i}.log').open('w') as log:
            subprocess.run([runtime['skin_blender'],'-b','-t',str(host.threads(runtime)),
                            '--python-exit-code','1','--python',str(root/'src/aha3d/blender/skin.py'),
                            '--','--motion',str(prepared),'--out',str(cache)],stdout=log,stderr=subprocess.STDOUT,check=True)
        caches.append(str(cache))
    request=dict(caches=caches,frames=frames,fps=fps,out=str(work),targets=str(Path(targets).resolve()) if targets else None)
    (work/'request.json').write_text(json.dumps(request,indent=2))
    return finish(work, out, fps, paths, frames, baseline, config)


def finish(work, out, fps, paths, frames, baseline=None, config=None):
    """Render an explicitly prepared request, then encode and validate it."""
    root=Path(__file__).resolve().parents[3]
    runtime=load_runtime(root,'local')
    with (work/'render.log').open('w') as log:
        subprocess.run([runtime['blender'],'-b','-t',str(host.threads(runtime)),'--python-exit-code','1',
                        '--python',str(root/'src/aha3d/blender/mesh_preview.py'),
                        '--',str(work/'request.json')],stdout=log,stderr=subprocess.STDOUT,check=True)
    return encode(work, out, fps, paths, frames, baseline, config)


def encode(work, out, fps, paths, frames, baseline=None, config=None):
    """Encode existing rendered frames; useful for caption-only retries."""
    if out.exists():
        raise RuntimeError('Choose a new output video')
    font_path='/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf'
    if not Path(font_path).exists(): font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font=ImageFont.truetype(font_path,23) if Path(font_path).exists() else ImageFont.load_default(size=23)
    settings=json.loads(Path(config).read_text()) if config else {}
    encoder=subprocess.Popen([ff.get_ffmpeg_exe(),'-y','-f','rawvideo','-vcodec','rawvideo',
        '-s','1280x720','-pix_fmt','rgb24','-r',fps,'-i','-','-an','-c:v','libx264',
        '-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(out)],stdin=subprocess.PIPE)
    previews=work/'previews'; previews.mkdir()
    marks={0,149,299,304,327,367,408,frames-1}
    try:
        for frame in range(frames):
            im=Image.open(work/'frames'/f'{frame+1:04d}.png').convert('RGB')
            draw=ImageDraw.Draw(im)
            draw.rectangle((0,0,1280,90),fill=(245,247,250))
            draw.text((25,12),settings.get('preview_title','SMPL-X motion preview'),font=font,fill=(30,45,65))
            if baseline:
                draw.text((160,52),settings.get('baseline_label','Baseline motion'),font=font,fill=(30,80,110))
                draw.text((790,52),settings.get('motion_label','Guided motion'),font=font,fill=(135,65,25))
            draw.rectangle((0,680,1280,720),fill=(245,247,250))
            draw.text((25,686),f'SMPL-X mesh  |  {frame/float(Fraction(fps)):.2f} s  |  fixed viewing direction',font=font,fill=(30,45,65))
            encoder.stdin.write(im.tobytes())
            if frame in marks: im.save(previews/f'{frame+1:04d}.png')
        encoder.stdin.close()
        if encoder.wait()!=0: raise RuntimeError('Encoding failed')
    finally:
        if encoder.poll() is None: encoder.kill(); encoder.wait()
    reader=ff.read_frames(str(out),pix_fmt='rgb24'); meta=next(reader)
    decoded=sum(1 for _ in reader)
    if decoded!=frames or tuple(meta['size'])!=(1280,720): raise RuntimeError('Video validation failed')
    report=dict(representation='SMPL-X locked-head mesh',frames=frames,decoded_frames=decoded,
                fps=fps,duration_seconds=frames/float(Fraction(fps)),full_decode_pass=True,
                width=1280,height=720,visual_review='pending',
                source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                timing='SLERP at output timestamps before skinning; native rate 30 fps; final endpoint held if needed',
                placement='Display follows each pelvis in XY, retaining world heading and vertical position',
                targets_displayed=False,room_contact_validated=False)
    out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
