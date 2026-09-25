"""Headless low-cost full-timeline preview of the already verified assembled scene."""
import argparse
from fractions import Fraction
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import bpy
from aha3d.io import digest, read, write


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--backend', choices=['cpu', 'gpu'], required=True)
    a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    recipe = read(a.out / 'snapshot/recipe.json'); original = read(a.run / 'snapshot/recipe.json')
    sampling_path = a.out / 'sampling.json'
    sampling = read(sampling_path) if sampling_path.exists() else None
    scene = bpy.context.scene; t = original['timing']; rate = float(Fraction(t['fps']))
    if (scene.frame_start, scene.frame_end) != (t['start'], t['end']) or abs(scene.render.fps / scene.render.fps_base - rate) > 1e-4:
        raise ValueError('Saved scene timing differs from frozen recipe')
    if not scene.camera:
        raise ValueError('Preview needs the evaluated scene camera')
    people_objects = [o for o in scene.objects if 'person_id' in o]
    ids = [o['person_id'] for o in people_objects]
    if len(ids) != len(set(ids)) or any(type(i) is not int or not 1 <= i <= 32767 for i in ids) or any(o.type != 'MESH' for o in people_objects):
        raise ValueError('Preview requires unique positive person_id values on evaluated body meshes')
    from aha3d.blender.rendering import configure_render
    mode = recipe['render']['mode']
    engine = recipe['render'].get('engine', 'auto')
    if engine == 'auto' and mode != 'preserve':
        engine = 'workbench' if mode == 'clay' else 'eevee'
    # An explicitly requested CPU preview retains the headless CPU route;
    # GPU previews default to raster engines without silently falling back.
    if a.backend == 'cpu': engine = 'cycles'
    renderer = configure_render(scene, mode, recipe['render']['samples'], engine,
                                cycles_device=a.backend.upper())
    for field in ('view_transform', 'look', 'exposure'):
        if field in recipe['render']: setattr(scene.view_settings, field, recipe['render'][field])
    scene.render.use_persistent_data = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    frames = a.out / 'stages/render/frames'; frames.mkdir(parents=True)
    sampled = sampling['scene_frames'] if sampling else list(range(t['start'], t['end'] + 1))
    for encoded, f in enumerate(sampled, recipe['timing']['start']):
        scene.frame_set(f)
        scene.render.resolution_x = recipe['render']['width']; scene.render.resolution_y = recipe['render']['height']
        scene.render.filepath = str(frames / f'frame_{encoded:06d}.png')
        bpy.ops.render.render(write_still=True)
    keys = sorted(set([t['start'], (t['start']+t['end'])//2, t['end']]))
    keydir = a.out / 'keyframes'; keydir.mkdir()
    key_renderer = configure_render(scene, 'preserve', max(8, min(16, original['render']['samples'])),
                                    engine, cycles_device=a.backend.upper())
    for f in keys:
        scene.frame_set(f)
        scene.render.resolution_x = original['render']['width']; scene.render.resolution_y = original['render']['height']
        scene.render.filepath = str(keydir / f'frame_{f:06d}.png')
        bpy.ops.render.render(write_still=True)
    from aha3d.blender.stage import checks
    checked = {}
    policy = dict(original, validation=dict(original['validation'], sample_frames='all', collisions='error' if original['validation'].get('collisions') == 'error' else 'report'))
    for obj in scene.objects:
        if 'person_id' in obj:
            folder = a.out / 'people' / str(int(obj['person_id'])); folder.mkdir(parents=True)
            checked[str(int(obj['person_id']))] = checks(scene, obj, None, policy, folder, save_samples=False)
    write(a.out / 'people_report.json', dict(status='passed', source_sha256=digest(a.run / 'stages/assemble/scene.blend'),
        people=checked, limitations='Evaluated meshes at every integer frame; triangle overlap diagnostics, no cache correspondence or continuous/self collision. Classify intended support contacts in review.'))
    actors = [{'id': int(o['person_id']), 'object': o.name} for o in scene.objects if 'person_id' in o]
    write(a.out / 'render_report.json', dict(status='passed', frames=len(sampled), timing=recipe['timing'],
        source_timing=t, sampled_scene_frames=sampled,
        resolution=[recipe['render']['width'], recipe['render']['height']],
        pixel_aspect=[scene.render.pixel_aspect_x, scene.render.pixel_aspect_y], backend=a.backend,
        renderer=renderer, keyframe_renderer=key_renderer,
        people=actors, keyframes=keys, limitations='Preview shading; person_id objects enumerated, no automatic all-person contact claim.'))

if __name__ == '__main__':
    main()
