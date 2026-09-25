#!/usr/bin/env python3
"""Export pinned GVHMR camera predictions and original detector observations.

Run in the separate configured GVHMR environment with authorized body assets.
No weights are downloaded. Inputs stay unchanged; output must be a new directory.
This exports native-camera consistency, not independent world/scene accuracy.
"""
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

try:
    from .motion_quality import JOINT_NAMES, diagnose, boolean_mask
    from .tracking_evidence import REVISION, file_sha256, validate_times, validated_detected, video_timeline
except ImportError:
    from motion_quality import JOINT_NAMES, diagnose, boolean_mask
    from tracking_evidence import REVISION, file_sha256, validate_times, validated_detected, video_timeline

PARAMETERS = {"body_pose": 63, "betas": 10, "global_orient": 3, "transl": 3}
MODEL_FILES = ["inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz",
               "hmr4d/utils/body_model/smplx2smpl_sparse.pt",
               "hmr4d/utils/body_model/smpl_coco17_J_regressor.pt"]
SOURCE_FILES = ["hmr4d/utils/smplx_utils.py", "hmr4d/utils/body_model/smplx_lite.py",
                "hmr4d/utils/geo/hmr_cam.py"]


def projection_arrays(keypoints, joints_camera, intrinsics, times, image_size, *,
                      detected=None, reviewed_visible=None, track_active=None):
    """Pure NumPy adapter; nonfinite predictions remain diagnosable failures."""
    t = validate_times(times)
    kp, joints, K = (np.asarray(x) for x in (keypoints, joints_camera, intrinsics))
    size = np.asarray(image_size)
    n = len(t)
    from tools.gvhmr.track_lifecycle import track_active_mask
    active = track_active_mask(track_active, n)
    if kp.shape != (n, 17, 3) or joints.shape != (n, 17, 3):
        raise ValueError("Observations and regressed COCO17 joints must retain every input frame")
    if size.shape != (2,) or not np.isfinite(size).all() or (size <= 0).any():
        raise ValueError("Invalid full-image raster")
    if K.shape == (3, 3):
        K = np.broadcast_to(K, (n, 3, 3))
    if K.shape != (n, 3, 3) or not np.isfinite(K).all() or not np.allclose(K[:, 2], [0, 0, 1]):
        raise ValueError("Invalid native intrinsics")
    if (K[:, 0, 0] <= 0).any() or (K[:, 1, 1] <= 0).any():
        raise ValueError("Native focal lengths must be positive")
    homogeneous = np.einsum("tij,tkj->tki", K.astype(float), joints.astype(float))
    uv = np.full((n, 17, 2), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        np.divide(homogeneous[..., :2], homogeneous[..., 2, None], out=uv,
                  where=homogeneous[..., 2, None] != 0)
    common = dict(time_seconds=t.copy(), image_size=size.copy(), joint_names=np.asarray(JOINT_NAMES))
    observations = dict(common, keypoints=kp.copy())
    for name, value, shape in [("detected", detected, (n,)),
                               ("reviewed_visible", reviewed_visible, (n, 17))]:
        if value is not None:
            observations[name] = boolean_mask(value, shape, name)
    prediction = dict(common, uv=uv, depth=joints[..., 2].copy(),
                      joints_camera=joints.copy(), K_fullimg=K.copy())
    observations['track_active'] = active
    prediction['track_active'] = active
    for values in (observations, prediction):
        values['source_frame_indices'] = np.arange(n)
    if not active.all():
        observations['detected'] = active if detected is None else observations['detected'] & active
        if 'reviewed_visible' in observations:
            observations['reviewed_visible'][~active] = False
        for name in ('uv', 'depth', 'joints_camera'):
            prediction[name][~active] = np.nan
    return observations, prediction


def regress_coco17(prediction, model, torch_module, *, device="cpu", batch_size=128):
    """Call the audited SmplxLiteCoco17 API without altering or resampling pose."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("Batch size must be a positive integer")
    params = prediction["smpl_params_incam"]
    if set(params) != set(PARAMETERS):
        raise ValueError("Unexpected GVHMR camera-space parameter schema")
    count = len(params["body_pose"])
    for name, width in PARAMETERS.items():
        if tuple(params[name].shape) != (count, width):
            raise ValueError(f"Unexpected {name} shape; expected {(count, width)}")
    results = []
    with torch_module.inference_mode():
        for start in range(0, count, batch_size):
            batch = {name: value[start:start + batch_size].to(device=device, dtype=torch_module.float32)
                     for name, value in params.items()}
            output = model(**batch)
            results.append(output.detach().cpu().numpy())
    if not results:
        raise ValueError("Empty GVHMR prediction")
    joints = np.concatenate(results, axis=0)
    if joints.shape != (count, 17, 3):
        raise ValueError("Configured body model did not return mesh-regressed COCO17 joints")
    return joints


def verify_upstream(repo):
    repo = Path(repo).resolve(strict=True)
    git = ["git", "-c", f"safe.directory={repo}", "-C", str(repo)]
    revision = subprocess.run([*git, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    if revision != REVISION:
        raise ValueError(f"GVHMR source revision differs from audited {REVISION}: {revision}")
    dirty = subprocess.run([*git, "diff", "HEAD", "--name-only", "--", *SOURCE_FILES],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    if dirty:
        raise ValueError("Audited body-regressor source has local modifications: " + ", ".join(dirty))
    return dict(path=str(repo), revision=revision,
                sources={name: file_sha256(repo / name) for name in SOURCE_FILES},
                body_assets={name: file_sha256(repo / name) for name in MODEL_FILES})


def _numpy(value):
    return value.detach().cpu().numpy()


def export_quality(*, repo, prediction_path, vitpose_path, video_path, output,
                   tracking_path=None, bbox_path=None, reviewed_visibility_path=None,
                   device="cpu", batch_size=128):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    repo = Path(repo).resolve(strict=True)
    paths = {"prediction": Path(prediction_path).resolve(strict=True),
             "vitpose": Path(vitpose_path).resolve(strict=True),
             "video": Path(video_path).resolve(strict=True)}
    upstream = verify_upstream(repo)
    timeline = video_timeline(paths["video"])
    hashes = {name: dict(path=str(path), sha256=file_sha256(path)) for name, path in paths.items()}
    import torch
    pred = torch.load(paths["prediction"], map_location="cpu", weights_only=True)
    keypoints = _numpy(torch.load(paths["vitpose"], map_location="cpu", weights_only=True))
    detected = None
    tracking = None
    if tracking_path is not None:
        sidecar = Path(tracking_path).resolve(strict=True)
        boxes_file = Path(bbox_path or paths["vitpose"].with_name("bbx.pt")).resolve(strict=True)
        tracking = json.loads(sidecar.read_text())
        boxes = _numpy(torch.load(boxes_file, map_location="cpu", weights_only=True)["bbx_xyxy"])
        detected = validated_detected(tracking, timeline["time_seconds"], timeline["image_size"],
                                      hashes["video"]["sha256"], boxes)
        hashes["tracking"] = dict(path=str(sidecar), sha256=file_sha256(sidecar))
        hashes["boxes"] = dict(path=str(boxes_file), sha256=file_sha256(boxes_file))
    visible = None
    if reviewed_visibility_path is not None:
        visibility_path = Path(reviewed_visibility_path).resolve(strict=True)
        with np.load(visibility_path, allow_pickle=False) as z:
            if z["joint_names"].tolist() != JOINT_NAMES or not np.array_equal(z["image_size"], timeline["image_size"]):
                raise ValueError("Reviewed visibility joint order or raster differs")
            if z["time_seconds"].shape != timeline["time_seconds"].shape or not np.allclose(z["time_seconds"], timeline["time_seconds"], atol=1e-6, rtol=0):
                raise ValueError("Reviewed visibility timestamps differ")
            visible = z["reviewed_visible"].copy()
        hashes["reviewed_visibility"] = dict(path=str(visibility_path), sha256=file_sha256(visibility_path))
    old_sys_path = sys.path.copy()
    try:
        sys.path.insert(0, str(repo))
        smplx_utils = importlib.import_module("hmr4d.utils.smplx_utils")
    finally:
        sys.path[:] = old_sys_path
    if Path(smplx_utils.__file__).resolve() != repo / "hmr4d/utils/smplx_utils.py":
        raise ValueError("Imported GVHMR body model belongs to another checkout")
    model = smplx_utils.make_smplx("supermotion_coco17").to(device).eval()
    joints = regress_coco17(pred, model, torch, device=device, batch_size=batch_size)
    observations, projection = projection_arrays(keypoints, joints, _numpy(pred["K_fullimg"]),
        timeline["time_seconds"], timeline["image_size"], detected=detected, reviewed_visible=visible,
        track_active=_numpy(pred['track_active']) if 'track_active' in pred else None)
    diagnostic = diagnose(observations["keypoints"], observations["time_seconds"], observations["image_size"],
        predictions={"native_camera": (projection["uv"], projection["depth"])},
        detected=observations.get('detected'), reviewed_visible=observations.get('reviewed_visible'))
    versions = {}
    for name in ("numpy", "torch", "av", "smplx"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unknown"
    provenance = dict(schema_version=1, scope="native_camera_observation_consistency",
        method="pinned make_smplx('supermotion_coco17') then native K projection",
        pose_resampled=False, motion_modified=False, motion_accepted=False,
        upstream=upstream, versions=versions, inputs=hashes,
        frames=timeline["frames"], image_size=timeline["image_size"].tolist(),
        video_fully_decoded=timeline["fully_decoded"], duration_seconds=timeline["duration_seconds"],
        tracking_support="original_selected_track" if detected is not None else "unknown_no_raw_sidecar",
        actor_id=tracking.get("actor_id") if tracking else None,
        selected_track_id=tracking.get("selected_track_id") if tracking else None,
        identity_review=tracking.get("identity_review", "pending") if tracking else "unknown",
        implementation_sha256=file_sha256(__file__),
        supporting_implementations_sha256={name: file_sha256(Path(__file__).with_name(name))
            for name in ("tracking_evidence.py", "motion_quality.py")},
        limitations=diagnostic["limitations"] + [
            "Native-camera agreement cannot establish the room-aligned global trajectory.",
            "This adapter preserves whichever upstream postprocessing variant the prediction file contains."])
    run_provenance = paths["prediction"].parent / "provenance.json"
    if run_provenance.is_file():
        provenance["inference_provenance"] = dict(path=str(run_provenance), sha256=file_sha256(run_provenance))
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "observations.npz", **observations)
    np.savez_compressed(output / "native_camera.npz", **projection)
    provenance["outputs"] = {name: file_sha256(output / name) for name in ("observations.npz", "native_camera.npz")}
    diagnostic["provenance"] = provenance
    for filename, payload in [("provenance.json", provenance), ("diagnostics.json", diagnostic)]:
        with (output / filename).open("x") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--vitpose", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True, help="Exact normalized 30 Hz input passed to GVHMR")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tracking-evidence", type=Path)
    parser.add_argument("--bbox", type=Path, help="Defaults to bbx.pt next to vitpose.pt; binds raw evidence to actor")
    parser.add_argument("--reviewed-visibility", type=Path)
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    report = export_quality(repo=args.repo, prediction_path=args.prediction, vitpose_path=args.vitpose,
        video_path=args.video, output=args.output, tracking_path=args.tracking_evidence,
        bbox_path=args.bbox, reviewed_visibility_path=args.reviewed_visibility,
        device=args.device, batch_size=args.batch_size)
    print(json.dumps(dict(output=str(args.output), frames=report["frames"], motion_accepted=False)))


if __name__ == "__main__":
    main()
