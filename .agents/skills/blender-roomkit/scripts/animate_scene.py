"""Apply a JSON camera/rig animation recipe to the currently loaded .blend."""
import argparse
import json
import sys
from pathlib import Path

import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomkit as rk

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--config', required=True)
ap.add_argument('--out', required=True, help='New .blend file; source is never overwritten')
args = ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
config = json.loads(Path(args.config).read_text(encoding='utf-8'))
out = Path(args.out).resolve()
if out == Path(bpy.data.filepath).resolve():
    raise ValueError('Choose a new output .blend')
out.parent.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.frame_set(1)
fps, seconds = config.get('fps',24), config.get('seconds',5)
frames = round(fps*seconds)
if fps <= 0 or frames < 2:
    raise ValueError('Positive FPS and at least two frames required')
scene.frame_start, scene.frame_end = 1, frames
scene.render.fps, scene.render.fps_base = fps, 1.
scene.render.resolution_x = config.get('width',1920)
scene.render.resolution_y = config.get('height',1080)
scene.render.resolution_percentage = 100
for rig in config.get('rigs', []):
    rk.rig_parts([bpy.data.objects[name] for name in rig['parts']], rig['pivot'], rig['name'],
                 axis=rig.get('axis','Z'), angle_degrees=rig.get('angle_degrees',90),
                 travel_m=rig.get('travel_m'))
report = []
for motion in config.get('motions', []):
    obj = bpy.data.objects[motion['object']]
    prop = motion.get('property','Open')
    values = rk.animate_property(obj, prop, motion['poses'], frames, fps)
    report.append({'object':obj.name,'property':prop,
                   'distinct_values':len(set(round(v,6) for v in values)),
                   'first_value':values[0],'last_value':values[-1]})
if 'camera' in config:
    rk.camera_path(seconds=seconds, fps=fps, **config['camera'])
    # An existing bound timeline marker otherwise overrides the newly selected camera.
    for marker in scene.timeline_markers:
        if marker.camera:
            marker.camera = scene.camera
rk.configure_render(scene, config.get('render_mode','clay'))
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
if 'camera' in config:
    rk.export_camera(scene, out.parent/(out.stem+'_data'))
(out.parent/(out.stem+'_motion.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('ANIMATION_COMPLETE',str(out),frames,'frames',flush=True)
