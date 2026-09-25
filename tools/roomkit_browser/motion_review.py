#!/usr/bin/env python3
"""Build a single-view review page from existing RoomKit scenes and mesh tracks.

Input JSON: cases[{id,title,note,source_video?,variants:[{id,label,scene,
frames?,fps?,view?,cutaway_names?,cutaway_classes?,actors?:[
{id,mesh,interval:[start,end],color:[r,g,b]}]}]}]. Paths resolve relative to
the input JSON. Scenes and motion inputs are read-only; output must be new.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def prepare(spec, base, folder):
    source = (base / spec['scene']).resolve()
    scene = copy.deepcopy(read(source))
    scene.pop('quick_actions', None)
    # Legacy exports can name supports whose geometry is ungrouped. Retain
    # world-space geometry, record the unresolved edge and freeze the child;
    # inventing a movable support group would claim unverified semantics.
    object_ids = {o['instance_id'] for o in scene['objects']}
    unresolved = []
    for obj in scene['objects']:
        support = obj.get('support_id')
        if support and support not in object_ids:
            unresolved.append(dict(object=obj['instance_id'], support=support))
            obj['source_support_id'] = support
            obj['support_id'] = None
            obj['movable'] = False
    if unresolved:
        scene.setdefault('validation', {})['unresolved_supports_for_review'] = unresolved
        scene['capability_note'] = (scene.get('capability_note', '') +
            ' Some source supports are absent from this export. Their objects retain world placement and cannot be dragged; support relations remain unverified.').strip()
    if 'actors' in spec:
        old = {a['owner'] for a in (scene.get('animation') or {}).get('actors', [])}
        scene['objects'] = [o for o in scene['objects'] if o['instance_id'] not in old]
        scene['meshes'] = [m for m in scene['meshes'] if m.get('owner') not in old]
        scene.pop('interaction', None)
        frames, fps = spec['frames'], spec['fps']
        actors = []
        names = {m['name'] for m in scene['meshes']}
        for item in spec['actors']:
            name = item['id']
            if name in names:
                raise ValueError('Duplicate mesh name: ' + name)
            names.add(name)
            with np.load(base / item['mesh']) as data:
                vertices = np.asarray(data['vertices'], dtype='<f4')
                faces = np.asarray(data['faces'], dtype=np.int32)
            start, end = item['interval']
            if not 0 <= start < end <= frames or len(vertices) != end - start:
                raise ValueError('Source interval does not match mesh frames: ' + name)
            if vertices.ndim != 3 or vertices.shape[2] != 3 or not np.isfinite(vertices).all():
                raise ValueError('Invalid mesh vertices: ' + name)
            if faces.min() < 0 or faces.max() >= vertices.shape[1]:
                raise ValueError('Invalid topology: ' + name)
            # Finite padding is hidden by the original source interval in viewer.js.
            padded = vertices[np.clip(np.arange(frames) - start, 0, len(vertices) - 1)]
            filename = name + '.bin'
            if Path(filename).name != filename:
                raise ValueError('Actor ID must be a filename component')
            padded.tofile(folder / filename)
            material = len(scene['materials'])
            scene['materials'].append(dict(name=name, color=item['color'], roughness=.8, metalness=0))
            scene['objects'].append(dict(instance_id=name, semantic_class='animation/source-human', movable=False))
            scene['meshes'].append(dict(name=name, owner=name, joint=None, surface='body', cutaway=False,
                matrix=np.eye(4).reshape(-1).tolist(), positions=padded[0].reshape(-1).tolist(),
                groups=[dict(material=material, indices=faces.reshape(-1).tolist())]))
            actors.append(dict(owner=name, mesh_name=name, vertex_count=vertices.shape[1],
                encoding='float32-le-world-xyz', positions_file=filename, active_frame_range=[start, end]))
        scene['animation'] = dict(frames=frames, fps=fps, start_frame=1, duration_seconds=frames/fps,
            actors=actors, description='Source reconstruction at original frame rate; uncertain poses and placement remain diagnostic.')
    else:
        for actor in (scene.get('animation') or {}).get('actors', []):
            if actor.get('positions_file'):
                file = actor['positions_file']
                if Path(file).name != file:
                    raise ValueError('Expected adjacent motion sidecar')
                shutil.copyfile(source.parent / file, folder / file)
    hidden = set(spec.get('cutaway_names', []))
    classes = set(spec.get('cutaway_classes', []))
    owners = {o['instance_id'] for o in scene['objects'] if o.get('semantic_class') in classes}
    for mesh in scene['meshes']:
        if mesh['name'] in hidden or mesh.get('owner') in owners:
            mesh['cutaway'] = True
    if spec.get('view'):
        scene['views']['orbit'] = spec['view']
    scene['title'] = spec['label']
    scene['description'] = 'Existing scene and motion; inspection only. Source assets are unchanged.'
    (folder / 'scene.json').write_text(json.dumps(scene))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--node', default='node', help='Configured Node.js executable')
    args = parser.parse_args()
    node = shutil.which(args.node)
    if not node:
        parser.error('Node.js not found; provide --node with the configured executable')
    manifest = args.manifest.resolve()
    data = read(manifest)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    jobs, public, ids = [], [], set()
    for case in data['cases']:
        if case['id'] in ids or Path(case['id']).name != case['id']:
            raise ValueError('Case IDs must be unique filename components')
        ids.add(case['id'])
        item = {k: case[k] for k in ('id', 'title', 'note')}
        for key in ('video_label', 'video_note'):
            if key in case:
                item[key] = case[key]
        item['variants'] = []
        if case.get('source_video'):
            filename = case['id'] + '-source.mp4'
            shutil.copyfile(manifest.parent / case['source_video'], out / filename)
            item['source_video'] = filename
        for variant in case['variants']:
            if Path(variant['id']).name != variant['id']:
                raise ValueError('Variant ID must be a filename component')
            folder = out / case['id'] / variant['id']
            folder.mkdir(parents=True, exist_ok=False)
            prepare(variant, manifest.parent, folder)
            jobs.append(str(folder))
            item['variants'].append(dict(id=variant['id'], label=variant['label'],
                url=str((folder / 'demo-fast.html').relative_to(out))))
        public.append(item)
    # Reuse the maintained viewer, template and lossless animation streamer.
    script = """
import {build} from './node_modules/esbuild/lib/main.js';
import {buildFast} from './build-fast.mjs';
import {completeFixtureLights} from './fixture-lights.js';
import {readFile} from 'node:fs/promises';
const folders=JSON.parse(process.argv[1]);
const bundle=await build({entryPoints:['viewer.js'],bundle:true,write:false,minify:true,format:'iife',legalComments:'inline'});
const notices=await Promise.all(['three','cannon-es'].map(n=>readFile('node_modules/'+n+'/LICENSE','utf8')));
const code=bundle.outputFiles[0].text+'\\n/* Bundled dependency licenses\\n'+notices.join('\\n\\n').replaceAll('*/','* /')+'\\n*/';
const template=await readFile('template.html','utf8');
for(const folder of folders){const scene=JSON.parse(await readFile(folder+'/scene.json','utf8'));completeFixtureLights(scene);await buildFast(scene,template,code,folder+'/demo-fast.html',folder);console.log('Built '+folder);}
"""
    subprocess.run([node, '--input-type=module', '-e', script, json.dumps(jobs)], cwd=HERE, check=True)
    (out / 'manifest.json').write_text(json.dumps(dict(cases=public), indent=2))
    (out / 'input-manifest.json').write_text(json.dumps(data, indent=2))
    shutil.copyfile(HERE / 'motion-review.html', out / 'index.html')
    shutil.copyfile(HERE / 'motion-review.js', out / 'motion-review.js')
    print(out / 'index.html')


if __name__ == '__main__':
    main()
