#!/usr/bin/env python3
"""Stage selected reviewed collections, then publish current library payloads.

``stage`` runs inside background Blender. ``publish`` runs in
ordinary Python after independent review of the staged report. Stable library
IDs and paths are retained; no second historical library is registered.
"""
import argparse
from collections import defaultdict
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    os.replace(temp, path)


def material_signature(material):
    """Name-independent shader/texture signature for conservative scene refresh."""
    if material is None:
        return None
    def value(v):
        if isinstance(v,(str,bool,int,float)) or v is None:return v
        try:return list(v)
        except TypeError:return str(v)
    def tree(tree, seen):
        if tree is None:return None
        if tree.as_pointer() in seen:raise ValueError('Recursive material node group')
        seen=seen|{tree.as_pointer()}
        nodes=[]
        for node in tree.nodes:
            item={'name':node.name,'type':node.bl_idname,
                  'inputs':[(s.identifier,value(s.default_value)) for s in node.inputs if hasattr(s,'default_value')]}
            for field in ('operation','blend_type','data_type','interpolation','extension','projection',
                          'noise_dimensions','normalize','vector_type','invert','distribution','subsurface_method'):
                if hasattr(node,field):item[field]=value(getattr(node,field))
            if hasattr(node,'color_ramp'):
                item['ramp']=[(e.position,list(e.color)) for e in node.color_ramp.elements]
                item['ramp_interpolation']=node.color_ramp.interpolation
            if node.type=='GROUP':item['group']=tree_fn(node.node_tree,seen)
            if getattr(node,'image',None):
                im=node.image
                item['image']=hashlib.sha256(bytes(im.packed_file.data)).hexdigest() if im.packed_file else im.filepath
            nodes.append(item)
        return {'nodes':nodes,'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in tree.links]}
    tree_fn=tree
    data={'nodes':tree(material.node_tree,set()),'diffuse':list(material.diffuse_color),
          'roughness':material.roughness,'metallic':material.metallic,
          'backface_culling':material.use_backface_culling}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def slot_signature(root):
    """Conservative fingerprint of geometry, UVs and effective materials in a slot."""
    import bpy
    from mathutils import Matrix
    bpy.context.view_layer.update()
    signatures=[]
    for obj in root.children_recursive:
        if obj.type!='MESH':continue
        # Compose local transforms, excluding the slot transform. Cancelling a
        # rotated world matrix introduces float noise into otherwise identical
        # objects and makes a conservative hash reject valid placements.
        chain=[];cursor=obj
        while cursor!=root:
            if cursor is None:raise ValueError('Object is outside the placement root')
            chain.append(cursor);cursor=cursor.parent
        matrix=Matrix.Identity(4)
        for part in reversed(chain):matrix=matrix@part.matrix_parent_inverse@part.matrix_basis
        item={'vertices':[[round(x,6) for x in matrix@v.co] for v in obj.data.vertices],
              'polygons':[list(p.vertices) for p in obj.data.polygons],
              'material_indices':[p.material_index for p in obj.data.polygons],
              'smooth':[p.use_smooth for p in obj.data.polygons],
              'uv':[[list(v.uv) for v in layer.data] for layer in obj.data.uv_layers],
              'materials':[material_signature(s.material) for s in obj.material_slots],
              'hide_render':obj.hide_render}
        signatures.append(hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest())
    return hashlib.sha256(''.join(sorted(signatures)).encode()).hexdigest()


def validate_plan(plan, registry, root=ROOT):
    if plan.get('schema_version') != 1 or not plan.get('entries'):
        raise ValueError('A nonempty explicit schema_version 1 plan is required')
    seen = set()
    for entry in plan['entries']:
        identity = (entry['library_id'], entry['datablock'])
        if identity in seen:
            raise ValueError('Duplicate collection selection: ' + str(identity))
        seen.add(identity)
        library = registry['assets'][entry['library_id']]
        manifest = read(root / library['metadata'])
        if entry['datablock'] not in {x['name'] for x in manifest['furniture']}:
            raise ValueError('Unknown registered collection: ' + str(identity))
        if entry.get('status') != 'upgraded' or not entry.get('changes'):
            raise ValueError('Only explicitly upgraded collections belong in the merge plan')
        if not entry.get('visual_review') or not entry.get('validation'):
            raise ValueError('Automated evidence and attributed visual review are required')
        candidate = Path(entry['candidate_library'])
        if not candidate.is_file() or candidate.resolve() == (root / library['path']).resolve():
            raise ValueError('Candidate must be a distinct existing library')
    return plan


def collection_stats(collection):
    import bpy
    from mathutils import Matrix, Vector
    bpy.context.view_layer.update()
    meshes = [o for o in collection.all_objects if o.type == 'MESH']
    offset = Matrix.Translation(-collection.instance_offset)
    points = [offset @ o.matrix_world @ Vector(p) for o in meshes for p in o.bound_box]
    if not points or not all(math.isfinite(x) for p in points for x in p):
        raise ValueError('Invalid bounds: ' + collection.name)
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    signatures = []
    for obj in collection.all_objects:
        item = {'type': obj.type, 'matrix': [list(row) for row in offset @ obj.matrix_world]}
        if obj.type == 'MESH':
            item['vertices'] = [list(v.co) for v in obj.data.vertices]
            item['polygons'] = [list(p.vertices) for p in obj.data.polygons]
            item['material_indices'] = [p.material_index for p in obj.data.polygons]
            item['smooth'] = [p.use_smooth for p in obj.data.polygons]
            item['uv'] = [[list(v.uv) for v in layer.data] for layer in obj.data.uv_layers]
            item['materials'] = [material_signature(s.material) for s in obj.material_slots]
            if not all(math.isfinite(x) for v in item['vertices'] for x in v):
                raise ValueError('Nonfinite mesh: ' + obj.name)
        signatures.append(hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest())
    return {'parts': len(meshes), 'vertices': sum(len(o.data.vertices) for o in meshes),
            'dimensions_m': [high[i]-low[i] for i in range(3)],
            'bounds_min_m': low, 'bounds_max_m': high,
            'objects': len(collection.all_objects),
            'collection_instance_offset': list(collection.instance_offset),
            'geometry_sha256': hashlib.sha256(''.join(sorted(signatures)).encode()).hexdigest()}


def assert_portable():
    import bpy
    linked = [b.name for group in (bpy.data.objects, bpy.data.collections, bpy.data.meshes,
              bpy.data.materials, bpy.data.images, bpy.data.node_groups) for b in group if b.library]
    external = [im.name for im in bpy.data.images if im.source == 'FILE' and not im.packed_file]
    if linked or external:
        raise ValueError('Nonportable dependencies: ' + str((linked, external)))


def stage(args):
    import bpy
    registry = read(ROOT / 'assets/registry.json')
    plan = validate_plan(read(args.plan), registry)
    if args.out.exists():
        raise ValueError('Staging output already exists; select a distinct directory')
    args.out.mkdir(parents=True)
    grouped = defaultdict(list)
    for entry in plan['entries']:
        grouped[entry['library_id']].append(entry)
    report = {'schema_version': 1, 'status': 'staging', 'job_id': os.environ.get('INDOOR_RUN_ID'),
              'blender': bpy.app.version_string, 'plan': str(args.plan.resolve()),
              'plan_sha256': digest(args.plan), 'registry_sha256': digest(ROOT/'assets/registry.json'),
              'libraries': [], 'entries': plan['entries'], 'physics_validation': 'not performed'}
    for identity, entries in grouped.items():
        registered = registry['assets'][identity]
        original = ROOT / registered['path']
        if digest(original) != registered['sha256']:
            raise ValueError('Source library changed: ' + identity)
        metadata = read(ROOT / registered['metadata'])
        selected = {e['datablock']: e for e in entries}
        bpy.ops.wm.read_factory_settings(use_empty=True)
        material_names = [m['name'] for m in metadata['materials']]
        with bpy.data.libraries.load(str(original), link=False) as (src, dst):
            dst.materials = list(material_names)
        materials = list(dst.materials)
        if any(x is None for x in materials):
            raise ValueError('Registered material missing: ' + identity)
        imports = defaultdict(list)
        for item in metadata['furniture']:
            entry = selected.get(item['name'])
            imports[str(Path(entry['candidate_library']).resolve()) if entry else str(original)].append(item['name'])
        collections = []
        for source, names in imports.items():
            with bpy.data.libraries.load(source, link=False) as (src, dst):
                if not set(names) <= set(src.collections):
                    raise ValueError('Candidate collection missing: ' + source)
                dst.collections = list(names)
            for name, collection in zip(names, dst.collections):
                if collection is None or collection.name != name:
                    raise ValueError('Ambiguous collection identity: ' + name)
                bpy.context.scene.collection.children.link(collection)
                collections.append(collection)
        assert_portable()
        stats = {c.name: collection_stats(c) for c in collections}
        for collection in collections:
            entry=selected.get(collection.name)
            if entry and entry.get('preview_source'):
                if collection.asset_data is None:collection.asset_mark()
                with bpy.context.temp_override(id=collection):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=entry['preview_source'])
        for item in metadata['furniture']:
            entry = selected.get(item['name'])
            if entry:
                item.update(entry.get('manifest_updates', {}))
                item.update({k: stats[item['name']][k] for k in ('parts','vertices','dimensions_m','bounds_min_m','bounds_max_m')})
                item['quality_review'] = {'date': '2026-09-14', 'status': 'upgraded',
                    'changes': entry['changes'], 'validation': entry['validation'],
                    'visual_review': entry['visual_review'], 'physics': 'not validated'}
                if entry.get('source_geometry'):
                    item['quality_review']['source_geometry'] = entry['source_geometry']
                if entry.get('source_signature'):
                    item['quality_review']['source_signature'] = entry['source_signature']
        folder = args.out / identity
        folder.mkdir()
        output = folder / original.name
        bpy.data.libraries.write(str(output), set(collections + materials), fake_user=True, compress=True)
        bpy.ops.wm.open_mainfile(filepath=str(output))
        for name in stats:
            if name not in bpy.context.scene.collection.children:
                bpy.context.scene.collection.children.link(bpy.data.collections[name])
        reopened = {name: collection_stats(bpy.data.collections[name]) for name in stats}
        if stats != reopened:
            raise ValueError('Save/reopen geometry changed: ' + identity)
        assert_portable()
        if not all(name in bpy.data.materials for name in material_names):
            raise ValueError('Registered material lost after reopen: ' + identity)
        metadata['blender_version'] = bpy.app.version_string
        metadata['current_quality_update'] = {'date': '2026-09-14', 'policy': 'Replace current payload after review; keep stable IDs',
            'changed_collections': sorted(selected), 'geometry_and_reopen_checked': True,
            'physics_validation': 'not performed'}
        write(folder/'manifest.json', metadata)
        report['libraries'].append({'id': identity, 'original': registered['path'],
            'original_sha256': registered['sha256'], 'original_manifest_sha256': digest(ROOT/registered['metadata']),
            'candidate': str(output.resolve()), 'candidate_sha256': digest(output),
            'manifest': str((folder/'manifest.json').resolve()), 'manifest_sha256': digest(folder/'manifest.json'),
            'collections': stats, 'registered_materials': material_names, 'reopen': 'passed'})
        write(args.out/'report.json', report)
    report['status'] = 'staged'
    write(args.out/'report.json', report)
    print(json.dumps({'report': str(args.out/'report.json'), 'libraries': len(report['libraries'])}))


def publish(args):
    report = read(args.report)
    registry = read(ROOT/'assets/registry.json')
    if report.get('status') != 'staged' or digest(ROOT/'assets/registry.json') != report['registry_sha256']:
        raise ValueError('Registry differs from the reviewed staging input')
    expected = {e['library_id'] for e in report['entries']}
    actual = [e['id'] for e in report['libraries']]
    if expected != set(actual) or len(actual) != len(set(actual)):
        raise ValueError('Staged library coverage is incomplete or duplicated')
    reviews = read(ROOT/'assets/orientation_reviews.json')
    for item in report['libraries']:
        original = registry['assets'][item['id']]
        metadata = read(ROOT/original['metadata'])
        if set(item['collections']) != {e['name'] for e in metadata['furniture']}:
            raise ValueError('Staged collection coverage is incomplete: ' + item['id'])
        checks = [(ROOT/item['original'],item['original_sha256']),
                  (ROOT/original['metadata'],item['original_manifest_sha256']),
                  (Path(item['candidate']),item['candidate_sha256']),
                  (Path(item['manifest']),item['manifest_sha256'])]
        if any(digest(path) != expected for path, expected in checks):
            raise ValueError('Staged or source bytes changed: ' + item['id'])
        for identity, review in reviews['reviews'].items():
            if identity.startswith(item['id']+'/') and review['library_sha256'] != item['original_sha256']:
                raise ValueError('Stale orientation input: ' + identity)
    for item in report['libraries']:
        original = registry['assets'][item['id']]
        for source, dest in [(Path(item['candidate']),ROOT/original['path']),
                             (Path(item['manifest']),ROOT/original['metadata'])]:
            temp = dest.with_name(dest.name+'.quality-tmp')
            shutil.copyfile(source,temp)
            os.replace(temp,dest)
        original['sha256'] = item['candidate_sha256']
        for identity, review in reviews['reviews'].items():
            if identity.startswith(item['id']+'/'):
                review['library_sha256'] = item['candidate_sha256']
                review['orientation']['evidence'] += '; current-quality update 2026-09-14 retained the authored frame; see assets/quality_review.json'
    write(ROOT/'assets/orientation_reviews.json',reviews)
    write(ROOT/'assets/registry.json',registry)
    report['status'] = 'published'
    report['published_registry_sha256'] = digest(ROOT/'assets/registry.json')
    write(args.report.with_name('publication.json'),report)
    print(json.dumps({'status':'published','libraries':len(report['libraries'])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='stage',required=True)
    build = sub.add_parser('stage');build.add_argument('--plan',type=Path,required=True);build.add_argument('--out',type=Path,required=True)
    install = sub.add_parser('publish');install.add_argument('--report',type=Path,required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    (stage if args.stage == 'stage' else publish)(args)


if __name__ == '__main__':
    main()
