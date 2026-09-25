"""Portable exception report and orthographic geometry evidence (standard library)."""
import html
import json
from pathlib import Path


def summarize(report):
    issues = report['issues']
    counts = {level: sum(i['severity'] == level for i in issues) for level in ('error', 'warning', 'unverified')}
    status = 'needs_attention' if counts['error'] or counts['warning'] else 'incomplete' if counts['unverified'] else 'no_issues_detected'
    return dict(status=status, counts=counts, objects=len(report['objects']),
                source_fidelity='Not assessed; retain Pi3X and native source-view review',
                accepted=False)


def hull(points):
    points = sorted(set(tuple(p) for p in points))
    if len(points) < 3:
        return points
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lo, hi = [], []
    for seq, out in ((points, lo), (reversed(points), hi)):
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
    return lo[:-1]+hi[:-1]


def projection(objects, axes, selected=()):
    points = [p for o in objects for part in o.get('projection_parts', []) for p in part]
    if not points:
        return '<svg viewBox="0 0 600 400"><text x="20" y="40">No geometry</text></svg>'
    x, y = axes
    low = [min(p[a] for p in points) for a in axes]
    high = [max(p[a] for p in points) for a in axes]
    scale = min(540/max(high[0]-low[0], .1), 340/max(high[1]-low[1], .1))
    def xy(p):
        return (30+(p[x]-low[0])*scale, 370-(p[y]-low[1])*scale)
    result = ['<svg viewBox="0 0 600 400" xmlns="http://www.w3.org/2000/svg">']
    for o in objects:
        color = '#d32f2f' if o['id'] in selected else '#526d82'
        for part in o.get('projection_parts', []):
            poly = hull([xy(p) for p in part])
            result.append('<polygon points="'+ ' '.join(f'{a:.2f},{b:.2f}' for a,b in poly) +f'" fill="{color}" fill-opacity=".10" stroke="{color}" stroke-width="1"><title>'+html.escape(o['id'])+'</title></polygon>')
        if o.get('role') in ('floor','wall','ceiling','structure') and o['id'] not in selected:
            continue
        p = [(a+b)/2 for a,b in zip(o['min'], o['max'])]; a,b = xy(p)
        result.append(f'<text x="{a:.2f}" y="{b:.2f}" fill="{color}" font-size="12">{o["number"]}</text>')
    result.append('</svg>')
    return ''.join(result)


def write_report(out, report):
    out = Path(out)
    report['summary'] = summarize(report)
    report['artifacts'] = ['report.json', 'report.html', 'REPORT.md']
    (out/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    s = report['summary']
    lines = ['# Placement check', '', f"Status: **{s['status']}**. {s['objects']} objects; {s['counts']}.", '',
             'Diagnostic only. Source fidelity and visual acceptance remain separate.', '',
             '[Open visual report](report.html)', '', '## Exceptions', '']
    rows = []
    for i in report['issues']:
        ids = ', '.join(i['objects']) or 'scene'
        lines.append(f"- **{i['severity']} / {i['code']}** — {ids}: {i['message']} Next: {i['next_action']}")
        rows.append('<tr><td>'+html.escape(i['severity'])+'</td><td>'+html.escape(i['code'])+'</td><td>'+html.escape(ids)+'</td><td>'+html.escape(i['message'])+'<br><b>Next:</b> '+html.escape(i['next_action'])+'</td></tr>')
    if not rows:
        lines.append('No issues detected within the reported coverage.')
    lines += ['', '## Coverage', '', '```json', json.dumps(report['coverage'], indent=2), '```', '', '## Limits', '']
    lines += ['- '+v for v in report['limits']]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    flagged = {oid for i in report['issues'] if i['severity'] in ('error','warning') for oid in i['objects']}
    views = ''.join('<figure><figcaption>'+name+'</figcaption>'+projection(report['objects'], axes, flagged)+'</figure>' for name,axes in [('Top (X/Y)',(0,1)),('Front (X/Z)',(0,2)),('Side (Y/Z)',(1,2))])
    pairs = []
    for i in report['issues'][:30]:
        objects = [o for o in report['objects'] if o['id'] in i['objects']]
        if objects:
            pairs.append('<details><summary>'+html.escape(i['code']+': '+', '.join(i['objects']))+'</summary><div class="views">'+''.join(projection(objects, a, i['objects']) for a in [(0,1),(0,2),(1,2)])+'</div></details>')
    inventory = ''.join('<tr><td>'+str(o['number'])+'</td><td>'+html.escape(o['id'])+'</td><td>'+html.escape(o['name'])+'</td><td>'+html.escape(o['grouping'])+'</td><td>'+html.escape(o.get('support', {}).get('status','not_checked'))+'</td></tr>' for o in report['objects'])
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Placement check</title><style>
body{font:15px system-ui;max-width:1400px;margin:30px auto;padding:0 20px;color:#172b3a;background:#fafafa}h1{font-size:26px}table{border-collapse:collapse;width:100%;margin:20px 0}.issues{table-layout:fixed}.issues th:nth-child(1){width:9%}.issues th:nth-child(2){width:14%}.issues th:nth-child(3){width:27%}.issues th:nth-child(4){width:50%}td,th{overflow-wrap:anywhere;padding:10px;border:1px solid #ccd4d9;text-align:left;vertical-align:top}.views{display:flex;flex-wrap:wrap}.views>figure,.views>svg{flex:1;min-width:260px;margin:6px}svg{width:100%;background:white}@media(max-width:650px){table{display:block;overflow-x:auto}td,th{min-width:75px}}details{margin:12px 0}pre{white-space:pre-wrap}summary{cursor:pointer}</style>'''
    document += '<h1>Placement check: '+html.escape(s['status'])+'</h1><p>'+html.escape(str(s['counts']))+' · '+str(s['objects'])+' objects. <a href="report.json">JSON</a> · <a href="REPORT.md">Agent summary</a></p><p>Numbered orthographic projections of evaluated geometry; red indicates an exception. Per-component convex silhouettes are diagnostic illustrations, not contact tests or source-view renders.</p><div class="views">'+views+'</div><h2>Exceptions</h2><table class="issues"><tr><th>Severity</th><th>Check</th><th>Objects</th><th>Evidence and next action</th></tr>'+''.join(rows)+'</table>'+''.join(pairs)+'<h2>Object inventory</h2><table><tr><th>#</th><th>ID</th><th>Blender root</th><th>Grouping evidence</th><th>Support</th></tr>'+inventory+'</table><h2>Coverage and limitations</h2><pre>'+html.escape(json.dumps(report['coverage'], indent=2))+'</pre><ul>'+''.join('<li>'+html.escape(v)+'</li>' for v in report['limits'])+'</ul></html>'
    (out/'report.html').write_text(document)
