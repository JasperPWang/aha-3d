#!/usr/bin/env python3
"""Check authored documentation for untranslated Chinese, filenames and local links."""
import argparse
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


EXCLUDED = {'kimodo_blender/upstream', 'kimodo_blender/tools',
            'kimodo_blender/checkpoints', 'runs', '.git', '.project_sync',
            '.runtime'}  # Installed third-party models/environments, not authored project docs.
HAN = re.compile('[\u3400-\u9fff\uf900-\ufaff]')
LINK = re.compile(r'\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def documents(root):
    for directory, dirs, files in os.walk(str(root), followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules', '.venv', 'venv', 'site-packages')
                   and not d.startswith('.claims-test-')
                   and (base / d).relative_to(root).as_posix() not in EXCLUDED
                   and not (base / d).is_symlink()]
        for name in files:
            path = base / name
            if path.suffix.lower() in ('.md', '.rst', '.txt') and not path.is_symlink():
                yield path


def check(root):
    problems = []
    count = 0
    for path in documents(root):
        count += 1
        relative = path.relative_to(root).as_posix()
        if any(ord(c) > 127 for c in relative):
            problems.append(relative + ': use an English ASCII document filename')
        content = path.read_text(encoding='utf-8')
        fenced = False
        for number, line in enumerate(content.splitlines(), 1):
            if HAN.search(line):
                problems.append('{}:{}: untranslated Chinese text'.format(relative, number))
            if line.lstrip().startswith(('```', '~~~')):
                fenced = not fenced
                continue
            if fenced or path.suffix.lower() != '.md':
                continue
            for match in LINK.finditer(line):
                target = match.group(1).strip('<>')
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = path.parent / unquote(parsed.path)
                if not destination.exists():
                    problems.append('{}:{}: missing local target {}'.format(relative, number, target))
    return count, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    count, problems = check(args.root.resolve())
    for problem in problems:
        print(problem)
    print('{} authored documents checked; {} issues. Third-party trees and symlinks excluded.'.format(count, len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
