"""One acceptance policy for exact reconstruction revisions, stages and publication.

Authoritative scope/findings live outside candidate directories. Cooperative locks
and hashes prevent accidental stale use, not hostile same-user shell modification.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path

from aha3d.config import identifier
from aha3d.io import digest, lock, now, read, signature, write
from .review_contract import ASPECTS, validate as validate_review

POLICY = 1
TERMINAL = ('cancelled', 'incomplete', 'failed', 'paused')


def folder(root, scene, task):
    return Path(root).resolve() / 'deliveries' / identifier(scene) / 'acceptance' / identifier(task)


def capture(path):
    path = Path(path).resolve(); a = path.stat(); checksum = digest(path); b = path.stat()
    if (a.st_size, a.st_mtime_ns, a.st_ctime_ns) != (b.st_size, b.st_mtime_ns, b.st_ctime_ns):
        raise ValueError('File changed during fingerprint: ' + str(path))
    return dict(path=str(path), sha256=checksum)


def current(record):
    return capture(record['path']) == record


def implementations():
    base = Path(__file__).parent
    return {p.name: digest(p) for p in [Path(__file__), base/'layout_gate.py', base/'preview_gate.py', base/'review_contract.py', base/'camera.py']}


def init(root, spec):
    scene, task = identifier(spec['scene']), identifier(spec['task'])
    if spec.get('kind') not in ('reconstruction', 'code', 'documentation'):
        raise ValueError('Declare reconstruction, code or documentation scope')
    if type(spec.get('repair_budget',3)) is not int or not 0<=spec.get('repair_budget',3)<=20:
        raise ValueError('Repair budget must be an integer from 0 to 20')
    scope = dict(spec, schema_version=1, policy=POLICY)
    if scope['kind'] == 'reconstruction':
        for key in ('reference_reconstruction', 'human_motion'):
            if type(scope.get(key)) is not bool:
                raise ValueError('Explicit boolean scope required: ' + key)
        if scope.get('render') not in ('none', 'stills', 'video'):
            raise ValueError('Declare render scope: none, stills, video')
        if not scope.get('required_artifacts') or 'scene' not in scope['required_artifacts']:
            raise ValueError('Declare required artifact roles including scene')
        if scope['render']=='video':
            from aha3d.config import timing
            scope['timing']=timing(scope.get('timing',{}))
        if scope['render'] != 'none' and 'render' not in scope['required_artifacts']:
            raise ValueError('Render scope requires a render artifact')
        if scope['human_motion'] and (not isinstance(scope.get('people'),list) or not scope['people']):
            raise ValueError('Human scope must declare every person ID')
        if not isinstance(scope.get('subjects'), list) or not scope['subjects']:
            raise ValueError('Declare salient object and relationship IDs for review')
        if scope['reference_reconstruction']:
            scope['source_video'] = capture(Path(root) / scope['source_video'])
        scene_file = Path(root) / 'scenes' / scene / 'scene.json'
        if scene_file.exists() and read(scene_file).get('reference') and not scope['reference_reconstruction']:
            raise ValueError('Registered reference scene cannot declare a text-only scope')
    out = folder(root, scene, task)
    pointer=Path(root)/'scenes'/scene/'task_scope.json'
    with ExitStack() as locks:
        if scope['kind']=='reconstruction':
            pointer.parent.mkdir(parents=True,exist_ok=True)
            locks.enter_context(lock(pointer.parent/'.scope.lock'))
            if pointer.exists() and read(pointer).get('task_scope')!=str(out/'scope.json'):
                raise ValueError('Scene already has an active scope; resume it or explicitly hand off the scene')
        out.mkdir(parents=True, exist_ok=True)
        locks.enter_context(lock(out/'.lock'))
        if (out/'scope.json').exists():
            raise ValueError('Task scope is immutable; resume this scope instead of replacing it')
        write(out/'scope.json', scope)
        write(out/'state.json', dict(status='awaiting_review', candidate=None, jobs=[], repair_attempts=0,
                                     repair_budget=spec.get('repair_budget', 3), scope_sha256=digest(out/'scope.json')))
        write(out/'findings.json', {'findings': []})
        if scope['kind']=='reconstruction':write(pointer,dict(task_scope=str(out/'scope.json')))
    return dict(status='awaiting_review', task=task, scene=scene, scope=str(out/'scope.json'), accepted=False)


def load_scope(out):
    scope = read(out/'scope.json'); state = read(out/'state.json')
    if scope.get('policy') != POLICY or state['scope_sha256'] != digest(out/'scope.json'):
        raise ValueError('Persisted task scope changed or policy is unsupported')
    return scope, state


@contextmanager
def transaction(root, scene, task):
    out = folder(root, scene, task)
    with lock(out/'.lock'):
        yield out


def register_candidate(root, scene, task, spec):
    with transaction(root, scene, task) as out:
        scope, state = load_scope(out)
        if scope['kind'] != 'reconstruction':
            raise ValueError('Only reconstruction scopes register scene candidates')
        context = spec['context']
        needed = {'room_scene', 'final_scene', 'configuration', 'cameras'}
        if scope['reference_reconstruction']: needed.add('source_video')
        if not needed <= set(context):
            raise ValueError('Candidate context missing: ' + ', '.join(sorted(needed-set(context))))
        binding = {k: capture(Path(root)/v) for k,v in context.items()}
        if scope['reference_reconstruction'] and binding['source_video']['sha256'] != scope['source_video']['sha256']:
            raise ValueError('Candidate reference differs from persisted task scope')
        artifacts = [dict(role=a['role'], **capture(Path(root)/a['path'])) for a in spec['artifacts']]
        if not any(a['role']=='scene' and a['sha256']==binding['final_scene']['sha256'] for a in artifacts):
            raise ValueError('Final assembled scene must be a candidate artifact')
        data = dict(schema_version=1, task=task, scene=scene, scope_sha256=state['scope_sha256'],
                    context=binding, artifacts=artifacts, implementations=implementations(),
                    purpose=spec.get('purpose', 'candidate'), completeness=spec.get('completeness', 'partial'),
                    layout=spec.get('layout'), run=str((Path(root)/spec['run']).resolve()) if spec.get('run') else None)
        data['final_views'] = capture(Path(root)/spec['final_views']) if spec.get('final_views') else None
        if data['final_views']:
            view_manifest=read(data['final_views']['path'])
            data['images']={k:capture(Path(data['final_views']['path']).parent/v) for k,v in view_manifest['images'].items()}
        else: data['images']={}
        revision = signature(data); data['revision'] = revision
        target = out/'candidates'/f'{revision}.json'
        if not target.exists(): write(target, data)
        state.update(candidate=revision, status=state['status'] if state['status'] in TERMINAL else 'awaiting_review'); write(out/'state.json', state)
        return dict(status='awaiting_review', accepted=False, candidate_revision=revision, path=str(target))


def candidate(out, revision):
    identifier(revision); value = read(out/'candidates'/f'{revision}.json')
    if value.get('revision') != revision or signature({k:v for k,v in value.items() if k!='revision'}) != revision:
        raise ValueError('Immutable candidate revision changed')
    return value


def requirements(scope, stage='complete'):
    checks = ['layout'] if scope.get('reference_reconstruction') else []
    if stage == 'people': return checks
    if scope.get('human_motion'): checks.append('alignment')
    if stage == 'preview': return checks
    if scope.get('render') != 'none': checks.append('preview')
    if stage == 'render': return checks
    return checks + ['technical', 'final_review']


def record_check(root, scene, task, revision, name, report_path):
    """Record actual validator/reviewer output, not a boolean success flag."""
    with transaction(root, scene, task) as out:
        scope, _ = load_scope(out); candidate(out, revision)
        if name not in requirements(scope) or name == 'layout':
            raise ValueError('Unknown check; layout uses the existing layout gate directly')
        report = capture(report_path)
        target = out/'checks'/revision/(name+'.json')
        # Replacement retains the previous receipt; findings have independent lifetime.
        if target.exists(): write(out/'history'/(name+'-'+signature(read(target))+'.json'), read(target))
        body=read(report['path'])
        for finding in body.get('review',{}).get('findings',[]):
            _add_finding(out,dict(finding,origin='reviewer',originating_revision=revision))
        write(target, report)
        return dict(status='awaiting_review', accepted=False, check=name, evidence=report)


def _add_finding(out, finding):
    data=read(out/'findings.json');identifier(finding['id'])
    if any(f['id']==finding['id'] for f in data['findings']):
        raise ValueError('Finding ID already exists; retain or explicitly resolve the original finding')
    if finding.get('origin') not in ('user','reviewer','validator') or finding.get('severity') not in ('blocking','nonblocking'):
        raise ValueError('Explicit finding origin and severity required')
    if finding['origin']=='user' and finding['severity']!='blocking':
        raise ValueError('User mismatches remain blocking until explicitly resolved with evidence')
    for key in ('affected_ids','views','originating_revision','resolution_needed','observation'):
        if not finding.get(key): raise ValueError('Missing finding field: '+key)
    candidate(out,finding['originating_revision'])
    data['findings'].append(dict(finding,status='open',history=[dict(action='opened',at=now())]))
    write(out/'findings.json',data)
    state=read(out/'state.json');state['status']=state['status'] if state['status'] in TERMINAL else 'blocked';write(out/'state.json',state)
    return data['findings'][-1]


def add_finding(root, scene, task, finding):
    with transaction(root,scene,task) as out:
        load_scope(out)
        return _add_finding(out,finding)


def resolve_finding(root, scene, task, finding_id, resolution):
    with transaction(root, scene, task) as out:
        scope, state = load_scope(out); data=read(out/'findings.json')
        finding=next(f for f in data['findings'] if f['id']==finding_id)
        revision=resolution['candidate_revision']; candidate(out,revision)
        if revision!=state['candidate']: raise ValueError('Resolve against the current corrected revision')
        if finding['status']!='open' and finding.get('resolution',{}).get('candidate_revision')==revision:
            raise ValueError('Finding is already resolved for this revision')
        # A preview-to-delivery revision changes the artifact set. Its previous
        # closure stays stale until a new, fully validated before/after review
        # demonstrates that the correction persists in the current candidate.
        if resolution.get('disposition') not in ('corrected','false_positive') or not resolution.get('rationale','').strip():
            raise ValueError('Specific resolution rationale and disposition required')
        if resolution['disposition']=='corrected' and revision==finding['originating_revision']:
            raise ValueError('Correction must identify a new corrected revision with before/after evidence')
        images=resolution['images']
        if not any(k.startswith('before:') for k in images) or not any(k.startswith('after:') for k in images):
            raise ValueError('Actual before/after verification images required')
        before=candidate(out,finding['originating_revision']); after=candidate(out,revision)
        for key,value in images.items():
            source=before if key.startswith('before:') else after
            view=key.split(':',1)[-1]
            if view not in source.get('images',{}) or capture(value)!=source['images'][view]:
                raise ValueError('Before/after image must come from the original and corrected candidate view manifests')
        review=read(resolution['review'])
        validate_review(review,revision,images,('relationships',),finding['affected_ids'])
        if review['verdict']!='accepted': raise ValueError('Resolution review rejected')
        saved=dict(resolution, review=capture(resolution['review']), images={k:capture(v) for k,v in images.items()})
        finding.update(status='resolved',resolution=saved)
        finding['history'].append(dict(action='resolved',at=now(),resolution=saved))
        write(out/'findings.json',data)
        return finding


def _report(out, data, name, scope):
    record=read(out/'checks'/data['revision']/(name+'.json'))
    if not current(record): raise ValueError('Registered check evidence fingerprint changed')
    report=read(record['path'])
    if report.get('candidate_revision')!=data['revision'] or report.get('policy')!=POLICY:
        raise ValueError('Check does not bind this candidate and validator policy')
    # Every image, validator and subordinate report is fingerprinted, not only the outer JSON.
    evidence=report.get('evidence', [])
    if not evidence or not all(current(e) for e in evidence):
        raise ValueError('Check evidence missing or changed')
    if name in ('preview','final_review','alignment'):
        images=report['images']
        if {k:capture(v) for k,v in images.items()}!=data['images']:
            raise ValueError('Visual review images differ from final scene evidence')
        required={'plan','front','side'}
        if scope['reference_reconstruction'] or scope['render']!='none':required.update(('early','middle','late'))
        if scope['reference_reconstruction']:required.update(('source_early','source_middle','source_late'))
        if not required<=set(images):raise ValueError('Final review needs matched plan/orthographic and early/middle/late views')
        if not data['final_views'] or not current(data['final_views']):raise ValueError('Final view manifest missing or changed')
        view_manifest=read(data['final_views']['path'])
        expected={k:v['sha256'] for k,v in data['context'].items()}
        if view_manifest.get('input_binding')!=expected:raise ValueError('Final views must bind exact scene, cameras and configuration')
        validate_review(report['review'],data['revision'],images,ASPECTS + (('human_alignment',) if name=='alignment' else ()),scope['subjects'] + (scope.get('people',[]) if name=='alignment' else []))
        if report['review']['verdict']!='accepted': raise ValueError('Visual review rejected')
    if report.get('diagnostic_only') or report.get('purpose')=='diagnostic' or report.get('completeness')=='partial':
        raise ValueError('Diagnostic or partial validator output cannot certify a delivery')
    if report.get('status')!='passed': raise ValueError('Technical check is not passed')
    validator=report.get('validator')
    if not validator or not current(validator): raise ValueError('Relevant validator changed or is missing')
    if name=='technical':
        if report.get('artifacts')!=data['artifacts']: raise ValueError('Technical checks must cover every exact delivery artifact')
        if scope['render']=='video':
            from fractions import Fraction
            validations=report.get('video_validation',[])
            if not validations or not all(current(v) for v in validations):raise ValueError('Full video decoding/timing receipts required')
            evidence=evidence+validations
            decoded=[read(v['path']) for v in validations]
            timing=scope['timing']
            for artifact in [a for a in data['artifacts'] if a['role'] in ('render','comparison','generated_video')]:
                matches=[r for r in decoded if r.get('sha256')==artifact['sha256']]
                if not matches:raise ValueError('Decode receipt does not cover actual final video')
                r=matches[0]
                if (r.get('full_decode_pass') is not True or r.get('decoded_frames')!=timing['frames'] or
                    Fraction(r.get('fps','0'))!=Fraction(timing['fps']) or
                    abs(r.get('decoder_duration_seconds',-1)-timing['duration_seconds'])>.02):
                    raise ValueError('Decoded final video does not meet persisted requested timing')
    if name=='alignment':
        if report.get('room_sha256')!=data['context']['room_scene']['sha256'] or report.get('scene_sha256')!=data['context']['final_scene']['sha256']:
            raise ValueError('Human alignment must bind both static room and assembled scene')
        if set(report.get('people',[]))!=set(scope.get('people',[])) or report.get('all_people_reviewed') is not True:
            raise ValueError('All-person alignment coverage required')
    if name=='preview' and data.get('run'):
        from .preview_gate import applicable
        run=Path(data['run'])
        if not applicable(run,read(run/'run.json')):raise ValueError('Existing full-clip preview gate is missing or stale')
    return [record]+evidence+[validator]+list(data.get('images',{}).values())


def evaluate(root, scene, task, revision=None, *, stage='complete', delivery=None):
    """Deterministic read-only policy. Caller holds task/selection locks for writes."""
    result=dict(policy=POLICY,stage=stage,completion_permitted=False,publication_permitted=False,status='blocked',task=task,scene=scene,candidate_revision=revision,
                required_checks=[],blockers=[],evidence=[],next_steps=[],permitted=False)
    def block(code,detail,step):
        result['blockers'].append(dict(code=code,detail=str(detail))); result['next_steps'].append(step)
    try:
        out=folder(root,scene,task); scope,state=load_scope(out)
        if scope['kind']!='reconstruction':
            result.update(status='not_applicable'); return result
        revision=revision or state['candidate']; result['candidate_revision']=revision
        if not revision: raise ValueError('Register an exact candidate revision first')
        data=candidate(out,revision)
        if revision!=state['candidate']: block('STALE_CANDIDATE','Candidate is not current','Review the current revision')
        if state['status'] in TERMINAL: block('TASK_INCOMPLETE',state['status'],'Resume explicitly before acceptance')
        for job in state['jobs']:
            if stage=='complete' and job['status'] in ('submitted','running'):
                block('JOB_PENDING',job,'Wait for job completion and validate actual outputs')
        if data['scope_sha256']!=state['scope_sha256'] or data['implementations']!=implementations():
            block('POLICY_CHANGED','Scope or validator versions changed','Register and review a new revision')
        for entry in list(data['context'].values())+data['artifacts']+list(data.get('images',{}).values()):
            if capture(entry['path'])!={k:entry[k] for k in ('path','sha256')}:
                block('ARTIFACT_CHANGED',entry['path'],'Regenerate checks for the changed inputs or artifacts')
            result['evidence'].append(entry)
        if stage=='complete':
            if data['purpose']!='delivery' or data['completeness']!='complete':
                block('NOT_DELIVERY','Diagnostic, candidate or partial output','Produce the complete requested delivery')
            if not set(scope['required_artifacts'])<={a['role'] for a in data['artifacts']}:
                block('ARTIFACT_MISSING','Required deliverable roles missing','Produce every scope-required artifact')
        for finding in read(out/'findings.json')['findings']:
            if finding['severity']!='blocking': continue
            resolution=finding.get('resolution',{})
            valid=finding['status']=='resolved' and resolution.get('candidate_revision')==revision
            if valid:
                valid=current(resolution['review']) and all(current(v) for v in resolution['images'].values())
            if not valid: block('OPEN_FINDING',finding['id']+': '+finding['observation'],'Correct and verify before/after for finding '+finding['id'])
        for name in requirements(scope,stage):
            check=dict(name=name,status='blocked'); result['required_checks'].append(check)
            try:
                if name=='layout':
                    from .layout_gate import require_current
                    layout=data.get('layout')
                    if not layout: raise ValueError('Layout inspection and visual review missing')
                    from .layout_gate import normalize_spec
                    spec=normalize_spec(layout['spec'])
                    for field,context in [('source_scene','room_scene'),('camera_cache','cameras'),('source_video','source_video')]:
                        if digest(spec[field])!=data['context'][context]['sha256']: raise ValueError('Layout context differs: '+field)
                    checked=require_current(spec,layout['evidence_dir'])
                    review=read(Path(layout['evidence_dir'])/'review.json')
                    if not set(scope['subjects'])<={s for r in review['visual_review']['observations'] for s in r['subjects']}:
                        raise ValueError('Layout review omits scope subjects')
                    result['evidence'].append(checked)
                else:
                    result['evidence'].extend(_report(out,data,name,scope))
                check['status']='passed'
            except (OSError,ValueError,KeyError,TypeError) as exc:
                check['detail']=str(exc)
                block('CHECK_'+name.upper(),exc,'Generate current '+name+' evidence and record complete review')
        if data.get('run'):
            from aha3d.pipeline.runner import load, stages
            run=Path(data['run']); manifest,recipe,_=load(run)
            if stage=='complete' and manifest.get('diagnostic_only'):
                block('NOT_DELIVERY','Producer marked this run diagnostic-only','Produce a delivery run; relabeling candidates does not change producer scope')
            if stage=='complete' and (manifest.get('status')!='validated' or manifest.get('scope')=='motion_only'):
                block('RUN_INCOMPLETE','Run is not technically complete','Complete all required run stages')
            if stage=='complete':
                from aha3d.io import intact
                for name in stages(recipe):
                    if name=='layout_inspection': continue
                    entry=manifest['stages'].get(name,{})
                    if entry.get('status')!='completed' or not intact(run/'stages'/name,entry.get('outputs',{})):
                        block('RUN_INCOMPLETE',name,'Complete and validate the required run stage')
                if digest(run/'stages/assemble/scene.blend')!=data['context']['final_scene']['sha256']:
                    block('FINAL_SCENE_MISMATCH','Run scene differs from reviewed assembled scene','Review the actual assembled output')
        if delivery is not None:
            expected=sorted((a['role'],a['path'],a['sha256']) for a in data['artifacts'])
            actual=sorted((a['role'],str((Path(root)/a['path']).resolve()),a['fingerprint']['sha256']) for a in delivery['artifacts'])
            if expected!=actual: block('DELIVERY_MISMATCH','Delivery is not the exact reviewed artifact set','Register the reviewed delivery artifacts')
            for item in delivery.get('evidence',[]):
                if digest(Path(root)/item['path'])!=item['fingerprint']['sha256']:
                    block('EVIDENCE_CHANGED',item['path'],'Regenerate and re-register changed delivery evidence')
        if not result['blockers']:
            result.update(status='accepted',permitted=True,completion_permitted=stage=='complete',publication_permitted=stage=='complete')
        elif any(b['code']=='JOB_PENDING' for b in result['blockers']):
            result['status']='running' if any(j['status']=='running' for j in state['jobs']) else 'submitted'
        elif all(b['code'].startswith('CHECK_') for b in result['blockers']): result['status']='awaiting_review'
    except (OSError,ValueError,KeyError,TypeError) as exc:
        block('STATE_INVALID',exc,'Declare task scope and register current evidence; do not bypass missing state')
    return result


def require(result):
    if not result['permitted']:
        raise ValueError('; '.join(b['code']+': '+b['detail'] for b in result['blockers']) or 'Reconstruction acceptance is not applicable')
    return result


def consumer_scope(manifest, manifest_path):
    value=manifest.get('task_scope')
    if not value: raise ValueError('Persisted task_scope required; omission cannot waive reference checks')
    path=(Path(manifest_path).resolve().parent/value).resolve()
    scope,state=load_scope(path.parent)
    if path.name!='scope.json' or scope['kind']!='reconstruction': raise ValueError('Invalid reconstruction scope')
    return scope,state,path.parent


def consumer_prerequisite(manifest, manifest_path, stage, *, diagnostic=False):
    if diagnostic: return dict(status='awaiting_review',accepted=False,permitted=False,purpose='diagnostic')
    scope,state,out=consumer_scope(manifest,manifest_path)
    root=out.parents[3]
    result=require(evaluate(root,scope['scene'],scope['task'],stage=stage))
    data=candidate(out,state['candidate']); base=Path(manifest_path).resolve().parent
    if manifest.get('inputs',{}).get('source.blend'):
        if manifest['inputs']['source.blend']['sha256']!=data['context']['room_scene']['sha256']:
            raise ValueError('Consumer room differs from accepted candidate room')
        if digest(base/'snapshot/recipe.json')!=data['context']['configuration']['sha256']:
            raise ValueError('Consumer configuration differs from reviewed candidate')
        if stage in ('render','preview') and digest(base/'stages/assemble/scene.blend')!=data['context']['final_scene']['sha256']:
            raise ValueError('Assembled consumer scene differs from reviewed final scene')
    else:
        for key,field in (('scene','room_scene'),('camera_cache','cameras')):
            value=manifest.get('render',{}).get(key)
            if not value or digest(base/value)!=data['context'][field]['sha256']:
                raise ValueError('Consumer '+key+' differs from accepted task candidate')
    return result


def record_job(manifest, manifest_path, job_id, status):
    """Runner lifecycle metadata; completion still needs actual evidence."""
    if not manifest.get('task_scope'): return
    scope,_,out=consumer_scope(manifest,manifest_path)
    with lock(out/'.lock'):
        _,state=load_scope(out)
        entry=next((j for j in state['jobs'] if j['id']==job_id),None)
        if entry and status=='submitted' and entry['status']!='submitted':return  # Fast worker already advanced.
        if entry:entry['status']=status
        else:state['jobs'].append(dict(id=job_id,status=status))
        if state['status'] not in TERMINAL:state['status']='awaiting_review' if status=='completed' else status
        write(out/'state.json',state)
