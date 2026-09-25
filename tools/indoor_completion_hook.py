#!/usr/bin/env python3
"""Lightweight hook entry; standard library only, no Blender/ML work or background jobs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aha3d.workflow.completion import main
if __name__=='__main__':
    raise SystemExit(main())
