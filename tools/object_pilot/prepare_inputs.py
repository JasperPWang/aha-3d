"""Prepare auditable source frames, segmentation masks and asset crops.

Start with --frames-only for SAM3, then supply reviewed masks.
Optional manual polygons use an explicit reference resolution. No inpainting
is used: hidden surfaces remain absent from the input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--masks-manifest", type=Path,
                        help="Reviewed segmentation outputs, each with id and full-resolution mask path")
    parser.add_argument("--frames-only", action="store_true",
                        help="Extract source frames for SAM3 without authoring any masks")
    args = parser.parse_args()
    if args.frames_only and args.masks_manifest:
        parser.error("--frames-only cannot be combined with --masks-manifest")
    started = time.perf_counter()
    cfg = json.loads(args.config.read_text())
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    hashes = {}
    supplied = {}
    if args.masks_manifest:
        items = json.loads(args.masks_manifest.read_text())["objects"]
        supplied = {item["id"]: item for item in items}
        if len(supplied) != len(items):
            raise ValueError("Duplicate segmentation object IDs")
        if set(supplied) != {item["id"] for item in cfg["objects"]}:
            raise ValueError("Segmentation and selection object IDs must match")
    for spec in cfg["objects"]:
        source = (args.root / spec["source_video"]).resolve()
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {source}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame = None
        for _ in range(spec["source_frame"] + 1):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"Cannot decode frame {spec['source_frame']} of {source}")
        timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        cap.release()
        rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        width, height = rgb.size
        if str(source) not in hashes:
            hashes[str(source)] = sha256(source)
        objdir = out / spec["id"]
        objdir.mkdir(parents=True, exist_ok=True)
        if args.frames_only:
            rgb.save(objdir / "image.png")
            record = dict(spec)
            record.update(image=str(objdir / "image.png"), image_size=[width, height],
                          image_sha256=sha256(objdir / "image.png"), source_sha256=hashes[str(source)],
                          source_timestamp_seconds=timestamp, source_fps=fps)
            records.append(record)
            continue
        mask_method = "manual polygon silhouette with explicit background holes; review required"
        if supplied:
            external = supplied[spec["id"]]
            if external["source_frame"] != spec["source_frame"]:
                raise ValueError("Segmentation source frame mismatch")
            mask_path = Path(external["mask"])
            if not mask_path.is_absolute():
                mask_path = args.masks_manifest.parent / mask_path
            mask = Image.open(mask_path).convert("L")
            if mask.size != rgb.size:
                raise ValueError(f"Mask size {mask.size} != source frame size {rgb.size}")
            mask = mask.point(lambda p: 255 if p > 127 else 0)
            mask_method = external.get("mask_method", "SAM3 segmentation, externally reviewed")
        else:
            refw, refh = spec["polygon_reference_size"]
            mask = Image.new("L", rgb.size, 0)
            draw = ImageDraw.Draw(mask)
            for polygon in spec["polygons"]:
                draw.polygon([(round(x * width / refw), round(y * height / refh))
                              for x, y in polygon], fill=255)
            for polygon in spec.get("holes", []):
                draw.polygon([(round(x * width / refw), round(y * height / refh))
                              for x, y in polygon], fill=0)
        if mask.getbbox() is None:
            raise ValueError("Empty object mask")
        rgb.save(objdir / "image.png")
        if supplied and supplied[spec["id"]].get("image_sha256"):
            if sha256(objdir / "image.png") != supplied[spec["id"]]["image_sha256"]:
                raise ValueError("Segmentation source image checksum mismatch")
        mask.save(objdir / "mask.png")
        rgba = rgb.convert("RGBA")
        rgba.putalpha(mask)
        x0, y0, x1, y1 = mask.getbbox()
        padding = max(8, round(max(x1 - x0, y1 - y0) * 0.08))
        box = [max(0, x0-padding), max(0, y0-padding), min(width, x1+padding), min(height, y1+padding)]
        rgba.crop(box).save(objdir / "crop_rgba.png")
        rgb.crop(box).save(objdir / "crop_rgb.png")
        mask.crop(box).save(objdir / "crop_mask.png")
        overlay = np.array(rgb).astype(np.float32)
        selected = np.array(mask) > 0
        overlay[selected] = overlay[selected] * 0.55 + np.array([40, 220, 120]) * 0.45
        overlay = Image.fromarray(overlay.astype(np.uint8))
        overlay.thumbnail((1008, 567))
        overlay.save(objdir / "mask_review.jpg", quality=94)
        record = dict(spec)
        record.update({"image": str(objdir / "image.png"), "mask": str(objdir / "mask.png"),
                       "crop_rgba": str(objdir / "crop_rgba.png"), "crop_rgb": str(objdir / "crop_rgb.png"),
                       "crop_mask": str(objdir / "crop_mask.png"), "image_size": [width, height],
                       "crop_xyxy": box, "source_sha256": hashes[str(source)],
                       "source_timestamp_seconds": timestamp, "source_fps": fps,
                       "mask_method": mask_method,
                       "mask_pixels": int(selected.sum()),
                       "image_sha256": sha256(objdir / "image.png"),
                       "mask_sha256": sha256(objdir / "mask.png")})
        if supplied:
            record["segmentation"] = supplied[spec["id"]]
            record["segmentation_manifest"] = str(args.masks_manifest.resolve())
        records.append(record)
    report = {"schema_version": 1, "status": "source_frames_prepared" if args.frames_only else "prepared_pending_visual_mask_review",
              "objects": records, "prepare_seconds": time.perf_counter()-started,
              "source_config": str(args.config.resolve()), "code_sha256": sha256(__file__),
              "scope": "Matched visible object pixels: SAM full RGB + mask, TRELLIS masked RGBA crop. No hidden-surface ground truth or real metric scale."}
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"manifest": str(out / "manifest.json"), "objects": len(records),
                      "prepare_seconds": report["prepare_seconds"]}))


if __name__ == "__main__":
    main()
