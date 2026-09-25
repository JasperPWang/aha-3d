"""Small source-control identity; exact run snapshot hashes remain authoritative."""
from pathlib import Path
import subprocess


def git_identity(root):
    root = Path(root).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args],
            stderr=subprocess.DEVNULL, text=True, timeout=10).rstrip('\n')
    try:
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            return {'kind': 'unversioned'}
        commit = git('rev-parse', 'HEAD')
        return {'kind': 'git', 'commit': commit,
                'branch': git('symbolic-ref', '--quiet', '--short', 'HEAD')
                    if git('rev-parse', '--abbrev-ref', 'HEAD') != 'HEAD' else None,
                'dirty': bool(git('status', '--porcelain', '--untracked-files=normal'))}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {'kind': 'unversioned'}
