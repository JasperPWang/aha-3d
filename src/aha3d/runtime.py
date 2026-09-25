"""Single-machine execution context: run identity, threads, GPU choice and background workers.

Every stage runs directly on the local workstation (one NVIDIA GPU by default).
There is no scheduler: long work is started as a detached local process whose
log, pid and exit status are written next to its outputs.
"""
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time

NO_DEVICE = ('', '-1', 'none', 'void', 'NoDevFiles')


def run_id():
    """Identity of this invocation, inherited by child processes for provenance and locks."""
    value = os.environ.get('INDOOR_RUN_ID')
    if not value:
        value = f"local-{socket.gethostname()}-{os.getpid()}-{time.strftime('%Y%m%dT%H%M%S')}"
        os.environ['INDOOR_RUN_ID'] = value
    return value


def threads(runtime=None):
    """CPU threads for Blender and numeric work: INDOOR_THREADS, then the runtime profile, then all cores."""
    value = os.environ.get('INDOOR_THREADS') or (runtime or {}).get('threads') or os.cpu_count() or 4
    value = int(value)
    if value < 1:
        raise ValueError('Thread count must be positive')
    return value


def gpu_visible(environ=None):
    """False only when CUDA devices were explicitly hidden; Torch/Blender still check usability."""
    env = os.environ if environ is None else environ
    return 'CUDA_VISIBLE_DEVICES' not in env or env['CUDA_VISIBLE_DEVICES'].strip() not in NO_DEVICE


def require_gpu(operation, environ=None):
    if not gpu_visible(environ):
        raise ValueError(f'{operation} needs a GPU, but CUDA_VISIBLE_DEVICES hides all devices; '
                         'unset it or use the CPU backend where one exists')


def start_background(script, log, env=None):
    """Start a bash script detached from this terminal; return its pid.

    The script keeps running after the caller exits. Its combined output goes to
    ``log``. Callers record the pid and inspect status files, logs and exit codes.
    """
    script, log = Path(script), Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'ab') as out, open(os.devnull, 'rb') as devnull:
        process = subprocess.Popen(['bash', str(script)], stdin=devnull, stdout=out, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True)
    return process.pid


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def sequential_script(lines_per_task, logs, env_script=None, preamble=()):
    """Bash that runs tasks one after another, continuing past failures and recording each exit code.

    ``lines_per_task`` holds one shell command per task; ``logs`` the per-task log paths.
    Writes ``<log>.exit`` beside each log and exits nonzero if any task failed.
    """
    lines = ['#!/usr/bin/env bash', 'set -uo pipefail', 'exec </dev/null']
    if env_script:
        lines.append('source ' + shlex.quote(str(env_script)))
    lines += list(preamble)
    lines.append('failed=0')
    for command, log in zip(lines_per_task, logs):
        log = shlex.quote(str(log))
        lines += [f'( {command} ) >{log} 2>&1', 'code=$?', f'echo "$code" >{log}.exit',
                  '[ "$code" -eq 0 ] || failed=1']
    lines.append('exit "$failed"')
    return '\n'.join(lines) + '\n'
