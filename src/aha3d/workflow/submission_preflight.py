"""Small-input checks shared by planning, submission and compute preparation.

No model imports or video decoding. Geometry/identity/contact remain
review tasks. Optional SAM checks use the explicitly supplied Pi3X processed raster.
"""
import math
from pathlib import Path

from aha3d.config import load_recipe, load_runtime, path
from aha3d.io import read


def vector(value, size, label, unit=False):
    if not isinstance(value, list) or len(value) != size or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError(f'{label} requires {size} finite numbers')
    if unit and abs(sum(x*x for x in value) - 1) > 1e-3:
        raise ValueError(f'{label} must be unit length; do not infer or repair intended facing')


def constraints_report(entries, native_frames):
    if not isinstance(entries, list):
        raise ValueError('Constraints must be a list')
    count = 0
    targets = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Each constraint must be an object')
        frames = entry.get('frame_indices', [])
        if not frames or any(type(f) is not int or not 0 <= f < native_frames for f in frames) or frames != sorted(set(frames)):
            raise ValueError(f'Constraint frames must be sorted unique integers in [0, {native_frames-1}]')
        for field, size, unit in [('global_root_heading', 2, True), ('smooth_root_2d', 2, False), ('root_positions', 3, False)]:
            if field in entry:
                if len(entry[field]) != len(frames):
                    raise ValueError(f'{field} row count differs from frame_indices')
                for frame, row in zip(frames, entry[field]):
                    vector(row, size, field, unit)
                    key = (field, frame)
                    if key in targets and any(abs(a-b) > 1e-4 for a,b in zip(targets[key], row)):
                        raise ValueError(f'Conflicting {field} targets at native frame {frame}; revise authored route/hand guidance')
                    targets[key] = row
        count += len(frames)
    return dict(keys=count, native_frames=native_frames,
        heading_convention='global_root_heading=(cos(angle),sin(angle)); native +Z forward is [1,0]. SAM facing_xz is an XZ direction (+Z=[0,1]). Unit checks cannot establish intended facing.')


def sam_report(selection, cameras):
    w, h = cameras['processed_size_wh']
    records = {f['source_frame']: f for f in cameras['frames']}
    fps, n = selection.get('native_fps', 30), selection['native_frames']
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps != 30 or type(n) is not int or n < 1:
        raise ValueError('Invalid native SAM timeline')
    if not selection['events']:
        raise ValueError('Select at least one SAM event')
    for event in selection['events']:
        f = event['source_frame']
        if type(f) is not int or f not in records:
            raise ValueError(f'SAM source frame {f} missing from same-shot camera records')
        if 'bbox_xyxy' in event:
            box = event['bbox_xyxy']; vector(box, 4, 'bbox_xyxy')
            if not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
                raise ValueError(f'SAM bbox exceeds processed source raster {w}x{h}; original-video coordinates are not interchangeable')
        t = event.get('target_time_seconds', records[f]['timestamp_seconds'] - selection.get('source_start_seconds', 0))
        if not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t < n/fps or not 0 <= math.floor(t * fps + .5) < n:
            raise ValueError('SAM event rounds outside native clip; author explicit earlier target_time_seconds')
        if 'facing_xz' in event:
            vector(event['facing_xz'], 2, 'facing_xz')
            if sum(x*x for x in event['facing_xz']) < 1e-12:
                raise ValueError('facing_xz must be nonzero; compiler normalizes this direction')
    return dict(events=len(selection['events']), processed_size_wh=[w, h],
        limitations='Bounds checked only for supplied boxes; timestamp checks only: inspect exact processed source and full-body overlays for identity, handedness and visibility.')


def check(root, scene, name, motion_only=False, sam_selection=None, sam_cameras=None):
    recipe = load_recipe(root, scene, name)
    runtime = load_runtime(root, recipe['runtime'])
    body = recipe['body']
    if motion_only and body['mode'] not in ('generate', 'native'):
        raise ValueError('motion-only requires generate or native body mode')
    reference = None if motion_only or recipe['render']['kind'] != 'video' else read(Path(root) / 'scenes' / scene / 'scene.json').get('reference')
    if reference and not path(root, reference).is_file():
        raise ValueError(f'Missing registered source reference: {path(root, reference)}')
    deps = {} if motion_only else {'source': path(root, recipe['source'])}
    deps.update({key: path(root, body[key]) for key in ('cache', 'native', 'constraints') if body.get(key)})
    for key, p in deps.items():
        if not p.is_file():
            raise ValueError(f'Missing {key} dependency: {p}')
    report = dict(status='passed', scene=scene, recipe=name, timing=recipe['timing'],
        dependencies={k: str(v) for k, v in deps.items()},
        limitations=['Does not load Blender/model assets or validate mesh placement, identity, external Blender dependencies or action quality.'])
    if body['mode'] == 'generate':
        segments = [int(d * 30) for d in body['durations']]
        if min(segments) < 1:
            raise ValueError('Each prompt must produce at least one native 30fps frame')
        report['native_segment_frames'] = segments
        if 'constraints' in deps:
            report['constraints'] = constraints_report(read(deps['constraints']), sum(segments))
    if bool(sam_selection) != bool(sam_cameras):
        raise ValueError('Supply both SAM selection and same-shot Pi3X cameras')
    if sam_selection:
        report['sam'] = sam_report(read(sam_selection), read(sam_cameras))
    report['preview_backends'] = {'cpu': 'headless Cycles CPU; no GPU required',
        'gpu': 'Cycles OptiX on the local GPU; explicit request fails when no device is visible'}
    return report


def device_check(backend, operation):
    """GPU visibility only; Blender still checks usable OptiX devices."""
    if backend not in ('cpu', 'gpu'):
        raise ValueError('Backend must be cpu or gpu')
    if backend == 'gpu':
        from aha3d.runtime import require_gpu
        require_gpu(operation)
