#!/usr/bin/env python3
"""Build/check a portable Markdown and local HTML interface from canonical inputs.

No project imports, model loading, network requests or third-party packages.
Run from an exported checkout: python tools/build_catalog.py build
Or use: python tools/build_catalog.py check --root /path/to/export
"""
import argparse
import ast
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit


# Small interface descriptions, not another asset/skill inventory. Stage presence
# is read from runner.stages() below. Generated pages link back to source.
STAGE_INFO = {
    'motion': ('Generate approximate actions and root paths', 'docs/install/kimodo.md'),
    'resample': ('Resample rotations while preserving requested duration', 'docs/install/kimodo.md'),
    'skin': ('Export the fixed-topology SMPL-X body mesh', 'docs/install/blender.md'),
    'layout_inspection': ('Render and review matched source/room layout evidence', 'docs/LAYOUT_INSPECTION.md'),
    'assemble': ('Place the body and assets in an editable room copy', 'docs/install/blender.md'),
    'verify': ('Check saved geometry and synthetic projection artifacts', 'docs/VALIDATION.md'),
    'render': ('Render the selected camera and frame range', 'docs/install/blender.md'),
    'video': ('Encode and fully decode the rendered sequence', 'docs/VALIDATION.md'),
}
INSTALL = {
    'gvhmr-body-reconstruction': 'docs/install/gvhmr.md',
    'pi3x-scene-reference': 'docs/install/pi3x.md',
    'sam3d-motion-reference': 'docs/install/sam3d-body.md',
    'kimodo-body-motion': 'docs/install/kimodo.md',
    'blender-roomkit': 'docs/install/blender.md',
    'indoor-scene-workflow': 'docs/INSTALLATION.md',
}


def esc(value):
    return html.escape(str(value), quote=True)


def md(value):
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('[', '\\[').replace(']', '\\]')


class Catalog:
    def __init__(self, root):
        self.root = root.resolve()
        self.roomkit_previews = None
        self.files = None
        if (self.root / '.git').exists():
            listed = subprocess.check_output(['git', '-C', str(self.root), 'ls-files',
                '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
            self.files = set(listed) - {''}

    def included(self, relative):
        """Local ignored evidence must not change the shared generated catalog."""
        return ((self.files is None or str(relative) in self.files)
                and (self.root / relative).is_file())

    def text(self, relative):
        path = self.root / relative
        return path.read_text(encoding='utf-8')

    def data(self, relative):
        return json.loads(self.text(relative))

    def url(self, value, required=False):
        """Bundle-relative references become docs/catalog-relative URLs."""
        if not value:
            return None
        value = str(value)
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            return value
        if parsed.scheme or parsed.netloc or Path(value).is_absolute():
            raise ValueError('Expected bundle-relative path or HTTPS URL: ' + value)
        path = (self.root / value).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            raise ValueError('Path escapes bundle: ' + value)
        if not self.included(path.relative_to(self.root).as_posix()):
            if required:
                raise ValueError('Catalog input is missing: ' + value)
            return None
        return quote(os.path.relpath(path, self.root / 'docs/catalog'), safe='/')

    def link(self, label, value, markdown=False):
        url = self.url(value)
        if not url:
            return md(label) if markdown else esc(label)
        return '[{}]({})'.format(md(label), url) if markdown else '<a href="{}">{}</a>'.format(esc(url), esc(label))

    def skills(self):
        paths = sorted(path for path in self.root.glob('.agents/skills/*/SKILL.md')
                       if self.included(path.relative_to(self.root).as_posix()))
        result = []
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            source = self.text(relative)
            # Project frontmatter uses plain one-line name/description fields.
            front = source.split('---', 2)
            if len(front) < 3 or front[0].strip():
                raise ValueError('Missing skill frontmatter: ' + relative)
            values = {}
            for key in ('name', 'description'):
                match = re.search(r'^' + key + r':\s*(.+)$', front[1], re.M)
                if not match or match.group(1).strip() in ('>', '|', '>-', '|-'):
                    raise ValueError('Expected one-line skill ' + key + ': ' + relative)
                values[key] = match.group(1).strip().strip('"\'')
            values.update(path=relative, optional=relative.startswith('optional/'))
            values['install'] = INSTALL.get(values['name'], 'docs/INSTALLATION.md')
            result.append(values)
        return result

    def stages(self):
        source = self.text('src/aha3d/pipeline/runner.py')
        self.text('src/aha3d/cli.py')
        module = ast.parse(source)
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'stages')
        # Only inspect literal lists in stages(); do not execute project code.
        names = []
        for node in ast.walk(function):
            if isinstance(node, ast.List):
                for item in node.elts:
                    value = getattr(item, 'value', getattr(item, 's', None))
                    if isinstance(value, str) and value not in names:
                        names.append(value)
        unknown = set(names) - set(STAGE_INFO)
        if unknown:
            raise ValueError('Add interface descriptions for runner stages: ' + ', '.join(sorted(unknown)))
        return [name for name in STAGE_INFO if name in names]

    def preview(self, entry):
        for key in ('preview', 'thumbnail', 'poster'):
            if isinstance(entry.get(key), str) and self.url(entry[key]):
                return entry[key]
        source = entry.get('source', {})
        pointer = source.get('pointer', '')
        match = re.fullmatch(r'/(furniture|materials)/(\d+)', pointer)
        if match and source.get('path'):
            stem = 'furniture' if match.group(1) == 'furniture' else 'material'
            folder = Path(source['path']).parent / 'previews'
            for extension in ('png', 'jpg', 'webp'):
                value = (folder / '{}_{:02d}.{}'.format(stem, int(match.group(2)) + 1, extension)).as_posix()
                if self.url(value):
                    return value
        # The bundled RoomKit skill includes previews of the same named canonical
        # roomkit-v1 assets. Match names, never assume two manifests share order.
        if entry.get('library_id') == 'roomkit-v1':
            if self.roomkit_previews is None:
                self.roomkit_previews = {}
                folder = '.agents/skills/blender-roomkit/assets/library'
                manifest = folder + '/manifest.json'
                if self.included(manifest):
                    library = self.data(manifest)
                    for group, stem in (('furniture', 'furniture'), ('materials', 'material')):
                        for index, item in enumerate(library.get(group, []), 1):
                            for extension in ('png', 'jpg', 'webp'):
                                value = '{}/previews/{}_{:02d}.{}'.format(folder, stem, index, extension)
                                if self.url(value):
                                    self.roomkit_previews[item['name']] = value
                                    break
            return self.roomkit_previews.get(entry.get('name'))
        return None

    def build(self):
        index = self.data('assets/index.json')
        registry = self.data('assets/registry.json')['assets']
        entries = sorted(index['entries'], key=lambda e: (e.get('category', ''), e['id']))
        skills, stages = self.skills(), self.stages()
        demo_file = 'references/unassigned/with_humans/manifest.json'
        demos = self.data(demo_file).get('demos', []) if self.included(demo_file) else []
        demos = sorted(demos, key=lambda d: d['id'])
        if len({d['id'] for d in demos}) != len(demos):
            raise ValueError('Duplicate demo IDs')
        markdown = ['# Indoor workflow catalog', '',
                    'Generated from the asset index, registry, skill frontmatter, pipeline source and optional demo manifest. '
                    'Rebuild with `python tools/build_catalog.py build`; verify with `python tools/build_catalog.py check`.', '',
                    '[Assets](#assets) · [Skills](#skills) · [Pipeline](#pipeline) · [Demos](#demos) · [Local HTML](index.html)', '',
                    self.link('Installation', 'docs/INSTALLATION.md', True) + ' · ' + self.link('Project home', 'README.md', True), '']
        body = ['<header><p class="eyebrow">REAL2SIM / INDOOR</p><h1>Build an editable scene.</h1>',
                '<p>Browse reusable assets, choose a skill, run a pipeline stage, and inspect demonstrations.</p>',
                '<p>' + self.link('Installation', 'docs/INSTALLATION.md') + ' · ' + self.link('Project home', 'README.md') +
                ' · <a href="README.md">Markdown catalog</a></p></header>',
                '<nav aria-label="Catalog sections"><a href="#assets">Assets</a><a href="#skills">Skills</a>'
                '<a href="#pipeline">Pipeline</a><a href="#demos">Demos</a></nav>',
                '<main><section id="assets"><h2>Reusable assets</h2>',
                '<p>{} libraries · {} indexed items. Metadata describes availability; it is not a new visual validation.</p>'.format(len(registry), len(entries)),
                '<label for="asset-search">Search name, category, status or description</label>'
                '<input id="asset-search" type="search" placeholder="Try chair, cabinet, material…">'
                '<p id="asset-count" aria-live="polite"></p>']
        markdown += ['## Assets', '', md(index.get('coverage', '')), '', '### Libraries', '',
                     '| Library | Blender file | Manifest |', '| --- | --- | --- |']
        body.append('<details><summary>Library files and manifests</summary><ul>')
        for name, library in sorted(registry.items()):
            markdown.append('| {} | {} | {} |'.format(md(name), self.link('Blender library', library['path'], True), self.link('Manifest', library['metadata'], True)))
            body.append('<li><strong>{}</strong> · {} · {}</li>'.format(esc(name), self.link('Blender library', library['path']), self.link('Manifest', library['metadata'])))
        body.append('</ul></details><div class="grid" id="asset-grid">')
        markdown += ['', 'Registered = reusable library entry; callable = source helper; needs_extraction = candidate requiring separate extraction/review.', '',
                     '| Item | Category / status | Dimensions (m) | Source / preview |', '| --- | --- | --- | --- |']
        for entry in entries:
            preview = self.preview(entry)
            name = entry.get('name', entry['id'])
            status = entry.get('status', 'unspecified')
            category = entry.get('category', '')
            dims = entry.get('dimensions_m')
            dimensions = ' × '.join('{:.3g}'.format(v) for v in dims) if isinstance(dims, list) else 'Not recorded'
            source = entry.get('source', {}).get('path', '')
            description = entry.get('description', '')
            markdown.append('| **{}**<br>{}<br>{} | {}<br>{} | {} | {}{} |'.format(
                md(name), md(entry['id']), md(description), md(category), md(status), dimensions,
                self.link('Source', source, True) if self.url(source) else 'Source not included',
                ' · ' + self.link('Preview', preview, True) if preview else ''))
            search = ' '.join(str(entry.get(k, '')) for k in ('id', 'name', 'category', 'status', 'description', 'aliases')).lower()
            body.append('<article class="asset card" data-search="{}">'.format(esc(search)))
            if preview:
                body.append('<a href="{0}"><img loading="lazy" src="{0}" alt="{1}"></a>'.format(esc(self.url(preview)), esc(name)))
            else:
                body.append('<div class="no-preview">{}<small>Preview not included</small></div>'.format(esc(category.split('/')[-1] or 'asset')))
            body.append('<div class="card-content"><span class="badge">{}</span><h3>{}</h3><p>{}</p>'
                        '<p class="meta">{}<br>{}<br>{} m</p><p>{}</p></div></article>'.format(
                            esc(status), esc(name), esc(description), esc(entry['id']), esc(category), esc(dimensions),
                            self.link('Source metadata', source) if self.url(source) else 'Source not included'))
        body.append('</div></section><section id="skills"><h2>Skills</h2><p>Core skills are available as project instructions.</p><div class="grid">')
        markdown += ['', '## Skills', '', '| Skill | Scope | Usage | Installation |', '| --- | --- | --- | --- |']
        for skill in skills:
            scope = 'Optional' if skill['optional'] else 'Core'
            markdown.append('| {} | {} | {} | {} |'.format(self.link(skill['name'], skill['path'], True), scope, md(skill['description']), self.link('Setup', skill['install'], True)))
            body.append('<article class="card"><div class="card-content"><span class="badge">{}</span><h3>{}</h3><p>{}</p><p>{}</p></div></article>'.format(
                esc(scope), self.link(skill['name'], skill['path']), esc(skill['description']), self.link('Installation', skill['install'])))
        body.append('</div></section><section id="pipeline"><h2>Pipeline</h2><p>References and reviewed guidance feed the scene workflow. Generated people are approximate motions, not recovered real-person tracks.</p>')
        markdown += ['', '## Pipeline', '', 'Stages below come from `runner.stages()`. Actual selection depends on body mode, render kind and motion-only scope.', '',
                     'Configure a runtime and copy the generic example into a claimed `scenes/new_scene` workspace first. '
                     'Supply your own room for assembly. Every stage runs on the local workstation.', '',
                     '```bash', 'bash tools/indoor plan new_scene --recipe walk', 'bash tools/indoor run new_scene --recipe walk --motion-only',
                     'bash tools/indoor prepare new_scene --recipe walk', 'bash tools/indoor submit /path/to/prepared-run', 'bash tools/indoor status --scene new_scene', '```', '',
                     '| Stage | Purpose | Local command | Setup |', '| --- | --- | --- | --- |']
        body.append('<p>' + self.link('Generic examples', 'examples/README.md') + ' · ' + self.link('CLI source', 'src/aha3d/cli.py') +
                    ' · ' + self.link('Stage selection source', 'src/aha3d/pipeline/runner.py') + '</p>'
                    '<pre><code>bash tools/indoor plan new_scene --recipe walk\nbash tools/indoor run new_scene --recipe walk --motion-only\nbash tools/indoor prepare new_scene --recipe walk\nbash tools/indoor submit /path/to/prepared-run\nbash tools/indoor status --scene new_scene</code></pre>'
                    '<p>Configure a runtime and copy the generic example into a claimed workspace first. Provide your own room before assembly. '
                    'The following commands resume a prepared run through the selected stage, including unfinished predecessors; '
                    'only stages enabled by its recipe can run.</p><ol class="stages">')
        for name in stages:
            description, install = STAGE_INFO[name]
            command = 'bash tools/indoor execute /path/to/prepared-run --until ' + name
            markdown.append('| {} | {} | `{}` | {} |'.format(name, description, command, self.link('Setup', install, True)))
            body.append('<li><h3>{}</h3><p>{}</p><code>{}</code><p>{}</p></li>'.format(esc(name), esc(description), esc(command), self.link('Setup', install)))
        markdown += ['', '`execute --until` runs unfinished predecessors too; the stop stage must be enabled by the recipe. '
                     'Visual review is separate from automated stage completion.', '',
                     'Reference adapters: ' + self.link('Pi3X reconstruction commands', 'docs/install/pi3x.md', True) + ' · ' +
                     self.link('SAM 3D Body guidance commands', 'docs/install/sam3d-body.md', True), '', '## Demos', '']
        body.append('</ol><p>Reference adapters: ' + self.link('Pi3X', 'docs/install/pi3x.md') + ' · ' + self.link('SAM 3D Body', 'docs/install/sam3d-body.md') + '</p></section><section id="demos"><h2>Demos</h2>')
        attribution = 'references/unassigned/with_humans/ATTRIBUTION.md'
        if self.included(attribution):
            markdown += ['Reference demos retain CC BY-NC-SA 4.0 terms. ' + self.link('Attribution and source details', attribution, True) + '.', '']
            body.append('<p>Reference demos retain CC BY-NC-SA 4.0 terms. ' + self.link('Attribution and source details', attribution) + '.</p>')
        if not demos:
            message = 'No demo videos are registered in this bundle. The generic configuration examples are not generated scene results.'
            markdown.append(message)
            body.append('<p>' + message + '</p>')
        for demo in demos:
            # Source videos may be omitted from a redistribution; the entry then
            # names the upstream clip so users can fetch it themselves.
            video = self.url(demo['video'])
            clip = (demo.get('source') or {}).get('video_path') if isinstance(demo.get('source'), dict) else None
            missing = 'Video not bundled; obtain source clip `{}` and save it as `{}`.'.format(clip or demo['id'], demo['video'])
            poster = self.url(demo.get('poster'), required=True) if demo.get('poster') else None
            title = demo.get('title', demo['id'])
            description = demo.get('description', '')
            identity = str(demo['id'])
            if demo.get('duration_seconds') is not None:
                identity += ' · ' + str(demo['duration_seconds']) + ' seconds'
            provenance = demo.get('provenance', demo.get('source', ''))
            provenance_url = None
            if isinstance(provenance, str):
                try:
                    provenance_url = self.url(provenance)
                except (ValueError, OSError):
                    pass  # A provenance statement can be prose rather than a path.
            if isinstance(provenance, (dict, list)):
                provenance = json.dumps(provenance, sort_keys=True, ensure_ascii=False)
            markdown += ['### ' + md(title), '', md(identity), '', md(description), '', '[Watch video]({})'.format(video) if video else missing, '']
            if poster:
                markdown += ['[![{}]({})]({})'.format(md(title), poster, video) if video else '![{}]({})'.format(md(title), poster), '']
            if provenance:
                markdown += ['[Provenance]({})'.format(provenance_url) if provenance_url else 'Provenance: ' + md(provenance), '']
            provenance_html = '<a href="{}">Provenance</a>'.format(esc(provenance_url)) if provenance_url else esc(provenance)
            if video:
                media = '<video controls preload="none"{}><source src="{}"><a href="{}">Download video</a></video>'.format(
                    ' poster="{}"'.format(esc(poster)) if poster else '', esc(video), esc(video))
            else:
                media = ('<img loading="lazy" src="{}" alt="{}">'.format(esc(poster), esc(title)) if poster else '') + '<p class="meta">{}</p>'.format(esc(missing.replace('`', '')))
            body.append('<article class="demo"><h3>{}</h3><p class="meta">{}</p><p>{}</p>{}<p class="meta">{}</p></article>'.format(
                esc(title), esc(identity), esc(description), media, provenance_html))
        markdown += ['', '## Maintaining this interface', '',
                     'Edit canonical asset metadata and rebuild `tools/asset_index.py` first when assets change. '
                     'Skill names/descriptions come from their own frontmatter; pipeline stage names come from source.', '',
                     'Optional demo registry: `references/unassigned/with_humans/manifest.json` uses `{"schema_version":1,"demos":[...]}`. '
                     'Each entry needs unique `id` and bundle-root-relative `video`; `title`, `description`, `duration_seconds`, `poster` and `provenance` are optional. '
                     'HTTPS video/poster URLs are also accepted. Register only authorized, reviewed media.', '',
                     'Run `python tools/build_catalog.py build`, then `python tools/build_catalog.py check`. '
                     'Use `--root /path/to/export` when invoking the source-template script. '
                     'The HTML opens directly from disk and uses no external scripts, fonts or services.', '']
        body.append('</section></main><footer>Generated from canonical source metadata. '
                    'Rebuild: <code>python tools/build_catalog.py build</code> · Check: <code>python tools/build_catalog.py check</code>. '
                    'No external services.</footer>')
        return {'README.md': '\n'.join(markdown), 'index.html': HTML_HEAD + '\n'.join(body) + HTML_END}


HTML_HEAD = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indoor workflow catalog</title><style>
:root{color-scheme:light;--ink:#182b31;--muted:#54686d;--paper:#f7f6f0;--line:#d9e0db;--accent:#166b5c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,sans-serif}
header,main,footer,nav{max-width:1220px;margin:auto;padding:24px}header{padding-top:60px}.eyebrow{font-size:12px;letter-spacing:.2em;color:var(--accent)}
h1{font-size:clamp(32px,6vw,64px);line-height:1.05;letter-spacing:-.04em;margin:12px 0}h2{font-size:30px}h3{line-height:1.35;margin:8px 0}
a{color:var(--accent);text-underline-offset:3px}nav{display:flex;gap:24px;position:sticky;top:0;background:var(--paper);z-index:2;border-bottom:1px solid var(--line)}
section{scroll-margin-top:80px;margin-bottom:64px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px;margin-top:24px}
.card{background:white;border:1px solid var(--line);border-radius:12px;overflow:hidden}.card-content{padding:20px}.card img{width:100%;height:190px;object-fit:contain;background:#eef0ea}
.no-preview{height:130px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);background:#e8eeea;font-size:22px}.no-preview small{font-size:12px}
.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.badge{display:inline-block;background:#edf5ef;color:var(--accent);padding:3px 8px;border-radius:5px;font-size:12px}
input{display:block;width:100%;padding:14px;margin-top:8px;border:1px solid var(--line);border-radius:8px;font:inherit}details{margin:20px 0}summary{cursor:pointer}
pre{padding:22px;background:#18372f;color:#f1faf5;overflow:auto;border-radius:10px}code{font-size:13px;overflow-wrap:anywhere}.stages{padding-left:24px}.stages li{padding:12px;border-bottom:1px solid var(--line)}
.demo video{max-width:100%;max-height:560px;background:#122721;border-radius:10px}.demo{margin-bottom:40px}footer{border-top:1px solid var(--line);font-size:13px;color:var(--muted)}[hidden]{display:none!important}
@media(max-width:600px){nav{gap:18px;padding:16px}header,main,footer{padding:20px}.grid{grid-template-columns:1fr}}
</style></head><body>
'''
HTML_END = '''
<script>
const search=document.getElementById('asset-search'),cards=Array.from(document.querySelectorAll('.asset'));
function filter(){let count=0;const terms=search.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);for(const card of cards){card.hidden=!terms.every(term=>card.dataset.search.includes(term));if(!card.hidden)count++;}document.getElementById('asset-count').textContent=count+' of '+cards.length+' items';}
search.addEventListener('input',filter);filter();
</script></body></html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'check'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        outputs = Catalog(args.root).build()
        folder = args.root / 'docs/catalog'
        stale = [name for name, content in outputs.items() if not (folder / name).is_file() or (folder / name).read_text() != content]
        if args.command == 'check':
            if stale:
                raise ValueError('Stale or missing generated catalog: ' + ', '.join(stale) + '; run tools/build_catalog.py build')
            print('CATALOG_OK: Markdown and HTML match canonical inputs')
        else:
            folder.mkdir(parents=True, exist_ok=True)
            for name, content in outputs.items():
                (folder / name).write_text(content, encoding='utf-8')
            print('Built docs/catalog/README.md and index.html')
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
