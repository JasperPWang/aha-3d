#!/usr/bin/env python3
"""Write a machine-local workstation runtime profile without loading models or starting work."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def executable(value):
    result = shutil.which(value)
    if result is None:
        candidate = Path(value).expanduser().resolve()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise ValueError('Executable not found: ' + value)
        result = str(candidate)
    return str(Path(result).resolve())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--blender', required=True)
    p.add_argument('--skin-blender', required=True)
    p.add_argument('--kimodo', required=True, type=Path)
    p.add_argument('--checkpoint', required=True, type=Path)
    p.add_argument('--threads', type=int, help='CPU threads for Blender and numeric work (default: all cores)')
    p.add_argument('--gpu', type=int, default=0, help='CUDA device index (default 0)')
    p.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'configs/runtimes/local.json')
    a = p.parse_args()
    upstream, checkpoint = a.kimodo.expanduser().resolve(), a.checkpoint.expanduser().resolve()
    if not (upstream / 'kimodo/__init__.py').is_file() or not checkpoint.is_dir():
        p.error('Provide an installed Kimodo checkout and authorized checkpoint directory')
    if a.threads is not None and a.threads < 1 or a.gpu < 0:
        p.error('--threads must be positive and --gpu nonnegative')
    value = {'schema_version': 2, 'python': executable(a.python), 'blender': executable(a.blender),
             'skin_blender': executable(a.skin_blender), 'env_script': 'kimodo_blender/env.sh',
             'upstream': str(upstream), 'checkpoint': str(checkpoint), 'threads': a.threads, 'gpu': a.gpu}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.exists():
        old = json.loads(a.out.read_text())
        # Placeholder templates and unsupported-schema profiles may be replaced.
        if '${' not in json.dumps(old) and old.get('schema_version') == 2:
            p.error('Refusing to replace a configured profile; choose a new --out')
    a.out.write_text(json.dumps(value, indent=2) + '\n')
    print(a.out)


if __name__ == '__main__':
    main()
