#!/usr/bin/env python3
"""Check source distribution structure and generated human documentation.

Uses Python's standard library. Does not import models or start pipeline jobs.
"""
import argparse
import ast
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.links.extend(value for key, value in attrs if key in {'href', 'src', 'poster'} and value)


def source_files(root):
    """Avoid walking installed environments and local run payloads in a checkout."""
    root = root.resolve()
    if (root / '.git').exists():
        listed = subprocess.check_output(['git', '-C', str(root), 'ls-files',
            '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
        return [root / p for p in sorted(set(listed)) if p]
    excluded = {'.git', '.venv', 'venv', '.runtime', '__pycache__', 'node_modules',
                'external', 'runs', 'tasks', '.project_sync', 'checkpoints'}
    result = []
    for base, dirs, names in os.walk(root, followlinks=False):
        symlinks = [Path(base) / d for d in dirs if (Path(base) / d).is_symlink()]
        result.extend(symlinks)
        dirs[:] = sorted(d for d in dirs if d not in excluded and not (Path(base) / d).is_symlink())
        result.extend(Path(base) / name for name in names)
    return sorted(result)


def verify(root):
    errors = []
    counts = {'python_files': 0, 'shell_files': 0, 'skills': 0, 'demos': 0}
    for path in source_files(root):
        relative = path.relative_to(root)
        if any(p in {'.git', '.venv', '.runtime', '__pycache__', 'external', 'runs', 'tasks'} for p in relative.parts):
            continue
        if path.is_symlink():
            errors.append(f'Symlink in distribution: {relative}')
        if not path.is_file():
            continue
        if path.suffix == '.py':
            ast.parse(path.read_text(), filename=str(relative))
            counts['python_files'] += 1
        if path.suffix == '.sh' or path.name == 'indoor':
            subprocess.run(['bash', '-n', str(path)], check=True)
            counts['shell_files'] += 1
        if path.name == 'SKILL.md':
            text = path.read_text()
            assert text.startswith('---\n') and '\n---\n' in text, relative
            front = text.split('---', 2)[1]
            assert re.search(r'^name:', front, re.M) and re.search(r'^description:', front, re.M), relative
            counts['skills'] += 1
        if path.suffix in {'.md', '.html'}:
            text = path.read_text()
            if path.suffix == '.html':
                parser = Links()
                parser.feed(text)
                links = parser.links
            else:
                # Ignore inline examples and fenced snippets when checking links.
                prose = re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*(?:\n|$)', '', text)
                links = re.findall(r'!?\[[^\]\n]*\]\(([^)\n]+)\)', prose)
            for link in links:
                parsed = urlsplit(link.strip('<>'))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (path.parent / unquote(parsed.path)).resolve()
                if not target.is_relative_to(root) or not target.exists():
                    errors.append(f'Missing local link: {relative}: {link}')
    # Optional demo registry (same path as tools/build_catalog.py); none is shipped.
    manifest = root / 'references/unassigned/with_humans/manifest.json'
    demos = json.loads(manifest.read_text())['demos'] if manifest.is_file() else []
    if demos:
        assert len({d['id'] for d in demos}) == len(demos), 'Duplicate demos'
        for demo in demos:
            for name in ('poster', 'provenance'):
                path = (root / demo[name]).resolve()
                assert path.is_relative_to(root) and path.is_file(), (demo['id'], name)
            # Source videos are fetched separately; check them only when present.
            video = (root / demo['video']).resolve()
            assert video.is_relative_to(root), (demo['id'], 'video')
            if video.is_file():
                assert video.stat().st_size == demo['bytes'], demo['id']
            assert not any(k.startswith('canonical_') for k in demo), demo['id']
    counts['demos'] = len(demos)
    assert not errors, '\n'.join(errors)
    subprocess.run([sys.executable, str(root / 'tools/asset_index.py'), 'check'], cwd=root, check=True)
    subprocess.run([sys.executable, str(root / 'tools/build_catalog.py'), 'check', '--root', str(root)], cwd=root, check=True)
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), indent=2))
