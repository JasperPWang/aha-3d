"""Bind observed-placement acceptance to the exact inputs and selected caches.

Uses only the standard library so saved evidence can be checked inside Blender.
"""
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def input_binding(manifest_path, refinement=None):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    base = path.parent
    rows = []
    for actor in manifest['actors']:
        actor_id = actor['id']
        if not isinstance(actor_id, str) or not actor_id or Path(actor_id).name != actor_id or actor_id in ('.', '..'):
            raise ValueError('Unsafe actor identity')
        source = (base / actor['motion']).resolve()
        pose = (base / actor['pose_confidence']).resolve() if actor.get('pose_confidence') else source.parent / 'preprocess' / 'vitpose.pt'
        cache = Path(refinement) / actor_id / 'body_room.npz' if refinement else base / actor['cache']
        rows.append({'id': actor_id, 'cache': digest(cache),
                     'alignment': digest(base / actor['alignment']),
                     'motion': digest(source), 'pose_confidence': digest(pose) if pose.is_file() else None})
    if not rows or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Expected unique actors')
    return {'manifest_sha256': digest(path),
            'camera_sha256': digest(base / manifest['render']['camera_cache']),
            'diagnostic_implementation_sha256': digest(Path(__file__).with_name('placement_diagnostics.py')),
            'actors': rows}


def validate_placement_report(report_path, manifest_path, refinement=None):
    report = json.loads(Path(report_path).read_text())
    if report.get('schema_version') != 1 or report.get('scope') != 'observed_projection_only':
        raise ValueError('Expected observed-source placement evidence')
    if report.get('accepted') is not True or report.get('status') != 'pass':
        raise ValueError('Source placement failed or is unverified; contact success cannot override it')
    if report.get('input_binding') != input_binding(manifest_path, refinement):
        raise ValueError('Placement evidence does not match current inputs/selected caches')
    return {'report_sha256': digest(report_path), 'scope': report['scope']}


def check_and_record(manifest_path, output, refinement=None):
    """Run in the model Python environment; failed evidence remains inspectable."""
    import subprocess
    import sys
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    destination = Path(output)
    camera = (path.parent / manifest['render']['camera_cache']).resolve()
    command = [sys.executable, str(Path(__file__).with_name('placement_diagnostics.py')),
               '--manifest', str(path), '--camera-cache', str(camera), '--output', str(destination)]
    if refinement is not None:
        command.extend(['--refinement', str(Path(refinement).resolve())])
    before = input_binding(path, refinement)
    subprocess.run(command, check=True)
    report_path = destination / 'report.json'
    report = json.loads(report_path.read_text())
    if before != input_binding(path, refinement):
        raise ValueError('Placement inputs changed during analysis')
    report['input_binding'] = before
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    return validate_placement_report(report_path, path, refinement)
