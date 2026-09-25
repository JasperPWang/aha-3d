"""Resolve retired project paths without recreating old root-level aliases.

Keep this module compatible with the system Python used for task coordination.
"""
import json
import os
from pathlib import Path


def migrated_path(root, value):
    root = Path(root).resolve()
    candidate = Path(os.path.abspath(str(value if Path(value).is_absolute() else root / value)))
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate
    config = root / 'configs/path_migrations.json'
    local = root / 'configs/path_migrations.local.json'
    if local.is_file():
        config = local
    if not config.is_file():
        return candidate
    data = json.loads(config.read_text())
    if data.get('schema_version') != 1 or not isinstance(data.get('paths'), dict):
        raise ValueError('Invalid path migration registry')
    for old, new in sorted(data['paths'].items(), key=lambda item: len(item[0]), reverse=True):
        for entry in (old, new):
            p = Path(entry)
            if not isinstance(entry, str) or p.is_absolute() or '..' in p.parts or str(p) == '.':
                raise ValueError('Migration paths must be nonempty project-relative paths')
        if relative == old or relative.startswith(old + '/'):
            return root / (new + relative[len(old):])
    return candidate
