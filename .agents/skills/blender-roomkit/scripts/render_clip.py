"""Render a configured Blender scene and encode a clip, or render selected still frames."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomkit as rk

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--out',required=True)
ap.add_argument('--mode',choices=['clay','material'],default='clay')
ap.add_argument('--engine',choices=['auto','workbench','eevee','cycles'],default='auto')
ap.add_argument('--cycles-device',choices=['GPU','CPU'],default='GPU')
ap.add_argument('--samples',type=int,default=32)
ap.add_argument('--scale',type=int,default=100)
ap.add_argument('--ffmpeg',default=shutil.which('ffmpeg'))
ap.add_argument('--stills',help='Comma separated frame numbers; skips video encoding')
ap.add_argument('--resume',action='store_true',help='Reuse frames only for an identical job fingerprint')
args=ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
scene=bpy.context.scene
source=Path(bpy.data.filepath)
if not source.is_file():
    raise ValueError('Load a saved .blend before rendering')
if not args.stills and (not args.ffmpeg or not Path(args.ffmpeg).is_file()):
    raise ValueError('Pass --ffmpeg with an installed FFmpeg executable')
if not 1 <= args.scale <= 100:
    raise ValueError('Scale must be between 1 and 100')
out=Path(args.out).resolve()
out.mkdir(parents=True,exist_ok=True)
frame_dir=out/'frames'
frame_dir.mkdir(exist_ok=True)
frame_list=[int(f) for f in args.stills.split(',')] if args.stills else list(range(scene.frame_start,scene.frame_end+1))
if any(f<scene.frame_start or f>scene.frame_end for f in frame_list):
    raise ValueError('Selected still frame lies outside the scene range')
from aha3d.blender import rendering
configured=rk.configure_render(scene,args.mode,args.samples,args.engine,cycles_device=args.cycles_device)
job={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'mode':args.mode,
     'renderer':configured,
     'samples':args.samples,'scale':args.scale,'frames':frame_list,
     'fps':scene.render.fps/scene.render.fps_base,'blender':bpy.app.version_string,
     'width':scene.render.resolution_x,'height':scene.render.resolution_y,
     'renderer_script_sha256':hashlib.sha256(Path(__file__).read_bytes()+Path(rk.__file__).read_bytes()+Path(rendering.__file__).read_bytes()).hexdigest()}
job_path=out/'render_job.json'
if any(frame_dir.glob('*.png')):
    if not args.resume or not job_path.exists() or json.loads(job_path.read_text()) != job:
        raise ValueError('Existing frames belong to a different/unfinished job; use a new output directory or matching --resume')
job_path.write_text(json.dumps(job,indent=2),encoding='utf-8')
scene.render.resolution_percentage=args.scale
scene.render.image_settings.compression=15
started=time.monotonic()
for i,frame in enumerate(frame_list):
    path=frame_dir/f'{frame:04d}.png'
    if args.resume and path.exists() and path.stat().st_size>100:
        continue
    scene.frame_set(frame)
    scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)
    if i%12==0 or i==len(frame_list)-1:
        print('RENDER_PROGRESS',i+1,len(frame_list),round(time.monotonic()-started,2),'seconds',flush=True)
render_seconds=time.monotonic()-started
report={'render_seconds':render_seconds,'frame_count':len(frame_list),'mode':args.mode,
        'renderer':configured,
        'width':round(scene.render.resolution_x*args.scale/100),
        'height':round(scene.render.resolution_y*args.scale/100),'fps':job['fps']}
if not args.stills:
    video=out/'walkthrough.mp4'
    subprocess.run([args.ffmpeg,'-hide_banner','-loglevel','error','-y','-framerate',str(job['fps']),
                    '-start_number',str(scene.frame_start),'-i',str(frame_dir/'%04d.png'),
                    '-frames:v',str(len(frame_list)),'-c:v','libx264','-crf','18','-preset','medium',
                    '-pix_fmt','yuv420p','-movflags','+faststart','-an',str(video)],check=True)
    subprocess.run([args.ffmpeg,'-hide_banner','-loglevel','error','-xerror','-i',str(video),'-f','null','-'],check=True)
    report.update(video=video.name,duration_s=len(frame_list)/job['fps'],full_decode_pass=True)
    probe=Path(args.ffmpeg).with_name('ffprobe'+Path(args.ffmpeg).suffix)
    if probe.exists():
        metadata=json.loads(subprocess.check_output([str(probe),'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(video)]))
        stream=next(s for s in metadata['streams'] if s['codec_type']=='video')
        assert int(stream['nb_read_frames'])==len(frame_list)
        assert abs(float(metadata['format']['duration'])-report['duration_s'])<.01
        assert (stream['width'],stream['height'])==(report['width'],report['height'])
        report['ffprobe_verified']=True
    if scene.camera.data.sensor_fit=='HORIZONTAL':
        rk.export_camera(scene,out)
report['total_seconds']=time.monotonic()-started
(out/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('RENDER_COMPLETE',json.dumps(report),flush=True)
