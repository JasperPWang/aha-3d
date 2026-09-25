#!/usr/bin/env python3
"""Fully decode source clips and create timestamp-linked visual-review sheets."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw


def command(args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def review(video, output, step):
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.loads(command([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-show_frames", "-show_entries",
        "stream=width,height,avg_frame_rate,time_base,duration,nb_frames:"
        "frame=best_effort_timestamp_time,pkt_duration_time", "-of", "json", str(video),
    ]))
    frames = metadata["frames"]
    times = [float(frame["best_effort_timestamp_time"]) for frame in frames]
    if not times or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"Missing or non-increasing timestamps: {video}")
    command(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", str(video),
             "-map", "0:v:0", "-an", "-f", "null", "-"])
    duration = times[-1] - times[0] + float(frames[-1].get("pkt_duration_time", 0))
    if duration <= times[-1] - times[0]:
        duration = times[-1] - times[0] + (times[-1] - times[-2])
    selected = sorted(set(
        [min(range(len(times)), key=lambda i: abs(times[i] - times[0] - k * step))
         for k in range(math.ceil(duration / step))] + [len(times) - 1]
    ))
    # Select by decoded index, rather than approximate input seeking.
    expression = "+".join(f"eq(n\\,{i})" for i in selected)
    command(["ffmpeg", "-v", "error", "-threads", "2", "-i", str(video),
             "-vf", f"select='{expression}',scale=480:-1", "-vsync", "0",
             "-threads", "2", str(output / "frame_%03d.jpg")])
    images = sorted(output.glob("frame_*.jpg"))
    if len(images) != len(selected):
        raise ValueError("Decoded image selection count differs")
    pages = []
    for page in range(math.ceil(len(images) / 12)):
        sheet = Image.new("RGB", (1440, 1200), "white")
        draw = ImageDraw.Draw(sheet)
        for slot, path in enumerate(images[page * 12:(page + 1) * 12]):
            index = selected[page * 12 + slot]
            x, y = (slot % 3) * 480, (slot // 3) * 300
            with Image.open(path) as im:
                sheet.paste(im, (x, y + 26))
            draw.text((x + 6, y + 6), f"{video.stem[:12]} | frame {index} | {times[index]:.3f}s", fill="black")
        name = f"sheet_{page + 1:02d}.jpg"
        sheet.save(output / name, quality=92)
        pages.append(name)
    with video.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = dict(
        source_video=str(video.resolve()), source_sha256=source_hash,
        decoded_frames=len(times), duration_seconds=float(metadata["streams"][0].get("duration", duration)),
        decoded_presentation_span_seconds=duration, first_presentation_timestamp_seconds=times[0],
        duration_note="Keep stream duration and decoded PTS span separate; edit lists/initial offsets can differ.",
        stream=metadata["streams"][0], presentation_timestamps_seconds=times,
        full_decode="passed_ffmpeg_xerror", visual_review="pending",
        selected_frames=[dict(index=i, time_seconds=times[i], image=p.name) for i, p in zip(selected, images)],
        sheets=pages, attribution="Source and derived images retain the source video's license terms",
    )
    (output / "review.json").write_text(json.dumps(report, indent=2) + "\n")
    return {k: report[k] for k in ("source_video", "decoded_frames", "duration_seconds", "full_decode", "visual_review")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", type=float, default=.5)
    args = parser.parse_args()
    if not math.isfinite(args.step) or args.step <= 0:
        parser.error("step must be finite and positive")
    videos = [args.root / line.strip() for line in args.list.read_text().splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if not videos or len({p.stem for p in videos}) != len(videos):
        parser.error("Video list must be nonempty with unique stems")
    for video in videos:
        if not video.is_file():
            raise FileNotFoundError(video)
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [review(video, args.output / video.stem, args.step) for video in videos]
    (args.output / "summary.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
