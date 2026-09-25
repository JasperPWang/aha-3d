#!/usr/bin/env python3
"""Coordinate writers; use acceptance validation for reconstruction completion.

Registry-only operations need just Python's standard library.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.paths import migrated_path


STATES = {'active', 'completed', 'handoff', 'blocked', 'cancelled'}
KINDS = ('reconstruction', 'preparation', 'code', 'documentation')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identifier(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}', value):
        raise ValueError('Task IDs must use lowercase letters, digits, underscores or hyphens.')
    return value


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.task-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def registry_lock(root, timeout=5.0):
    folder = root / 'tasks'
    folder.mkdir(exist_ok=True)
    if folder.is_symlink():
        raise ValueError('The tasks registry must be a real directory in the project.')
    lock = folder / '.registry.lock'
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError('Registry is locked: {}. Inspect owner.json; do not expire it automatically.'.format(lock))
            time.sleep(0.05)
    try:
        atomic_json(lock / 'owner.json', dict(host=socket.gethostname(), pid=os.getpid(), created_at=now()))
        yield
    finally:
        if (lock / 'owner.json').exists():
            (lock / 'owner.json').unlink()
        lock.rmdir()


def scope(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = migrated_path(root, path.resolve()).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        raise ValueError('Writable paths must stay inside the project: ' + value)
    if relative in ('.', 'tasks') or relative.startswith('tasks/.'):
        raise ValueError('Claim specific files/directories, not the project or registry root.')
    if any(char in relative for char in '*?[]'):
        raise ValueError('Writable paths are literal paths, not glob patterns.')
    return relative


def overlaps(left, right):
    return left == right or left.startswith(right + '/') or right.startswith(left + '/')


def records(root):
    result = {}
    for folder in sorted((root / 'tasks').iterdir()):
        if folder.name.startswith('.') or not folder.is_dir():
            continue
        identifier(folder.name)
        if folder.is_symlink():
            raise ValueError('Task directories must not be symlinks: ' + str(folder))
        path = folder / 'task.json'
        if not path.is_file():
            raise ValueError('Incomplete task record: {}. Inspect before recovery.'.format(folder))
        data = json.loads(path.read_text(encoding='utf-8'))
        if (data.get('schema_version') != 1 or data.get('task_id') != folder.name
                or data.get('status') not in STATES or not data.get('owner')
                or not isinstance(data.get('paths'), list) or not data['paths']):
            raise ValueError('Invalid task record: ' + str(path))
        data['paths'] = [scope(root, p) for p in data['paths']]
        result[folder.name] = data
    return result


def check_conflicts(all_tasks, task_id, paths):
    for other_id, other in all_tasks.items():
        if other_id == task_id or other['status'] != 'active':
            continue
        for requested in paths:
            for held in other['paths']:
                if overlaps(requested, held):
                    raise ValueError('{} overlaps {} held by {} ({})'.format(requested, held, other_id, other['owner']))


def event(data, owner, action, message, job_ids=None):
    data['updated_at'] = now()
    data.setdefault('history', []).append(dict(at=data['updated_at'], owner=owner,
        action=action, message=message, job_ids=job_ids or []))


def execute(args):
    root = args.root.resolve()
    validated_claim = None
    if args.command == 'release' and args.status == 'completed':
        # Full scene validation can hash large artifacts. Never hold the global
        # writer registry lock during it; compare the claim again before release.
        with registry_lock(root):
            data = records(root).get(identifier(args.task))
            if not data or data['status'] != 'active' or data['owner'] != args.owner:
                raise ValueError('Only the recorded owner of an active task can update or release it.')
        if data.get('kind', 'reconstruction' if data.get('scene') else 'code') == 'reconstruction':
            from aha3d.workflow.completion import require_completed_claim
            require_completed_claim(root, data['scene'], data.get('acceptance_task', data['task_id']))
            validated_claim = data
    with registry_lock(root):
        all_tasks = records(root)
        if args.command == 'list':
            listed = [v for v in all_tasks.values() if args.all or v['status'] == 'active']
            if args.compact:
                return [dict(task_id=v['task_id'], owner=v['owner'], status=v['status'],
                             scene=v.get('scene'), path_count=len(v['paths']),
                             kind=v.get('kind', 'reconstruction' if v.get('scene') else 'code'),
                             acceptance_task=v.get('acceptance_task'),
                             paths=[p for p in v['paths'] if '__pycache__' not in Path(p).parts])
                        for v in listed]
            return listed
        task_id = identifier(args.task)
        if args.command == 'show':
            if task_id not in all_tasks:
                raise ValueError('Unknown task: ' + task_id)
            return all_tasks[task_id]
        if not args.owner.strip():
            raise ValueError('Use a nonempty, session-specific owner ID.')
        if not (args.title if args.command == 'claim' else args.note).strip():
            raise ValueError('Supply a nonempty title or checkpoint/release note.')
        if args.command == 'claim':
            if task_id in all_tasks or (root / 'tasks' / task_id).exists():
                raise ValueError('Task already exists. Use resume for a handoff/blocked task, or a new ID.')
            paths = sorted(set([scope(root, p) for p in args.paths] + ['tasks/' + task_id]))
            for dependency in args.depends_on:
                if dependency not in all_tasks or all_tasks[dependency]['status'] != 'completed':
                    raise ValueError('Dependency is not completed: ' + dependency)
            check_conflicts(all_tasks, task_id, paths)
            kind = args.kind or ('reconstruction' if args.scene else 'code')
            if kind == 'reconstruction' and not args.scene:
                raise ValueError('Reconstruction claims require --scene SCENE.')
            if args.scene:
                identifier(args.scene)
            if args.acceptance_task and kind != 'reconstruction':
                raise ValueError('--acceptance-task applies only to reconstruction claims.')
            data = dict(schema_version=1, task_id=task_id, title=args.title,
                scene=args.scene, owner=args.owner, status='active', paths=paths,
                kind=kind, depends_on=args.depends_on, created_at=now(), history=[])
            if kind == 'reconstruction':
                data['acceptance_task'] = identifier(args.acceptance_task or task_id)
            event(data, args.owner, 'claim', args.title)
            folder = root / 'tasks' / task_id
            folder.mkdir()
            template = root / 'docs' / 'templates' / 'HANDOFF.md'
            handoff = template.read_text(encoding='utf-8') if template.exists() else (
                '# Task handoff\n\nObjective:\n\nInputs and versions:\n\n'
                'Changes:\n\nEvidence:\n\nRunning jobs and logs:\n\nIssues:\n\nNext action:\n')
            (folder / 'HANDOFF.md').write_text(handoff, encoding='utf-8')
        else:
            if task_id not in all_tasks:
                raise ValueError('Unknown task: ' + task_id)
            data = all_tasks[task_id]
            if args.command == 'resume':
                if data['status'] not in ('handoff', 'blocked'):
                    raise ValueError('Only a released handoff/blocked task can be resumed.')
                check_conflicts(all_tasks, task_id, data['paths'])
                data['owner'], data['status'] = args.owner, 'active'
                event(data, args.owner, 'resume', args.note)
            else:
                if data['status'] != 'active' or data['owner'] != args.owner:
                    raise ValueError('Only the recorded owner of an active task can update or release it.')
                if args.command == 'release':
                    if validated_claim is not None and data != validated_claim:
                        raise ValueError('Claim changed during validation; inspect the current owner/state before retrying.')
                    data['status'] = args.status
                event(data, args.owner, args.command, args.note, getattr(args, 'job_id', []))
        atomic_json(root / 'tasks' / task_id / 'task.json', data)
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest='command')
    listing = commands.add_parser('list', help='List active claims; use --all for history.')
    listing.add_argument('--all', action='store_true')
    listing.add_argument('--compact', action='store_true', help='Omit history and bytecode-cache paths.')
    showing = commands.add_parser('show')
    showing.add_argument('task')
    for name in ('claim', 'checkpoint', 'release', 'resume'):
        cmd = commands.add_parser(name)
        cmd.add_argument('task')
        cmd.add_argument('--owner', required=True)
        if name == 'claim':
            cmd.add_argument('--title', required=True)
            cmd.add_argument('--paths', nargs='+', required=True)
            cmd.add_argument('--scene')
            cmd.add_argument('--kind', choices=KINDS,
                             help='Defaults to reconstruction with --scene, otherwise code. Preparation is an upstream stage, not scene delivery.')
            cmd.add_argument('--acceptance-task', help='Existing acceptance task to resume; defaults to this claim ID.')
            cmd.add_argument('--depends-on', nargs='*', default=[])
        else:
            cmd.add_argument('--note', required=True)
        if name == 'checkpoint':
            cmd.add_argument('--job-id', action='append', default=[])
        if name == 'release':
            cmd.add_argument('--status', choices=sorted(STATES - {'active'}), required=True)
    args = parser.parse_args()
    if args.command is None:
        parser.error('Choose a command.')
    try:
        print(json.dumps(execute(args), indent=2))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('task_claim: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
