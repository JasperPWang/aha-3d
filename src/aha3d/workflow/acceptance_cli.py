"""Explicit persisted scope, evidence, findings and runtime lifecycle commands."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from aha3d.io import read, write
from . import acceptance as policy


def main(argv=None, root=None):
    parser=argparse.ArgumentParser(prog='indoor acceptance')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init'); p.add_argument('spec',type=Path); p.add_argument('--session',default=os.environ.get('CODEX_THREAD_ID'))
    p=sub.add_parser('review-images'); p.add_argument('request',type=Path); p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('layout-request'); p.add_argument('spec',type=Path); p.add_argument('evidence_dir',type=Path); p.add_argument('--out',type=Path,required=True)
    for name in ('candidate','record-check','finding','resolve','check','bind','state'):
        p=sub.add_parser(name);p.add_argument('scene');p.add_argument('task')
        if name in ('candidate','finding','resolve'): p.add_argument('spec',type=Path)
        if name=='resolve':p.add_argument('--id',required=True)
        if name=='record-check':
            p.add_argument('revision');p.add_argument('name');p.add_argument('report',type=Path)
        if name=='check':
            p.add_argument('--revision');p.add_argument('--stage',choices=['people','preview','render','complete'],default='complete')
        if name=='bind':p.add_argument('session')
        if name=='state':
            p.add_argument('status',choices=['active','submitted','running','paused','cancelled','incomplete','failed'])
            p.add_argument('--reason',required=True);p.add_argument('--job-id');p.add_argument('--repair-budget',type=int)
    args=parser.parse_args(argv);root=Path(root).resolve()
    try:
        if args.command=='init':
            spec=read(args.spec); result=policy.init(root,spec)
            if args.session:
                from .completion import bind
                bind(root,spec['scene'],spec['task'],args.session)
        elif args.command=='review-images':
            from .review_contract import run_reviewer
            result=run_reviewer(read(args.request),args.out)
        elif args.command=='layout-request':
            from .layout_gate import review_request
            if args.out.exists():raise ValueError('Request output already exists')
            result=review_request(read(args.spec),args.evidence_dir);write(args.out,result)
        elif args.command=='candidate': result=policy.register_candidate(root,args.scene,args.task,read(args.spec))
        elif args.command=='record-check':result=policy.record_check(root,args.scene,args.task,args.revision,args.name,args.report)
        elif args.command=='finding':result=policy.add_finding(root,args.scene,args.task,read(args.spec))
        elif args.command=='resolve':result=policy.resolve_finding(root,args.scene,args.task,args.id,read(args.spec))
        elif args.command=='bind':
            from .completion import bind
            result=bind(root,args.scene,args.task,args.session)
        else:
            with policy.transaction(root,args.scene,args.task) as out:
                scope,state=policy.load_scope(out)
                if args.command=='state':
                    if not args.reason.strip(): raise ValueError('Concrete lifecycle reason required')
                    if args.repair_budget is not None:
                        if args.status!='active' or not 0<=args.repair_budget<=20:raise ValueError('An explicit resume may set a bounded repair budget from 0 to 20')
                        state.update(repair_attempts=0,repair_budget=args.repair_budget)
                    state.update(status='awaiting_review' if args.status=='active' else args.status,reason=args.reason)
                    if args.job_id:
                        jobs=[j for j in state['jobs'] if j['id']!=args.job_id]
                        jobs.append(dict(id=args.job_id,status=args.status));state['jobs']=jobs
                    write(out/'state.json',state);result=dict(state,accepted=False)
                else:
                    result=policy.evaluate(root,args.scene,args.task,args.revision,stage=args.stage)
                    if args.stage=='complete':
                        from .completion import cache_result
                        cache_result(out,result)
        print(json.dumps(result,indent=2))
        return 0 if args.command!='check' or result.get('permitted') or result['status']=='not_applicable' else 2
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        if args.command=='check':
            result=dict(policy=policy.POLICY,status='blocked',task=args.task,scene=args.scene,candidate_revision=args.revision,
                        required_checks=[],blockers=[dict(code='STATE_INVALID',detail=str(exc))],evidence=[],
                        next_steps=['Initialize task scope or inspect the active writer; run the full check'],
                        permitted=False,completion_permitted=False,publication_permitted=False)
            print(json.dumps(result,indent=2));return 2
        parser.exit(2,'acceptance: '+str(exc)+'\n')
