"""Render acceptance-gated batch contact caches into a separate Blender/video bundle.

Manifest render paths resolve relative to the manifest. Render output
must not exist; defaults never overwrite room scenes or previous results.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import shutil
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'refinement', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--blender', type=Path, default=Path(os.environ.get('BLENDER_BIN') or shutil.which('blender') or 'blender'))
    p.add_argument('--diagnostic-layout',action='store_true',help='Waive layout review only; output remains explicitly unaccepted and all body gates still apply')
    p.add_argument('--stage', choices=['run','assemble','verify'], default='run')
    return p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)


def inputs(a):
    m = json.loads(a.manifest.read_text())
    sys.path.insert(0,str(ROOT/'src'))
    from aha3d.workflow.layout_gate import validate_layout
    a.layout_validation=validate_layout(m,a.manifest,diagnostic=getattr(a,'diagnostic_layout',False))
    if not getattr(a,'diagnostic_layout',False):
        from aha3d.workflow.acceptance import consumer_prerequisite
        stage='people' if getattr(a,'stage','run')=='assemble' else 'render'
        consumer_prerequisite(m,a.manifest,stage)
    from group_scale_gate import validate_group
    validate_group(m, a.manifest.parent)
    from placement_gate import validate_placement_report
    validate_placement_report(a.refinement/'placement_after'/'report.json', a.manifest, a.refinement)
    summary = json.loads((a.refinement/'summary.json').read_text())
    if not summary.get('all_accepted'):
        raise ValueError('Refinement batch has rejected candidates; refusing delivery render')
    if [x['id'] for x in m['actors']] != [x['id'] for x in summary['actors']]:
        raise ValueError('Manifest identities differ from refined batch')
    for actor, report in zip(m['actors'], summary['actors']):
        if report.get('accepted') is not True:
            raise ValueError(f'Actor {actor["id"]} was not accepted')
        for key in ('cache', 'motion', 'alignment'):
            path = (a.manifest.parent/actor[key]).resolve()
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            if digest.hexdigest() != report['input_hashes'][key]:
                raise ValueError(f'Input changed after refinement: {actor["id"]}/{key}')
    original_manifest = json.loads((a.refinement/'manifest.json').read_text())
    for actor, original in zip(m['actors'], original_manifest['actors']):
        for key in ('id', 'cache', 'motion', 'alignment', 'grounded_motion', 'exclude_seconds', 'vertical_translation_m'):
            if actor.get(key) != original.get(key):
                raise ValueError(f'Render manifest changed refined actor input: {key}')
    if m.get('config', {}) != original_manifest.get('config', {}):
        raise ValueError('Render manifest config differs from accepted refinement')
    cfg = m['render']
    resolve = lambda key: (a.manifest.parent/cfg[key]).resolve()
    scene, camera, source = [resolve(k) for k in ('scene','camera_cache','source_video')]
    output_blend = resolve('output_blend') if cfg.get('output_blend') else a.output/'scene.blend'
    with np.load(a.refinement/m['actors'][0]['id']/'body_room.npz') as z:
        times = z['time_seconds']; fps = float(z['fps'])
    for actor in m['actors']:
        with np.load(a.refinement/actor['id']/'body_room.npz') as z:
            if float(z['fps']) != fps or not np.array_equal(z['time_seconds'], times):
                raise ValueError('Actor timing differs')
    with np.load(camera) as z:
        size = z['image_size'].astype(int).tolist()
        if not np.allclose(z['time_seconds'], times, atol=1e-6):
            raise ValueError('Camera timing differs from people')
    if abs(times[0]) > 1e-6:
        raise ValueError('Source comparison requires a zero-start whole-clip cache')
    timing = dict(frames=len(times), start=1, end=len(times), fps=str(fps))
    return m, scene, camera, source, output_blend, times, fps, size, timing


def blender_stage(a, data):
    import bpy
    sys.path.insert(0, str(ROOT/'src'))
    from aha3d.blender.body import import_cache
    from aha3d.blender.ensemble import bake_camera, camera_check
    m, _, camera, _, blend, times, fps, size, timing = data
    scene = bpy.context.scene
    scene['layout_diagnostic_unaccepted']=bool(getattr(a,'diagnostic_layout',False))
    scene['layout_validation_json']=json.dumps(a.layout_validation)
    if a.stage == 'assemble':
        actor_reports = json.loads((a.refinement/'summary.json').read_text())['actors']
        if blend.exists():
            raise FileExistsError(blend)
        if any(o.name.startswith('Person_') for o in bpy.data.objects):
            raise ValueError('Render.scene must be a room-only scene')
        scene.frame_start=1; scene.frame_end=len(times)
        bake_camera(scene, camera, timing, size)
        colors=[(.40,.54,.63,1),(.48,.57,.43,1),(.64,.50,.40,1)]
        for idx, actor in enumerate(m['actors'],1):
            body,_ = import_cache(a.refinement/actor['id']/'body_room.npz',person_id=idx)
            body['source_identity']=actor['id']
            body['method']='GVHMR approximate estimate; ' + actor_reports[idx-1].get('method', 'legacy contact refinement')
            body['constant_vertical_shift_m']=actor_reports[idx-1].get('constant_vertical_shift_m',0.)
            body.data.materials[0].diffuse_color=actor.get('color_rgba',colors[(idx-1)%len(colors)])
            until=actor.get('visible_until_seconds')
            if until is not None:
                for i,t in enumerate(times):
                    body.hide_render=bool(t>float(until));body.keyframe_insert('hide_render',frame=i+1)
        scene.render.engine='BLENDER_WORKBENCH'
        scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL'
        blend.parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        return
    report={'diagnostic_unaccepted':bool(getattr(a,'diagnostic_layout',False)),'layout_validation':a.layout_validation,'camera':camera_check(scene,camera,timing,size,{}),'people':{},'frames':len(times),'fps':fps}
    for idx,actor in enumerate(m['actors'],1):
        obj=bpy.data.objects[f'Person_{idx:03d}_Body']
        with np.load(a.refinement/actor['id']/'body_room.npz') as z:
            vertices=z['vertices']
        error=0.
        for i in range(len(times)):
            scene.frame_set(i+1);obj.hide_viewport=False;bpy.context.view_layer.update()
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
            v=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',v)
            matrix=np.asarray(evaluated.matrix_world)
            world=v.reshape(-1,3)@matrix[:3,:3].T+matrix[:3,3]
            error=max(error,float(np.abs(world-vertices[i]).max()));evaluated.to_mesh_clear()
            expected=actor.get('visible_until_seconds')
            if expected is not None and obj.hide_render != bool(times[i]>float(expected)):
                raise ValueError('Visibility changed during scene save/reopen')
        if error>1e-4:
            raise ValueError(f'{actor["id"]}: baked mesh mismatch {error}')
        report['people'][actor['id']]={'all_frames_mesh_max_error_m':error}
    (a.output/'blender_validation.json').write_text(json.dumps(report,indent=2))
    frames=a.output/'render';frames.mkdir()
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    for frame in range(1,len(times)+1):
        scene.frame_set(frame);scene.render.filepath=str(frames/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)


def output_names(a):
    prefix='diagnostic_unaccepted_' if getattr(a,'diagnostic_layout',False) else ''
    return prefix+'reconstruction.mp4',prefix+'source_comparison.mp4'


def finish(a, data):
    import av
    from PIL import Image, ImageDraw
    _,_,_,source,_,times,fps,size,_=data
    reconstruction,comparison=output_names(a)
    ff=os.environ.get('FFMPEG_BIN') or shutil.which('ffmpeg')
    if ff is None:
        import imageio_ffmpeg
        ff=Path(imageio_ffmpeg.get_ffmpeg_exe())
    run=lambda args:subprocess.run([str(ff),'-v','error','-n',*args],check=True)
    run(['-framerate',str(fps),'-start_number','1','-i',str(a.output/'render/%04d.png'),'-frames:v',str(len(times)),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(a.output/reconstruction)])
    # Validate source timing before composition; do not truncate a mismatched source.
    report={'diagnostic_unaccepted':bool(getattr(a,'diagnostic_layout',False)),'layout_validation':a.layout_validation}
    def decode(path, expected=True):
        ts=[]
        with av.open(str(path)) as c:
            stream=c.streams.video[0]; rate=float(stream.average_rate)
            for frame in c.decode(video=0):ts.append(float(frame.pts*frame.time_base))
        if expected and (len(ts)!=len(times) or abs(rate-fps)>1e-5 or not np.allclose(np.asarray(ts)-ts[0],times,atol=1e-4)):
            raise ValueError(f'Video timing mismatch: {path}')
        return dict(frames=len(ts),fps=rate,duration_seconds=ts[-1]-ts[0]+1/rate,full_decode=True)
    report['source']=decode(source)
    run(['-i',str(source),'-i',str(a.output/reconstruction),'-filter_complex','[0:v]scale=640:360,setsar=1[a];[1:v]scale=640:360,setsar=1[b];[a][b]hstack=inputs=2','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(a.output/comparison)])
    for name in [reconstruction,comparison]:report[name]=decode(a.output/name)
    (a.output/'video_validation.json').write_text(json.dumps(report,indent=2))
    indices=np.unique(np.linspace(0,len(times)-1,min(12,len(times))).astype(int)).tolist()
    with av.open(str(a.output/comparison)) as c:
        selected=[]
        for i,frame in enumerate(c.decode(video=0)):
            if i in indices:
                im=frame.to_image();ImageDraw.Draw(im).text((8,8),f'{times[i]:.2f}s | '+('DIAGNOSTIC UNACCEPTED | ' if getattr(a,'diagnostic_layout',False) else '')+'source / refined estimate',fill='red');selected.append(im)
    for part in range(0,len(selected),4):
        rows=selected[part:part+4];sheet=Image.new('RGB',(1280,360*len(rows)))
        for j,im in enumerate(rows):sheet.paste(im,(0,j*360))
        sheet.save(a.output/f'review_{part//4+1}.jpg')


def main():
    a=arguments()
    a.manifest=a.manifest.resolve();a.refinement=a.refinement.resolve();a.output=a.output.resolve()
    data=inputs(a)
    if a.stage!='run':return blender_stage(a,data)
    if data[4].exists():raise FileExistsError(data[4])
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'render_manifest.json').write_text(a.manifest.read_text())
    (a.output/'layout_validation.json').write_text(json.dumps(a.layout_validation,indent=2))
    (a.output/'render_status.json').write_text(json.dumps({'diagnostic_unaccepted':bool(a.diagnostic_layout),'accepted':False,'status':'awaiting_review','purpose':'diagnostic' if a.diagnostic_layout else 'candidate'},indent=2))
    common=['--manifest',str(a.manifest),'--refinement',str(a.refinement),'--output',str(a.output)]
    if a.diagnostic_layout:common.append('--diagnostic-layout')
    for stage,scene in [('assemble',data[1]),('verify',data[4])]:
        subprocess.run([str(a.blender),'-b',str(scene),'-t',os.environ.get('INDOOR_THREADS') or str(os.cpu_count() or 8),'--python-exit-code','1','--python',str(Path(__file__).resolve()),'--',*common,'--stage',stage],check=True)
    finish(a,data)

if __name__=='__main__':main()
