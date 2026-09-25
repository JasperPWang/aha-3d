#!/usr/bin/env python3
"""Apply a semantic scene variant in background Blender, saving a distinct file.

blender -b --python-exit-code 1 --python tools/scene_variant.py -- \
  --source source.blend --recipe variant.json --out new.blend [--dry-run]
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--dry-run', action='store_true', help='Print validated match/provenance plan without saving or scene edits')
    args = parser.parse_args(argv)
    source, output = args.source.resolve(), args.out.resolve()
    if source == output:
        parser.error('--out must differ from --source')
    if not source.is_file() or source.suffix != '.blend' or output.suffix != '.blend':
        parser.error('--source must be an existing .blend and --out must end in .blend')
    report_path = output.with_suffix('.variant.json')
    semantic_path = output.with_suffix('.semantics.json')
    if any(path.exists() for path in (output, report_path, semantic_path)):
        parser.error('Output or sidecar already exists; choose a new output name')
    sys.path.insert(0, str(args.project_root / 'src'))
    import bpy
    from aha3d.io import digest, write
    from aha3d.blender.semantics import export_semantics
    from aha3d.blender.variants import apply_variant, plan_variant
    recipe = json.loads(args.recipe.read_text())
    input_hash = digest(source)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    if args.dry_run:
        report = plan_variant(recipe, args.project_root)
    else:
        report = apply_variant(recipe, args.project_root)
    report.update(source=str(source), source_sha256=input_hash, recipe_path=str(args.recipe.resolve()),
                  recipe_file_sha256=digest(args.recipe), output=str(output), job_id=os.environ.get('INDOOR_RUN_ID'))
    if args.dry_run:
        print(json.dumps(report, indent=2, allow_nan=False))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene['variant_provenance'] = json.dumps(report, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=True)
    report['output_sha256'] = digest(output)
    write(report_path, report)
    export_semantics(semantic_path)
    print(json.dumps({'output': str(output), 'report': str(report_path), 'semantics': str(semantic_path)}))


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else None)
