"""Create a bounded, machine-readable agent review from cached object outlines.

No UI interaction, geometry inference or scene acceptance is performed here.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw
from .overview import draw_overview


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(data, inventory=None, source_fit=None):
    inventory = inventory or {}
    objects = {o['id']: o for o in data['objects']}
    if len(objects) != len(data['objects']):
        raise ValueError('Duplicate object IDs')
    findings, coverage = [], {}
    unknown = sorted(o['id'] for o in objects.values() if o['grouping'] == 'ungrouped component' or o['semantic_class'] == 'unknown')
    if unknown:
        findings.append(dict(id='unclassified_geometry', severity='warning', object_ids=unknown,
                             message=f'{len(unknown)} groups lack complete semantic ownership/classification.',
                             next_action='Review and tag these groups before using them in semantic counts. They remain explicitly unclassified context.'))
    for identity, obj in objects.items():
        views = {}
        for name, view in data['views'].items():
            item = view['objects'][identity]
            state = 'contour_present' if item['paths'] else ('filtered_small_contour' if item['mask_pixels'] else 'no_projected_samples')
            views[name] = dict(state=state, mask_pixels=item['mask_pixels'], paths=len(item['paths']))
        coverage[identity] = dict(semantic_class=obj['semantic_class'], views=views)
        if obj['semantic_class'].startswith('furniture/') and not any(v['paths'] for v in views.values()):
            findings.append(dict(id='no_contour:' + identity, severity='warning', object_ids=[identity],
                                 message='Furniture has no retained contour in any selected view.',
                                 next_action='Inspect crop, projection and contour filtering; absence is not proof of missing model geometry.'))
    seen = set()
    for rule in inventory.get('expected_counts', []):
        key = rule['id']; expected = rule['count']
        if key in seen or type(expected) is not int or expected < 0 or not rule.get('evidence'):
            raise ValueError('Count rules need unique IDs, nonnegative integer counts and source evidence')
        seen.add(key)
        matched = sorted(o['id'] for o in objects.values() if o['semantic_class'] == rule['semantic_class'])
        if len(matched) != expected:
            findings.append(dict(id='count:' + key, severity='error', object_ids=matched,
                                 expected_count=expected, modeled_count=len(matched), evidence=rule['evidence'],
                                 message=f"{key}: expected {expected}, modeled {len(matched)}.",
                                 next_action='Compare the reviewed source inventory with these modeled instances; do not infer identities from color.'))
    for item in inventory.get('review_items', []):
        if not item.get('evidence') or not item.get('source_scene_sha256'):
            raise ValueError('Review items require evidence and the scene hash they describe')
        unchanged = item['source_scene_sha256'] == data['source_scene_sha256']
        missing = sorted(set(item['object_ids']) - set(objects))
        findings.append(dict(id='review:' + item['id'], severity='review', object_ids=[i for i in item['object_ids'] if i in objects],
                             missing_object_ids=missing, evidence=item['evidence'],
                             state='open' if unchanged and not missing else 'requires_recheck',
                             message=item['message'], next_action='Review matched source and model views. No numerical target or automatic resolution is implied.'))
    if not inventory.get('expected_counts'):
        findings.append(dict(id='source_inventory_not_assessed', severity='review', object_ids=[],
                             message='No reviewed source count expectations were supplied.',
                             next_action='Record source-linked object counts before accepting furniture completeness.'))
    if source_fit is None:
        findings.append(dict(id='source_fit_not_assessed', severity='review', object_ids=[],
                             message='No measured source-to-model object agreement was supplied.',
                             next_action='Check source fit for salient objects using masks, boxes, boundaries or source-linked landmarks as appropriate.'))
    else:
        if source_fit['source_scene_sha256'] != data['source_scene_sha256']:
            raise ValueError('Source-fit report describes a different scene')
        measured = set()
        for row in source_fit['rows']:
            identity = row.get('object_id')
            if identity and identity not in objects:
                raise ValueError('Source-fit object is absent from outline export')
            if identity and row.get('isolated'):
                measured.add(identity)
            findings.append(dict(id='source_fit:' + row['id'], severity='error' if row['status']=='needs_attention' else 'review',
                                 object_ids=[identity] if identity else [], source_frame=row.get('source_frame'),
                                 metrics=row.get('isolated'), state=row['status'],
                                 support_envelope=row.get('support_envelope'),
                                 message=f"{row['id']}: {row['status']}; reasons: {', '.join(row.get('review_reasons', [])) or 'review required'}.",
                                 next_action='Inspect source mask identity, paired visible/isolated comparisons and boundary/extent deltas; resolve across views before acceptance.'))
        unmeasured = sorted(o['id'] for o in objects.values() if o['semantic_class'].startswith('furniture/') and o['id'] not in measured)
        if unmeasured:
            findings.append(dict(id='source_fit_coverage', severity='review', object_ids=unmeasured,
                                 message=f'{len(unmeasured)} furniture objects have no measured source fit in this packet.',
                                 next_action='Extend checks to salient unmeasured objects; one checked sofa does not certify the room.'))
    priority = {'error': 0, 'review': 1, 'warning': 2}
    findings.sort(key=lambda f: (priority[f['severity']], f['id']))
    return dict(schema_version=1, status='needs_attention' if findings else 'visual_review_required',
                source_fidelity='not_accepted', source_scene_sha256=data['source_scene_sha256'],
                counts=dict(objects=len(objects), unclassified=len(unknown), views=len(data['views']),
                            findings=dict(Counter(f['severity'] for f in findings))),
                findings=findings, coverage=coverage,
                limits=['Contour presence measures projected model coverage, not real visibility or source agreement.',
                        'No automatic wall recognition: unclassified geometry is retained as context, not silently relabeled.',
                        'Source count rules are explicit reviewed inputs; size/layout observations stay open until reviewed.'])


def review_image(background, view, objects, highlight):
    """Retain every projected object as context, then emphasize selected objects."""
    image = Image.open(background).convert('RGBA')
    layer = Image.new('RGBA', image.size); draw = ImageDraw.Draw(layer)
    present = []
    for obj in objects:
        paths = view['objects'][obj['id']]['paths']
        if paths:
            present.append(obj['id'])
        if obj['id'] in highlight:
            continue
        for path in paths:
            points = [tuple(p) for p in path + path[:1]]
            draw.line(points, fill=(15, 20, 25, 100), width=3)
            draw.line(points, fill=(205, 215, 225, 150), width=1)
    for obj in objects:
        if obj['id'] not in highlight:
            continue
        for path in view['objects'][obj['id']]['paths']:
            draw.line([tuple(p) for p in path + path[:1]], fill=tuple(obj['color']) + (255,), width=2)
    return Image.alpha_composite(image, layer).convert('RGB'), present


def create(outlines, out, inventory=None, previous=None, source_fit=None, all_objects=False):
    outlines, out = Path(outlines), Path(out)
    data = json.loads(outlines.read_text())
    expected = json.loads(Path(inventory).read_text()) if inventory else None
    fit = json.loads(Path(source_fit).read_text()) if source_fit else None
    matching_fit_hashes = [value for key,value in fit['inputs'].items() if Path(key).resolve()==outlines.resolve()] if fit else []
    if fit and matching_fit_hashes != [digest(outlines)]:
        raise ValueError('Source fit and outline evidence do not match')
    report = analyze(data, expected, fit)
    inspection = Path(data['source_inspection'])
    backgrounds = {}
    for name in data['views']:
        path = inspection / f'{name}_source.png'
        if not path.exists():
            path = inspection / f'{name}_reference.png'
        backgrounds[name] = dict(path=str(path), sha256=digest(path), type='source_rgb' if '_source.png' in path.name else 'reference_mesh')
    report['inputs'] = dict(outlines_sha256=digest(outlines), inventory_sha256=digest(inventory) if inventory else None,
                            source_fit_sha256=digest(source_fit) if source_fit else None,
                            implementation_sha256=digest(__file__), backgrounds=backgrounds)
    report['input_signature'] = hashlib.sha256(json.dumps(report['inputs'], sort_keys=True).encode()).hexdigest()
    if previous:
        prior = json.loads(Path(previous).read_text())
        old = {f['id']: {k:v for k,v in f.items() if k!='review_images'} for f in prior['findings']}
        current = {f['id']: f for f in report['findings']}
        report['delta'] = dict(inputs_unchanged=prior.get('input_signature') == report['input_signature'],
                               new=sorted(set(current)-set(old)), removed=sorted(set(old)-set(current)),
                               changed=sorted(k for k in set(old)&set(current) if old[k] != current[k]))
    else:
        report['delta'] = None
    out.mkdir(parents=True, exist_ok=False)
    furniture = {o['id'] for o in data['objects'] if o['semantic_class'].startswith('furniture/')}
    images = []
    for name, view in data['views'].items():
        image, present = draw_overview(backgrounds[name]['path'], view, data['objects'])
        filename = f'{name}_context.png'; image.save(out / filename)
        images.append(dict(path=filename, view=name, kind='overview', context_object_ids=present,
                           highlighted_ids=sorted(present), presentation='Numbered semantic envelopes; faint architecture, stable ID colors and legend. Internal edges and enclosed holes are omitted.'))
    # Keep the priority visual work queue bounded; no per-object image explosion.
    focus = [f for f in report['findings'] if f['severity'] in ('error', 'review') and f['object_ids'] and f['id']!='source_fit_coverage'][:6]
    for index, finding in enumerate(focus):
        ids = set(finding['object_ids'])
        native = [n for n in data['views'] if n.startswith('source_')]
        native.sort(key=lambda n: (-sum(data['views'][n]['objects'][i]['mask_pixels'] for i in ids), n))
        exact = f"source_{finding['source_frame']:06d}" if finding.get('source_frame') is not None else None
        if exact in native:
            native.remove(exact); native.insert(0, exact)
        names = (['top'] if 'top' in data['views'] else []) + native[:1]
        finding['review_images'] = []
        for name in names:
            image, present = review_image(backgrounds[name]['path'], data['views'][name], data['objects'], ids)
            filename = f'focus_{index:02d}_{name}.png'; image.save(out / filename)
            finding['review_images'].append(filename)
            images.append(dict(path=filename, view=name, kind='focus', finding_id=finding['id'],
                               context_object_ids=present, highlighted_ids=sorted(ids & set(present))))
        if fit and finding['id'].startswith('source_fit:'):
            row=next(r for r in fit['rows'] if 'source_fit:'+r['id']==finding['id'])
            for kind in ('envelope','comparison'):
                if kind not in row.get('images',{}):
                    continue
                path=Path(source_fit).parent/row['images'][kind]
                filename=f'focus_{index:02d}_{kind}.png'
                (out/filename).write_bytes(path.read_bytes())
                finding['review_images'].append(filename)
                images.append(dict(path=filename,view=exact,kind='source_fit_'+kind,finding_id=finding['id'],
                                   source_path=str(path),source_sha256=digest(path)))
    # The gate uses complete object coverage, independent of finding priority.
    # Architecture and unclassified geometry must not disappear in a furniture filter.
    if all_objects:
        for index, obj in enumerate(data['objects']):
            identity = obj['id']
            available = [name for name, view in data['views'].items()
                         if view['objects'][identity]['paths']]
            native = sorted((n for n in available if n.startswith('source_')),
                            key=lambda n: (-data['views'][n]['objects'][identity]['mask_pixels'], n))
            orthographic = [n for n in ('top', 'front', 'side') if n in available]
            for name in orthographic[:1] + native[:2]:
                image, present = review_image(backgrounds[name]['path'], data['views'][name], data['objects'], {identity})
                filename = f'object_{index:03d}_{name}.png'; image.save(out / filename)
                images.append(dict(path=filename, view=name, kind='object_focus', object_id=identity,
                                   context_object_ids=present, highlighted_ids=[identity]))
    report['images'] = images
    report['next_images'] = [path for f in focus for path in f['review_images']]
    report['next_images'] += [item['path'] for item in images if item['kind'] == 'object_focus']
    report['image_sha256'] = {item['path']: digest(out/item['path']) for item in images}
    (out/'agent_review.json').write_text(json.dumps(report, indent=2))
    summary = {k: report[k] for k in ('status', 'source_fidelity', 'counts', 'input_signature', 'delta', 'next_images')}
    summary['priority_findings'] = [{k: f[k] for k in ('id', 'severity', 'message')} for f in report['findings'][:8]]
    if source_fit:
        summary['source_fit_report'] = str(source_fit)
    (out/'summary.json').write_text(json.dumps(summary, indent=2))
    lines = ['# Agent layout review', '', '**Status: '+report['status']+'; source fidelity is not accepted.**', '',
             'Read `summary.json` first; use `agent_review.json` for exact IDs, coverage and provenance.',
             'All projected geometry remains in gray context. Highlighted objects retain their colors. Native views use original RGB.', '',
             '## Findings', '']
    for finding in report['findings']:
        lines += [f"- **{finding['severity']} — {finding['id']}**: {finding['message']} {finding['next_action']}"]
    lines += ['', '## Priority images', '']
    for path in report['next_images']:
        lines += [f'![{path}]({path})', '']
    lines += ['## Limits', ''] + ['- '+text for text in report['limits']]
    (out/'agent_review.md').write_text('\n'.join(lines)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outlines', required=True, help='Existing objects.json; no rerender or new inference')
    parser.add_argument('--out', required=True)
    parser.add_argument('--inventory', help='Reviewed source count rules and scene-specific open observations')
    parser.add_argument('--previous', help='Previous agent_review.json for a compact change summary')
    parser.add_argument('--source-fit', help='Reviewed source_fit.json from matched geometry and source views')
    parser.add_argument('--all-objects', action='store_true', help='Focus every object, including walls, in an orthographic and up to two source views')
    print(json.dumps(create(**vars(parser.parse_args())), indent=2))
