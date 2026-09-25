"""Standard-library entry point for scene result management."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from ..io import read, write
from . import batch, gallery, registry


def main(argv=None, root=None):
    p = argparse.ArgumentParser(prog='indoor results')
    p.add_argument('--root', type=Path, default=root or Path(__file__).resolve().parents[3])
    subs = p.add_subparsers(dest='command', required=True)
    q = subs.add_parser('inventory', help='Discover scenes and candidates; never infer final selection')
    q.add_argument('--out', type=Path); q.add_argument('--verify', action='store_true')
    q = subs.add_parser('build', help='Build the local gallery and JSON index')
    q.add_argument('--verify', action='store_true'); q.add_argument('--posters', action='store_true')
    q.add_argument('--no-sha', action='store_true', help='Build from recorded metadata without SHA-256 checks')
    q.add_argument('--web-previews', action='store_true', help='Create validated 640px WebM copies for browsers without H.264')
    q = subs.add_parser('check'); q.add_argument('--verify', action='store_true')
    q = subs.add_parser('register'); q.add_argument('manifest', type=Path)
    q = subs.add_parser('select'); q.add_argument('scene'); q.add_argument('version')
    q = subs.add_parser('select-correction'); q.add_argument('scene'); q.add_argument('correction_id')
    q = subs.add_parser('new-run'); q.add_argument('scene'); q.add_argument('--purpose', required=True); q.add_argument('--owner', required=True)
    q = subs.add_parser('demo-plan'); q.add_argument('--scene', action='append'); q.add_argument('--out', type=Path, required=True)
    q.add_argument('--blender', default=os.environ.get('BLENDER_BIN', 'blender')); q.add_argument('--tabletop', action='store_true'); q.add_argument('--chairs', action='store_true')
    q.add_argument('--retry', type=Path, help='Previous batch.json; retry failed/interrupted/unfinished rows into new outputs')
    q = subs.add_parser('demo-batch'); q.add_argument('plan', type=Path); q.add_argument('--owner', required=True)
    q.add_argument('--concurrency', type=int, default=1, help='Parallel browser exports inside the batch (1-8)')
    q.add_argument('--submit', action='store_true', help='Start demo-execute as a detached local worker')
    q = subs.add_parser('demo-execute'); q.add_argument('batch', type=Path)
    q = subs.add_parser('serve'); q.add_argument('--host', default='127.0.0.1'); q.add_argument('--port', type=int, default=8767)
    args = p.parse_args(argv); root = args.root.resolve()
    try:
        if args.command == 'inventory':
            result = registry.build_index(root, args.verify)
            if args.out:
                write(args.out, result); result = dict(path=str(args.out), counts=result['counts'])
        elif args.command == 'build':
            result = gallery.build(root, args.verify, args.posters, args.web_previews, hash_free=args.no_sha)
        elif args.command == 'check':
            result = gallery.check(root, args.verify)
        elif args.command == 'register':
            result = registry.register(root, read(args.manifest))
        elif args.command == 'select':
            result = registry.select(root, args.scene, args.version)
        elif args.command == 'select-correction':
            result = registry.select_correction(root, args.scene, args.correction_id)
        elif args.command == 'new-run':
            result = batch.new_run(root, args.scene, args.purpose, args.owner)
        elif args.command == 'demo-plan':
            if args.out.exists():
                raise ValueError('Plan output already exists; choose a new path')
            result = batch.plan(root, args.scene, args.blender, args.tabletop, args.retry, chairs=args.chairs)
            write(args.out, result)
            result = dict(path=str(args.out), counts=result['counts'], rows=result['rows'])
        elif args.command == 'demo-batch':
            folder = batch.create_batch(root, read(args.plan), args.owner, args.concurrency)
            result = batch.submit(root, folder) if args.submit else dict(status='prepared', batch=str(folder), next='demo-execute ' + str(folder))
        elif args.command == 'demo-execute':
            result = batch.execute(root, args.batch)
        else:
            gallery.serve(root, args.host, args.port); return 0
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get('status') in ('needs_attention', 'partial_failure') else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        p.exit(2, 'results: ' + str(exc) + '\n')
