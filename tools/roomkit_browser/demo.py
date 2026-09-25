#!/usr/bin/env python3
"""One-command saved Blender scene -> validated standalone browser demo."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import shutil
import hashlib
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from aha3d import runtime  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True, help='New output directory')
    p.add_argument('--blender', default=os.environ.get('BLENDER_BIN', shutil.which('blender') or 'blender'))
    p.add_argument('--bake-indirect', action='store_true', help='Bake fixed daylight GI and a diffuse room probe with Cycles')
    p.add_argument('--tabletop', action='store_true', help='Enable tabletop physics and seeded asset swaps')
    p.add_argument('--chairs', action='store_true', help='Enable constrained native-size chair swaps')
    p.add_argument('--background', action='store_true', help='Run build and QA as a detached local process; prints its pid and log')
    p.add_argument('--serve', type=Path, help='Atomically mirror validated HTML to this explicitly requested file')
    a = p.parse_args()
    source, out = a.source.resolve(), a.out.resolve()
    if not source.is_file():
        p.error('Source file does not exist')
    if out.exists():
        p.error('Output directory already exists; choose a new run directory')
    if a.background:
        out.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(Path(__file__).resolve()), '--source', str(source), '--out', str(out), '--blender', a.blender]
        if a.bake_indirect:
            command += ['--bake-indirect']
        if a.tabletop:
            command += ['--tabletop']
        if a.chairs:
            command += ['--chairs']
        if a.serve:
            command += ['--serve', str(a.serve.resolve())]
        script = out.parent/('browser-demo-'+time.strftime('%Y%m%dT%H%M%S')+'-'+out.name+'.sh')
        script.write_text('#!/bin/bash\nset -euo pipefail\ncd '+shlex.quote(str(ROOT))+'\nsource kimodo_blender/env.sh\n'+' '.join(shlex.quote(x) for x in command)+'\n')
        log = script.with_suffix('.log')
        pid = runtime.start_background(script, log, env={**os.environ, 'INDOOR_RUN_ID': runtime.run_id()})
        print(json.dumps({'pid':pid,'log':str(log),'output':str(out),'status':'started, not validated'}));return
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    if (HERE/'node_modules/.browsers').is_dir():
        env.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(HERE/'node_modules/.browsers'))
    snapshot = out/'source_snapshot'
    snapshot.mkdir()
    source_files = sorted(path for path in HERE.iterdir() if path.is_file() and path.suffix in ('.py', '.js', '.mjs', '.html', '.json'))
    source_hashes = {}
    for path in source_files:
        content = path.read_bytes()
        (snapshot/path.name).write_bytes(content)
        source_hashes[path.name] = hashlib.sha256(content).hexdigest()
    def git(*args):
        result = subprocess.run(['git', *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        return result.stdout.strip() if result.returncode == 0 else None
    report = {'source':str(source),'output':str(out),'status':'running','job':runtime.run_id(),
              'git': {'commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
                      'dirty': bool(git('status', '--porcelain', '--untracked-files=no'))},
              'source_snapshot_sha256': source_hashes, 'tabletop': a.tabletop, 'chairs': a.chairs, 'bake_indirect': a.bake_indirect}
    def save():
        (out/'run.json').write_text(json.dumps(report,indent=2))
    save()
    try:
        with (out/'pipeline.log').open('w') as log:
            for cmd in ([a.blender,'--background','--factory-startup','--python-exit-code','1','--python',str(HERE/'export_scene.py'),'--','--source',str(source),'--out',str(out/'scene.json'),'--auto'] + (['--tabletop'] if a.tabletop else []) + (['--chairs'] if a.chairs else []) + (['--bake-indirect'] if a.bake_indirect else []),
                        ['node',str(HERE/'build.mjs'),str(out/'scene.json'),str(out/'demo.html')],
                        ['node',str(HERE/'qa-lighting.mjs'),str(out/'demo.html'),str(out)],
                        ['node',str(HERE/'qa-generic.mjs'),str(out/'demo.html'),str(out)],
                        ['node',str(HERE/'qa-scene-graph.mjs'),str(out/'demo.html'),str(out)],
                        ['node',str(HERE/'qa-streaming.mjs'),str(out/'demo-fast.html'),str(out)]):
                subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
        if a.tabletop:
            with (out/'pipeline.log').open('a') as log:
                subprocess.run(['node', str(HERE/'qa-tabletop.mjs'), str(out/'demo.html'), str(out)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        if a.chairs:
            with (out/'pipeline.log').open('a') as log:
                subprocess.run(['node', str(HERE/'qa-chairs.mjs'), str(out/'demo.html'), str(out)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        if a.chairs:
            chair_check = json.loads((out/'chair-validation.json').read_text())
            if chair_check.get('alternativeToSourceAssetExercised'):
                with (out/'pipeline.log').open('a') as log:
                    subprocess.run(['node', str(HERE/'qa-chair-interaction.mjs'), str(out/'demo.html'), str(out)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        # Persist discovery separately so callers need not read geometry payloads.
        payload=json.loads((out/'scene.json').read_text())
        (out/'discovery.json').write_text(json.dumps(payload.get('discovery',{}),indent=2))
        if any(hashlib.sha256((HERE/name).read_bytes()).hexdigest() != digest for name, digest in source_hashes.items()):
            raise RuntimeError('Browser tool sources changed during conversion; rerun from stable sources')
        report.update(status='validated',objects=len(payload['objects']),joints=len(payload['joints']),actors=len((payload.get('animation') or {}).get('actors',[])),source_sha256=payload['source_sha256'])
        if a.serve:
            import tempfile
            target=a.serve.resolve()
            if not target.parent.is_dir():
                raise ValueError('Serve destination directory does not exist')
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.demo-',delete=False) as tmp:
                temporary=Path(tmp.name)
                with (out/'demo.html').open('rb') as src:
                    shutil.copyfileobj(src,tmp)
            temporary.replace(target);report['served_file']=str(target)
        save();print(json.dumps(report))
    except Exception as error:
        report.update(status='failed',error=str(error));save();raise


if __name__=='__main__':
    main()
