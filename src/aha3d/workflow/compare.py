"""Compose and fully decode a source-timed comparison without Python per-frame compositing."""
import argparse
from fractions import Fraction
from pathlib import Path
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw
from aha3d.config import timing
from aha3d.io import digest, read, write
from aha3d.pipeline.runner import completed_artifact


def comparison_inputs(run=None, render=None, config=None):
    if run is not None:
        if render is not None or config is not None:
            raise ValueError('--run supplies the render and frozen timing; omit --render and --config')
        render, recipe = completed_artifact(run, 'video')
        # Frozen timing is normalized and includes a derived rounded duration/end.
        # Reconstruct from authoritative rational cadence and count, not that float.
        raw = recipe['timing']
        t = timing({k: raw[k] for k in ('frames', 'fps', 'start') if k in raw})
        provenance = dict(run=str(Path(run).resolve()), recipe_sha256=digest(Path(run) / 'snapshot/recipe.json'))
    else:
        if render is None or config is None:
            raise ValueError('Supply --run, or both --render and --config')
        t = timing(read(config)['timing'])
        provenance = dict(config_sha256=digest(config))
    return Path(render), t, provenance


def validate_video(video, t, size=None):
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    # One complete strict decode provides count and end timestamp via ffmpeg progress.
    result = subprocess.run([exe, '-nostdin', '-v', 'error', '-xerror', '-i', str(video),
        '-map', '0:v:0', '-an', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'],
        check=True, capture_output=True, text=True)
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    reader = imageio_ffmpeg.read_frames(str(video))
    try:
        metadata = next(reader)
    finally:
        reader.close()
    count = int(fields['frame']); seconds = int(fields['out_time_us']) / 1e6
    if count != t['frames'] or abs(seconds - t['duration_seconds']) > .02 or abs(metadata['fps'] - float(Fraction(t['fps']))) > .02:
        raise ValueError(f'Video timing mismatch: {video}: {count} frames, {seconds} seconds, {metadata["fps"]} fps')
    if size is not None and list(metadata['size']) != list(size):
        raise ValueError('Video raster differs')
    return dict(full_decode_pass=True, decoded_frames=count, decoder_duration_seconds=seconds,
        fps=t['fps'], duration_seconds=t['duration_seconds'], resolution=list(metadata['size']), sha256=digest(video))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', type=Path, help='Completed pipeline run; resolve recorded video and exact frozen timing')
    group.add_argument('--render', type=Path)
    p.add_argument('--config', type=Path, help='Timing config, required only with --render')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--tile-width', type=int, default=640); p.add_argument('--tile-height', type=int, default=360)
    a = p.parse_args()
    if min(a.tile_width, a.tile_height) <= 0 or a.tile_width % 2 or a.tile_height % 2:
        p.error('Comparison tile dimensions must be positive and even')
    render, t, provenance = comparison_inputs(a.run, a.render, a.config)
    report = {label: validate_video(video, t) for label, video in [('reference', a.reference), ('render', render)]}
    report['inputs'] = provenance
    a.out.mkdir(parents=True, exist_ok=False)
    w, h = a.tile_width, a.tile_height
    banner_h = 48 if w < 480 else 32
    banner = Image.new('RGB', (2*w, banner_h), '#f1f1ef'); draw = ImageDraw.Draw(banner)
    draw.text((12, 10), 'Source reference', fill='black')
    draw.text((w+12, 10), 'White model + generated people' if w < 480 else 'White model + approximate generated people', fill='black')
    banner.save(a.out / 'labels.png')
    exe = imageio_ffmpeg.get_ffmpeg_exe(); temp = a.out / 'comparison.partial.mp4'
    filt = (f'[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[l];'
            f'[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[r];'
            f'[l][r]hstack=inputs=2,pad={2*w}:{h+banner_h}:0:{banner_h}:color=0xF1F1EF[b];[b][2:v]overlay=0:0:shortest=1[v]')
    subprocess.run([exe, '-nostdin', '-v', 'error', '-i', str(a.reference), '-i', str(render),
        '-loop', '1', '-framerate', t['fps'], '-i', str(a.out / 'labels.png'), '-filter_complex_threads', '1',
        '-filter_complex', filt, '-map', '[v]', '-frames:v', str(t['frames']), '-r', t['fps'], '-an',
        '-c:v', 'libx264', '-threads', '4', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(temp)], check=True)
    report['comparison'] = validate_video(temp, t, [2*w, h+banner_h])
    temp.rename(a.out / 'comparison.mp4')
    selected = sorted(set([0, t['frames']//4, t['frames']//2, 3*t['frames']//4, t['frames']-1]))
    reader = imageio_ffmpeg.read_frames(str(a.out / 'comparison.mp4')); meta = next(reader)
    sheet = Image.new('RGB', (2*w, (h+banner_h)*len(selected)))
    try:
        for index, raw in enumerate(reader):
            if index in selected:
                im = Image.frombytes('RGB', meta['size'], raw)
                ImageDraw.Draw(im).text((2*w-110, 30 if w < 480 else 10), f'{index/float(Fraction(t["fps"])):.3f} s', fill='black')
                sheet.paste(im, (0, selected.index(index)*(h+banner_h)))
    finally:
        reader.close()
    sheet.save(a.out / 'contact_sheet.jpg', quality=93)
    report['contact_source_frames'] = selected
    report['alignment'] = 'CFR inputs with matching frame count/rate/duration; both streams start at their first frame. Split/retime VFR and cuts explicitly.'
    write(a.out / 'validation.json', report)


if __name__ == '__main__':
    main()
