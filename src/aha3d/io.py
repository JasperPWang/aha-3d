"""Small filesystem primitives shared by orchestration and compute stages."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile

from . import runtime


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def lock(path):
    path = Path(path)
    try:
        path.mkdir()
    except FileExistsError:
        raise ValueError(f'Already owned: {path}. Inspect owner.json and active jobs before recovery; locks never expire automatically.')
    try:
        write(path / 'owner.json', {'host': socket.gethostname(), 'pid': os.getpid(),
              'job_id': runtime.run_id(), 'created_at': now()})
        yield
    finally:
        (path / 'owner.json').unlink(missing_ok=True)
        path.rmdir()


def files(path):
    return sorted(p for p in Path(path).rglob('*') if p.is_file() and '__pycache__' not in p.parts)


def inventory(folder):
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): digest(p) for p in files(folder)}


def intact(folder, recorded):
    return bool(recorded) and all((Path(folder) / p).is_file() and digest(Path(folder) / p) == checksum
                                  for p, checksum in recorded.items())
