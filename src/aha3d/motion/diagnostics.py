"""Inspect native root travel and height before resampling/skinning; never edit motion."""
import argparse
import math
from pathlib import Path

import numpy as np

from aha3d.io import digest, read, write


def root_report(root, fps=30., durations=None, limits=None):
    root = np.asarray(root, dtype=float)
    if root.ndim == 3 and root.shape[0] == 1:
        root = root[0]
    if root.ndim != 2 or root.shape[1] != 3 or not len(root) or not np.isfinite(root).all():
        raise ValueError('Expected one finite native root trajectory [frames, 3]')
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('Native FPS must be positive and finite')
    # Native Kimodo is Y-up. Blender conversion is (-x, z, y).
    delta = np.diff(root, axis=0)
    steps = np.linalg.norm(delta, axis=1)
    planar = np.linalg.norm(delta[:, [0, 2]], axis=1)
    height = root[:, 1]
    metrics = dict(planar_travel_m=float(planar.sum()),
        planar_displacement_m=float(np.linalg.norm((root[-1] - root[0])[[0, 2]])),
        maximum_root_step_m=float(steps.max()) if len(steps) else 0.,
        minimum_root_height_m=float(height.min()), maximum_root_height_m=float(height.max()),
        root_height_range_m=float(np.ptp(height)), final_minus_initial_height_m=float(height[-1] - height[0]))
    boundaries = []
    if durations is not None:
        if not durations or any(not math.isfinite(d) or int(d * fps) < 1 for d in durations):
            raise ValueError('Each duration must supply at least one native frame')
        counts = [int(d * fps) for d in durations]
        if sum(counts) != len(root):
            raise ValueError('Segment durations do not match native frame count; use the matching generation recipe')
        for frame in np.cumsum(counts)[:-1]:
            frame = int(frame)
            boundaries.append(dict(native_index=frame, time_seconds=frame / fps,
                root_step_m=float(steps[frame-1]), height_step_m=float(delta[frame-1, 1])))
    rules = dict(max_travel_m=('planar_travel_m', 'max'),
        max_root_step_m=('maximum_root_step_m', 'max'),
        min_root_height_m=('minimum_root_height_m', 'min'),
        max_height_range_m=('root_height_range_m', 'max'))
    violations = []
    for name, limit in (limits or {}).items():
        if name not in rules or not math.isfinite(limit) or name != 'min_root_height_m' and limit < 0:
            raise ValueError('Unknown or invalid motion limit: ' + name)
        metric, direction = rules[name]; actual = metrics[metric]
        if (direction == 'max' and actual > limit) or (direction == 'min' and actual < limit):
            violations.append(dict(limit=name, threshold=float(limit), actual=actual))
    return dict(schema_version=1, status='needs_review' if violations else 'diagnostic',
        frames=len(root), native_fps=fps, duration_seconds=len(root)/fps,
        coordinates='Native Kimodo Y-up; horizontal X/Z; not world-placed',
        metrics=metrics, segment_boundaries=boundaries, limits=limits or {}, violations=violations,
        root_samples=[dict(native_index=int(i), time_seconds=float(i/fps), xyz=root[i].tolist())
                      for i in sorted(set(np.linspace(0, len(root)-1, min(11, len(root))).astype(int)))],
        limitations='Root diagnostics only: no foot contact, mesh facing, collision, camera framing or source correspondence certification. No automatic correction.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--motion', type=Path, required=True)
    p.add_argument('--recipe', type=Path, help='Matching generation recipe for segment boundaries and native FPS')
    p.add_argument('--source-fps', type=float, help='Override native FPS (default: recipe source_fps or 30)')
    p.add_argument('--out', type=Path, required=True)
    for flag in ('max-travel-m', 'max-root-step-m', 'min-root-height-m', 'max-height-range-m'):
        p.add_argument('--' + flag, type=float)
    a = p.parse_args()
    cfg = read(a.recipe).get('body', {}) if a.recipe else {}
    fps = a.source_fps if a.source_fps is not None else cfg.get('source_fps', 30.)
    limits = {name: getattr(a, name) for name in ('max_travel_m', 'max_root_step_m', 'min_root_height_m', 'max_height_range_m')
              if getattr(a, name) is not None}
    with np.load(a.motion, allow_pickle=False) as data:
        report = root_report(data['root_positions'], fps, cfg.get('durations'), limits)
    report.update(motion=str(a.motion.resolve()), motion_sha256=digest(a.motion), code_sha256=digest(__file__),
        recipe_sha256=digest(a.recipe) if a.recipe else None)
    a.out.mkdir(parents=True, exist_ok=False)
    write(a.out / 'native_diagnostics.json', report)
    print(report['status'], report['metrics'])
    return 2 if report['violations'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
