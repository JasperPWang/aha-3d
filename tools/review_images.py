#!/usr/bin/env python3
"""Schema-constrained transport for the existing, unchanged visual-review gate."""
import argparse
import json
import os
from pathlib import Path
import sys


def codex_command(arguments):
    if not arguments or arguments[0] != 'exec':
        raise ValueError('Expected Codex exec arguments')
    return ['codex', 'exec', '--output-schema',
            str(Path(__file__).with_suffix('.schema.json')), *arguments[1:]]


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments and arguments[0] == 'exec':
        command = codex_command(arguments)
        os.execvp(command[0], command)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(arguments)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from aha3d.workflow.review_contract import run_reviewer
    request = json.loads(args.request.read_text())
    result = run_reviewer(request, args.out, executable=str(Path(__file__).resolve()))
    print(json.dumps(result, indent=2))
    return 0 if result['verdict'] == 'accepted' else 2


if __name__ == '__main__':
    sys.exit(main())
