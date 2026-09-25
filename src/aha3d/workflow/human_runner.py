"""Resumable, artifact-bound DAG execution for human experiments (stdlib only).

This is independent of the existing scene recipe pipeline. A completed process is
an engineering result, never an implicit reconstruction/contact acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from aha3d import runtime
from aha3d.io import digest, lock, now, read, signature, write

SCHEMA = 1
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
TOKEN = re.compile(r'\{(input:[A-Za-z0-9_-]+|output:[A-Za-z0-9_-]+|stage_dir|params_file|dependency_status_file|root|run_dir|python)\}')
TRACKED_ENV = ('PATH', 'PYTHONPATH', 'VIRTUAL_ENV', 'CUDA_VISIBLE_DEVICES',
               'CUDA_DEVICE_ORDER', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
               'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')
SUCCESS = 'completed'


def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{label}: expected object; unknown fields {set(value) - set(allowed) if isinstance(value, dict) else value!r}')


def _name(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f'Invalid identifier: {value!r}')
    return value


def _strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or '\0' in x for x in value):
        raise ValueError(f'{label} must be an array of strings without NUL')
    return value


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Output requires a relative POSIX path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or value in ('.', '') or p.parts[0] == '_runner':
        raise ValueError(f'Output escapes or overlaps runner metadata: {value}')
    return p.as_posix()


def _external(value, label):
    _keys(value, ('path', 'sha256'), label)
    if not isinstance(value.get('path'), str) or not value['path'] or '\0' in value['path']:
        raise ValueError(f'{label} requires path')
    if 'sha256' in value and not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise ValueError(f'{label}: expected lowercase SHA256')


def load_config(path):
    """Validate all graph edges and output ownership before any stage launches."""
    path = Path(path).resolve()
    config = read(path)
    _keys(config, ('schema_version', 'id', 'root', 'stages'), 'config')
    if config.get('schema_version') != SCHEMA:
        raise ValueError('Unsupported human runner schema')
    _name(config.get('id'))
    if not isinstance(config.get('root', '.'), str):
        raise ValueError('root must be a path string')
    root = (path.parent / config.get('root', '.')).resolve()
    if not root.is_dir():
        raise ValueError(f'Missing root: {root}')
    stages = config.get('stages')
    if not isinstance(stages, list) or not stages:
        raise ValueError('stages must be a nonempty array')
    by_id = {}
    for stage in stages:
        _keys(stage, ('id', 'needs', 'argv', 'inputs', 'code', 'outputs', 'params',
                      'env', 'inherit_env', 'gates', 'needs_policy', 'timeout_seconds'), 'stage')
        sid = _name(stage.get('id'))
        if sid in by_id:
            raise ValueError(f'Duplicate stage: {sid}')
        by_id[sid] = stage
        needs = _strings(stage.setdefault('needs', []), 'needs')
        if len(needs) != len(set(needs)):
            raise ValueError(f'Duplicate dependency in {sid}')
        if not _strings(stage.get('argv'), 'argv'):
            raise ValueError('argv cannot be empty')
        if stage.setdefault('needs_policy', 'success') not in ('success', 'settled'):
            raise ValueError('needs_policy must be success or settled')
        for key in ('inputs', 'outputs', 'params', 'env'):
            if not isinstance(stage.setdefault(key, {}), dict):
                raise ValueError(f'{key} must be an object')
        if not stage['outputs']:
            raise ValueError(f'{sid} must declare at least one output artifact')
        paths = []
        for name, output in stage['outputs'].items():
            _name(name); paths.append(_relative(output))
        if any(a == b or a.startswith(b + '/') or b.startswith(a + '/')
               for i, a in enumerate(paths) for b in paths[i+1:]):
            raise ValueError(f'Overlapping declared outputs in {sid}')
        for name, item in stage['inputs'].items():
            _name(name)
            if isinstance(item, dict) and 'stage' in item:
                _keys(item, ('stage', 'output'), 'stage input')
                _name(item.get('stage')); _name(item.get('output'))
            else:
                _external(item, f'{sid} input {name}')
        if not isinstance(stage.get('code'), list) or not stage['code']:
            raise ValueError(f'{sid} requires nonempty declared code dependencies')
        for item in stage['code']:
            _external(item, f'{sid} code')
        if any(not isinstance(k, str) or not k or '=' in k or '\0' in k or
               not isinstance(v, str) or '\0' in v for k, v in stage['env'].items()):
            raise ValueError('env requires string names and values')
        _strings(stage.setdefault('inherit_env', []), 'inherit_env')
        timeout = stage.get('timeout_seconds')
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('timeout_seconds must be positive and finite')
        if not isinstance(stage.setdefault('gates', []), list):
            raise ValueError('gates must be an array')
        for gate in stage['gates']:
            _keys(gate, ('stage', 'output', 'pointer', 'equals'), 'gate')
            if set(gate) != {'stage', 'output', 'pointer', 'equals'}:
                raise ValueError('gate needs stage, output, pointer and equals')
            if not isinstance(gate['pointer'], str) or (gate['pointer'] and not gate['pointer'].startswith('/')):
                raise ValueError('gate pointer must be an RFC6901 JSON pointer')
    for stage in stages:
        for dep in stage['needs']:
            if dep not in by_id or dep == stage['id']:
                raise ValueError(f'Unknown/self dependency: {dep}')
        refs = [v for v in stage['inputs'].values() if 'stage' in v] + stage['gates']
        for ref in refs:
            if ref['stage'] not in stage['needs'] or ref['output'] not in by_id[ref['stage']]['outputs']:
                raise ValueError(f'{stage["id"]}: artifact reference must name a declared direct dependency/output')
    ordered, visited, visiting = [], set(), set()
    def visit(sid):
        if sid in visiting:
            raise ValueError('Dependency graph has a cycle')
        if sid in visited:
            return
        visiting.add(sid)
        for dep in by_id[sid]['needs']:
            visit(dep)
        visiting.remove(sid); visited.add(sid); ordered.append(by_id[sid])
    for sid in by_id:
        visit(sid)
    json.dumps(config, allow_nan=False)  # Reject NaN params/gate values.
    return config, root, ordered


def _path(root, spec):
    return (root / spec['path']).resolve()


def _hash_artifact(path, *, code=False):
    """Hash complete file/directory membership; outputs cannot contain symlinks."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'Artifact symlink is not an immutable output: {path}')
    if path.is_file():
        return {'kind': 'file', 'sha256': digest(path), 'bytes': path.stat().st_size}
    if path.is_dir():
        members = {}
        for p in sorted(path.rglob('*')):
            if code and ('__pycache__' in p.parts or p.suffix == '.pyc'):
                continue
            if p.is_symlink():
                raise ValueError(f'Directory artifact contains symlink: {p}')
            if p.is_file():
                members[p.relative_to(path).as_posix()] = digest(p)
            elif not p.is_dir():
                raise ValueError(f'Unsupported artifact type: {p}')
        if not members:
            raise ValueError(f'Empty output/code directory: {path}')
        return {'kind': 'directory', 'sha256': signature(members), 'files': members}
    raise ValueError(f'Missing artifact: {path}')


def _bound_external(root, spec, *, code=False):
    p = _path(root, spec)
    record = _hash_artifact(p, code=code)
    if spec.get('sha256') and record['sha256'] != spec['sha256']:
        raise ValueError(f'Pinned SHA256 mismatch: {p}')
    return p, record


def _output_path(run, entry, name):
    record = entry.get('outputs', {}).get(name)
    if entry.get('status') != SUCCESS or not record:
        raise ValueError(f'Dependency has no completed output: {name}')
    p = run / record['path']
    if not p.resolve().is_relative_to(run):
        raise ValueError('Recorded output escaped run')
    if _hash_artifact(p) != record['artifact']:
        raise ValueError(f'Dependency output changed: {p}')
    return p, record['artifact']


def _context(root, run, stage, results):
    paths, hashes = {}, {}
    for name, spec in stage['inputs'].items():
        if 'stage' in spec:
            p, value = _output_path(run, results[spec['stage']], spec['output'])
        else:
            p, value = _bound_external(root, spec)
        paths[name] = p; hashes[name] = value
    code = {str(_path(root, spec)): _bound_external(root, spec, code=True)[1] for spec in stage['code']}
    env = os.environ.copy(); env.update(stage['env'])
    tracked = {key: env.get(key) for key in sorted(set(TRACKED_ENV) | set(stage['inherit_env']) | set(stage['env']))}
    executable = stage['argv'][0].replace('{python}', sys.executable).replace('{root}', str(root))
    executable = shutil.which(executable, path=env.get('PATH')) if not os.path.isabs(executable) else executable
    if not executable or not Path(executable).is_file():
        raise ValueError(f'Missing executable: {stage["argv"][0]}')
    executable = str(Path(executable).resolve())
    dependencies = {dep: {'status': results[dep]['status'],
        'fingerprint': results[dep].get('fingerprint'),
        'outputs': {k: v['artifact'] for k, v in results[dep].get('outputs', {}).items()},
        'reason': results[dep].get('reason')} for dep in stage['needs']}
    identity = {'stage': stage, 'inputs': hashes, 'code': code, 'dependencies': dependencies,
        'environment': tracked, 'executable': {'path': executable, 'sha256': digest(executable)},
        'runner_code': digest(__file__), 'io_code': digest(Path(__file__).parents[1] / 'io.py')}
    return paths, env, identity


def _gate_value(value, pointer):
    for token in pointer.split('/')[1:] if pointer else []:
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _gates(run, stage, results):
    rows = []
    for gate in stage['gates']:
        try:
            path, artifact = _output_path(run, results[gate['stage']], gate['output'])
            value = _gate_value(read(path), gate['pointer'])
            passed = type(value) is type(gate['equals']) and value == gate['equals']
            rows.append(dict(gate=gate, passed=passed, value=value, artifact=artifact))
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            rows.append(dict(gate=gate, passed=False, error=str(exc)))
    return rows


class Interrupted(KeyboardInterrupt):
    pass


@contextmanager
def _signals():
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def stop(signum, frame):
            raise Interrupted(f'Received signal {signum}')
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _stop_process(proc):
    # All stage children belong to this private process group, not the caller's.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _run(argv, cwd, env, log, timeout, on_start):
    with log.open('xb') as stream:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            on_start(proc.pid)
            status = proc.wait(timeout=timeout)
        except BaseException:
            _stop_process(proc)
            raise
        # A stage may not detach background writers and claim completion.
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return status
        _stop_process(proc)
        raise RuntimeError('Stage exited with background processes still alive; terminated its process group')


def _expand(value, tokens):
    def replace(match):
        if match[1] not in tokens:
            raise ValueError(f'Unknown placeholder: {match[0]}')
        return str(tokens[match[1]])
    return TOKEN.sub(replace, value)


def _cache_entry(run, stage, fingerprint):
    base = run / 'stages' / stage['id']
    invalid = []
    for receipt in sorted(base.glob('attempt-*/_runner/receipt.json'), reverse=True):
        try:
            old = read(receipt)
            if old.get('status') != SUCCESS or old.get('fingerprint') != fingerprint:
                continue
            if set(old.get('outputs', {})) != set(stage['outputs']):
                raise ValueError('Declared output set changed')
            for name in stage['outputs']:
                _output_path(run, old, name)
            return old, invalid
        except (ValueError, OSError, KeyError, TypeError) as exc:
            invalid.append({'receipt': str(receipt.relative_to(run)), 'reason': str(exc)})
    return None, invalid


def execute(config_path, run_dir, *, until=None):
    config, root, ordered = load_config(config_path)
    if until is not None and until not in {s['id'] for s in ordered}:
        raise ValueError(f'Unknown until stage: {until}')
    run = Path(run_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    with lock(run / '.execute.lock'), _signals():
        manifest_path = run / 'run.json'
        manifest = read(manifest_path) if manifest_path.exists() else {
            'schema_version': SCHEMA, 'id': config['id'], 'root': str(root), 'created_at': now(), 'invocations': []}
        if manifest.get('schema_version') != SCHEMA or manifest.get('id') != config['id'] or manifest.get('root') != str(root):
            raise ValueError('Run identity/root differs; select another run directory')
        revision = signature(config)
        write(run / 'configs' / f'{revision}.json', config)
        results = {}
        invocation = {'started_at': now(), 'config_sha256': revision, 'until': until, 'stages': {},
                      'host': socket.gethostname(), 'pid': os.getpid(), 'run_id': runtime.run_id()}
        manifest.setdefault('invocations', []).append(invocation)
        manifest.update(status='running', config_sha256=revision, stages=results, updated_at=now())
        def save():
            manifest['updated_at'] = now(); write(manifest_path, manifest)
        save()
        try:
            for stage in ordered:
                sid = stage['id']
                blocked = [dep for dep in stage['needs'] if results[dep]['status'] != SUCCESS]
                if blocked and stage['needs_policy'] == 'success':
                    entry = {'status': 'blocked_dependency', 'reason': f'Incomplete dependencies: {blocked}'}
                else:
                    gate_rows = _gates(run, stage, results)
                    if any(not row['passed'] for row in gate_rows):
                        entry = {'status': 'skipped_gate', 'reason': 'Pre-execution decision rejected or unavailable', 'gates': gate_rows}
                    else:
                        entry = _execute_stage(root, run, stage, results, gate_rows, save, invocation)
                results[sid] = entry
                invocation['stages'][sid] = {'status': entry['status'], 'reused': entry.get('reused', False),
                    'attempt': entry.get('attempt'), 'reason': entry.get('reason')}
                save()
                if sid == until:
                    break
        except BaseException as exc:
            manifest['status'] = 'interrupted' if isinstance(exc, (Interrupted, KeyboardInterrupt)) else 'failed'
            invocation.update(finished_at=now(), error=str(exc), status=manifest['status']); save()
            raise
        statuses = [x['status'] for x in results.values()]
        manifest['status'] = ('failed' if any(x in ('failed', 'blocked_dependency') for x in statuses)
            else 'completed_with_gate_skips' if 'skipped_gate' in statuses
            else 'staged' if until and len(results) < len(ordered) else 'completed')
        invocation.update(finished_at=now(), status=manifest['status']); save()
        return manifest


def _execute_stage(root, run, stage, results, gates, save, invocation):
    sid = stage['id']; started = time.monotonic()
    base = run / 'stages' / sid; base.mkdir(parents=True, exist_ok=True)
    numbers = [int(p.name.split('-')[1]) for p in base.glob('attempt-*') if re.fullmatch(r'attempt-[0-9]+', p.name)]
    attempt = max(numbers, default=0) + 1
    folder = base / f'attempt-{attempt:04d}'
    entry = {'status': 'running', 'attempt': attempt, 'started_at': now(), 'gates': gates}
    results[sid] = entry
    try:
        paths, env, identity = _context(root, run, stage, results)
        fingerprint = signature(identity)
        old, invalid = _cache_entry(run, stage, fingerprint)
        if old:
            old = dict(old); old.update(reused=True, reused_at=now())
            print('STAGE_REUSED', sid, flush=True)
            return old
        folder.mkdir(); meta = folder / '_runner'; meta.mkdir()
        entry.update(fingerprint=fingerprint, identity=identity, invalid_cache=invalid,
                     directory=str(folder.relative_to(run)), log=str((meta/'stage.log').relative_to(run)))
        write(meta/'params.json', stage['params'])
        write(meta/'dependencies.json', {dep: results[dep] for dep in stage['needs']})
        tokens = {'root': root, 'run_dir': run, 'python': sys.executable, 'stage_dir': folder,
                  'params_file': meta/'params.json', 'dependency_status_file': meta/'dependencies.json'}
        tokens.update({f'input:{k}': v for k, v in paths.items()})
        tokens.update({f'output:{k}': folder/v for k, v in stage['outputs'].items()})
        argv = [_expand(x, tokens) for x in stage['argv']]
        entry['argv'] = argv; write(meta/'receipt.json', entry); save()
        print('STAGE_START', sid, attempt, flush=True)
        def process_started(pid):
            entry.update(process_id=pid, process_group_id=pid, host=socket.gethostname())
            write(meta/'receipt.json', entry); save()
        code = _run(argv, root, env, meta/'stage.log', stage.get('timeout_seconds'), process_started)
        entry['exit_code'] = code
        if code:
            raise RuntimeError(f'Process exited {code}')
        # Mutation of declared inputs/code while executing never creates a valid cache.
        if _context(root, run, stage, results)[2] != identity:
            raise ValueError('Declared input/code/runtime identity changed during stage')
        outputs = {}
        for name, rel in stage['outputs'].items():
            p = folder/rel
            if not p.resolve().is_relative_to(folder):
                raise ValueError('Output escaped attempt directory')
            outputs[name] = {'path': str(p.relative_to(run)), 'artifact': _hash_artifact(p)}
        entry.update(status=SUCCESS, outputs=outputs, reused=False)
    except BaseException as exc:
        interrupted = isinstance(exc, (Interrupted, KeyboardInterrupt))
        entry.update(status='interrupted' if interrupted else 'failed', reason=f'{type(exc).__name__}: {exc}')
        if not folder.exists():
            folder.mkdir(); (folder/'_runner').mkdir()
            entry['directory'] = str(folder.relative_to(run))
        entry.setdefault('log', str((folder/'_runner/stage.log').relative_to(run)))
        with (folder/'_runner/stage.log').open('ab') as stream:
            stream.write(('\nRUNNER_FAILURE: ' + entry['reason'] + '\n').encode())
        if interrupted:
            entry.update(seconds=time.monotonic()-started, finished_at=now())
            write(folder/'_runner/receipt.json', entry); save()
            raise
    entry.update(seconds=time.monotonic()-started, finished_at=now())
    write(folder/'_runner/receipt.json', entry)
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('execute'); p.add_argument('config'); p.add_argument('--run-dir', required=True); p.add_argument('--until')
    p = sub.add_parser('plan'); p.add_argument('config')
    p = sub.add_parser('status'); p.add_argument('run_dir')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            config, root, ordered = load_config(args.config)
            print(json.dumps({'id': config['id'], 'root': str(root), 'ordered_stages': [s['id'] for s in ordered]}, indent=2))
            return 0
        if args.command == 'status':
            result = read(Path(args.run_dir)/'run.json')
        else:
            result = execute(args.config, args.run_dir, until=args.until)
        print(json.dumps({'status': result['status'], 'stages': {k: {f:v.get(f) for f in ('status','attempt','reused','reason')} for k,v in result['stages'].items()}}, indent=2))
        return 1 if result['status'] in ('failed', 'interrupted') else 0
    except (KeyboardInterrupt, Interrupted):
        return 130
    except (ValueError, OSError) as exc:
        print(f'Human runner: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
