#!/usr/bin/env python3
"""Observation-based, body-part motion diagnostics; never accepts or edits motion.

The CLI consumes timestamp-matched COCO17 observations and optional projected
COCO17 predictions. Use GVHMR's supermotion_coco17 regressor for correspondence.
ViTPose is also a GVHMR input: residuals measure consistency, not independent truth.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

JOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
    "right_knee", "left_ankle", "right_ankle",
]
GROUPS = {"upper_body": list(range(5, 11)), "lower_body": list(range(11, 17)),
          "left_arm": [5, 7, 9], "right_arm": [6, 8, 10],
          "left_leg": [11, 13, 15], "right_leg": [12, 14, 16],
          "wrists": [9, 10], "ankles": [15, 16]}


def timestamps(values):
    t = np.asarray(values, dtype=float)
    if t.ndim != 1 or len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError("Need at least two finite, strictly increasing timestamps")
    if not np.allclose(np.diff(t), np.median(np.diff(t)), atol=1e-6, rtol=1e-5):
        raise ValueError("Need uniform full-frame timestamps; retain missing observations as masked rows")
    return t


def boolean_mask(value, shape, name):
    a = np.asarray(value)
    if a.shape != shape or not np.isin(a, [False, True]).all():
        raise ValueError(f"{name} must be a boolean mask of shape {shape}")
    return a.astype(bool, copy=True)


def stats(values):
    a = np.asarray(values)
    if not np.isfinite(a).all():
        raise ValueError("Nonfinite values cannot enter metric statistics")
    return dict(samples=int(a.size), median=float(np.median(a)) if a.size else None,
                p90=float(np.percentile(a, 90)) if a.size else None,
                maximum=float(a.max()) if a.size else None)


def intervals(mask, times):
    """Half-open sample-support intervals; final duration uses median cadence."""
    edges = np.r_[times, times[-1] + np.median(np.diff(times))]
    padded = np.r_[False, mask, False].astype(int)
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1)
    return [dict(first_frame=int(a), end_frame_exclusive=int(b),
                 start_seconds=float(edges[a]), end_seconds=float(edges[b]),
                 duration_seconds=float(edges[b] - edges[a])) for a, b in zip(starts, ends)]


def observation_support(keypoints, times, image_size, *, threshold=.5,
                        detected=None, reviewed_visible=None):
    t = timestamps(times)
    kp = np.asarray(keypoints, dtype=float)
    size = np.asarray(image_size, dtype=float)
    if kp.shape != (len(t), 17, 3):
        raise ValueError("keypoints must be [T,17,3] COCO XY/score")
    if size.shape != (2,) or not np.isfinite(size).all() or (size <= 0).any():
        raise ValueError("image_size must be positive [width,height]")
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Invalid confidence threshold")
    finite = np.isfinite(kp).all(-1)
    inside = finite & (kp[..., 0] >= 0) & (kp[..., 0] < size[0])
    inside &= (kp[..., 1] >= 0) & (kp[..., 1] < size[1])
    confidence = finite & (kp[..., 2] > threshold)
    supported = inside & confidence
    detection = None if detected is None else boolean_mask(detected, (len(t),), "detected")
    visible = None if reviewed_visible is None else boolean_mask(reviewed_visible, (len(t), 17), "reviewed_visible")
    if detection is not None:
        supported &= detection[:, None]
    if visible is not None:
        supported &= visible
    return supported, dict(
        nonfinite_joint_samples=int((~finite).sum()),
        low_confidence_joint_samples=int((finite & ~confidence).sum()),
        out_of_raster_joint_samples=int((finite & ~inside).sum()),
        raw_tracking_support="provided" if detection is not None else "unknown",
        undetected_frames=int((~detection).sum()) if detection is not None else None,
        visibility_evidence="reviewed_mask" if visible is not None else "unknown",
        reviewed_hidden_joint_samples=int((~visible).sum()) if visible is not None else None,
        reasons_overlap=True,
    )


def diagnose(keypoints, times, image_size, *, predictions=None, threshold=.5,
             detected=None, reviewed_visible=None, window_seconds=2., error_fraction=.05):
    """predictions: {label: (projected_uv[T,17,2], camera_depth[T,17])}.

    Observation cohorts are fixed across all variants. Invalid candidate outputs
    count as failures instead of silently shrinking their evaluation cohort.
    Thresholds flag review windows; no score establishes 3D correctness.
    """
    t = timestamps(times)
    if not np.isfinite([window_seconds, error_fraction]).all() or min(window_seconds, error_fraction) <= 0:
        raise ValueError("Window/error thresholds must be finite and positive")
    kp = np.asarray(keypoints, dtype=float)
    support, evidence = observation_support(kp, t, image_size, threshold=threshold,
                                            detected=detected, reviewed_visible=reviewed_visible)
    diagonal = float(np.linalg.norm(image_size))
    predicted = {}
    for name, (uv, depth) in (predictions or {}).items():
        uv, depth = np.asarray(uv, dtype=float), np.asarray(depth, dtype=float)
        if uv.shape != (len(t), 17, 2) or depth.shape != (len(t), 17):
            raise ValueError("Projection and depth must match timestamped COCO17 observations")
        predicted[name] = (uv, depth)

    def summary(frame_mask, ids):
        mask = support[:, ids] & frame_mask[:, None]
        slots = int(frame_mask.sum()) * len(ids)
        complete = support[:, ids].all(1) & frame_mask
        row = dict(expected_joint_samples=slots, supported_joint_samples=int(mask.sum()),
                   joint_coverage=float(mask.sum() / slots) if slots else None,
                   fully_supported_frames=int(complete.sum()),
                   support_status="supported" if slots and mask.sum() == slots else "partial_or_unknown",
                   predictions={})
        for name, (uv, depth) in predicted.items():
            valid = np.isfinite(uv[:, ids]).all(-1) & np.isfinite(depth[:, ids]) & (depth[:, ids] > 0)
            count_invalid = int((mask & ~valid).sum())
            residual = np.linalg.norm(uv[:, ids] - kp[:, ids, :2], axis=-1)
            values = residual[mask & valid]
            distribution = stats(values)
            p90 = distribution["p90"]
            excessive = mask & valid & (residual > error_fraction * diagonal)
            flag = ("invalid_prediction" if count_invalid else "no_observations" if p90 is None
                    else "large_residual" if excessive.any() else "consistent_2d_only")
            row["predictions"][name] = dict(residual_px=distribution,
                p90_image_diagonal_fraction=p90 / diagonal if p90 is not None else None,
                excessive_residual_joint_samples=int(excessive.sum()),
                flagged_intervals=intervals((excessive | (mask & ~valid)).any(1), t),
                invalid_observed_predictions=count_invalid, review_flag=flag,
                cohort_samples=int(mask.sum()))
        return row

    groups = {}
    windows = []
    end = t[-1] + np.median(np.diff(t))
    for lo in np.arange(t[0], end, window_seconds):
        hi = min(lo + window_seconds, end)
        frame_mask = (t >= lo) & (t < hi)
        if frame_mask.any():
            windows.append(dict(start_seconds=float(lo), end_seconds=float(hi),
                                groups={name: summary(frame_mask, ids) for name, ids in GROUPS.items()}))
    for name, ids in GROUPS.items():
        row = summary(np.ones(len(t), bool), ids)
        row["unsupported_intervals"] = intervals(~support[:, ids].all(1), t)
        groups[name] = row
    return dict(schema_version=1, scope="observation_consistency_diagnostic",
                motion_accepted=False, mutates_motion=False, frames=len(t),
                start_seconds=float(t[0]), end_seconds=float(end),
                config=dict(confidence_threshold=threshold, window_seconds=window_seconds,
                            review_error_image_diagonal_fraction=error_fraction),
                evidence=evidence, groups=groups, windows=windows,
                joints={name: summary(np.ones(len(t), bool), [i]) for i, name in enumerate(JOINT_NAMES)},
                limitations=[
                    "ViTPose is a GVHMR input: these are not independent accuracy measurements.",
                    "High confidence and in-raster coordinates do not establish visibility or identity.",
                    "Undetected boxes interpolated by the tracker are not raw detections.",
                    "2D agreement cannot establish depth, world trajectory, floor or object contact.",
                    "A COCO wrist/ankle is not a palm/sole surface or articulated finger observation.",
                    "Review flags are engineering thresholds, not calibrated confidence probabilities.",
                ])


def surface_contact_metrics(signed_distance_m, vertex_area_m2, support_local_vertices_m,
                            times, reviewed_contact, stationary_contact, *, tolerance_m=.01):
    """Measure supplied body patches against reviewed scene supports.

    Distances [T,P,V] are signed distances to the *corresponding actual support
    surface*, negative inside; areas [P,V] integrate each body patch. Vertices
    [T,P,V,3] must have fixed correspondence and use that support's rigid local frame.
    Surface speed averages per-vertex speeds by area, capturing rotational slip
    even when the patch centroid stays fixed. The caller
    computes geometry distances and retains source support/object identities.
    This measures simulated near-contact area, not contact area recovered in 2D.
    """
    t = timestamps(times)
    d, areas, positions = map(lambda x: np.asarray(x, dtype=float),
                              (signed_distance_m, vertex_area_m2, support_local_vertices_m))
    if d.ndim != 3 or d.shape[0] != len(t) or min(d.shape[1:]) < 1:
        raise ValueError("Distances must be [T,P,V]")
    n, patches, vertices = d.shape
    if areas.shape != (patches, vertices) or positions.shape != (n, patches, vertices, 3):
        raise ValueError("Contact patch geometry shapes differ")
    if not all(np.isfinite(x).all() for x in (d, areas, positions)) or (areas <= 0).any():
        raise ValueError("Finite distances/positions and positive patch areas required")
    if not np.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("Positive finite contact tolerance required")
    contact = boolean_mask(reviewed_contact, (n, patches), "reviewed_contact")
    stationary = boolean_mask(stationary_contact, (n, patches), "stationary_contact")
    if (stationary & ~contact).any():
        raise ValueError("Stationary-contact samples must be reviewed contact")
    pair = stationary[1:] & stationary[:-1]
    vertex_speed = np.linalg.norm(np.diff(positions, axis=0), axis=-1) / np.diff(t)[:, None, None]
    speed = (vertex_speed * areas[None]).sum(-1) / areas.sum(-1)[None]
    near_area = ((np.abs(d) <= tolerance_m) * areas[None]).sum(-1)
    positive_gap = np.maximum(d.min(-1), 0)
    penetration = np.maximum(-d.min(-1), 0)
    return dict(scope="supplied_reviewed_support_geometry", accepted=False,
                tolerance_m=tolerance_m, patches=[dict(
                    patch_index=i, reviewed_contact_frames=int(contact[:, i].sum()),
                    stationary_pairs=int(pair[:, i].sum()),
                    gap_m=stats(positive_gap[contact[:, i], i]),
                    near_contact_area_m2=stats(near_area[contact[:, i], i]),
                    stationary_relative_surface_speed_m_s=stats(speed[pair[:, i], i]),
                    penetration_m_all_supplied_frames=stats(penetration[:, i]),
                    contact_status="measured" if contact[:, i].any() else "unverified",
                ) for i in range(patches)],
                limitations=["Requires separately validated signed-distance geometry, support identities and contact labels.",
                             "Near-surface area is a tolerance-based geometric proxy, not measured source contact area.",
                             "Speed uses consecutive stationary-contact samples only; it never bridges a missing interval."])


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence-threshold", type=float, default=.5)
    parser.add_argument("--window-seconds", type=float, default=2.)
    args = parser.parse_args()
    with np.load(args.observations, allow_pickle=False) as z:
        times, keypoints, size = z["time_seconds"], z["keypoints"], z["image_size"]
        if z["joint_names"].tolist() != JOINT_NAMES:
            raise ValueError("Observation joint_names must be exact COCO17 order")
        options = {k: z[k] for k in ("detected", "reviewed_visible") if k in z}
    predictions = {}
    for path in args.prediction:
        if path.stem in predictions:
            raise ValueError("Prediction stems must be unique")
        with np.load(path, allow_pickle=False) as z:
            if z["time_seconds"].shape != times.shape or not np.allclose(z["time_seconds"], times, atol=1e-6, rtol=0):
                raise ValueError("Prediction timestamps differ; resample rotations before skinning/projection")
            if z["joint_names"].tolist() != JOINT_NAMES:
                raise ValueError("Prediction joint_names must match COCO17 regressor convention")
            if z["image_size"].shape != size.shape or not np.array_equal(z["image_size"], size):
                raise ValueError("Prediction/observation full-image rasters differ")
            predictions[path.stem] = (z["uv"], z["depth"])
    report = diagnose(keypoints, times, size, predictions=predictions,
                      threshold=args.confidence_threshold, window_seconds=args.window_seconds, **options)
    report["provenance"] = dict(observations=dict(path=str(args.observations.resolve()), sha256=digest(args.observations)),
        predictions=[dict(path=str(p.resolve()), sha256=digest(p)) for p in args.prediction], implementation_sha256=digest(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "scope": report["scope"], "motion_accepted": False}))


if __name__ == "__main__":
    main()
