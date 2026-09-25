"""Codex 0.154 Stop/Interrupt adapter. Never launches compute in a stop hook."""
import json
from pathlib import Path
import sys

from aha3d.config import identifier
from aha3d.io import lock, read, write
from . import acceptance


def binding_path(root, session):
    return Path(root)/'tasks'/'.acceptance_sessions'/(identifier(session)+'.json')


def bind(root, scene, task, session):
    scope, _ = acceptance.load_scope(acceptance.folder(root,scene,task))
    path=binding_path(root,session)
    path.parent.mkdir(parents=True,exist_ok=True)
    with lock(path.parent/'.lock'):
        if path.exists() and read(path)!={'scene':scene,'task':task}:
            raise ValueError('Session already belongs to another declared task')
        write(path,dict(scene=scene,task=task))
    return dict(status='bound',kind=scope['kind'],session=session)


def stamp(path):
    path=Path(path).resolve(); stat=path.stat()
    return dict(path=str(path),size=stat.st_size,mtime_ns=stat.st_mtime_ns,
                ctime_ns=stat.st_ctime_ns,inode=stat.st_ino,device=stat.st_dev)


def evidence_snapshot(out, result, extra=()):
    """Called only after full hash validation under task and publication locks.

    Stat tokens only invalidate a previously hash-validated receipt. They never
    create acceptance. NFS caching and unrestricted same-user access are limits.
    """
    paths={out/name for name in ('scope.json','state.json','findings.json')}
    revision=result.get('candidate_revision')
    if revision:
        paths.add(out/'candidates'/(revision+'.json'))
        paths.update((out/'checks'/revision).glob('*.json'))
    # Recursively collect the bound inputs, subordinate reports, images and code.
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='path' and isinstance(item,str) and Path(item).is_file(): paths.add(Path(item).resolve())
                else: collect(item)
        elif isinstance(value,list):
            for item in value: collect(item)
    for path in list(paths):
        value=read(path);collect(value)
        if path.parent.parent.name=='checks' and value.get('path'):
            collect(read(value['path']))
    collect(result)
    revision=result.get('candidate_revision')
    if revision:
        data=acceptance.candidate(out,revision)
        if data.get('layout'):
            from .layout_gate import normalize_spec, PATH_FIELDS
            spec=normalize_spec(data['layout']['spec'])
            paths.update(Path(spec[k]) for k in PATH_FIELDS if spec.get(k))
            directory=Path(data['layout']['evidence_dir'])
            paths.update(directory/name for name in ('evidence.json','review.json'))
            paths.update(p for p in (directory/'inspection').rglob('*') if p.is_file())
        if data.get('run'):
            run=Path(data['run']); paths.add(run/'run.json')
            paths.update(p for base in ('inputs','snapshot','stages') for p in (run/base).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(Path(p).resolve() for p in extra)
    selected=out.parents[1]/'selected.json'
    if selected.exists():
        paths.add(selected)
        pointer=read(selected)
        if pointer.get('delivery'):
            manifest=out.parents[3]/pointer['delivery']
            paths.add(manifest)
            for item in read(manifest).get('evidence',[]):paths.add(out.parents[3]/item['path'])
    base=Path(acceptance.__file__).parent
    paths.update(base/name for name in acceptance.implementations())
    return [stamp(p) for p in sorted(paths)]


def cache_result(out, result, extra=()):
    write(out/'acceptance.json',dict(result=result,files=evidence_snapshot(out,result,extra)))


def cached_result(out):
    try:
        receipt=read(out/'acceptance.json')
        if not receipt.get('files') or any(stamp(s['path'])!=s for s in receipt['files']):
            raise ValueError('Validated evidence or authoritative state changed')
        return receipt['result']
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return dict(status='blocked',permitted=False,blockers=[dict(code='ACCEPTANCE_REFRESH_REQUIRED',detail=str(exc))],
                    next_steps=['Run indoor acceptance check; refresh selection after all checks pass'])


def require_completed_claim(root, scene, task):
    """Gate registry completion independently of optional Codex hook trust.

    A claim may precede scope initialization, but
    missing scope can never turn that reconstruction claim into completed work.
    """
    root = Path(root).resolve()
    pointer = root / 'scenes' / identifier(scene) / 'task_scope.json'
    if not pointer.is_file():
        raise ValueError('SCOPE_REQUIRED: initialize and bind reconstruction acceptance before completion; use handoff for unfinished work.')
    scope_path = Path(read(pointer)['task_scope']).resolve()
    if not scope_path.is_relative_to(root / 'deliveries' / scene / 'acceptance'):
        raise ValueError('Task scope must belong to this scene in this checkout.')
    scope, _ = acceptance.load_scope(scope_path.parent)
    if scope['kind'] != 'reconstruction' or scope['scene'] != scene:
        raise ValueError('A reconstruction claim requires reconstruction scope for the same scene.')
    if scope['task'] != identifier(task):
        raise ValueError('SCOPE_MISMATCH: Scene scope does not belong to this claim; declare --acceptance-task at intake when resuming an existing scope.')
    if scope_path != acceptance.folder(root, scene, scope['task']) / 'scope.json':
        raise ValueError('Task scope pointer does not match its declared task.')
    from aha3d.results.registry import selected
    with lock(root / 'deliveries' / scene / '.selection.lock'), acceptance.transaction(root, scene, scope['task']) as out:
        delivery = selected(root, scene)
        _, state = acceptance.load_scope(out)
        if (not delivery or delivery.get('certification') != 'accepted'
                or delivery.get('acceptance', {}).get('task') != scope['task']
                or delivery.get('acceptance', {}).get('candidate_revision') != state['candidate']):
            raise ValueError('SELECTION_REQUIRED: select the exact accepted delivery before completing the reconstruction claim.')
        before = evidence_snapshot(out, dict(candidate_revision=state['candidate']))
        result = acceptance.evaluate(root, scene, scope['task'], delivery=delivery)
        if not result.get('permitted'):
            raise ValueError('Reconstruction remains unaccepted: ' + json.dumps(result['blockers']))
        if evidence_snapshot(out, result) != before:
            raise ValueError('STATE_CHANGED: Evidence changed during completion validation.')


def handle(root, event):
    if event.get('hook_event_name') not in ('Stop','Interrupt') or not event.get('session_id'): return {}
    path=binding_path(root,event['session_id'])
    if not path.exists(): return {}  # Explicit registration scopes this to reconstruction sessions.
    binding=read(path); out=acceptance.folder(root,binding['scene'],binding['task'])
    with lock(out/'.lock'):
        scope,state=acceptance.load_scope(out)
        if scope['kind']!='reconstruction': return {}
        if event['hook_event_name']=='Interrupt':
            state.update(status='incomplete'); write(out/'state.json',state)
            return dict(systemMessage='Reconstruction interrupted; no successful acceptance recorded.')
        if state['status'] in acceptance.TERMINAL:
            return {'continue':False,'stopReason':'Reconstruction '+state['status']+'; not accepted.'}
        result=cached_result(out)
        if result.get('permitted'):
            selected=Path(root)/'deliveries'/scope['scene']/'selected.json'
            pointer=read(selected) if selected.exists() else {}
            if pointer.get('acceptance',{}).get('candidate_revision')==state['candidate'] and pointer['acceptance'].get('task')==scope['task']:
                from aha3d.results.registry import selected as read_selected
                delivery=read_selected(Path(root).resolve(),scope['scene'])
                data=acceptance.candidate(out,state['candidate'])
                actual=sorted((a['role'],str((Path(root)/a['path']).resolve()),a['fingerprint']['sha256']) for a in delivery['artifacts'])
                expected=sorted((a['role'],a['path'],a['sha256']) for a in data['artifacts'])
                if delivery.get('certification')=='accepted' and actual==expected:return {}
            result=dict(status='blocked',permitted=False,blockers=[dict(code='SELECTION_REQUIRED',detail='Current accepted candidate has not been selected')],next_steps=['Select the exact reviewed delivery'])
        reason=json.dumps(result,separators=(',',':'))
        # Persist a bounded task budget across turn IDs/restarts. stop_hook_active
        # is not a reason to waive policy or reset the budget.
        if state['repair_attempts']>=state['repair_budget']:
            state.update(status='incomplete'); write(out/'state.json',state)
            return {'continue':False,'stopReason':'Repair budget exhausted; reconstruction incomplete.',
                    'systemMessage':'Not accepted. '+reason}
        state['repair_attempts']+=1; state['status']='blocked'; write(out/'state.json',state)
        return dict(decision='block',reason='Reconstruction cannot complete successfully. '+reason+
                    ' Continue the authorized repair, or record paused/cancelled/incomplete/failed with a reason. Do not announce acceptance.')


def main(root=None):
    root=Path(root or Path(__file__).resolve().parents[3])
    try:
        result=handle(root,json.load(sys.stdin))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        # Fail closed without an endless repair loop on broken controller state.
        result={'continue':False,'stopReason':'Acceptance controller failed; task remains unaccepted.', 'systemMessage':str(exc)}
    print(json.dumps(result))
    return 0
