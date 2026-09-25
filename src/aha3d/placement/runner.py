"""One-command run creation, local execution, source integrity and report receipt."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .. import runtime
from ..io import digest, read, write, now
from ..results.batch import new_run, release
from .config import normalize


def arguments(parser):
    parser.add_argument('source',type=Path,help='Explicit saved authored .blend')
    parser.add_argument('--scene',help='Inferred for inputs under scenes/SCENE or runs/SCENE')
    parser.add_argument('--out',type=Path,help='Explicit new output directory already covered by your task claim')
    parser.add_argument('--config',type=Path,help='Optional placement thresholds and exact object overrides')
    parser.add_argument('--physics',choices=['auto','off'])
    parser.add_argument('--frame',type=int,help='Default: saved current frame')
    parser.add_argument('--blender',default=os.environ.get('BLENDER_BIN','blender'))
    parser.add_argument('--owner',default='placement-'+os.environ.get('USER','agent'))
    parser.add_argument('--cpus',type=int,help='Blender threads (default: INDOOR_THREADS or all cores)')


def infer_scene(root, source):
    for parent in ('scenes','runs'):
        try:
            parts=source.relative_to(root/parent).parts
        except ValueError: continue
        if len(parts)>1 and parts[0]!='_tools': return parts[0]
    raise ValueError('Cannot infer scene. Supply --scene SCENE, or a claimed --out directory for cross-scene checks.')


def command(args):
    root=args.root.resolve(); source=args.source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower()!='.blend': raise ValueError('source must be an existing saved .blend')
    cpus=runtime.threads() if args.cpus is None else args.cpus
    if cpus<1: raise ValueError('cpus must be positive')
    blender=shutil.which(args.blender) or str(Path(args.blender).expanduser().resolve())
    if not Path(blender).is_file(): raise ValueError('Blender not found; source kimodo_blender/env.sh or pass --blender')
    config=normalize(read(args.config) if args.config else {})
    if args.physics: config['physics']=args.physics
    if args.frame is not None: config['frame']=args.frame
    owned=None
    if args.out:
        out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
        (out/'logs').mkdir(); (out/'snapshot').mkdir()
    else:
        owned=new_run(root,args.scene or infer_scene(root,source),'placement-check',args.owner)
        out=root/owned['path']
    request=dict(root=str(root),source=str(source),out=str(out),blender=blender,cpus=cpus,config=config,
                 task=owned['task'] if owned else None,owner=args.owner)
    write(out/'request.json',request)
    write(out/'status.json',dict(status='starting',created_at=now(),source=str(source)))
    print(json.dumps(dict(status='starting',run=str(out),report=str(out/'placement/report.html'),log=str(out/'logs/placement.log'))),flush=True)
    cmd=[sys.executable,'-m','aha3d.placement.runner','--execute',str(out/'request.json')]
    try:
        env=dict(os.environ,PYTHONPATH=str(root/'src')+os.pathsep+os.environ.get('PYTHONPATH',''))
        result=subprocess.run(cmd,cwd=root,env=env,check=False)
        status=read(out/'status.json')
        if result.returncode or status.get('status') not in ('completed',):
            if status.get('status')!='failed':
                write(out/'status.json',dict(status='failed',error='Worker exited without a complete report',returncode=result.returncode))
            raise RuntimeError('Placement check failed; see '+str(out/'logs/placement.log')+' and '+str(out/'status.json'))
        return dict(status='completed',run=str(out),summary=status['summary'],report=str(out/'placement/report.html'),source_unchanged=status['source_unchanged'])
    finally:
        # The foreground worker has returned: no writer remains. Report worker failures too.
        if owned:
            success=read(out/'status.json').get('status')=='completed'
            release(root,owned['task'],args.owner,'completed' if success else 'handoff',
                    'Placement worker stopped; see status.json and logs/placement.log. Diagnostic completion is not scene acceptance.')


def execute(request_path):
    req=read(request_path); out=Path(req['out']); root=Path(req['root']); source=Path(req['source'])
    write(out/'status.json',dict(status='running',job_id=runtime.run_id(),started_at=now()))
    try:
        before=digest(source)
        package=root/'src/aha3d'
        snapshot=out/'snapshot/src/aha3d'
        shutil.copytree(package,snapshot,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        code={str(p.relative_to(snapshot)):digest(p) for p in snapshot.rglob('*.py')}
        original={str(p.relative_to(package)):digest(p) for p in package.rglob('*.py')}
        if code!=original: raise ValueError('Code changed while snapshotting')
        write(out/'config.json',req['config'])
        env=dict(os.environ,PYTHONPATH=str(out/'snapshot/src'))
        cmd=[req['blender'],'-b',str(source),'-t',str(req['cpus']),'--disable-autoexec','--python-exit-code','1',
             '--python',str(snapshot/'blender/placement_check.py'),'--','--config',str(out/'config.json'),'--out',str(out/'placement')]
        with (out/'logs/placement.log').open('w') as log:
            subprocess.run(cmd,env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
        after=digest(source)
        if before!=after: raise ValueError('Source changed during check; evidence is stale')
        report=read(out/'placement/report.json')
        receipt=dict(status='completed',job_id=runtime.run_id(),finished_at=now(),source=str(source),source_sha256=before,
                     source_unchanged=True,code_sha256=code,config=req['config'],summary=report['summary'],
                     artifacts={str(p.relative_to(out)):digest(p) for p in (out/'placement').iterdir() if p.is_file()})
        write(out/'status.json',receipt)
        if (out/'run.json').is_file():
            data=read(out/'run.json'); data.update(status='diagnosed',artifacts=list(receipt['artifacts'])); write(out/'run.json',data)
        print(json.dumps(dict(status='completed',summary=report['summary'],report=str(out/'placement/report.html'))),flush=True)
        return 0
    except Exception as exc:
        write(out/'status.json',dict(status='failed',job_id=runtime.run_id(),error=str(exc),finished_at=now()))
        traceback.print_exc(); return 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--execute',type=Path,required=True)
    sys.exit(execute(parser.parse_args().execute))
