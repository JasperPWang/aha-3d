#!/usr/bin/env python3
"""Adapt DPVO scalar dispatch to Torch 2.7 without changing the algorithm."""
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=Path)
args=parser.parse_args()
for rel in ['dpvo/altcorr/correlation_kernel.cu','dpvo/lietorch/src/lietorch_cpu.cpp','dpvo/lietorch/src/lietorch_gpu.cu']:
 path=args.root/rel
 old=path.read_text()
 lines=[line.replace('.type()', '.scalar_type()') if 'DISPATCH_' in line else line for line in old.splitlines(keepends=True)]
 new=''.join(lines)
 if new != old:
  path.write_text(new)
  print('Updated scalar dispatch:',rel)
