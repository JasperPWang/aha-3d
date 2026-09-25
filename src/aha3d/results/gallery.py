"""Generate a local, rebuildable result gallery without changing source media."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit

from ..io import lock, read, signature, write
from .gallery_presentation import curate, preview_media
from .batch import demo_attempts, demo_runs, exporter_fingerprint
from .registry import build_index, describe, fingerprint, local, relative


def attach_demos(root, index, verify, *, hash_free=False):
    exporter = None if hash_free else exporter_fingerprint(root)
    for row in index['scenes']:
        sources = [a for a in row['artifacts'] if a['role'] == 'scene' and a.get('default', True)]
        source_hash = (sources[0].get('fingerprint', {}).get('sha256')
                       if len(sources) == 1 and sources[0]['availability'] in ('present', 'intact') else None)
        row['demo_status'] = 'missing'
        attempts = list(demo_attempts(root, row['id']))
        row['demo_attempts'] = [dict(status=run['status'], run_id=run['run_id'],
                                     href='../' + quote(run['record_path']),
                                     diagnostic=run.get('diagnostic', run.get('error', '')))
                                for run in attempts]
        for run in demo_runs(root, row['id']):
            if run.get('source_fingerprint', {}).get('sha256') != source_hash:
                row['demo_status'] = 'stale'
                continue
            artifacts = [describe(root, a, verify) for a in run.get('artifacts', [])]
            demos = [a for a in artifacts if a['role'] == 'demo']
            if (not hash_free and run.get('exporter_fingerprint') != exporter) or not demos or any(a['availability'] not in ('present', 'intact') for a in artifacts):
                row['demo_status'] = 'stale'
                continue
            row['demo_status'] = 'unverified' if hash_free else 'current'
            row['derived_demo'] = dict(artifacts=artifacts, visual_review=run.get('visual_review', 'pending'),
                                       options=run.get('options', {}), run_id=run['run_id'])
            break
        selected_demos = [a for a in row['artifacts'] if a['role'] == 'demo']
        selected_resources = [a for a in row['artifacts'] if a['role'] in ('demo', 'demo_resource', 'demo_offline')]
        if row['demo_status'] != 'current' and selected_demos and all(a['availability'] in ('present', 'intact') for a in selected_resources):
            row['demo_status'] = 'selected'
        if row['demo_status'] == 'missing' and any(a['role'] == 'demo' for a in row['artifacts'] + row['candidates']):
            row['demo_status'] = 'unverified'
        if row['demo_status'] not in ('current', 'selected'):
            relevant = [r for r in attempts if r.get('source_fingerprint', {}).get('sha256') == source_hash]
            if relevant and relevant[0]['status'] in ('failed', 'running'):
                row['demo_status'] = relevant[0]['status']


def posters(root, index, folder):
    binary = shutil.which('ffmpeg')
    if not binary:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    dest = folder / 'posters'; dest.mkdir(exist_ok=True)
    for row in index['scenes']:
        media = preview_media(root, row)
        if not media:
            continue
        item = media[0]; path = dest / (row['id'] + '.jpg'); stamp = path.with_suffix('.json')
        source = local(root, item['path']); stat = source.stat()
        binding = dict(path=item['path'], size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        if not path.exists() or not stamp.exists() or read(stamp) != binding:
            result = subprocess.run([binary, '-v', 'error', '-y', '-threads', '1', '-i', str(source),
                                     '-frames:v', '1', '-vf', 'scale=-2:320', '-threads', '1', str(path)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode:
                row['warnings'].append('Poster unavailable: ' + result.stderr[-300:]); continue
            write(stamp, binding)
        row['poster'] = 'posters/' + quote(path.name)


def web_previews(root, index, folder, generate, verify):
    """Optional codec-compatible navigation copies; original videos stay linked."""
    dest = folder / 'previews'
    if generate:
        dest.mkdir(exist_ok=True)
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    settings = dict(codec='vp9', max_width=640, crf=38, audio='opus', version=1)
    for row in index['scenes']:
        for item in row['artifacts']:
            if not item['path'].lower().endswith(('.mp4', '.webm', '.mov')) or item['availability'] not in ('present', 'intact', 'unverified'):
                continue
            source = local(root, item['path']); stat = source.stat()
            binding = dict(path=item['path'], size=stat.st_size, mtime_ns=stat.st_mtime_ns, settings=settings)
            key = row['id'] + '-' + signature(dict(path=item['path'], settings=settings))[:12]
            output = dest / (key + '.webm'); receipt = dest / (key + '.json')
            old = read(receipt) if receipt.exists() else {}
            good = (old.get('binding') == binding and output.is_file() and
                    describe(root, old.get('artifact', {'path': str(output)}), verify)['availability'] in ('intact', 'present'))
            if not good and generate:
                temp = output.with_suffix('.partial.webm')
                try:
                    source_fp = fingerprint(source)
                    subprocess.run([binary, '-v', 'error', '-y', '-threads', '2', '-i', str(source),
                                    '-map', '0:v:0', '-map', '0:a:0?', '-vf', "scale=w='min(640,iw)':h=-2",
                                    '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '6', '-row-mt', '1',
                                    '-crf', '38', '-b:v', '0', '-threads', '2', '-vsync', '0',
                                    '-c:a', 'libopus', '-b:a', '64k', str(temp)], check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    original_frames, original_seconds = imageio_ffmpeg.count_frames_and_secs(str(source))
                    preview_frames, preview_seconds = imageio_ffmpeg.count_frames_and_secs(str(temp))
                    if original_frames != preview_frames or abs(original_seconds - preview_seconds) > .05:
                        raise ValueError('Browser preview frame count/timing differs from its source')
                    if fingerprint(source) != source_fp:
                        raise ValueError('Source changed while creating browser preview')
                    temp.replace(output)
                    old = dict(binding=binding, source_fingerprint=source_fp,
                               artifact=dict(role='browser_preview', path=relative(root, output), fingerprint=fingerprint(output)),
                               validation=dict(full_decode=True, frames=preview_frames, seconds=preview_seconds,
                                               source_frames=original_frames, source_seconds=original_seconds))
                    write(receipt, old); good = True
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    row['warnings'].append('Browser preview unavailable: ' + str(exc))
                finally:
                    temp.unlink(missing_ok=True)
            if good:
                item['preview'] = describe(root, old['artifact'], verify)


def build(root, verify=False, make_posters=False, make_web_previews=False, *, hash_free=False):
    if hash_free and (verify or make_web_previews):
        raise ValueError('Hash-free build cannot verify hashes or create hashed web previews')
    folder = root / 'gallery'; folder.mkdir(exist_ok=True)
    with lock(folder / '.build.lock'):
        index = build_index(root, verify, hash_free=hash_free)
        curate(index)
        attach_demos(root, index, verify, hash_free=hash_free)
        if not hash_free:
            web_previews(root, index, folder, make_web_previews, verify)
        if make_posters:
            posters(root, index, folder)
        else:
            for row in index['scenes']:
                poster = folder / 'posters' / (row['id'] + '.jpg')
                stamp = poster.with_suffix('.json')
                if poster.exists() and stamp.exists():
                    binding = read(stamp)
                    for item in preview_media(root, row):
                        if item['path'] == binding.get('path'):
                            stat = local(root, item['path']).stat()
                            if (stat.st_size, stat.st_mtime_ns) == (binding.get('size'), binding.get('mtime_ns')):
                                row['poster'] = 'posters/' + quote(poster.name)
        template = Path(__file__).with_name('template.html').read_text()
        payload = json.dumps(index, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        page = template.replace('__RESULTS_JSON__', payload)
        fd, temp = tempfile.mkstemp(dir=folder, prefix='.gallery-', suffix='.html')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(page)
            write(folder / 'index.json', index)
            os.replace(temp, folder / 'index.html')
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return dict(path=str(folder / 'index.html'), generated_at=index['generated_at'], counts=index['counts'],
                demo_counts={s: sum(r['demo_status'] == s for r in index['scenes']) for s in ('current', 'selected', 'missing', 'stale', 'unverified', 'failed', 'running')})


def check(root, verify=False):
    index = read(root / 'gallery/index.json')
    errors = []
    for row in index['scenes']:
        if row['selection_status'] == 'broken_selection':
            errors.append(dict(scene=row['id'], error='Broken selection', details=row['warnings']))
        for item in row['artifacts'] + row.get('derived_demo', {}).get('artifacts', []):
            current = describe(root, item, verify)
            if current['availability'] not in ('present', 'intact'):
                errors.append(dict(scene=row['id'], path=item['path'], status=current['availability']))
            if item.get('preview'):
                preview = describe(root, item['preview'], verify)
                if preview['availability'] not in ('present', 'intact'):
                    errors.append(dict(scene=row['id'], path=preview['path'], status=preview['availability']))
    return dict(status='passed' if not errors else 'needs_attention', errors=errors,
                scope='Selected and derived artifact integrity only; no new visual, decode or simulation validation.')


def _allowed_files(root):
    """Read the current index without exposing files outside its inventory."""
    index = read(root / 'gallery/index.json')
    allowed = {root / 'gallery/index.html', root / 'gallery/index.json'}
    for row in index['scenes']:
        for item in row['artifacts'] + row['candidates'] + row['evidence'] + row.get('derived_demo', {}).get('artifacts', []):
            try:
                allowed.add(local(root, item['path']))
                if item.get('preview'):
                    allowed.add(local(root, item['preview']['path']))
            except ValueError:
                pass
        for entry in row.get('versions', []):
            allowed.add(local(root, unquote(entry['href'][3:])))
        for attempt in row.get('demo_attempts', []):
            record = local(root, unquote(attempt['href'][3:]))
            allowed.add(record)
            allowed.add(record.parent / 'logs/demo.log')
            allowed.add(record.parent / 'stages/demo/pipeline.log')
        if row.get('state'):
            allowed.add(root / 'scenes' / row['id'] / 'STATE.md')
        if row.get('poster'):
            allowed.add(local(root, Path('gallery') / unquote(row['poster'])))
        if row.get('reference', {}).get('path'):
            try:
                allowed.add(local(root, row['reference']['path']))
            except ValueError:
                pass
    return {p.resolve() for p in allowed}


def serve(root, host, port):
    """Serve indexed files, refreshing the inventory after an atomic rebuild."""
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Lock

    inventory_lock = Lock()
    inventory_stamp = None
    allowed = set()

    def current_inventory():
        nonlocal inventory_stamp, allowed
        with inventory_lock:
            stat = (root / "gallery/index.json").stat()
            stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if stamp != inventory_stamp:
                allowed = _allowed_files(root)
                inventory_stamp = stamp
            return allowed

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def send_response(self, code, message=None):
            self.response_status = code
            super().send_response(code, message)

        def end_headers(self):
            if self.response_status in (200, 206, 304) and re.search(r'/[0-9a-f]{64}\.(?:js|json\.gz|bin\.gz|props\.json\.gz)$', urlsplit(self.path).path):
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            super().end_headers()

        def send_head(self):
            self.remaining = None
            if urlsplit(self.path).path in ('/', '/gallery/', '/gallery'):
                self.send_response(302)
                self.send_header('Location', '/gallery/index.html')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            target = Path(self.translate_path(self.path)).resolve()
            if target not in current_inventory() or not target.is_file():
                self.send_error(404); return None
            request = self.headers.get('Range')
            if request:
                size = target.stat().st_size
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', request)
                try:
                    if not match or not any(match.groups()) or size == 0:
                        raise ValueError('Unsupported range')
                    first, last = match.groups()
                    start = int(first) if first else max(0, size - int(last))
                    end = min(size - 1, int(last)) if first and last else size - 1
                    if start > end or start >= size:
                        raise ValueError('Unsatisfiable range')
                except ValueError:
                    self.send_response(416); self.send_header('Content-Range', 'bytes */' + str(size))
                    self.send_header('Content-Length', '0'); self.end_headers(); return None
                stream = target.open('rb'); stream.seek(start); self.remaining = end - start + 1
                self.send_response(206)
                self.send_header('Content-Type', self.guess_type(str(target)))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Range', 'bytes {}-{}/{}'.format(start, end, size))
                self.send_header('Content-Length', str(self.remaining)); self.end_headers()
                return stream
            return super().send_head()

        def copyfile(self, source, outputfile):
            if self.remaining is None:
                return super().copyfile(source, outputfile)
            while self.remaining:
                block = source.read(min(1024 * 1024, self.remaining))
                if not block:
                    break
                outputfile.write(block); self.remaining -= len(block)

    server = ThreadingHTTPServer((host, port), Handler)
    print('Gallery: http://{}:{}/gallery/index.html'.format(host, server.server_port), flush=True)
    server.serve_forever()
