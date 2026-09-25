"""Local robust refit of reviewed arm directions before native constraint compilation.

This operates on derived guidance, never raw SAM observations or generated motion.
"""
from copy import deepcopy
import numpy as np

FIELDS = ('upper_arm_direction', 'forearm_direction')


def unit(x):
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or not np.isfinite(x).all() or np.linalg.norm(x) < 1e-8:
        raise ValueError('Expected a finite nonzero direction')
    return x / np.linalg.norm(x)


def angle(a, b):
    return float(np.degrees(np.arccos(np.clip(unit(a) @ unit(b), -1, 1))))


def diagnostics(keys):
    """Expose close keys and heading/arm rates without labelling real turns noise."""
    pairs = []
    for side in ('left', 'right'):
        seq = sorted((k for k in keys if k['side'] == side), key=lambda k: k['target_time_seconds'])
        for a, b in zip(seq, seq[1:]):
            dt = b['target_time_seconds'] - a['target_time_seconds']
            if not np.isfinite(dt) or dt <= 0:
                raise ValueError('Same-hand target timestamps must be strictly increasing')
            changes = {f: angle(a[f], b[f]) for f in (*FIELDS, 'facing_xz')}
            pairs.append(dict(side=side, source_frames=[a['source_frame'], b['source_frame']],
                              interval_seconds=dt, close_keys=bool(dt < .2),
                              angle_change_degrees=changes,
                              average_rate_degrees_s={f: v/dt for f, v in changes.items()}))
    return pairs


def refit(keys, support=None, *, window_seconds=.2, max_gap_seconds=.1,
          max_correction_degrees=20.):
    """Fit directions locally in source time; keep sparse output keys and facing.

    Five reviewed samples, including the exact target and both temporal sides,
    are required. Large gaps, abrupt direction changes and large corrections are
    reported and left unchanged for review. Defaults are pilot heuristics.
    """
    if not (np.isfinite([window_seconds, max_gap_seconds, max_correction_degrees]).all()
            and window_seconds > 0 and max_gap_seconds > 0
            and 0 < max_correction_degrees < 90):
        raise ValueError('Invalid temporal refit parameters')
    result = deepcopy(keys)
    support = keys if support is None else support
    by_side = {}
    for k in support:
        if k['side'] not in ('left', 'right'):
            raise ValueError('Invalid support side')
        t = k['source_timestamp_seconds']
        if not np.isfinite(t):
            raise ValueError('Nonfinite source timestamp')
        for f in FIELDS:
            if np.asarray(k[f]).shape != (3,):
                raise ValueError('Expected three-dimensional arm direction')
            unit(k[f])
        by_side.setdefault(k['side'], []).append(k)
    for seq in by_side.values():
        seq.sort(key=lambda k: k['source_timestamp_seconds'])
        if any(b['source_timestamp_seconds'] <= a['source_timestamp_seconds']
               for a, b in zip(seq, seq[1:])):
            raise ValueError('Duplicate support timestamps')
    records = []
    for target in result:
        t = target['source_timestamp_seconds']
        if not np.isfinite(t):
            raise ValueError('Nonfinite target timestamp')
        seq = [k for k in by_side.get(target['side'], [])
               if abs(k['source_timestamp_seconds'] - t) <= window_seconds + 1e-9]
        ts = np.array([k['source_timestamp_seconds'] for k in seq])
        record = dict(source_frame=target['source_frame'], side=target['side'],
                      support_source_frames=[k['source_frame'] for k in seq], fields={})
        records.append(record)
        anchor = [k for k in seq if k['source_frame'] == target['source_frame']
                  and abs(k['source_timestamp_seconds'] - t) < 1e-8]
        if not anchor or any(not np.allclose(anchor[0][f], target[f], atol=1e-8) for f in FIELDS):
            raise ValueError('Support must contain the exact unmodified target observation')
        if len(seq) < 5 or not ts[0] < t < ts[-1]:
            record['status'] = 'unchanged: insufficient bracketing support'
            continue
        if np.max(np.diff(ts)) > max_gap_seconds + 1e-9:
            record['status'] = 'unchanged: temporal gap'
            continue
        x = (ts - t) / window_seconds
        design = np.column_stack([np.ones(len(x)), x])
        locality = np.exp(-2*x*x)
        record['status'] = 'evaluated'
        for field in FIELDS:
            values = np.array([unit(k[field]) for k in seq])
            if max(angle(a, b) for a, b in zip(values, values[1:])) > 75:
                record['fields'][field] = dict(status='unchanged: abrupt change or identity/limb ambiguity')
                continue
            weights = locality.copy()
            for _ in range(8):
                coeff = np.linalg.lstsq(design * np.sqrt(weights[:, None]),
                                       values * np.sqrt(weights[:, None]), rcond=None)[0]
                residual = np.linalg.norm(values - design @ coeff, axis=1)
                # Huber residual threshold ~3 degrees in unit-vector chord distance.
                weights = locality * np.minimum(1., .05236 / np.maximum(residual, 1e-9))
            if np.linalg.norm(coeff[0]) < .5:
                record['fields'][field] = dict(status='unchanged: ambiguous fit')
                continue
            fitted = unit(coeff[0])
            correction = angle(target[field], fitted)
            accepted = correction <= max_correction_degrees
            record['fields'][field] = dict(status='refit' if accepted else 'unchanged: correction requires review',
                                            proposed_correction_degrees=correction)
            if accepted:
                target[field] = fitted.tolist()
    return result, dict(method='robust local linear unit-direction refit',
                        window_seconds=window_seconds, max_gap_seconds=max_gap_seconds,
                        max_correction_degrees=max_correction_degrees,
                        facing_policy='unchanged; diagnose separately',
                        raw_observations_modified=False, records=records,
                        before=diagnostics(keys), after=diagnostics(result))
