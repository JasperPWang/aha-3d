#!/usr/bin/env python3
"""Search cached asset metadata without importing Blender or scanning scene files."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import os
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.orientation import normalize_orientation, unknown_orientation
STATUSES = ('registered', 'needs_extraction', 'callable')
KINDS = ('collection', 'material', 'scene_object', 'generator', 'utility')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def local(root, relative):
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise ValueError('Missing source file: ' + relative)
    return path


def build(root):
    """Materialize manifests and curated source anchors; never execute source code."""
    fingerprints = {}

    def source_text(relative):
        data = local(root, relative).read_bytes()
        fingerprints[relative] = hashlib.sha256(data).hexdigest()
        return data.decode('utf-8')

    def source_json(relative):
        return json.loads(source_text(relative))

    config = source_json('assets/catalog_sources.json')
    registry = source_json('assets/registry.json')
    source_text('tools/asset_index.py')
    source_text('src/aha3d/orientation.py')
    review_path = 'assets/orientation_reviews.json'
    reviews = source_json(review_path) if (root / review_path).exists() else {'schema_version': 1, 'reviews': {}}
    if reviews.get('schema_version') != 1 or not isinstance(reviews.get('reviews'), dict):
        raise ValueError('Invalid orientation review registry')
    used_reviews = set()
    entries = []
    used_annotations = set()
    for library_id, library in sorted(registry['assets'].items()):
        manifest = source_json(library['metadata'])
        local(root, library['path'])  # Existence only; large binary hashes belong to resolve().
        catalog_path = str(Path(library['metadata']).parent / 'blender_assets.cats.txt')
        catalogs = {}
        for line in source_text(catalog_path).splitlines():
            if line and not line.startswith(('#', 'VERSION')):
                catalog_id, category, _ = line.split(':', 2)
                if category.startswith('RoomKit/'):
                    category = category[len('RoomKit/'):]
                catalogs[catalog_id] = category.lower().replace(' ', '_')
        for section, kind in [('furniture', 'collection'), ('materials', 'material')]:
            for i, item in enumerate(manifest[section]):
                short_name = item['name'][2:] if item['name'].startswith('RK') else item['name']
                entry_id = library_id + '/' + slug(short_name.strip(' |'))
                annotation = config.get('library_annotations', {}).get(entry_id, {})
                if annotation:
                    used_annotations.add(entry_id)
                category = annotation.get('category') or catalogs[item['catalog_id']]
                entry = dict(id=entry_id, name=item['name'], kind=kind, status='registered',
                    category=category, family_id=annotation.get('family_id', entry_id),
                    aliases=annotation.get('aliases', []),
                    description=item.get('description', 'Editable procedural material: ' + item['name']),
                    source={'path': library['metadata'], 'pointer': '/' + section + '/' + str(i)},
                    library_id=library_id, library_path=library['path'],
                    library_sha256=library['sha256'], datablock=item['name'],
                    dimensions_m=item.get('dimensions_m'),
                    units=manifest['units'] if kind == 'collection' else None,
                    origin=manifest.get('origin') if kind == 'collection' else None,
                    forward=manifest.get('forward') if kind == 'collection' else None,
                    parts=item.get('parts'), vertices=item.get('vertices'),
                    world_coordinates=item.get('world_coordinates'),
                    validation='Registered metadata; this index does not reopen or visually validate the binary.')
                if kind == 'collection':
                    if 'seating_type' in annotation:
                        seating_type = annotation['seating_type']
                        if not isinstance(seating_type, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', seating_type):
                            raise ValueError('Invalid seating type: ' + entry_id)
                        entry['seating_type'] = seating_type
                    orientation = item.get('orientation', unknown_orientation())
                    if entry_id in reviews['reviews']:
                        review = reviews['reviews'][entry_id]
                        if review['library_sha256'] != library['sha256'] or review['datablock'] != item['name']:
                            raise ValueError('Orientation review does not match immutable asset: ' + entry_id)
                        orientation = review['orientation']
                        if orientation.get('status') != 'reviewed':
                            raise ValueError('Orientation review must record reviewed evidence: ' + entry_id)
                        used_reviews.add(entry_id)
                    entry['orientation'] = normalize_orientation(orientation)
                    entry['forward'] = entry['orientation']['front_axis']
                    entry['origin'] = entry['orientation']['origin']
                    for field in ('articulation', 'import_mode', 'controls', 'support_plane', 'seat_height_m', 'quality_review', 'preview'):
                        if field in item:
                            entry[field] = item[field]
                    entry['reuse'] = {
                        'method': 'append_collection',
                        'python': 'from aha3d.assets import resolve\n'
                                  'from aha3d.blender.roomkit import import_collection\n'
                                  f'obj = import_collection(resolve({library_id!r}, root=project_root), {item["name"]!r})',
                        'limitations': manifest['geometry'] + ' ' + annotation.get('limitations', '')}
                    if item.get('articulation'):
                        entry['reuse']['method'] = 'append_articulated'
                        entry['reuse']['python'] = (
                            'from aha3d.blender.roomkit import place_asset\n'
                            f'obj = place_asset({entry_id!r}, project_root=project_root)')
                        entry['reuse']['limitations'] += (
                            ' Use independent object hierarchies and remapped drivers for each placement; '
                            'ordinary shared collection instances do not have independent controls.')
                    # One placement entry point consumes item-level reviewed frames.
                    entry['reuse']['python'] = (
                        'from aha3d.blender.roomkit import place_asset\n'
                        f'obj = place_asset({entry_id!r}, project_root=project_root)')
                    entry['reuse']['limitations'] += ' Automated placement requires authored/reviewed orientation; legacy library-wide forward labels are not verification.'
                else:
                    entry['reuse'] = {
                        'method': 'append_material',
                        'python': 'import bpy\nfrom aha3d.assets import resolve\n'
                                  f'with bpy.data.libraries.load(str(resolve({library_id!r}, root=project_root)), link=False) as (src, dst):\n'
                                  f'    dst.materials = [{item["name"]!r}]\nmaterial = dst.materials[0]',
                        'limitations': 'Material only; no object geometry. Inspect texture coordinates when resizing or rotating objects.'}
                entries.append(entry)
    unused = set(config.get('library_annotations', {})) - used_annotations
    if unused:
        raise ValueError('Annotations reference absent assets: ' + ', '.join(sorted(unused)))
    if set(reviews['reviews']) - used_reviews:
        raise ValueError('Orientation reviews reference absent assets: ' + ', '.join(sorted(set(reviews['reviews']) - used_reviews)))
    for group in config['source_groups']:
        lines = source_text(group['path']).splitlines()
        if group.get('scene_state'):
            local(root, group['scene_state'])
        for item in group['entries']:
            entry = {k: v for k, v in item.items() if k != 'anchor'}
            matches = [i + 1 for i, line in enumerate(lines) if item['anchor'] in line]
            if len(matches) != 1:
                raise ValueError(f'{entry["id"]}: source anchor must match once, found {len(matches)}')
            entry.update(source={'path': group['path'], 'line': matches[0], 'anchor': item['anchor']},
                         scene=group.get('scene'), scene_state=group.get('scene_state'),
                         source_scope=group['scope'], dimensions_m=None,
                         validation='Source inspected; no new extraction or visual validation by this index.')
            entries.append(entry)
    ids = set()
    for entry in entries:
        if entry['id'] in ids:
            raise ValueError('Duplicate entry ID: ' + entry['id'])
        ids.add(entry['id'])
        if entry['kind'] not in KINDS or entry['status'] not in STATUSES:
            raise ValueError('Invalid kind/status: ' + entry['id'])
        if not all(entry.get(k) for k in ('name', 'category', 'family_id', 'description', 'reuse')):
            raise ValueError('Incomplete asset card: ' + entry['id'])
        expected = {'collection': 'registered', 'material': 'registered',
                    'scene_object': 'needs_extraction', 'generator': 'callable', 'utility': 'callable'}
        if entry['status'] != expected[entry['kind']]:
            raise ValueError('Kind/status mismatch: ' + entry['id'])
    for entry in entries:
        for relation in entry.get('related_ids', []):
            if relation not in ids:
                raise ValueError('Missing related ID: ' + relation)
    return dict(schema_version=1, coverage=config['coverage'],
                input_sha256=dict(sorted(fingerprints.items())),
                query_aliases=config['query_aliases'],
                counts=dict(sorted(Counter(e['status'] for e in entries).items())),
                entries=sorted(entries, key=lambda e: e['id']))


def search(index, query='', kind=None, status=None, category=None, scene=None):
    """AND between terms, OR between each term's explicitly curated synonyms."""
    terms = query.casefold().split()
    groups = [[term] + index['query_aliases'].get(term, []) for term in terms]
    ranked = []
    for entry in index['entries']:
        if kind and entry['kind'] != kind or status and entry['status'] != status:
            continue
        if category and not entry['category'].startswith(category) or scene and entry.get('scene') != scene:
            continue
        label = ' '.join([entry['id'], entry['name']] + entry.get('aliases', [])).casefold()
        description = ' '.join([entry['description'], entry['category'], entry['family_id']]).casefold()
        scores = [max([3 if term in label else 1 if term in description else 0 for term in group]) for group in groups]
        if all(scores):
            ranked.append((sum(scores), entry))
    return [entry for _, entry in sorted(ranked, key=lambda pair: (-pair[0], STATUSES.index(pair[1]['status']), pair[1]['id']))]


def tree(entries):
    hierarchy = {}
    for entry in entries:
        node = hierarchy
        for part in [entry['status']] + entry['category'].split('/'):
            node = node.setdefault(part, {})
        node[entry['name'] + ' [' + entry['id'] + ']'] = {}
    lines = ['Assets']

    def walk(node, prefix):
        for i, (name, children) in enumerate(sorted(node.items())):
            last = i == len(node) - 1
            lines.append(prefix + ('└── ' if last else '├── ') + name)
            walk(children, prefix + ('    ' if last else '│   '))
    walk(hierarchy, '')
    return '\n'.join(lines)


def markdown(index):
    lines = ['# Asset index', '', 'Generated by `python3 tools/asset_index.py build`; do not edit this file.', '',
             '[Search and maintenance instructions](README.md) · [Full JSON cards](index.json) · [Curated sources](catalog_sources.json)', '',
             index['coverage'], '',
             '- `registered`: listed in a versioned library; import through its registry ID.',
             '- `needs_extraction`: source-code candidate; grouping, dependencies and portability still need review.',
             '- `callable`: existing Blender generator or utility; requires its documented runtime.', '',
             'Counts: ' + ', '.join(f'{k}={v}' for k, v in index['counts'].items()) + '.', '',
             'Unknown candidate dimensions remain null; source coordinates are not verified asset bounds.', '',
             '```text', tree(index['entries']), '```', '', '## Source cards', '',
             '| ID | Description | Source |', '| --- | --- | --- |']
    for entry in index['entries']:
        source = entry['source']
        target = '../' + quote(source['path'], safe='/')
        label = source['path'] + (':' + str(source['line']) if 'line' in source else source.get('pointer', ''))
        description = entry['description'].replace('|', '\\|')
        lines.append(f'| `{entry["id"]}` | {description} | [{label}]({target}) |')
    return '\n'.join(lines) + '\n'


def atomic_write(path, text):
    fd, temporary = tempfile.mkstemp(prefix='.asset-index-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    subs = parser.add_subparsers(dest='command')
    subs.required = True  # argparse's keyword form requires Python 3.7+.
    for name in ('build', 'check'):
        subs.add_parser(name)
    for name in ('search', 'tree'):
        sub = subs.add_parser(name)
        sub.add_argument('query', nargs='*')
        sub.add_argument('--kind', choices=KINDS)
        sub.add_argument('--status', choices=STATUSES)
        sub.add_argument('--category', help='Category prefix, for example furniture or materials/wood')
        sub.add_argument('--scene')
        if name == 'search':
            sub.add_argument('--limit', type=int, default=20)
            sub.add_argument('--json', action='store_true')
    sub = subs.add_parser('show')
    sub.add_argument('id')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command in ('build', 'check'):
            result = build(root)
            outputs = {'assets/index.json': json.dumps(result, indent=2, ensure_ascii=False) + '\n',
                       'assets/INDEX.md': markdown(result)}
            if args.command == 'build':
                for path, content in outputs.items():
                    atomic_write(root / path, content)
            else:
                stale = [path for path, content in outputs.items()
                         if not (root / path).exists() or (root / path).read_text(encoding='utf-8') != content]
                if stale:
                    raise ValueError('Stale index; claim outputs and rebuild: ' + ', '.join(stale))
            print(json.dumps({'command': args.command, 'entries': len(result['entries']), 'counts': result['counts']}))
            return 0
        index = read(root / 'assets/index.json')
        if args.command == 'show':
            entry = next((e for e in index['entries'] if e['id'] == args.id), None)
            if entry is None:
                raise ValueError('Unknown asset ID: ' + args.id)
            print(json.dumps(entry, indent=2, ensure_ascii=False))
            return 0
        results = search(index, ' '.join(args.query), args.kind, args.status, args.category, args.scene)
        if args.command == 'tree':
            print(tree(results))
            return 0
        if args.limit < 1:
            raise ValueError('--limit must be positive')
        shown = results[:args.limit]
        if args.json:
            print(json.dumps({'total': len(results), 'returned': len(shown), 'entries': shown}, indent=2, ensure_ascii=False))
        else:
            print(f'{len(results)} matches; showing {len(shown)}. Use show ID for the full card.')
            for entry in shown:
                print(f'{entry["id"]} | {entry["status"]} | {entry["kind"]}')
                print('  ' + entry['description'])
                source = entry['source']
                print('  ' + source['path'] + (':' + str(source['line']) if 'line' in source else ' ' + source.get('pointer', '')))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'asset-index: {exc}\n')


if __name__ == '__main__':
    sys.exit(main())
