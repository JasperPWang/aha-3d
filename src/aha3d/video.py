"""Encode and independently decode a complete image sequence inside the job."""
from fractions import Fraction
from pathlib import Path
import subprocess
import sys

from .io import digest, read, write


def main(run):
    import imageio_ffmpeg
    run = Path(run)
    recipe = read(run / 'snapshot/recipe.json')
    timing, render = recipe['timing'], recipe['render']
    folder = run / 'stages/render/frames'
    expected = [f'frame_{f:06d}.png' for f in range(timing['start'], timing['end'] + 1)]
    if sorted(p.name for p in folder.glob('*.png')) != expected:
        raise ValueError('Video requires the exact complete frame sequence')
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = run / 'stages/video'; out.mkdir(parents=True, exist_ok=True)
    temporary, video = out / 'video.partial.mp4', out / 'video.mp4'
    subprocess.run([exe, '-nostdin', '-v', 'error', '-y', '-framerate', timing['fps'], '-start_number', str(timing['start']),
        '-i', str(folder / 'frame_%06d.png'), '-frames:v', str(timing['frames']), '-c:v', 'libx264', '-threads', '4',
        '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', str(temporary)], check=True)
    subprocess.run([exe, '-nostdin', '-v', 'error', '-xerror', '-i', str(temporary), '-f', 'null', '-'], check=True)
    count, seconds = imageio_ffmpeg.count_frames_and_secs(str(temporary))
    reader = imageio_ffmpeg.read_frames(str(temporary)); metadata = next(reader); reader.close()
    if count != timing['frames'] or abs(seconds - timing['duration_seconds']) > .02:
        raise ValueError(f'Wrong decoded timing: {count} frames, {seconds} seconds')
    if tuple(metadata['size']) != (render['width'], render['height']) or abs(metadata['fps'] - float(Fraction(timing['fps']))) > .02:
        raise ValueError(f'Wrong decoded dimensions/rate: {metadata}')
    temporary.replace(video)
    write(out / 'validation.json', {'full_decode_pass': True, 'decoded_frames': count,
        'fps': timing['fps'], 'duration_seconds': timing['duration_seconds'], 'decoder_duration_seconds': seconds,
        'resolution': list(metadata['size']), 'video': 'video.mp4', 'sha256': digest(video)})


if __name__ == '__main__':
    main(sys.argv[1])
