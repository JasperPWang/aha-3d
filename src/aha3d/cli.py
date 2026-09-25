"""Command line entry point; planning and submission do not load ML dependencies."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from . import runtime as host
from .config import identifier, load_recipe, load_runtime
from .io import intact, lock, now, read, write
from .pipeline.runner import execute, launch, load, prepare, stages, submit, submit_recipes


def batches(root):
    """Background batch workers: recorded pid liveness and each finished task's exit code."""
    result = []
    for p in sorted((root / 'runs/batches').glob('*/submission.json')):
        data = read(p); exits = {}
        for q in sorted(p.parent.glob('*.log.exit'), key=lambda q: int(q.name.split('.')[0]) if q.name.split('.')[0].isdigit() else -1):
            text = q.read_text().strip()
            exits[q.name.split('.')[0]] = int(text) if text.lstrip('-').isdigit() else text
        tasks = len(data.get('runs', []))
        alive = bool(data.get('pid')) and host.alive(data['pid'])
        result.append({'job_id': data.get('job_id'), 'batch': str(p.parent), 'pid': data.get('pid'), 'alive': alive,
            'status': 'unknown' if not data.get('pid') else 'running' if alive else 'failed' if any(v != 0 for v in exits.values()) else 'completed' if len(exits) == tasks else 'stopped',
            'tasks': tasks, 'exit_codes': exits, 'log': str(p.parent / 'batch.log')})
    return result


def main():
    parser = argparse.ArgumentParser(prog='indoor')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('INDOOR_PROJECT_ROOT', Path(__file__).resolve().parents[2])))
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('scenes')
    subs.add_parser('completion-hook', help=argparse.SUPPRESS)
    from .placement.runner import arguments as placement_arguments
    placement_arguments(subs.add_parser('check-placement', help='Run saved-room geometry and stability diagnostics end to end'))
    p = subs.add_parser('acceptance', add_help=False, help='Persisted reconstruction acceptance and findings')
    p.add_argument('-h','--help',dest='acceptance_help',action='store_true')
    p.add_argument('acceptance_args', nargs=argparse.REMAINDER)
    p = subs.add_parser('results', help='Scene deliveries, result gallery and incremental demo batches', add_help=False)
    p.add_argument('-h', '--help', dest='results_help', action='store_true')
    p.add_argument('result_args', nargs=argparse.REMAINDER)
    p = subs.add_parser('intake', help='Resolve scene requirements and missing questions without submitting work')
    p.add_argument('--request', type=Path); p.add_argument('--answers', type=Path)
    p.add_argument('--preset', choices=['whitebox', 'materials', 'whitebox_people', 'source_camera'])
    p.add_argument('--out', type=Path, help='New directory for request.json, intake.json and BRIEF.md')
    p = subs.add_parser('preflight', help='Unified read-only recipe/input and optional SAM bounds checks')
    p.add_argument('scene'); p.add_argument('--recipe', required=True); p.add_argument('--motion-only', action='store_true')
    p.add_argument('--sam-selection', type=Path); p.add_argument('--sam-cameras', type=Path)
    p = subs.add_parser('preview', help='Render/decode full-duration cheap preview of an assembled, verified run')
    p.add_argument('run', type=Path); p.add_argument('--backend', choices=['cpu', 'gpu'], default='gpu')
    p.add_argument('--max-width', type=int, default=320)
    p.add_argument('--preview-fps', default='5', help='Diagnostic sampling rate (default 5); use 1 for coarse inspection or source for every frame. Final timing is unchanged.')
    p.add_argument('--source-frames', type=int, nargs='+', help='Explicit zero-based source frame indices for start/middle/end keyframes when clip timing differs')
    p = subs.add_parser('review-layout', help='Record explicit agent layout review; resume with execute or submit')
    p.add_argument('run', type=Path); p.add_argument('--reviewer', required=True)
    p.add_argument('--notes', required=True); p.add_argument('--verdict', choices=['accepted', 'rejected'], required=True)
    p.add_argument('--visual-review', type=Path, required=True)
    p.add_argument('--views', nargs='+', required=True, help='Exact inspected view names, including native source views')
    p = subs.add_parser('accept-preview', help='Record agent technical review bound to current preview and frozen inputs')
    p.add_argument('run', type=Path); p.add_argument('--evidence', type=Path, required=True)
    for name in ('plan', 'prepare', 'run'):
        p = subs.add_parser(name, help={'plan': 'Read-only recipe, stage and runtime summary', 'prepare': 'Snapshot inputs into a new run',
                                        'run': 'Prepare and execute in the foreground; use batch for a background worker'}[name])
        p.add_argument('scene'); p.add_argument('--recipe', required=True)
        p.add_argument('--preview', action='store_true')
        p.add_argument('--motion-only', action='store_true', help='Generate/resample/skin without copying or opening a room')
        if name != 'plan':
            p.add_argument('--run-id'); p.add_argument('--reuse-run', type=Path)
    p = subs.add_parser('execute'); p.add_argument('run', type=Path)
    p.add_argument('--until'); p.add_argument('--frame-budget', type=int)
    p = subs.add_parser('submit', help='Execute prepared runs one after another in a detached local worker')
    p.add_argument('runs', type=Path, nargs='+'); p.add_argument('--until'); p.add_argument('--frame-budget', type=int)
    p = subs.add_parser('batch', help='Prepare and execute recipes one after another in a detached local worker')
    p.add_argument('recipes', nargs='+', help='SCENE:RECIPE pairs'); p.add_argument('--preview', action='store_true')
    p = subs.add_parser('launch', help=argparse.SUPPRESS); p.add_argument('request', type=Path)
    p = subs.add_parser('status'); p.add_argument('--scene')
    p.add_argument('--live', action='store_true', help='Also report background batch workers: pid alive and per-task exit codes')
    p = subs.add_parser('review'); p.add_argument('run', type=Path); p.add_argument('--reviewer', required=True)
    p.add_argument('--note', required=True); p.add_argument('--frames', nargs='+', type=int, required=True)
    p = subs.add_parser('promote'); p.add_argument('run', type=Path); p.add_argument('--name', default='selected')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == 'completion-hook':
            from .workflow.completion import main as hook_main
            return hook_main(root)
        if args.command == 'acceptance':
            from .workflow.acceptance_cli import main as acceptance_main
            return acceptance_main(['--help'] if args.acceptance_help else args.acceptance_args, root=root)
        if args.command == 'results':
            from .results.cli import main as results_main
            return results_main(['--help'] if args.results_help else args.result_args, root=root)
        elif args.command == 'check-placement':
            from .placement.runner import command as placement_command
            result = placement_command(args)
        elif args.command == 'intake':
            from .workflow.intake import command
            result = command(args)
        elif args.command == 'scenes':
            result = [{'scene': p.parent.name, 'recipes': sorted(q.stem for q in (p.parent / 'recipes').glob('*.json'))}
                      for p in sorted((root / 'scenes').glob('*/scene.json'))]
        elif args.command == 'preflight':
            from .workflow.submission_preflight import check
            result = check(root, args.scene, args.recipe, args.motion_only, args.sam_selection, args.sam_cameras)
        elif args.command == 'preview':
            from .workflow.preview_gate import render
            result = render(args.run, args.backend, args.max_width, args.source_frames, args.preview_fps)
        elif args.command == 'review-layout':
            from .pipeline.runner import review_layout
            result = review_layout(args.run, args.reviewer, args.notes, args.verdict, args.views, read(args.visual_review))
        elif args.command == 'accept-preview':
            from .workflow.preview_gate import accept
            result = accept(args.run, args.evidence)
        elif args.command == 'plan':
            recipe = load_recipe(root, args.scene, args.recipe)
            from .workflow.submission_preflight import check
            result = {'preflight': check(root, args.scene, args.recipe, args.motion_only), 'recipe': recipe, 'stages': stages(recipe, args.motion_only), 'runtime': load_runtime(root, recipe['runtime']),
                      'preview': args.preview, 'compute': 'local; this command is read-only'}
        elif args.command in ('prepare', 'run'):
            run = prepare(root, args.scene, args.recipe, args.run_id, args.reuse_run, args.preview, args.motion_only)
            result = execute(run) if args.command == 'run' else {'run': str(run)}
        elif args.command == 'execute':
            if args.frame_budget is not None and args.frame_budget < 1:
                raise ValueError('frame-budget must be positive')
            result = execute(args.run, args.until, args.frame_budget)
        elif args.command == 'submit':
            result = submit(args.runs, args.until, args.frame_budget)
        elif args.command == 'batch':
            pairs = [p.split(':') for p in args.recipes]
            if any(len(p) != 2 for p in pairs):
                raise ValueError('Use SCENE:RECIPE pairs')
            result = submit_recipes(root, pairs, preview=args.preview)
        elif args.command == 'launch':
            result = launch(args.request)
        elif args.command == 'status':
            if args.scene:
                identifier(args.scene)
            records = sorted((root / 'runs').glob((args.scene or '*') + '/*/run.json'))
            result = []
            for p in records:
                data = read(p)
                if data.get('results_kind'):
                    result.append({'scene': data['scene'], 'run_id': data['run_id'], 'status': data['status'],
                                   'kind': data['results_kind'], 'path': str(p.parent)})
                    continue
                if not all(k in data for k in ('scene', 'run_id', 'stages', 'visual_review')):
                    continue  # Standalone historical tool receipts have a different schema.
                result.append({'scene': data['scene'], 'run_id': data['run_id'], 'status': data['status'],
                    'stages': {s: v['status'] for s, v in data['stages'].items()}, 'visual_review': data['visual_review']['status'],
                    'jobs': [read(q)['job_id'] for q in sorted(p.parent.glob('submission-*.json'))], 'path': str(p.parent)})
            if args.live:
                result = {'runs': result, 'batches': batches(root)}
        elif args.command == 'promote':
            from .results.registry import promote
            result = promote(root,args.run,args.name)
        elif args.command == 'review':
            run = args.run.resolve()
            with lock(run / '.execute.lock'):
                data, recipe, runtime = load(run)
                if data['status'] != 'validated' or not all(v['status'] == 'completed' and intact(run / 'stages' / k, v['outputs']) for k, v in data['stages'].items()):
                    raise ValueError('Run must have intact, completed validation artifacts')
                if args.command == 'review':
                    if not args.reviewer.strip() or not args.note.strip():
                        raise ValueError('Record the reviewer and concrete observations')
                    frames = recipe['render'].get('stills', range(recipe['timing']['start'], recipe['timing']['end'] + 1))
                    if any(f not in frames for f in args.frames):
                        raise ValueError('Review frames must have been rendered')
                    data['visual_review'] = {'status': 'reviewed', 'reviewer': args.reviewer,
                        'at': now(), 'frames': args.frames, 'note': args.note}
                    write(run / 'run.json', data); result = data['visual_review']
        if isinstance(result,dict) and result.get('status') in ('validated','staged','prepared','preview_accepted'):
            result=dict(result,technical_status=result['status'],status='awaiting_review',accepted=False)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, f'indoor: {exc}\n')
