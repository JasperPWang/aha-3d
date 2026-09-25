#!/usr/bin/env python3
"""Run the packaged v2 placement optimizer on an adapted results file."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time

import joblib
import torch
from omegaconf import OmegaConf

REPO = Path(__file__).resolve().parents[2]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, REPO / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_prompt_hmr():
    """Make `prompt_hmr.utils.rotation_conversions` importable without the package.

    Both post-processing modules import it at module scope, but prompt_hmr's
    __init__ pulls yacs and the full model stack, which the GVHMR runtime need
    not have. Register namespace stubs and the one real leaf module instead.
    """
    import types
    for name, path in (('prompt_hmr', 'prompt_hmr'), ('prompt_hmr.utils', 'prompt_hmr/utils')):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(REPO / path)]
            sys.modules[name] = pkg
    _load('prompt_hmr.utils.rotation_conversions', 'prompt_hmr/utils/rotation_conversions.py')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', required=True, help='results_init.pkl from build_results.py')
    ap.add_argument('--smplx-model', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--iters', type=int, default=1000)
    ap.add_argument('--lr', type=float, default=1e-2)
    ap.add_argument('--flat-ground', type=int, default=1)
    ap.add_argument('--versions', default='v2', choices=('v2',))
    ap.add_argument('--tag', default='')
    ap.add_argument('--ground', default=None, help='flat | heightmap | none')
    ap.add_argument('--vreg', type=float, default=None)
    ap.add_argument('--cont-vel', type=float, default=None)
    ap.add_argument('--cont-height', type=float, default=None)
    ap.add_argument('--lr-v2', type=float, default=None)
    ap.add_argument('--acc', type=float, default=None)
    ap.add_argument('--orient-source', default=None, choices=('global', 'camera'))
    ap.add_argument('--opt-scale', type=int, default=0)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    import smplx as smplx_pkg
    body = smplx_pkg.SMPLX(a.smplx_model, use_pca=False, flat_hand_mean=True, num_betas=10)

    init = joblib.load(a.init)
    n_frames = int(init['n_frames'])
    images = [None] * n_frames

    cfg = OmegaConf.create({
        'postopt_lr': a.lr, 'fps': a.fps, 'postopt_iters': a.iters,
        'run_post_opt_cam': True, 'flat_ground': bool(a.flat_ground),
        **({'postopt_ground': a.ground} if a.ground else {}),
        **({'postopt_vreg': a.vreg} if a.vreg is not None else {}),
        **({'postopt_cont_vel': a.cont_vel} if a.cont_vel is not None else {}),
        **({'postopt_cont_height': a.cont_height} if a.cont_height is not None else {}),
        **({'postopt_lr_v2': a.lr_v2} if a.lr_v2 is not None else {}),
        **({'postopt_acc': a.acc} if a.acc is not None else {}),
        **({'postopt_orient_source': a.orient_source} if a.orient_source else {}),
        'postopt_optimize_scale': bool(a.opt_scale),
    })

    _stub_prompt_hmr()
    mods = {
        'v2': (_load('phmr_postproc_v2', 'pipeline/postprocessing_v2.py'), 'post_optimization_v2'),
    }
    kwargs = {'v2': {'flat_ground': bool(a.flat_ground)}}

    timing = {}
    for v in [x.strip() for x in a.versions.split(',') if x.strip()]:
        mod, fn = mods[v]
        print(f'\n================ {v} ================', flush=True)
        res = copy.deepcopy(init)
        torch.manual_seed(0)
        t0 = time.time()
        res = getattr(mod, fn)(cfg, res, images, body, **kwargs[v])
        timing[v] = time.time() - t0
        joblib.dump(res, out / f'results_{v}{a.tag}.pkl')
        print(f'{v} done in {timing[v]:.1f}s -> {out / f"results_{v}{a.tag}.pkl"}', flush=True)

    (out / 'run_ab.json').write_text(json.dumps(
        {'init': str(a.init), 'iters': a.iters, 'lr': a.lr, 'fps': a.fps,
         'flat_ground': bool(a.flat_ground), 'n_frames': n_frames,
         'seconds': timing}, indent=2))


if __name__ == '__main__':
    main()
