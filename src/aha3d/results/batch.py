"""Incremental demo plans and isolated, claim-owned batch execution."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

from .. import runtime as host
from ..config import identifier
from ..io import digest, lock, now, read, signature, write
from .registry import describe, fingerprint, local, relative, selected


def run_id(purpose):
    identifier(purpose)
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower() + '-' + purpose[:35] + '-' + uuid.uuid4().hex[:8]


def claim(root, task, owner, paths, title):
    cmd = [sys.executable, str(root / 'tools/task_claim.py'), '--root', str(root), 'claim', task,
           '--owner', owner, '--title', title, '--paths'] + [relative(root, p) for p in paths]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def release(root, task, owner, status, note):
    subprocess.run([sys.executable, str(root / 'tools/task_claim.py'), '--root', str(root), 'release', task,
                    '--owner', owner, '--status', status, '--note', note], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def new_run(root, scene, purpose, owner):
    identifier(scene)
    if not (root / 'scenes' / scene).is_dir():
        raise ValueError('Unknown scene: ' + scene)
    rid = run_id(purpose); task = 'run-' + rid
    folder = root / 'runs' / scene / rid
    claim(root, task, owner, [folder], 'Scene run: ' + purpose)
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('snapshot', 'stages', 'logs'):
        (folder / name).mkdir()
    data = dict(schema_version=1, results_kind='workspace', scene=scene, run_id=rid,
                purpose=purpose, owner=owner, task=task, status='created', created_at=now(), artifacts=[])
    write(folder / 'run.json', data)
    return dict(data, path=relative(root, folder), note='Claim stays active until all writers stop; use task_claim.py release.')


def exporter_fingerprint(root):
    folder = root / 'tools/roomkit_browser'
    # The exporter currently imports direct sibling modules only. Lockfile pins
    # dependencies. Exclude generated node_modules and local runtime files.
    entries = {p.name: digest(p) for p in sorted(folder.iterdir())
               if p.is_file() and p.suffix in ('.py', '.js', '.mjs', '.html', '.json')}
    if 'demo.py' not in entries:
        raise ValueError('Browser exporter is not installed in this checkout')
    return signature(entries)


def runtime_identity(blender):
    binary = Path(shutil.which(blender) or blender).resolve()
    if not binary.is_file():
        raise ValueError('Blender executable not found: ' + blender)
    stat = binary.stat()
    return dict(blender=str(binary), blender_size=stat.st_size, blender_mtime_ns=stat.st_mtime_ns,
                python=sys.version, node=subprocess.check_output(['node', '--version'], text=True).strip())


def demo_attempts(root, scene):
    for path in sorted((root / 'runs' / scene).glob('*/run.json'), reverse=True):
        try:
            data = read(path)
            if data.get('results_kind') == 'demo':
                yield dict(data, record_path=relative(root, path))
        except (OSError, ValueError, TypeError):
            continue


def demo_runs(root, scene):
    return (data for data in demo_attempts(root, scene) if data.get('status') == 'validated')


def plan(root, scenes, blender, tabletop=False, retry=None, chairs=False):
    exporter = exporter_fingerprint(root)
    runtime = runtime_identity(blender)
    options = dict(tabletop=tabletop, chairs=chairs)
    tool_signature = signature(dict(exporter=exporter, runtime=runtime, options=options))
    if retry:
        previous = read(retry)
        scenes = [r['scene'] for r in previous['rows'] if r.get('status') in ('failed', 'interrupted', 'queued', 'running')]
    if scenes is None:
        scenes = sorted(p.name for p in (root / 'scenes').iterdir() if p.is_dir() and not p.name.startswith('.'))
    rows = []
    for scene in sorted(set(scenes)):
        identifier(scene)
        row = dict(scene=scene, action='blocked')
        try:
            delivery = selected(root, scene)
            if not delivery:
                raise ValueError('No explicit selected delivery')
            if delivery.get('certification') == 'blocked':
                raise ValueError('Current acceptance is stale or blocked; refresh before demo publication')
            sources = [a for a in delivery['artifacts'] if a['role'] == 'scene' and a.get('default', True)]
            if len(sources) != 1:
                raise ValueError('Select exactly one default Blender input')
            source = sources[0]
            if not source['path'].endswith('.blend'):
                raise ValueError('Default demo input must be a saved .blend')
            path = local(root, source['path']); fp = fingerprint(path)
            if fp['sha256'] != source.get('fingerprint', {}).get('sha256'):
                raise ValueError('Selected Blender is missing a matching registered fingerprint')
            row.update(action='build', source=relative(root, path), source_fingerprint=fp, delivery_id=delivery['id'],
                       reason='Demo missing or stale')
            for old in demo_runs(root, scene):
                if old.get('source_fingerprint', {}).get('sha256') == fp['sha256'] and old.get('tool_signature') == tool_signature:
                    demos = [a for a in old.get('artifacts', []) if a['role'] == 'demo']
                    if len(demos) == 1 and all(describe(root, a, verify=True)['availability'] == 'intact' for a in old.get('artifacts', [])):
                        row.update(action='skip', reason='Matching input, exporter, runtime, options and intact demo', demo=demos[0]['path'])
                        break
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(action='blocked', reason=str(exc))
        rows.append(row)
    return dict(schema_version=1, kind='demo_plan', created_at=now(), exporter_fingerprint=exporter,
                runtime=runtime, options=options, tool_signature=tool_signature, rows=rows,
                counts={action: sum(r['action'] == action for r in rows) for action in ('build', 'skip', 'blocked')})


def validate_plan(data):
    if data.get('schema_version') != 1 or data.get('kind') != 'demo_plan':
        raise ValueError('Expected a demo_plan')
    if signature(dict(exporter=data['exporter_fingerprint'], runtime=data['runtime'], options=data['options'])) != data['tool_signature']:
        raise ValueError('Plan tool signature mismatch')
    if set(data['options']) not in ({'tabletop'}, {'tabletop','chairs'}) or any(type(v) is not bool for v in data['options'].values()):
        raise ValueError('Unsupported demo options')
    scenes = [identifier(row['scene']) for row in data['rows']]
    if len(scenes) != len(set(scenes)):
        raise ValueError('Duplicate scene in batch plan')
    if any(row['action'] not in ('build', 'skip', 'blocked') for row in data['rows']):
        raise ValueError('Unknown plan action')


def create_batch(root, data, owner, concurrency=1):
    validate_plan(data)
    if concurrency < 1 or concurrency > 8:
        raise ValueError('Concurrency must be between 1 and 8')
    builds = [r for r in data['rows'] if r['action'] == 'build']
    if not builds:
        raise ValueError('Plan has no buildable scenes; inspect blocked/skipped reasons')
    bid = run_id('demo-batch'); folder = root / 'runs/_batches' / bid
    rows = []
    for r in data['rows']:
        row = dict(r, status='queued' if r['action'] == 'build' else r['action'])
        if r['action'] == 'build':
            local(root, r['source'])
            row['output'] = 'runs/' + r['scene'] + '/' + run_id('demo')
        rows.append(row)
    task = 'batch-' + bid
    claim(root, task, owner, [folder] + [root / r['output'] for r in rows if r['action'] == 'build'], 'Incremental browser demo batch')
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / 'plan.json', data)
    result = dict(schema_version=1, batch_id=bid, task=task, owner=owner, status='prepared',
                  created_at=now(), concurrency=concurrency, plan_sha256=digest(folder / 'plan.json'), rows=rows)
    write(folder / 'batch.json', result)
    return folder


def execute(root, folder):
    folder = local(root, folder)
    if folder.parent != root / 'runs/_batches':
        raise ValueError('Batch must be under runs/_batches')
    with lock(folder / '.execute.lock'):
        data = read(folder / 'batch.json'); spec = read(folder / 'plan.json'); validate_plan(spec)
        if digest(folder / 'plan.json') != data['plan_sha256']:
            raise ValueError('Batch plan changed')
        if len(data['rows']) != len(spec['rows']) or any(
                any(row.get(k) != original.get(k) for k in original)
                for row, original in zip(data['rows'], spec['rows'])):
            raise ValueError('Batch rows differ from the pinned plan')
        if data['status'] != 'prepared':
            raise ValueError('Use demo-plan --retry for a new batch; do not overwrite old attempts')
        data.update(status='running', job_id=host.run_id(), started_at=now())
        write(folder / 'batch.json', data)

        def worker(row):
            out = local(root, row['output'])
            expected = root / 'runs' / identifier(row['scene'])
            if out.parent != expected:
                raise ValueError('Invalid scene output path')
            record = dict(schema_version=1, results_kind='demo', run_id=out.name, scene=row['scene'],
                          status='running', source=row['source'], source_fingerprint=row['source_fingerprint'],
                          tool_signature=spec['tool_signature'], exporter_fingerprint=spec['exporter_fingerprint'],
                          runtime=spec['runtime'], options=spec['options'], batch=relative(root, folder),
                          started_at=now(), artifacts=[], visual_review='pending')
            created = False
            try:
                out.mkdir(parents=True, exist_ok=False)
                created = True
                write(out / 'run.json', record)
                write(out / 'snapshot/request.json', dict(row=row, tool_signature=spec['tool_signature']))
                (out / 'logs').mkdir()
                source = local(root, row['source'])
                def unchanged():
                    if fingerprint(source)['sha256'] != row['source_fingerprint']['sha256']:
                        raise ValueError('Selected source changed after planning')
                    if exporter_fingerprint(root) != spec['exporter_fingerprint'] or runtime_identity(spec['runtime']['blender']) != spec['runtime']:
                        raise ValueError('Exporter or runtime changed after planning; make a fresh plan')
                unchanged()
                demo = out / 'stages/demo'
                demo.parent.mkdir()
                cmd = [sys.executable, str(root / 'tools/roomkit_browser/demo.py'), '--source', str(source),
                       '--out', str(demo), '--blender', spec['runtime']['blender']]
                if spec['options']['tabletop']:
                    cmd.append('--tabletop')
                if spec['options'].get('chairs'):
                    cmd.append('--chairs')
                with (out / 'logs/demo.log').open('w') as log:
                    subprocess.run(cmd, cwd=root, check=True, stdout=log, stderr=subprocess.STDOUT)
                unchanged()
                receipt = read(demo / 'run.json')
                if receipt.get('status') != 'validated' or receipt.get('source_sha256') != row['source_fingerprint']['sha256']:
                    raise ValueError('Exporter did not validate this exact source')
                for role, name in [('demo', 'demo-fast.html'), ('demo_offline', 'demo.html'), ('thumbnail', 'orbit.png')]:
                    p = demo / name
                    record['artifacts'].append(dict(role=role, path=relative(root, p), fingerprint=fingerprint(p)))
                for name in read(demo / 'demo-fast.html.json')['files'] + ['demo-fast.html.json']:
                    p = demo / name
                    record['artifacts'].append(dict(role='demo_resource', path=relative(root, p), fingerprint=fingerprint(p)))
                if not (demo / 'validation.json').is_file():
                    raise ValueError('Browser QA evidence missing')
                record.update(status='validated', finished_at=now(), evidence=[relative(root, demo / 'validation.json')])
                write(out / 'run.json', record)
                return dict(row, status='validated', run=relative(root, out))
            except Exception as exc:
                record.update(status='failed', error=str(exc), finished_at=now())
                pipeline_log = out / 'stages/demo/pipeline.log'
                if pipeline_log.exists():
                    with pipeline_log.open('rb') as stream:
                        stream.seek(max(0, pipeline_log.stat().st_size - 65536))
                        lines = stream.read().decode('utf-8', errors='replace').splitlines()
                    details = [line for line in lines if line.startswith(('ValueError:', 'RuntimeError:', 'AssertionError:', 'Error:'))]
                    if details:
                        record['diagnostic'] = details[0][:800]
                # Never overwrite a preexisting output after mkdir failed.
                if created:
                    write(out / 'run.json', record)
                return dict(row, status='failed', error=str(exc), diagnostic=record.get('diagnostic'))

        with ThreadPoolExecutor(max_workers=data['concurrency']) as pool:
            futures = {pool.submit(worker, r): i for i, r in enumerate(data['rows']) if r['action'] == 'build'}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    data['rows'][i] = future.result()
                except Exception as exc:
                    data['rows'][i].update(status='failed', error=str(exc))
                write(folder / 'batch.json', data)
        failed = any(r['status'] == 'failed' for r in data['rows'])
        data.update(status='partial_failure' if failed else 'completed', finished_at=now())
        write(folder / 'batch.json', data)
    release(root, data['task'], data['owner'], 'handoff' if failed else 'completed',
            'All batch writers stopped; see ' + relative(root, folder / 'batch.json'))
    return data


def submit(root, folder):
    """Start demo-execute as a detached local worker; its output goes to <batch>/worker.log."""
    data = read(folder / 'batch.json')
    job = data['batch_id']
    cmd = [sys.executable, str(root / 'tools/scene_results.py'), '--root', str(root), 'demo-execute', str(folder)]
    script = ('#!/bin/bash\nset -euo pipefail\ncd ' + shlex.quote(str(root)) + '\nsource kimodo_blender/env.sh\n'
              'export INDOOR_RUN_ID=' + shlex.quote(job) + '\n' + shlex.join(cmd) + '\n')
    (folder / 'submit.sh').write_text(script)
    pid = host.start_background(folder / 'submit.sh', folder / 'worker.log')
    receipt = dict(status='submitted', job_id=job, pid=pid, batch=relative(root, folder), log=relative(root, folder / 'worker.log'), at=now())
    write(folder / 'submission.json', receipt)
    subprocess.run([sys.executable, str(root / 'tools/task_claim.py'), '--root', str(root), 'checkpoint', data['task'],
                    '--owner', data['owner'], '--job-id', job, '--note', 'Started demo batch worker; retain claims until writers stop'],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return receipt
