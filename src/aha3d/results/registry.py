"""Explicit delivery records with conservative adapters for historical runs.

Discovery is not acceptance. Paths in new records are project-relative; source
artifacts stay in place. Hashing is explicit.
"""
import os
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import quote

from ..config import identifier
from ..io import digest, lock, now, read, write

ROLES = {'scene', 'whitebox', 'material', 'render', 'comparison', 'cameras', 'camera', 'camera_json', 'demo',
         'thumbnail', 'reference', 'generated_video', 'demo_offline', 'demo_resource'}
MEDIA = {'.blend', '.mp4', '.webm', '.mov'}
SKIP = {'snapshot', 'inputs', 'references', 'node_modules', '__pycache__',
        'frames', 'source_frames', 'masks', 'depth', 'cache', 'source'}


def local(root, value):
    """Reject paths outside this checkout, including symlink escapes."""
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    path.relative_to(root.resolve())
    return path


def relative(root, path):
    return local(root, path).relative_to(root.resolve()).as_posix()


def fingerprint(path):
    before = path.stat()
    checksum = digest(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('File changed while hashing: ' + str(path))
    return dict(sha256=checksum, size=after.st_size, mtime_ns=after.st_mtime_ns)


def describe(root, spec, verify=False):
    result = dict(spec)
    try:
        path = local(root, spec['path'])
        result['path'] = relative(root, path)
        result['href'] = '../' + quote(result['path'], safe='/')
        if not path.is_file():
            result['availability'] = 'missing'
            return result
        stat = path.stat()
        result['bytes'] = stat.st_size
        recorded = spec.get('fingerprint', {})
        if recorded.get('sha256') and verify:
            result['availability'] = 'intact' if fingerprint(path)['sha256'] == recorded['sha256'] else 'changed'
        elif recorded.get('sha256'):
            result['availability'] = ('present' if (stat.st_size, stat.st_mtime_ns) ==
                                      (recorded.get('size'), recorded.get('mtime_ns')) else 'needs_verification')
        elif 'size' in spec:
            result['availability'] = 'present' if stat.st_size == spec['size'] else 'changed'
        else:
            result['availability'] = 'unverified'
    except (OSError, ValueError) as exc:
        result.update(availability='unavailable', error=str(exc))
    return result


def validate_manifest(data):
    if data.get('schema_version') != 1:
        raise ValueError('Delivery manifest requires schema_version: 1')
    identifier(data['scene']); identifier(data['id'])
    if data.get('status') not in ('candidate', 'recorded_delivery'):
        raise ValueError('Delivery status must be candidate or recorded_delivery')
    artifacts = data.get('artifacts', [])
    if not artifacts:
        raise ValueError('Record at least one artifact')
    keys = []
    for item in artifacts:
        if item.get('role') not in ROLES or not isinstance(item.get('path'), str):
            raise ValueError('Unknown artifact role or missing path')
        keys.append((item['role'], item.get('variant', 'default')))
    if len(keys) != len(set(keys)):
        raise ValueError('Each role/variant pair must be unique')
    if sum(x['role'] == 'scene' and x.get('default', True) for x in artifacts) > 1:
        raise ValueError('Only one scene can be the default demo input')
    if data['status'] == 'recorded_delivery':
        review = data.get('review', {})
        if not review.get('note', '').strip() or not review.get('by', '').strip() or not data.get('evidence'):
            raise ValueError('Recorded delivery requires attribution, a review note and evidence paths')


def register(root, data):
    validate_manifest(data)
    if not (root / 'scenes' / data['scene']).is_dir():
        raise ValueError('Create the scene directory first')
    target = root / 'deliveries' / data['scene'] / 'versions' / (data['id'] + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    with lock(target.parent / '.register.lock'):
        if target.exists():
            raise ValueError('Delivery versions are immutable; choose a new ID')
        result = dict(data, registered_at=now())
        result['artifacts'] = []
        for item in data['artifacts']:
            path = local(root, item['path'])
            if not path.is_file():
                raise ValueError('Missing artifact: ' + str(path))
            result['artifacts'].append(dict(item, path=relative(root, path), fingerprint=fingerprint(path)))
        result['evidence'] = []
        for item in data.get('evidence', []):
            path = local(root, item['path'])
            result['evidence'].append(dict(item, path=relative(root, path), fingerprint=fingerprint(path)))
        write(target, result)
    return result


def select(root, scene, version):
    """Revalidate artifacts AND evidence under the existing selection lock."""
    from aha3d.workflow import acceptance as policy
    from aha3d.workflow.completion import cache_result, evidence_snapshot
    root=Path(root).resolve(); identifier(scene); identifier(version)
    folder=root/'deliveries'/scene; path=folder/'versions'/(version+'.json')
    with lock(folder/'.selection.lock'):
        data=read(path); validate_manifest(data)
        if data['scene']!=scene or data['id']!=version or data['status']!='recorded_delivery':
            raise ValueError('Select a recorded delivery belonging to this scene')
        ref=data.get('acceptance')
        if not ref: raise ValueError('SCOPE_REQUIRED: Historical/unscoped records are readable but cannot be newly selected')
        with policy.transaction(root,scene,ref['task']) as out, ExitStack() as writers:
            candidate=policy.candidate(out,ref['candidate_revision'])
            if candidate.get('run'):writers.enter_context(lock(Path(candidate['run'])/'.execute.lock'))
            watched=dict(candidate_revision=ref['candidate_revision'])
            extra=[path]+[local(root,i['path']) for i in data.get('evidence',[])]
            before=evidence_snapshot(out,watched,extra)
            for item in data['artifacts']+data.get('evidence',[]):
                if describe(root,item,verify=True)['availability']!='intact':
                    raise ValueError('EVIDENCE_CHANGED: Artifact/evidence fingerprint differs from registration')
            result=policy.require(policy.evaluate(root,scene,ref['task'],ref['candidate_revision'],delivery=data))
            if evidence_snapshot(out,watched,extra)!=before:
                raise ValueError('STATE_CHANGED: Evidence changed between acceptance and selection')
            pointer=dict(schema_version=3,scene=scene,delivery=relative(root,path),delivery_sha256=digest(path),
                         selected_at=now(),acceptance=dict(task=ref['task'],candidate_revision=result['candidate_revision'],policy=policy.POLICY))
            # All cooperating candidate/finding/check writers use the task lock.
            write(folder/'selected.json',pointer)
            state=read(out/'state.json');state['status']='accepted';write(out/'state.json',state)
            cache_result(out,result,[path,folder/'selected.json'])
    return dict(pointer,status='accepted',permitted=True)


def select_correction(root, scene, correction_id):
    """Publish a directly reviewed targeted correction without hashing files.

    This is a distinct, explicitly limited certification. It does not invoke or
    claim the whole-scene acceptance policy.
    """
    root = Path(root).resolve(); identifier(scene); identifier(correction_id)
    folder = root / 'deliveries' / scene
    record_path = folder / 'corrections' / (correction_id + '.json')
    with lock(folder / '.selection.lock'):
        record = read(record_path)
        if (record.get('scene'), record.get('id'), record.get('status')) != (scene, correction_id, 'targeted_correction_verified'):
            raise ValueError('Correction identity or direct-review status is invalid')
        if record.get('automatic_acceptance') is not False or not record.get('evidence'):
            raise ValueError('Correction must declare its limited acceptance and evidence')
        required = {'scene', 'whitebox_scene', 'material_video', 'whitebox_video', 'comparison'}
        artifacts = record.get('artifacts', [])
        if not required.issubset({item.get('role') for item in artifacts}):
            raise ValueError('Correction lacks required scene and video artifacts')
        stamps = []
        record_stat = record_path.stat()
        stamps.append(dict(path=relative(root, record_path), size=record_stat.st_size,
                           mtime_ns=record_stat.st_mtime_ns))
        for item in artifacts:
            path = local(root, item['path'])
            if not path.is_file() or path.stat().st_size != item.get('size'):
                raise ValueError('Correction artifact missing or size changed: ' + str(path))
            stamps.append(dict(path=relative(root, path), size=path.stat().st_size,
                               mtime_ns=path.stat().st_mtime_ns))
        for name in record['evidence']:
            path = local(root, name)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Correction evidence missing: ' + str(path))
            stamps.append(dict(path=relative(root, path), size=path.stat().st_size,
                               mtime_ns=path.stat().st_mtime_ns))
        review = read(root / 'runs' / scene / correction_id / 'visual_review.json')
        videos = read(root / 'runs' / scene / correction_id / 'delivery' / 'video_validation.json')
        saved = read(root / 'runs' / scene / correction_id / 'delivery' / 'saved_blends_validation.json')
        if review.get('targeted_correction') != 'verified' or review.get('automatic_acceptance') is not False:
            raise ValueError('Direct visual review is incomplete')
        if any(not videos.get(k, {}).get('full_decode') or not videos[k].get('pts_checked')
               for k in ('source', 'materials', 'whitebox', 'comparison')):
            raise ValueError('Full video decoding and timing evidence is incomplete')
        if any(saved.get(k, {}).get('camera', {}).get('frames_checked') != videos[k]['frames']
               for k in ('materials', 'whitebox')):
            raise ValueError('Saved scene camera checks do not match video frames')
        pointer = dict(schema_version=4, scene=scene, correction=relative(root, record_path),
                       selected_at=now(), validation='direct_targeted_review', files=stamps)
        write(folder / 'selected.json', pointer)
    return dict(pointer, status='targeted_correction_selected', permitted=True)


def promote(root, run, name='selected'):
    """Promotion uses the identical acceptance/selection policy, including old runs."""
    if name!='selected': raise ValueError('Only the authoritative selected delivery can be promoted')
    data=read(Path(run)/'run.json'); scope=data.get('task_scope')
    if not scope: raise ValueError('SCOPE_REQUIRED: Historical runs need explicit scope and new evidence')
    from aha3d.workflow import acceptance as policy
    declared,state,out=policy.consumer_scope(data,Path(run)/'run.json')
    candidate=policy.candidate(out,state['candidate'])
    if candidate.get('run')!=str(Path(run).resolve()): raise ValueError('Promotion run differs from candidate')
    policy.require(policy.evaluate(root,data['scene'],declared['task'],state['candidate']))
    version='accepted-'+state['candidate'][:24]
    target=Path(root)/'deliveries'/data['scene']/'versions'/(version+'.json')
    if not target.exists():
        register(root,dict(schema_version=1,scene=data['scene'],id=version,status='recorded_delivery',
            artifacts=[dict(role=a['role'],path=relative(root,a['path'])) for a in candidate['artifacts']],
            evidence=[dict(path=relative(root,Path(run)/'run.json'))],
            review=dict(by='acceptance-policy',note='See current structured checks and visual judgments'),
            acceptance=dict(task=declared['task'],candidate_revision=state['candidate'])))
    return select(root,data['scene'],version)


def selected(root, scene, *, hash_free=False):
    path = root / 'deliveries' / scene / 'selected.json'
    if not path.is_file():
        return None
    pointer = read(path)
    if pointer.get('schema_version') == 4:
        if pointer.get('scene') != scene:
            raise ValueError('Correction selection belongs to another scene')
        record_path = local(root, pointer['correction'])
        if record_path.parent != root / 'deliveries' / scene / 'corrections':
            raise ValueError('Correction selection points outside this scene')
        record = read(record_path)
        if record.get('scene') != scene or record.get('status') != 'targeted_correction_verified':
            raise ValueError('Selected correction record is invalid')
        for item in pointer['files']:
            source = local(root, item['path'])
            stat = source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (item['size'], item['mtime_ns']):
                raise ValueError('Selected correction artifact or evidence changed')
        roles = {'whitebox_scene': ('scene', 'whitebox'), 'material_video': ('material', None),
                 'whitebox_video': ('whitebox', None)}
        artifacts = []
        for item in record['artifacts']:
            role, variant = roles.get(item['role'], (item['role'], None))
            if role == 'archive':
                continue
            artifact = dict(role=role, path=item['path'], size=item['size'])
            if variant:
                artifact.update(variant=variant, default=False)
            artifacts.append(artifact)
        return dict(schema_version=1, id=record['id'], scene=scene, status='recorded_delivery',
                    artifacts=artifacts, evidence=[dict(path=p) for p in record['evidence']],
                    certification='targeted_correction_verified',
                    review=dict(by='codex', note='Entrance vase correction reviewed against source and decoded output.'),
                    validation_scope='Targeted entrance vase correction only; whole-room acceptance remains open.')
    if pointer.get('schema_version') in (2,3):
        manifest = local(root, pointer['delivery'])
        if manifest.parent != root / 'deliveries' / scene / 'versions':
            raise ValueError('Selection must reference this scene\'s versions directory')
        if not hash_free and digest(manifest) != pointer['delivery_sha256']:
            raise ValueError('Selected delivery manifest changed')
        data = read(manifest); validate_manifest(data)
        if data['scene'] != scene or data['status'] != 'recorded_delivery':
            raise ValueError('Invalid selected delivery')
        certification = 'historical_unverified'
        if pointer.get('schema_version') == 3:
            from aha3d.workflow.acceptance import folder as acceptance_folder
            from aha3d.workflow.completion import cached_result
            ref = pointer['acceptance']
            checked = cached_result(acceptance_folder(root,scene,ref['task']))
            certification = 'accepted' if checked.get('permitted') and checked.get('candidate_revision')==ref['candidate_revision'] else 'blocked'
        return dict(data, selection=relative(root, path), certification=certification)
    # Existing pipeline promotion: do not mutate or newly approve old records.
    run = local(root, pointer['run'])
    if run.parent != root / 'runs' / scene:
        raise ValueError('Historical selection points to a different scene')
    data = read(run / 'run.json')
    if data.get('scene') != scene or data.get('status') != 'validated' or pointer.get('visual_review', {}).get('status') != 'reviewed':
        raise ValueError('Historical selection lacks validated run and recorded review')
    artifacts = []
    for role, stage, name in [('scene', 'assemble', 'scene.blend'), ('render', 'video', 'video.mp4')]:
        entry = data.get('stages', {}).get(stage, {})
        if entry.get('status') == 'completed' and name in entry.get('outputs', {}):
            artifacts.append(dict(role=role, path=relative(root, run / 'stages' / stage / name),
                                  fingerprint={'sha256': entry['outputs'][name]}))
    if not artifacts:
        raise ValueError('Historical selection has no recorded final artifacts')
    return dict(schema_version=1, id=run.name, scene=scene, status='recorded_delivery',
                artifacts=artifacts, selection=relative(root, path), evidence=[{'path': relative(root, run / 'run.json')}],
                review={'by': pointer['visual_review'].get('reviewer'), 'note': pointer['visual_review'].get('note')},
                certification='historical_unverified',
                validation_scope='Historical pipeline validation and review; not certified against current acceptance policy.')


def discover(root, scene):
    """Find candidates without reading meshes, video frames or image sequences."""
    paths = set()
    for base in (root / 'scenes' / scene, root / 'runs' / scene):
        if not base.is_dir():
            continue
        for folder, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(folder) / d).is_symlink())
            for name in sorted(files):
                p = Path(folder) / name
                if p.suffix.lower() in MEDIA or name in ('demo.html', 'demo-drag.html'):
                    try:
                        paths.add(relative(root, p))
                    except ValueError:
                        pass
    return [describe(root, dict(path=p, role='scene' if p.endswith('.blend') else 'demo' if p.endswith('.html') else 'render',
                                status='candidate')) for p in sorted(paths)]


def build_index(root, verify=False, *, hash_free=False):
    scenes = []
    base = root / 'scenes'
    directories = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')) if base.exists() else []
    for folder in directories:
        scene = identifier(folder.name)
        row = dict(id=scene, title=scene.replace('_', ' '), selection_status='unselected', artifacts=[],
                   evidence=[], warnings=[], state='../scenes/' + quote(scene) + '/STATE.md' if (folder / 'STATE.md').exists() else None)
        config = folder / 'scene.json'
        try:
            context = root / 'deliveries' / scene / 'context.json'
            if context.exists():
                notes = read(context)
                row.update({k: notes[k] for k in ('title', 'selection_note', 'kind') if k in notes})
            if config.exists():
                metadata = read(config)
                row.update(description=metadata.get('description', ''), kind=metadata.get('kind', 'unspecified'))
                if metadata.get('reference'):
                    row['reference'] = describe(root, dict(role='reference', path=metadata['reference']))
            else:
                row['warnings'].append('scene.json missing; discovered from the scene directory')
            delivery = selected(root, scene, hash_free=hash_free)
            if delivery:
                row.update(selection_status='selected', certification=delivery.get('certification','historical_unverified'), delivery_id=delivery['id'], review=delivery.get('review'),
                           validation_scope=delivery.get('validation_scope', 'Recorded evidence; no new scene acceptance by the gallery.'))
                row.update({k: delivery[k] for k in ('title', 'description', 'kind') if k in delivery})
                if delivery.get('certification')!='accepted':
                    row['warnings'].append('Current acceptance: '+delivery.get('certification','historical_unverified'))
                row['artifacts'] = [describe(root, a, verify) for a in delivery['artifacts']]
                row['evidence'] = [describe(root, a) for a in delivery.get('evidence', [])]
                if any(a['availability'] not in ('intact', 'present') for a in row['artifacts']):
                    row['selection_status'] = 'needs_verification'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(selection_status='broken_selection')
            row['warnings'].append(str(exc))
        row['candidates'] = discover(root, scene)
        chosen = {a['path'] for a in row['artifacts']}
        row['candidates'] = [a for a in row['candidates'] if a['path'] not in chosen]
        row['versions'] = []
        for manifest in sorted((root / 'deliveries' / scene / 'versions').glob('*.json')):
            try:
                version = read(manifest); validate_manifest(version)
                row['versions'].append(dict(id=version['id'], status=version['status'], href='../' + quote(relative(root, manifest))))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                row['warnings'].append('Invalid delivery version: ' + str(exc))
        scenes.append(row)
    return dict(schema_version=1, generated_at=now(), verification='metadata_only' if hash_free else 'sha256' if verify else 'metadata_only', scenes=scenes,
                counts={'scenes': len(scenes), 'selected': sum(r['selection_status'] == 'selected' for r in scenes),
                        'candidates': sum(len(r['candidates']) for r in scenes)})
