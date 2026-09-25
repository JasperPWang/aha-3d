"""Source-linked numerical inspection before expensive human-scene rendering.

Run ``python -m aha3d.workflow.human_inspection --config SPEC --output NEW``.
Paths in SPEC are relative to SPEC's directory. Every input is an explicit
``{path, sha256}`` file reference. Numerical rejection writes a readable package
and exits zero; malformed/unbound inputs exit nonzero. A runner gates rendering
on ``decision.json#/allow_render``. Passing this gate is permission to render a
candidate for review, never acceptance of source style or complete physics.

The module consumes evaluated geometry, not a producer's aggregate ``accepted``.
All-active coverage includes occlusion/cropping and excludes terminal padding.
The two historical adapters retain their finite/convex proxy limitations.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import shutil
import textwrap
import time

import numpy as np

from aha3d.motion.lifecycle import source_frame_mapping, track_active_mask


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def _scalar(z, key):
    return str(np.asarray(z[key]).item())


class Inputs:
    """Resolve and hash an explicit input inventory, with an end-of-run check."""
    def __init__(self, base):
        self.base = Path(base).resolve()
        self.files = {}

    def file(self, spec, name):
        if not isinstance(spec, dict) or not isinstance(spec.get('path'), str):
            raise ValueError(f'{name}: expected a path/sha256 file reference')
        raw = self.base / spec['path']
        if raw.is_symlink():
            raise ValueError(f'{name}: symlink input is not allowed')
        path = raw.resolve()
        if not path.is_file() or len(spec.get('sha256', '')) != 64:
            raise ValueError(f'{name}: missing file or SHA256')
        actual = digest(path)
        if actual != spec['sha256']:
            raise ValueError(f'{name}: SHA256 mismatch')
        self.files[name] = dict(path=str(path), sha256=actual)
        return path

    def recheck(self):
        for name, ref in self.files.items():
            if digest(ref['path']) != ref['sha256']:
                raise ValueError(f'{name}: input changed during inspection')


def _same_time(value, expected, label):
    value = np.asarray(value, dtype=float)
    if value.shape != expected.shape or not np.allclose(value, expected, atol=1e-7, rtol=0):
        raise ValueError(f'{label}: source PTS mismatch')


def _timeline(config, inputs):
    source = inputs.file(config['source_video'], 'source_video')
    body = inputs.file(config['body_cache'], 'body_cache')
    scene = inputs.file(config['scene'], 'scene')
    review_path = inputs.file(config['lifecycle_review'], 'lifecycle_review')
    review = read_json(review_path)
    with np.load(body, allow_pickle=False) as z:
        times = np.asarray(z['time_seconds'], float)
        if times.ndim != 1 or not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError('Body must retain an ordered finite full source timeline')
        ids = source_frame_mapping(z['source_frame_indices'], len(times))
        active = track_active_mask(z['track_active'], len(times))
        actor = _scalar(z, 'source_actor_id')
        if _scalar(z, 'source_video_sha256') != config['source_video']['sha256']:
            raise ValueError('Body/source hash mismatch')
        if float(np.asarray(z['body_scale']).item()) != 1.0:
            raise ValueError('Inspection requires fixed body scale 1')
    if actor != config['actor_id'] or review.get('actor_id') != actor:
        raise ValueError('Actor binding mismatch')
    if review.get('source_video_sha256') != config['source_video']['sha256']:
        raise ValueError('Lifecycle/source hash mismatch')
    _same_time(review['time_seconds'], times, 'Lifecycle')
    if not review.get('reviewer') or not review.get('reason'):
        raise ValueError('Lifecycle requires an explicit reviewer and reason')
    exit_frame = review.get('terminal_exit_frame')
    expected_exit = int(active.sum()) if not active.all() else None
    if exit_frame != expected_exit:
        raise ValueError('Lifecycle exit differs from body activity')
    size = review.get('image_size')
    if not isinstance(size, list) or len(size) != 2 or any(type(x) is not int or x <= 0 for x in size):
        raise ValueError('Lifecycle image_size must contain positive width/height')
    return dict(source=source, body=body, scene=scene, times=times, ids=ids,
                active=active, actor=actor, exit_frame=exit_frame, image_size=size)


def series(identifier, label, values, scope_mask, *, limit=None, kind='diagnostic', unit='m', detail=None):
    values = np.asarray(values, float)
    scope_mask = np.asarray(scope_mask, bool)
    if values.shape != scope_mask.shape or values.ndim != 1:
        raise ValueError(f'{identifier}: series must have exactly T scalar values')
    if limit is not None and (not np.isfinite(limit) or limit < 0):
        raise ValueError(f'{identifier}: threshold must be finite and nonnegative')
    if np.isinf(values).any() or np.any(values[np.isfinite(values)] < 0):
        raise ValueError(f'{identifier}: metric must be nonnegative; missing is NaN')
    return dict(id=identifier, label=label, values=values, mask=scope_mask,
                limit=limit, kind=kind, unit=unit, detail=detail or '')


def _rows(rows, timeline, frame_key='source_frame', require_time=True):
    n = len(timeline['times'])
    mapping = {}
    for row in rows:
        f = row[frame_key]
        if type(f) is not int or f < 0 or f >= n or f in mapping:
            raise ValueError('Geometry rows have duplicate/invalid source frame IDs')
        if require_time and not np.isclose(row['time_seconds'], timeline['times'][f], atol=1e-7, rtol=0):
            raise ValueError('Geometry rows/source PTS mismatch')
        if 'track_active' in row and row['track_active'] != bool(timeline['active'][f]):
            raise ValueError('Geometry row activity differs from body lifecycle')
        mapping[f] = row
    return mapping


def _bound_report(report, config, body_key, scene_key):
    if report.get(body_key) != config['body_cache']['sha256']:
        raise ValueError('Geometry metrics belong to a different body cache')
    if report.get(scene_key) != config['scene']['sha256']:
        raise ValueError('Geometry metrics belong to a different authored scene')


def load_metrics(config, inputs, timeline):
    """Return normalized per-frame series, preserving exact metric scopes."""
    spec = config['metrics']
    path = inputs.file(spec, 'metrics')
    n, active = len(timeline['times']), timeline['active']
    policy = config['policy']
    floor_limit = policy['max_floor_penetration_m']
    object_limit = policy['max_object_penetration_m']
    floor, objects = np.full(n, np.nan), np.full(n, np.nan)
    output, limits, object_scope = [], [], ''
    if spec['format'] in ('placement_json', 'pantry_json'):
        report = read_json(path)
        pantry = spec['format'] == 'pantry_json'
        _bound_report(report, config, 'cache_sha256', 'source_blend_sha256' if pantry else 'source_room_sha256')
        rows = _rows(report['rows'], timeline)
        for f, row in rows.items():
            if not active[f] or row.get('geometry_assessed', True) is False:
                continue
            if pantry:
                floor[f] = max(0., -float(row['mesh_min_z_m']))
                objects[f] = row['whole_body_max_convex_pantry_depth_m']
            else:
                floor[f] = row['whole_body_max_support_penetration_m']
                depths = row['convex_furniture_penetrations']
                objects[f] = max((x['max_depth_m'] for x in depths.values()), default=np.nan)
        object_scope = ('Finite pantry components only; other furniture requires a separate report.' if pantry
                        else 'Only declared convex furniture components; concave shells excluded from signed containment.')
        limits.extend(report.get('limitations', report.get('limits', [])))
        if pantry:
            output.append(series('pantry_penetration', 'Finite pantry penetration', objects.copy(), active,
                                 limit=object_limit, kind='object_penetration'))
            # This historical report has a separately bound cases inventory.
            supplement = spec.get('other_furniture')
            if supplement:
                other_path = inputs.file(supplement, 'other_furniture')
                cases = read_json(inputs.file(supplement['cases'], 'other_furniture_cases'))
                selected = supplement['variant_id']
                if cases[selected]['cache_sha256'] != config['body_cache']['sha256']:
                    raise ValueError('Other-furniture case/body hash mismatch')
                other_report = read_json(other_path)
                matches = [r for r in other_report['results'] if r['variant'] == selected]
                if len(matches) != 1:
                    raise ValueError('Other-furniture report must identify exactly one candidate')
                other_rows = _rows(matches[0]['rows'], timeline, 'frame', require_time=False)
                extra = np.full(n, np.nan)
                for f, row in other_rows.items():
                    if active[f]: extra[f] = row['max_conservative_depth_m']
                output.append(series('other_furniture_penetration', 'Other finite furniture containment', extra,
                                     active, limit=object_limit, kind='object_penetration', detail=other_report['scope']))
                objects = np.maximum(objects, extra)
                object_scope += ' Separate island/counter/dining-top report included; chairs/stools remain unassessed.'
                limits.extend(other_report.get('limits', []))
            else:
                # A pantry-only report cannot satisfy the requested noncontact furniture check.
                objects[:] = np.nan
        limits.append('Vertex containment does not establish triangle-intersection, self-collision or complete physical validity.')
    elif spec['format'] == 'scene_npz':
        provenance = read_json(inputs.file(spec['provenance'], 'metrics_provenance'))
        _bound_report(provenance, config, 'body_cache_sha256', 'scene_sha256')
        if provenance.get('source_video_sha256') != config['source_video']['sha256'] or provenance.get('actor_id') != timeline['actor']:
            raise ValueError('Scene metrics source/actor binding mismatch')
        if provenance.get('metrics_sha256') != spec['sha256']:
            raise ValueError('Scene metrics provenance does not bind metric bytes')
        with np.load(path, allow_pickle=False) as z:
            _same_time(z['time_seconds'], timeline['times'], 'Scene metrics')
            if not np.array_equal(z['source_frame_indices'], timeline['ids']) or not np.array_equal(z['track_active'], active):
                raise ValueError('Scene metric source IDs/activity mismatch')
            floor = np.asarray(z['floor_penetration_m'], float)
            arr = np.asarray(z['object_max_penetration_m'], float)
            names = [str(x) for x in z['object_names']]
            if arr.shape != (n, len(names)) or not names:
                raise ValueError('Scene metrics require at least one explicit object and T rows')
            objects = np.max(arr, axis=1)
            if 'floor_support_outside_vertex_count' not in z:
                raise ValueError('Finite-floor metrics require support coverage counts')
            output.append(series('floor_support_outside', 'Support vertices outside assessed finite floor',
                                 z['floor_support_outside_vertex_count'], active, limit=0., kind='floor_coverage', unit='vertices'))
            if 'floor_min_signed_m' in z:
                output.append(series('whole_body_minimum_clearance',
                                     'Whole-body minimum clearance above finite support (diagnostic)',
                                     np.maximum(0., np.asarray(z['floor_min_signed_m'], float)), active,
                                     kind='clearance_diagnostic',
                                     detail='Positive minimum supported-vertex height flags possible floating for source-action review. Jumping may legitimately have positive clearance; no universal threshold or acceptance claim.'))
            for i, name in enumerate(names):
                output.append(series(f'object_{i}', name + ' penetration', arr[:, i], active,
                                     limit=object_limit, kind='object_penetration'))
        object_scope = provenance.get('object_scope', provenance.get('scope'))
        if not object_scope:
            raise ValueError('Scene metrics require an explicit object assessment scope')
        limits.extend(provenance.get('limitations', provenance.get('exclusions', [])))
    else:
        raise ValueError('Unsupported metrics format')
    output[0:0] = [series('floor_penetration', 'Whole-body floor/support penetration', floor, active,
                         limit=floor_limit, kind='floor_penetration'),
                   series('object_penetration', 'Maximum assessed object penetration', objects, active,
                         limit=object_limit, kind='object_penetration', detail=object_scope)]
    # Generic, fully bound per-frame contact/slip measurements. A missing source
    # frame is not silently filled or treated as a passing observation.
    for index, extra in enumerate(config.get('additional_metrics', [])):
        filename = inputs.file(extra, f'additional_metrics_{index}')
        provenance = read_json(inputs.file(extra['provenance'], f'additional_provenance_{index}'))
        _bound_report(provenance, config, 'body_cache_sha256', 'scene_sha256')
        if provenance.get('metrics_sha256') != extra['sha256']:
            raise ValueError('Additional metrics provenance/hash mismatch')
        if provenance.get('source_video_sha256') != config['source_video']['sha256'] or provenance.get('actor_id') != timeline['actor']:
            raise ValueError('Additional metrics source/actor binding mismatch')
        with np.load(filename, allow_pickle=False) as z:
            _same_time(z['time_seconds'], timeline['times'], 'Additional metrics')
            if not np.array_equal(z['source_frame_indices'], timeline['ids']) or not np.array_equal(z['track_active'], active):
                raise ValueError('Additional metrics source IDs/activity mismatch')
            for desc in extra['series']:
                ids = desc['source_frames']
                if not ids or len(set(ids)) != len(ids) or any(type(f) is not int or f < 0 or f >= n or not active[f] for f in ids):
                    raise ValueError('Additional metrics require explicit active source-frame scope')
                mask = np.zeros(n, bool); mask[ids] = True
                if not desc.get('review_scope'):
                    raise ValueError('Contact/slip metrics require an explicit review scope')
                output.append(series(desc['id'], desc['label'], z[desc['field']], mask,
                                     limit=desc.get('max_value'), kind=desc['kind'], unit=desc.get('unit', 'm'),
                                     detail=desc['review_scope']))
    if config.get('contact_metrics'):
        extra = config['contact_metrics']
        filename = inputs.file(extra, 'contact_metrics')
        meta = read_json(inputs.file(extra['provenance'], 'contact_provenance'))
        _bound_report(meta, config, 'body_cache_sha256', 'scene_sha256')
        if meta.get('metrics_sha256') != extra['sha256'] or meta.get('source_video_sha256') != config['source_video']['sha256'] or meta.get('actor_id') != timeline['actor']:
            raise ValueError('Canonical contact metrics source/actor/bytes mismatch')
        with np.load(filename, allow_pickle=False) as z:
            _same_time(z['time_seconds'], timeline['times'], 'Canonical contact metrics')
            if not np.array_equal(z['source_frame_indices'], timeline['ids']) or not np.array_equal(z['track_active'], active):
                raise ValueError('Canonical contact metrics source IDs/activity mismatch')
            for desc in meta['series']:
                arr = np.asarray(z[desc['field']], float)
                column = desc['column']
                if arr.ndim != 2 or arr.shape[0] != n or type(column) is not int or not 0 <= column < arr.shape[1]:
                    raise ValueError('Canonical contact metrics require a valid T,C column')
                values = arr[:, column]
                acceptance = desc['acceptance_source_frames']
                if not acceptance or len(set(acceptance)) != len(acceptance) or any(type(f) is not int or not 0 <= f < n or not active[f] for f in acceptance):
                    raise ValueError('Invalid canonical contact acceptance source frames')
                if desc['source_frames'] != np.flatnonzero(np.isfinite(values)).tolist():
                    raise ValueError('Canonical contact finite-frame inventory mismatch')
                mask = np.zeros(n, bool); mask[acceptance] = True
                if desc['kind'] == 'slip':
                    semantics = desc.get('temporal_semantics')
                    if semantics is None or semantics == 'event_source_frames':
                        # Legacy descriptors list event frames; derive the
                        # adjacent-pair ending domain exactly once.
                        mask &= np.r_[False, mask[:-1]]
                    elif semantics == 'adjacent_event_pair_ending_frame':
                        # V2 already lists pair endings. Re-eroding it would
                        # drop each event's first real velocity measurement.
                        if 'contact_event_mask' not in z:
                            raise ValueError('Explicit slip endpoints require contact_event_mask')
                        event = np.asarray(z['contact_event_mask'])
                        if event.dtype != np.bool_ or event.shape != arr.shape:
                            raise ValueError('contact_event_mask must be boolean T,C')
                        event = event[:, column]
                        if np.any(event & ~active):
                            raise ValueError('Contact event includes departed inactive frames')
                        expected = event & np.r_[False, event[:-1]]
                        if not np.array_equal(mask, expected):
                            raise ValueError('Slip endpoint scope must include every adjacent event pair exactly once')
                    else:
                        raise ValueError('Unknown slip temporal_semantics')
                if not desc.get('review_scope') or desc.get('threshold') is None:
                    raise ValueError('Canonical contact acceptance requires review scope and threshold')
                output.append(series(desc['id'], desc['label'] + ' ' + desc['kind'], values, mask,
                                     limit=desc['threshold'], kind=desc['kind'], unit=desc['unit'], detail=desc['review_scope']))
                diagnostic = np.isfinite(values) & active & ~mask
                if diagnostic.any():
                    output.append(series(desc['id'] + '__diagnostic', desc['label'] + ' outside acceptance cohort',
                                         values, diagnostic, kind='diagnostic_' + desc['kind'], unit=desc['unit'],
                                         detail='Diagnostic-only values are not additional accepted contact observations.'))
    if len({s['id'] for s in output}) != len(output):
        raise ValueError('Metric IDs must be unique')
    return output, object_scope, list(dict.fromkeys(limits))


def evaluate_series(series_list, active):
    """A local pass can never override a failed/missing full-active metric."""
    checks = []
    for item in series_list:
        scope = item['mask'] & active
        finite = np.isfinite(item['values'])
        missing = np.flatnonzero(scope & ~finite).tolist()
        usable = np.flatnonzero(scope & finite)
        failing = [] if item['limit'] is None else np.flatnonzero(scope & finite & (item['values'] > item['limit'])).tolist()
        worst = int(usable[np.argmax(item['values'][usable])]) if len(usable) else None
        checks.append(dict(id=item['id'], label=item['label'], kind=item['kind'], unit=item['unit'],
                           scope_source_frames=np.flatnonzero(scope).tolist(), threshold=item['limit'],
                           missing_source_frames=missing, failing_source_frames=failing,
                           worst_source_frame=worst, maximum=None if worst is None else float(item['values'][worst]),
                           numerical_pass=None if item['limit'] is None else bool(scope.any() and not missing and not failing),
                           detail=item['detail']))
    gate_checks = [c for c in checks if c['threshold'] is not None]
    allow = bool(gate_checks) and all(c['numerical_pass'] for c in gate_checks)
    return dict(schema_version=1, allow_render=allow,
                status='numerical_gate_passed_awaiting_visual_review' if allow else 'rejected_before_full_render',
                checks=checks, active_frame_count=int(active.sum()), inactive_frame_count=int((~active).sum()),
                source_style_accepted=False, complete_physics_accepted=False,
                scope='Declared mesh/containment and reviewed contact proxies only; visual source action and physical validity require separate review.')


def select_frames(timeline, metrics, config, events=(), tracking=None):
    """Deterministic source-frame sampling; no budget can hide a worst failure."""
    n = len(timeline['times']); active_ids = np.flatnonzero(timeline['active'])
    selection = config.get('selection', {})
    normal = selection.get('normal_count', 5); worst = selection.get('worst_per_metric', 2)
    if type(normal) is not int or not 2 <= normal <= 20 or type(worst) is not int or not 1 <= worst <= 10:
        raise ValueError('Selection counts must be normal_count2:20 and worst_per_metric1:10')
    reasons = {}
    def add(f, reason):
        if 0 <= f < n:
            reasons.setdefault(int(f), [])
            if reason not in reasons[int(f)]: reasons[int(f)].append(reason)
    for i in np.linspace(0, len(active_ids) - 1, normal).round().astype(int):
        add(int(active_ids[i]), 'Representative active-timeline frame (not a quality pass)')
    add(n - 1, 'Full-duration endpoint')
    for s in metrics:
        candidates = np.flatnonzero(s['mask'] & timeline['active'] & np.isfinite(s['values']))
        if len(candidates):
            ranked = sorted(candidates.tolist(), key=lambda f: (-s['values'][f], f))
            for rank, f in enumerate(ranked[:worst]):
                add(f, f"Worst {s['label']} #{rank+1}: {s['values'][f]:.6g} {s['unit']}")
        for f in np.flatnonzero(s['mask'] & timeline['active'] & ~np.isfinite(s['values']))[:2]:
            add(int(f), 'Missing required metric: ' + s['label'])
    for event in events:
        a, b = event['frames']
        for boundary in (a, b):
            for f in (boundary - 1, boundary, boundary + 1):
                add(f, f"{event['kind']} boundary: {event['id']} [{a},{b})")
    if timeline['exit_frame'] is not None:
        for f in range(timeline['exit_frame'] - 2, timeline['exit_frame'] + 2):
            add(f, 'Reviewed terminal exit boundary; body must be hidden from exit onward')
    if tracking is not None:
        observed = np.asarray(tracking['detected'], bool)
        for f in np.flatnonzero(observed[1:] != observed[:-1]) + 1:
            for j in (int(f) - 1, int(f)):
                add(j, 'Tracking observation-support boundary; not proof of occlusion or exit')
    for f in selection.get('extra_source_frames', []):
        if type(f) is not int or not 0 <= f < n: raise ValueError('Invalid extra source frame')
        add(f, 'Explicit predeclared source-review frame')
    return [dict(source_frame=f, time_seconds=float(timeline['times'][f]),
                 track_active=bool(timeline['active'][f]), reasons=reasons[f]) for f in sorted(reasons)]


def _events(config, inputs, timeline):
    events = config.get('events', [])
    for i, event in enumerate(events):
        review = read_json(inputs.file(event['evidence'], f'event_{i}_evidence'))
        if review.get('source_video_sha256') != config['source_video']['sha256'] or review.get('actor_id') != timeline['actor']:
            raise ValueError('Event review/source actor mismatch')
        a, b = event['frames']
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(timeline['times']):
            raise ValueError('Invalid reviewed event interval')
        if not event.get('id') or not event.get('kind') or not event.get('review_scope'):
            raise ValueError('Events need id, kind, review_scope and evidence')
    return events


def _tracking(config, inputs, timeline):
    if 'tracking' not in config:
        return None
    spec = config['tracking']; path = inputs.file(spec, 'tracking')
    if path.suffix != '.json':
        raise ValueError('Tracking currently requires source-bound raw_tracking.json')
    tracking = read_json(path)
    if tracking['source']['sha256'] != config['source_video']['sha256'] or tracking['actor_id'] != timeline['actor']:
        raise ValueError('Tracking/source actor binding mismatch')
    _same_time(tracking['time_seconds'], timeline['times'], 'Tracking')
    if tracking['image_size'] != timeline['image_size']:
        raise ValueError('Tracking/source raster mismatch')
    n = len(timeline['times'])
    if len(tracking['detected']) != n or len(tracking['raw_history']) != n:
        raise ValueError('Tracking must retain all source observations')
    # Select only the explicitly bound target identity. Context tracks are never
    # drawn as this actor's support, and gap-filled boxes are not observations.
    if tracking.get('selected_track_id') is None:
        raise ValueError('Tracking overlay requires an explicit selected target ID')
    return tracking


def _extract_frames(timeline, selected, tracking, output):
    import av
    from PIL import ImageDraw
    wanted = {r['source_frame']: r for r in selected}
    raw_dir = output / 'frames'; raw_dir.mkdir()
    decoded_times, decoded_sizes = [], set()
    with av.open(str(timeline['source'])) as container:
        for index, frame in enumerate(container.decode(video=0)):
            if frame.pts is None: raise ValueError('Source contains a frame without PTS')
            timestamp = float(frame.pts * frame.time_base)
            decoded_times.append(timestamp); decoded_sizes.add((frame.width, frame.height))
            if index not in wanted: continue
            rgb = frame.to_image().convert('RGB')
            item = wanted[index]
            item['source_rgb_sha256'] = hashlib.sha256(np.asarray(rgb).tobytes()).hexdigest()
            filename = f'frames/source_{index:06d}.png'
            rgb.save(output / filename); item['source_image'] = filename
            overlay = rgb.copy(); draw = ImageDraw.Draw(overlay)
            status = 'ACTIVE (visibility may be unknown)' if item['track_active'] else 'INACTIVE: departed; body must be hidden'
            caption = f"Source {index} | PTS {timestamp:.6f}s | {status}"
            draw.rectangle((0, 0, rgb.width, 36), fill='#101820')
            draw.text((8, 8), caption, fill='white')
            if tracking is not None:
                target = tracking['selected_track_id']
                raw = [x for x in tracking['raw_history'][index] if x['id'] == target]
                for obs in raw:
                    draw.rectangle(tuple(obs['bbx_xyxy']), outline='#00ff80', width=3)
                item['tracking_observed'] = bool(tracking['detected'][index])
                item['tracking_fill_status'] = tracking.get('box_fill_status', ['unknown'] * len(timeline['times']))[index]
                item['raw_target_observations'] = raw
                draw.rectangle((0, 36, rgb.width, 66), fill='#101820')
                draw.text((8, 42), f"Raw target box support: {bool(raw)}; filled crop is not visibility evidence", fill='white')
            overlay_name = f'frames/overlay_{index:06d}.png'
            overlay.save(output / overlay_name); item['source_overlay'] = overlay_name
    _same_time(decoded_times, timeline['times'], 'Fully decoded source video')
    if decoded_sizes != {tuple(timeline['image_size'])}:
        raise ValueError('Decoded source raster differs from bound lifecycle')
    return dict(decoded_frame_count=len(decoded_times), exact_source_pts_verified=True,
                image_size=timeline['image_size'], source_rgb_hash_semantics='SHA256 of uint8 RGB pixels before annotations')


def _room_images(config, inputs, selected, output):
    from PIL import Image
    wanted = {r['source_frame']: r for r in selected}
    views = list(config.get('cached_room_views', []))
    if config.get('room_preview'):
        receipt_path = inputs.file(config['room_preview'], 'room_preview')
        receipt = read_json(receipt_path)
        if receipt.get('schema_version') != 1 or receipt.get('body_sha256') != config['body_cache']['sha256'] or receipt.get('scene_sha256') != config['scene']['sha256']:
            raise ValueError('Room preview receipt/candidate/scene mismatch')
        if receipt.get('all_visibility_verified') is not True:
            raise ValueError('Room preview requires all-frame saved visibility verification')
        for view in receipt['views']:
            if view.get('relation') != 'same_candidate':
                raise ValueError('Room preview relation must be same_candidate')
            f = view['source_frame']
            if f not in wanted or view.get('body_hidden') != (not wanted[f]['track_active']):
                raise ValueError('Room preview frame/hidden state differs from reviewed lifecycle')
            views.append(dict(path=str((receipt_path.parent / view['path']).resolve()), sha256=view['sha256'],
                              source_frame=f, status=view['relation'], label='Sparse saved-scene preview of this candidate',
                              body_cache_sha256=view['body_sha256'], scene_sha256=view['scene_sha256'],
                              provenance=config['room_preview']))
    for i, view in enumerate(views):
        f = view['source_frame']
        if type(f) is not int or f not in wanted:
            raise ValueError('Cached room view must identify a selected source frame')
        image = inputs.file(view, f'room_view_{i}')
        proof = inputs.file(view['provenance'], f'room_view_{i}_provenance')
        if view['status'] not in ('same_candidate', 'historical'):
            raise ValueError('Cached room view status must be same_candidate or historical')
        if view['status'] == 'same_candidate' and (view['body_cache_sha256'] != config['body_cache']['sha256'] or view['scene_sha256'] != config['scene']['sha256']):
            raise ValueError('Cached room view belongs to a different candidate/scene')
        # Provenance is archived/hash-bound, not silently interpreted as an
        # independent rendering validation by this image-packaging stage.
        with Image.open(image) as im:
            im.verify()
        name = f'frames/room_{f:06d}_{i}.png'
        with Image.open(image) as im: im.convert('RGB').save(output / name)
        wanted[f].setdefault('room_views', []).append(dict(image=name, status=view['status'], label=view['label'],
            body_cache_sha256=view['body_cache_sha256'], scene_sha256=view['scene_sha256'],
            original_sha256=view['sha256'], provenance_sha256=digest(proof)))


def _contact_sheets(selected, output):
    from PIL import Image, ImageDraw
    sheets = []
    for offset in range(0, len(selected), 12):
        subset = selected[offset:offset + 12]
        sheet = Image.new('RGB', (1200, ((len(subset) + 2) // 3) * 310), '#141b24')
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(subset):
            x, y = (i % 3) * 400, (i // 3) * 310
            with Image.open(output / row['source_overlay']) as im:
                im.thumbnail((396, 223)); sheet.paste(im, (x, y))
            caption = 'f%d | ' % row['source_frame'] + '; '.join(row['reasons'])
            for j, line in enumerate(textwrap.wrap(caption, 57)[:5]):
                draw.text((x + 4, y + 224 + 15 * j), line, fill='white')
        name = f'contact_sheet_{offset // 12:02d}.jpg'
        sheet.save(output / name, quality=90); sheets.append(name)
    return sheets


def _html(report):
    esc = lambda x: html.escape(str(x), quote=True)
    decision = report['decision']
    checks = ''.join('<tr><td>%s</td><td>%s %s</td><td>%s %s</td><td>%s</td><td>%s</td></tr>' % (
        esc(c['label']), esc(c['maximum']), esc(c['unit']), esc(c['threshold']), esc(c['unit']),
        esc('diagnostic' if c['numerical_pass'] is None else 'PASS' if c['numerical_pass'] else 'FAIL'),
        ('unavailable' if c['worst_source_frame'] is None else '<a href="#frame-%d">%d</a>' % (c['worst_source_frame'],c['worst_source_frame']))) for c in decision['checks'])
    cards = []
    for row in report['selected_frames']:
        reasons = ''.join('<li>' + esc(r) + '</li>' for r in row['reasons'])
        rooms = ''.join('<figure><a href="%s"><img src="%s" alt="Room view"></a><figcaption>%s: %s</figcaption></figure>' % (
            esc(v['image']), esc(v['image']), esc(v['status']), esc(v['label'])) for v in row.get('room_views', []))
        cards.append('<article id="frame-%d"><h2>Source frame %d · %.6f s · %s</h2><ul>%s</ul>'
                     '<div class="images"><figure><a href="%s"><img src="%s" alt="Source tracking evidence"></a>'
                     '<figcaption><a href="%s">Unannotated source pixels</a></figcaption></figure>%s</div></article>' % (
                         row['source_frame'], row['source_frame'], row['time_seconds'],
                         'active; visibility not inferred' if row['track_active'] else 'departed; hidden body required',
                         reasons, esc(row['source_overlay']), esc(row['source_overlay']), esc(row['source_image']), rooms))
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
        '<title>Human inspection</title><style>body{font:16px system-ui;background:#101720;color:#eaf1fa;margin:2rem auto;max-width:1250px;padding:0 1rem}a{color:#8ecaff}table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #46576a}article{padding:1rem 0;border-top:1px solid #46576a}.images{display:flex;flex-wrap:wrap}figure{margin:.5rem;flex:1;min-width:300px}img{width:100%}li{margin:.3rem 0}</style>' \
        '<h1>' + esc(report['label']) + '</h1><p><strong>' + esc(decision['status']) + '</strong></p>' \
        '<p>This is a numerical pre-render gate, not acceptance of source action/style or complete physics. Occluded and cropped active frames remain assessed. Departed padding is excluded.</p>' \
        '<p><a href="inspection.json">Complete inspection and source-frame reasons</a> · <a href="decision.json">Machine-readable decision</a></p>' \
        '<p>Actor: ' + esc(report['actor_id']) + '</p><table><tr><th>Metric</th><th>Maximum</th><th>Limit</th><th>Result</th><th>Worst source frame</th></tr>' + checks + '</table>' \
        '<h2>Limits</h2><ul>' + ''.join('<li>' + esc(s) + '</li>' for s in report['limitations']) + '</ul>' + ''.join(cards) + '</html>'


def build(config_path, output_dir, *, overrides=None):
    started = time.perf_counter()
    config_path = Path(config_path).resolve(); config = copy.deepcopy(read_json(config_path))
    # Runner dependency paths are dynamically materialized here. They never
    # change the frozen source, actor, scene, lifecycle, policy or metric format.
    for key, path in (overrides or {}).items():
        if key not in ('body', 'metrics', 'provenance', 'room_preview', 'contact_metrics', 'contact_provenance'):
            raise ValueError('Unsupported inspection override: ' + key)
        ref = dict(path=str(Path(path).absolute()), sha256=digest(path))
        if key == 'body': config['body_cache'] = ref
        elif key == 'metrics': config['metrics'].update(ref)
        elif key == 'provenance': config['metrics']['provenance'] = ref
        elif key == 'contact_metrics': config.setdefault('contact_metrics', {}).update(ref)
        elif key == 'contact_provenance': config.setdefault('contact_metrics', {})['provenance'] = ref
        else: config[key] = ref
    if config.get('schema_version') != 1 or not config.get('policy', {}).get('id'):
        raise ValueError('Inspection requires schema_version1 and explicit policy ID')
    output = Path(output_dir).resolve()
    if output.exists(): raise ValueError('Inspection output must be a fresh path')
    inputs = Inputs(config_path.parent)
    inputs.files['config'] = dict(path=str(config_path), sha256=digest(config_path))
    timeline = _timeline(config, inputs)
    for i, ref in enumerate(config.get('extra_evidence', [])):
        inputs.file(ref, f'extra_evidence_{i}')
    metric_series, object_scope, limitations = load_metrics(config, inputs, timeline)
    events = _events(config, inputs, timeline); tracking = _tracking(config, inputs, timeline)
    selected = select_frames(timeline, metric_series, config, events, tracking)
    decision = evaluate_series(metric_series, timeline['active'])
    decision.update(case_id=config['case_id'], variant_id=config['variant_id'], actor_id=timeline['actor'],
                    body_cache_sha256=config['body_cache']['sha256'], scene_sha256=config['scene']['sha256'],
                    source_video_sha256=config['source_video']['sha256'], policy=config['policy'])
    output.mkdir(parents=True)
    try:
        decode_started = time.perf_counter()
        decoding = _extract_frames(timeline, selected, tracking, output)
        decoding['elapsed_seconds'] = time.perf_counter() - decode_started
        _room_images(config, inputs, selected, output)
        sheets = _contact_sheets(selected, output)
        # Copy every input JSON receipt. Heavy body/video data stays external;
        # package images, per-frame numbers and all necessary receipts are local.
        evidence = output / 'evidence'; evidence.mkdir()
        for i, (name, ref) in enumerate(inputs.files.items()):
            if Path(ref['path']).suffix == '.json':
                receipt = f'evidence/input_{i:03d}.json'; shutil.copyfile(ref['path'], output / receipt)
                ref['package_receipt'] = receipt
        limitations += ['Detector boxes are observation support, not body-part visibility ground truth.',
                        'Finite convex containment misses some triangle-only, concave and self-body collisions.',
                        'Image packaging does not certify saved-scene visibility or source-style fidelity.',
                        'No new candidate room rendering is fabricated; cached views retain candidate/history provenance.']
        report = dict(schema_version=1, kind='human_inspection_package', case_id=config['case_id'], variant_id=config['variant_id'],
                      label=config.get('label', config['variant_id']), actor_id=timeline['actor'], decision=decision,
                      input_binding=inputs.files, source_frame_indices=timeline['ids'].tolist(), time_seconds=timeline['times'].tolist(),
                      track_active=timeline['active'].tolist(), terminal_exit_source_frame=timeline['exit_frame'],
                      selected_frames=selected, contact_sheets=sheets, events=events, source_decode=decoding,
                      object_scope=object_scope, limitations=list(dict.fromkeys(limitations)),
                      elapsed_before_package_write_seconds=time.perf_counter()-started,
                      metric_series=[dict(id=s['id'], values=[None if not np.isfinite(v) else float(v) for v in s['values']],
                                          assessed_source_frames=np.flatnonzero(s['mask'] & timeline['active']).tolist()) for s in metric_series],
                      implementation_sha256=digest(__file__))
        inputs.recheck()
        write_json(output / 'effective_config.json', config)
        write_json(output / 'decision.json', decision)
        write_json(output / 'inspection.json', report)
        (output / 'index.html').write_text(_html(report))
        artifacts = {}
        for path in sorted(output.rglob('*')):
            if path.is_symlink(): raise ValueError('Package artifact must not be a symlink')
            if path.is_file(): artifacts[path.relative_to(output).as_posix()] = digest(path)
        write_json(output / 'bundle_manifest.json', dict(schema_version=1, entry='index.html', artifacts=artifacts))
        return report
    except Exception as exc:
        # Never leave a pass decision after incomplete packaging/input mutation.
        for name in ('decision.json', 'bundle_manifest.json'):
            (output / name).unlink(missing_ok=True)
        write_json(output / 'error.json', dict(status='invalid_or_incomplete_inspection', error=str(exc)))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--body', help='Hash-bound runner dependency; source/actor/scene remain pinned')
    parser.add_argument('--metrics', help='Metric dependency; configured format is unchanged')
    parser.add_argument('--provenance', help='Metric provenance JSON dependency')
    parser.add_argument('--room-preview', help='Sparse renderer preview.json receipt')
    parser.add_argument('--contact-metrics', help='Canonical solver T,C contact_metrics.npz')
    parser.add_argument('--contact-provenance', help='Canonical contact_metrics.json; threshold is a limit, max_value is a measurement')
    parser.add_argument('--decision-output', help='Optional fresh sibling gate.json, written only after successful package creation')
    args = parser.parse_args(argv)
    try:
        decision_output = Path(args.decision_output).absolute() if args.decision_output else None
        if decision_output is not None:
            if decision_output.exists() or decision_output.is_symlink() or decision_output.resolve().is_relative_to(Path(args.output).resolve()):
                raise ValueError('External decision output must be a fresh file outside the package')
        overrides = {key: getattr(args, key) for key in ('body', 'metrics', 'provenance', 'room_preview', 'contact_metrics', 'contact_provenance') if getattr(args, key)}
        report = build(args.config, args.output, overrides=overrides)
        if decision_output is not None:
            decision_output.parent.mkdir(parents=True, exist_ok=True)
            write_json(decision_output, report['decision'])
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f'Inspection input/error: {exc}\n')
    print(json.dumps(dict(allow_render=report['decision']['allow_render'], output=str(Path(args.output).resolve()),
                          selected_source_frames=[r['source_frame'] for r in report['selected_frames']]), allow_nan=False))


if __name__ == '__main__':
    main()
