#!/usr/bin/env python3
"""Blender CLI: source.blend --python this_file -- --root NAME --out NEW_DIR."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.blender.articulated import export_articulated

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', required=True, help='Placement root and all its descendants')
parser.add_argument('--out', required=True, help='New immutable version directory')
parser.add_argument('--name', help='Collection asset name')
parser.add_argument('--orientation', type=Path, help='JSON with authored/reviewed local front/up evidence; otherwise use root metadata')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
orientation = json.loads(args.orientation.read_text()) if args.orientation else None
manifest = export_articulated(args.root, args.out, asset_name=args.name, orientation=orientation)
print(json.dumps({'output': str(Path(args.out).resolve()), 'library': manifest['library'],
                  'sha256': manifest['library_sha256'], 'furniture': manifest['furniture'][0]['name']}))
