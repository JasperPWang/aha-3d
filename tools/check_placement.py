#!/usr/bin/env python3
"""One-command saved-room placement report. Configure runtime with kimodo_blender/env.sh."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aha3d.placement.runner import arguments, command

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    arguments(parser)
    try:
        result=command(parser.parse_args()); print(json.dumps(result,indent=2))
    except (ValueError,RuntimeError,OSError) as exc:
        parser.exit(2,str(exc)+'\n')
