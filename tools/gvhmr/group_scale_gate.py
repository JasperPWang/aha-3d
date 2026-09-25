"""Validate locked native units and rigid alignment before contact optimization."""
from pathlib import Path
import hashlib
import json
import math


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_group(manifest, manifest_dir):
    base = Path(manifest_dir)
    actors = manifest["actors"]
    scales = []
    for actor in actors:
        alignment = json.loads((base / actor["alignment"]).read_text())
        scale = float(alignment["body_scale"])
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Invalid actor scale")
        scales.append(scale)
    if max(scales) - min(scales) > 1e-6 * max(scales):
        raise ValueError("Independent actor scales prohibited: use rigid group alignment before contact repair")
    if any(not math.isclose(scale, 1.0, rel_tol=0, abs_tol=1e-7) for scale in scales):
        raise ValueError("Native human units are locked: fitted scale is prohibited")
    if len(actors) < 2 and not manifest.get("group_alignment", {}).get("report"):
        return {"mode": "single_actor", "shared_scale": scales[0]}
    path = manifest.get("group_alignment", {}).get("report")
    if not path:
        raise ValueError("Multi-person contact repair requires an accepted group alignment report")
    report_path = (base / path).resolve()
    report = json.loads(report_path.read_text())
    if report.get("schema_version") != 1 or report.get("accepted") is not True:
        raise ValueError("Group alignment has not passed scale/projection checks")
    if report.get("scale_policy") != "native_units_locked" or report.get("scale_optimized") is not False:
        raise ValueError("Group evidence must preserve native units without scale optimization")
    if not math.isclose(float(report["shared_scale"]), scales[0], rel_tol=1e-6):
        raise ValueError("Group report scale differs from actor scale")
    rows = report.get("actors", [])
    if [r["id"] for r in rows] != [a["id"] for a in actors]:
        raise ValueError("Group report actor identities/order differ")
    for actor, row in zip(actors, rows):
        for key in ("alignment", "cache"):
            if row.get(key + "_sha256") != digest(base / actor[key]):
                raise ValueError("Group alignment input changed: " + actor["id"] + "/" + key)
        evidence = row.get("pose_evidence")
        if evidence:
            path = actor.get("pose_confidence")
            if not path or digest(base / path) != evidence.get("sha256"):
                raise ValueError("Pose confidence evidence changed: " + actor["id"])
    camera_path = manifest.get("render", {}).get("camera_cache")
    if camera_path and report.get("camera_sha256") != digest(base / camera_path):
        raise ValueError("Group alignment camera differs from render camera")
    return {"mode": "native_units_locked", "shared_scale": scales[0],
            "report": str(report_path), "report_sha256": digest(report_path)}
