"""Inspect all registered library payloads in background Blender, without saving."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / 'assets/registry.json').read_text())['assets']
    report = {'blender': bpy.app.version_string, 'libraries': [], 'visual_review': 'not performed'}
    for name, entry in registry.items():
        library = root / entry['path']
        with library.open('rb') as handle:
            assert hashlib.file_digest(handle, 'sha256').hexdigest() == entry['sha256'], name
        metadata = json.loads((root / entry['metadata']).read_text())
        bpy.ops.wm.read_factory_settings(use_empty=True)
        names = [item['name'] for item in metadata['furniture']]
        materials = [item['name'] for item in metadata['materials']]
        with bpy.data.libraries.load(str(library), link=False) as (available, loaded):
            assert set(names) <= set(available.collections), name
            assert set(materials) <= set(available.materials), name
            loaded.collections = names
            loaded.materials = materials
        collections = []
        for collection in loaded.collections:
            assert collection is not None, name
            bpy.context.scene.collection.children.link(collection)
            bpy.context.view_layer.update()
            points = [obj.matrix_world @ Vector(corner) for obj in collection.all_objects
                      if obj.type == 'MESH' for corner in obj.bound_box]
            assert points, collection.name
            low = [min(v[i] for v in points) for i in range(3)]
            high = [max(v[i] for v in points) for i in range(3)]
            collections.append({'name': collection.name, 'objects': len(collection.all_objects),
                                'bounds_min': low, 'bounds_max': high})
        assert all(item is not None for item in loaded.materials), name
        linked = [block.name for group in (bpy.data.objects, bpy.data.meshes,
                  bpy.data.collections, bpy.data.materials, bpy.data.images, bpy.data.node_groups)
                  for block in group if block.library]
        external_images = [im.name for im in bpy.data.images if im.source == 'FILE' and not im.packed_file]
        assert not linked, (name, linked)
        assert not external_images, (name, external_images)
        report['libraries'].append({'id': name, 'sha256': entry['sha256'],
                                    'collections': collections, 'registered_materials': len(materials),
                                    'linked_dependencies': linked, 'unpacked_images': external_images})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'libraries': len(report['libraries']), 'report': str(args.out)}))


if __name__ == '__main__':
    main()
