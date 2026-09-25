"""Generate and bind object-focused layout evidence; no automatic fidelity verdict."""
import os
from pathlib import Path
import subprocess
import sys

from aha3d.io import digest, read


def generate(spec, out, *, blender=None, python=None, tools_root=None, threads=4):
    """Reuse the completed inspection and export the saved scene exactly once."""
    out = Path(out)
    root = Path(tools_root or Path(__file__).resolve().parents[3] / 'tools/layout_inspection')
    config = read(spec['config'])
    cmd = [blender or os.environ.get('BLENDER_BIN', 'blender'), '-b', spec['source_scene'],
           '-t', str(threads), '--python-exit-code', '1', '--python', str(root / 'export_model.py'),
           '--', '--cameras', spec['cameras'], '--out', str(out / 'export'),
           '--frame', str(config.get('model_frame', 1))]
    for name in config.get('exclude_objects', []):
        cmd += ['--exclude', name]
    python = python or os.environ.get('PI3X_MESH_PY') or sys.executable
    env = dict(os.environ, PYTHONPATH=str(root.parent.parent), PYTHONDONTWRITEBYTECODE='1')
    commands = [cmd,
        [python, '-m', 'tools.layout_inspection.object_outline', '--geometry', str(out/'export/model.npz'),
         '--metadata', str(out/'export/model.json'), '--inspection', str(out/'inspection'),
         '--out', str(out/'outlines'), '--threads', str(threads)],
        [python, '-m', 'tools.layout_inspection.agent_review', '--outlines', str(out/'outlines/objects.json'),
         '--out', str(out/'objects'), '--all-objects']]
    with (out/'object_generation.log').open('w') as log:
        for command in commands:
            subprocess.run(command, cwd=root.parent.parent, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)


def packet(spec, directory, expected_views):
    """Stdlib-only consumer: validate provenance, real contours and exact focus IDs."""
    directory = Path(directory).resolve()
    artifacts = {}

    def bind(relative):
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing or unsafe object review artifact: ' + str(relative))
        artifacts[str(relative)] = digest(path)
        return path

    export = read(bind('export/model.json'))
    bind('export/model.npz')
    geometry_hash = artifacts['export/model.npz']
    outlines = read(bind('outlines/objects.json'))
    report = read(bind('objects/agent_review.json'))
    if (export.get('source_scene_sha256') != digest(spec['source_scene']) or
            export.get('cameras_sha256') != digest(spec['cameras']) or
            export.get('geometry_sha256') != geometry_hash or
            outlines.get('source_scene_sha256') != export['source_scene_sha256'] or
            report.get('source_scene_sha256') != export['source_scene_sha256']):
        raise ValueError('Object review scene/camera/geometry provenance differs')
    expected = dict(geometry=geometry_hash, metadata=artifacts['export/model.json'],
                    inspection=digest(directory/'inspection/inspection.json'))
    if outlines.get('input_hashes') != expected or report.get('inputs', {}).get('outlines_sha256') != artifacts['outlines/objects.json']:
        raise ValueError('Object review input hashes differ')
    objects = {item['id']: item for item in outlines['objects']}
    exported_ids = {item['id'] for item in export.get('object_groups', [])}
    if not objects or len(objects) != len(outlines['objects']) or set(objects) != exported_ids:
        raise ValueError('Empty or inconsistent object review inventory')
    required = spec.get('required_object_ids', [])
    if not isinstance(required, list) or any(not isinstance(i, str) or not i for i in required):
        raise ValueError('required_object_ids must list exact authored IDs')
    if not set(required) <= set(objects):
        raise ValueError('Required object IDs absent from export: ' + ', '.join(sorted(set(required)-set(objects))))
    if set(outlines['views']) != set(expected_views):
        raise ValueError('Object review view inventory differs')
    backgrounds = report['inputs'].get('backgrounds', {})
    for view in expected_views:
        name = view + ('_source.png' if view.startswith('source_') else '_reference.png')
        if backgrounds.get(view, {}).get('sha256') != digest(directory/'inspection'/name):
            raise ValueError('Object review background differs: ' + view)
    images, focused = {}, {identity: {} for identity in objects}
    for item in report.get('images', []):
        name, view = item['path'], item['view']
        if Path(name).name != name or view not in outlines['views'] or name in images:
            raise ValueError('Invalid or duplicate object review image')
        path = bind('objects/' + name)
        if artifacts['objects/' + name] != report.get('image_sha256', {}).get(name):
            raise ValueError('Object review image changed: ' + name)
        images[name] = str(path)
        ids = item.get('highlighted_ids', [])
        if not set(ids) <= set(objects):
            raise ValueError('Unknown highlighted object ID')
        if item.get('kind') == 'object_focus':
            identity = item.get('object_id')
            if ids != [identity] or identity not in objects:
                raise ValueError('Focus image highlights the wrong object')
            contour = outlines['views'][view]['objects'].get(identity, {})
            if not contour.get('paths') or contour.get('mask_pixels', 0) <= 0:
                raise ValueError('Focus image has no object contour: ' + identity)
            focused[identity][view] = 'object:' + name
    for identity, views in focused.items():
        if not any(v in ('top', 'front', 'side') for v in views) or not any(v.startswith('source_') for v in views):
            raise ValueError('Missing plan/side and source focus evidence: ' + identity)
    return dict(artifacts=artifacts, images={'object:'+k: v for k, v in images.items()},
                object_views={k: list(v.values()) for k, v in focused.items()})
