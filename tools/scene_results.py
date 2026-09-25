#!/usr/bin/env python3
"""Scene result management; use the configured core Python (3.10+)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.results.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
