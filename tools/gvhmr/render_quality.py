#!/usr/bin/env python3
"""Render source/detector/COCO17 projection diagnostics, never motion acceptance.

Default runtime dependencies are NumPy, Pillow and PyAV (already in GVHMR).
No model weights or inference are involved. Input observations must retain all
normalized 30 Hz frames, including unsupported ones.
"""
import argparse
import csv
from fractions import Fraction
import importlib.metadata
import json
from pathlib import Path

import numpy as np

try:
    from .motion_quality import JOINT_NAMES, observation_support, stats
    from .tracking_evidence import file_sha256, validate_times
except ImportError:
    from motion_quality import JOINT_NAMES, observation_support, stats
    from tracking_evidence import file_sha256, validate_times

EDGES = [(0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9),
         (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13),
         (13, 15), (12, 14), (14, 16)]
COLORS = dict(detector=(0, 230, 255), low_score=(255, 165, 0),
              unsupported=(165, 165, 165), model=(255, 70, 220), invalid=(255, 40, 40))


def validate_arrays(observations, prediction, *, threshold=.5):
    """Enforce identical timing, raster and anatomical order without resampling."""
    times = validate_times(observations['time_seconds'])
    other_times = np.asarray(prediction['time_seconds'], dtype=float)
    if other_times.shape != times.shape or not np.allclose(other_times, times, atol=1e-6, rtol=0):
        raise ValueError('Prediction timestamps differ from source observations')
    size = np.asarray(observations['image_size'])
    if size.shape != (2,) or not np.isfinite(size).all() or np.any(size <= 0) or np.any(size != np.floor(size)):
        raise ValueError('Image raster must contain positive integer width/height')
    if not np.array_equal(size, prediction['image_size']):
        raise ValueError('Prediction and observation rasters differ')
    for name, source in [('observation', observations), ('prediction', prediction)]:
        if np.asarray(source['joint_names']).tolist() != JOINT_NAMES:
            raise ValueError(f'{name} joint_names must use exact COCO17 anatomical order')
    kp, uv, depth = (np.asarray(x, dtype=float) for x in
                     (observations['keypoints'], prediction['uv'], prediction['depth']))
    if kp.shape != (len(times), 17, 3) or uv.shape != (len(times), 17, 2) or depth.shape != (len(times), 17):
        raise ValueError('Full-frame COCO17 observation/projection shapes differ')
    support, evidence = observation_support(kp, times, size, threshold=threshold,
        detected=observations.get('detected'), reviewed_visible=observations.get('reviewed_visible'))
    valid_model = np.isfinite(uv).all(-1) & np.isfinite(depth) & (depth > 0)
    return dict(times=times, image_size=size.astype(int), keypoints=kp, uv=uv,
                depth=depth, support=support, valid_model=valid_model, evidence=evidence,
                detected=observations.get('detected'), threshold=float(threshold))


def frame_metrics(data, index):
    support, valid = data['support'][index], data['valid_model'][index]
    cohort = support & valid
    errors = np.linalg.norm(data['uv'][index, cohort] - data['keypoints'][index, cohort, :2], axis=-1)
    result = stats(errors)
    diagonal = float(np.linalg.norm(data['image_size']))
    return dict(frame=index, source_time_seconds=float(data['times'][index]),
        supported_joints=int(support.sum()), invalid_supported_predictions=int((support & ~valid).sum()),
        invalid_model_joints=int((~valid).sum()),
        invalid_depth_joints=int((~np.isfinite(data['depth'][index]) | (data['depth'][index] <= 0)).sum()),
        invalid_projection_joints=int((~np.isfinite(data['uv'][index]).all(-1)).sum()),
        residual_samples=result['samples'],
        median_error_px=result['median'], p90_error_px=result['p90'], maximum_error_px=result['maximum'],
        maximum_error_image_diagonal_fraction=result['maximum'] / diagonal if result['maximum'] is not None else None,
        tracking_support='unknown' if data['detected'] is None else ('assigned_track' if data['detected'][index] else 'no_assigned_track'))


def clipped_line(a, b, width, height):
    """Liang-Barsky clipping keeps dashed drawing bounded even for distant points."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if not np.isfinite([a, b]).all():
        return None
    with np.errstate(over='ignore'):
        delta = b - a
    if not np.isfinite(delta).all():
        return None
    lower, upper = 0., 1.
    for p, q in [(-delta[0], a[0]), (delta[0], width - 1 - a[0]),
                 (-delta[1], a[1]), (delta[1], height - 1 - a[1])]:
        if p == 0:
            if q < 0:
                return None
        else:
            ratio = q / p
            if p < 0:
                lower = max(lower, ratio)
            else:
                upper = min(upper, ratio)
    if lower > upper:
        return None
    return a + lower * delta, a + upper * delta


def draw_line(draw, a, b, color, image_size, *, width=2, dashed=False):
    segment = clipped_line(a, b, *image_size)
    if segment is None:
        return
    a, b = segment
    if not dashed:
        draw.line([tuple(a), tuple(b)], fill=color, width=width)
        return
    length = float(np.linalg.norm(b - a))
    if length == 0:
        return
    for start in np.arange(0., length, 10.):
        end = min(start + 5., length)
        draw.line([tuple(a + (b - a) * start / length), tuple(a + (b - a) * end / length)], fill=color, width=width)


def draw_overlay(source_image, data, index):
    """Pillow drawing only; no keypoints are changed or inferred here."""
    from PIL import ImageDraw
    image = source_image.convert('RGB').copy()
    size = tuple(int(x) for x in data['image_size'])
    if image.size != size:
        raise ValueError('Decoded source frame raster differs from observations')
    draw = ImageDraw.Draw(image)
    kp, uv = data['keypoints'][index], data['uv'][index]
    support, valid = data['support'][index], data['valid_model'][index]
    inside = np.isfinite(kp[:, :2]).all(-1) & (kp[:, 0] >= 0) & (kp[:, 0] < size[0]) & (kp[:, 1] >= 0) & (kp[:, 1] < size[1])
    # Model is an estimate everywhere; dashed edges have unsupported source endpoints.
    for left, right in EDGES:
        if valid[[left, right]].all():
            draw_line(draw, uv[left], uv[right], COLORS['model'], size, width=3,
                      dashed=not support[[left, right]].all())
    for joint in range(17):
        if valid[joint] and 0 <= uv[joint, 0] < size[0] and 0 <= uv[joint, 1] < size[1]:
            x, y = uv[joint]
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=COLORS['model'], width=2)
    for left, right in EDGES:
        if inside[[left, right]].all():
            both = support[[left, right]].all()
            draw_line(draw, kp[left, :2], kp[right, :2], COLORS['detector'] if both else COLORS['unsupported'],
                      size, width=1, dashed=not both)
    for joint in range(17):
        if not inside[joint]:
            continue
        if support[joint]:
            color = COLORS['detector']
        elif np.isfinite(kp[joint, 2]) and kp[joint, 2] <= data['threshold']:
            color = COLORS['low_score']
        else:
            color = COLORS['unsupported']
        x, y = kp[joint, :2]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
        if not valid[joint]:
            # Anchor invalid model symbols at the detector location when drawable.
            draw.line((x - 6, y - 6, x + 6, y + 6), fill=COLORS['invalid'], width=2)
            draw.line((x - 6, y + 6, x + 6, y - 6), fill=COLORS['invalid'], width=2)
    row = frame_metrics(data, index)
    error = 'unknown' if row['maximum_error_image_diagonal_fraction'] is None else f"{row['maximum_error_image_diagonal_fraction']:.3f} diag"
    labels = [f"frame {index}  source {row['source_time_seconds']:.3f}s  supported {row['supported_joints']}/17",
              f"max residual {error}  invalid on support {row['invalid_supported_predictions']}  bad depth {row['invalid_depth_joints']}  track {row['tracking_support']}",
              'cyan: supported detector | orange: low score | gray: unsupported detector',
              'magenta: model (dashed: unsupported source) | red X: invalid model',
              '2D consistency only; source visibility/contact are not established']
    for i, label in enumerate(labels):
        y = 3 + i * 13
        draw.text((4, y), label, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
    return image, row


def validate_video_frames(frame_times, image_size, expected_times, expected_size, *, label):
    t = np.asarray(frame_times, dtype=float)
    expected = np.asarray(expected_times, dtype=float)
    if t.shape != expected.shape or not np.allclose(t, expected, atol=1e-6, rtol=0):
        raise ValueError(f'{label} full decoding timestamps/frame count differ')
    if not np.array_equal(image_size, expected_size):
        raise ValueError(f'{label} decoded raster differs')


def write_review_sheets(samples, output, *, columns=3, per_sheet=12, tile_width=480):
    from PIL import Image, ImageDraw
    paths = []
    for first in range(0, len(samples), per_sheet):
        page = samples[first:first + per_sheet]
        height = max(1, round(page[0][1].height * tile_width / page[0][1].width))
        rows = (len(page) + columns - 1) // columns
        sheet = Image.new('RGB', (columns * tile_width, rows * (height + 22)), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, (index, image, timestamp) in enumerate(page):
            x, y = (i % columns) * tile_width, (i // columns) * (height + 22)
            sheet.paste(image.resize((tile_width, height)), (x, y))
            draw.text((x + 4, y + height + 3), f'frame {index}, source {timestamp:.3f} s', fill='black')
        path = output / f'review_{first // per_sheet + 1:02d}.png'
        sheet.save(path)
        paths.append(path.name)
    return paths


def validate_export_provenance(paths, provenance_path):
    """Bind input video and both NPZs to one export, including actor selection."""
    path = Path(provenance_path).resolve(strict=True)
    provenance = json.loads(path.read_text())
    if provenance.get('scope') != 'native_camera_observation_consistency':
        raise ValueError('Expected native-camera exporter provenance')
    hashes = {name: file_sha256(value) for name, value in paths.items()}
    if provenance['inputs']['video']['sha256'] != hashes['video']:
        raise ValueError('Source video hash differs from exporter provenance')
    for name, filename in [('observations', 'observations.npz'), ('prediction', 'native_camera.npz')]:
        if provenance['outputs'][filename] != hashes[name]:
            raise ValueError(f'{name} hash differs from exporter provenance')
    return dict(path=str(path), sha256=file_sha256(path),
                actor_id=provenance.get('actor_id'), selected_track_id=provenance.get('selected_track_id'),
                identity_review=provenance.get('identity_review', 'unknown'))


def render_quality(video_path, observations_path, prediction_path, output, *, threshold=.5,
                   review_frames=12, provenance_path=None):
    import av
    from PIL import Image
    del Image  # Dependency check before creating an output directory.
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if isinstance(review_frames, bool) or not isinstance(review_frames, int) or not 1 <= review_frames <= 48:
        raise ValueError('review_frames must be an integer between 1 and 48')
    paths = {name: Path(value).resolve(strict=True) for name, value in
             [('video', video_path), ('observations', observations_path), ('prediction', prediction_path)]}
    provenance = validate_export_provenance(paths, provenance_path or paths['observations'].parent / 'provenance.json')
    with np.load(paths['observations'], allow_pickle=False) as z:
        observations = {key: z[key].copy() for key in z.files}
    with np.load(paths['prediction'], allow_pickle=False) as z:
        prediction = {key: z[key].copy() for key in z.files}
    data = validate_arrays(observations, prediction, threshold=threshold)
    width, height = (int(value) for value in data['image_size'])
    if width % 2 or height % 2:
        raise ValueError('Exact-raster yuv420p preview requires even source width and height')
    chosen = set(np.unique(np.round(np.linspace(0, len(data['times']) - 1, min(review_frames, len(data['times'])))).astype(int)).tolist())
    source_times, rows, samples = [], [], []
    output.mkdir(parents=True, exist_ok=False)
    partial = output / 'overlay.partial.mp4'
    try:
        with av.open(str(paths['video'])) as source, av.open(str(partial), mode='w') as destination:
            stream = source.streams.video[0]
            if (stream.width, stream.height) != (width, height):
                raise ValueError('Source video raster differs from NPZ metadata')
            encoded = destination.add_stream('libx264', rate=30)
            encoded.width, encoded.height, encoded.pix_fmt = width, height, 'yuv420p'
            encoded.options = {'crf': '18', 'preset': 'veryfast'}
            for index, frame in enumerate(source.decode(stream)):
                if index >= len(data['times']) or frame.pts is None:
                    raise ValueError('Source has extra frames or missing timestamps')
                timestamp = float(frame.pts * frame.time_base)
                if abs(timestamp - data['times'][index]) > 1e-6:
                    raise ValueError(f'Source timestamp differs at frame {index}; do not retime observations')
                source_times.append(timestamp)
                image, row = draw_overlay(frame.to_image(), data, index)
                rows.append(row)
                if index in chosen:
                    samples.append((index, image.copy(), timestamp))
                result = av.VideoFrame.from_image(image)
                result.pts, result.time_base = index, Fraction(1, 30)
                for packet in encoded.encode(result):
                    destination.mux(packet)
            for packet in encoded.encode():
                destination.mux(packet)
        validate_video_frames(source_times, [width, height], data['times'], data['image_size'], label='Source')
        decoded_times = []
        with av.open(str(partial)) as container:
            stream = container.streams.video[0]
            decoded_size = [stream.width, stream.height]
            for frame in container.decode(stream):
                if frame.pts is None or [frame.width, frame.height] != decoded_size:
                    raise ValueError('Encoded output lacks timestamps or changes raster')
                decoded_times.append(float(frame.pts * frame.time_base))
        validate_video_frames(decoded_times, decoded_size, np.arange(len(data['times'])) / 30,
                              data['image_size'], label='Output')
        partial.rename(output / 'overlay.mp4')
        sheets = write_review_sheets(samples, output)
        with (output / 'frame_metrics.csv').open('x', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        versions = {}
        for name in ('numpy', 'Pillow', 'av'):
            versions[name] = importlib.metadata.version(name)
        report = dict(schema_version=1, status='rendered_and_fully_decoded', motion_accepted=False,
            scope='native_camera_observation_overlay', source_frames_decoded=len(source_times),
            output_frames_decoded=len(decoded_times), fps=30, duration_seconds=len(decoded_times) / 30,
            output_zero_origin_source_offset_seconds=float(data['times'][0]), image_size=[width, height],
            confidence_threshold=threshold, evidence=data['evidence'], versions=versions,
            export_provenance=provenance,
            visual_review='pending', sampled_review_frame_indices=[row[0] for row in samples], review_sheets=sheets,
            frame_metrics=rows, inputs={name: dict(path=str(path), sha256=file_sha256(path)) for name, path in paths.items()},
            implementation_sha256=file_sha256(__file__),
            outputs={name: file_sha256(output / name) for name in ['overlay.mp4', 'frame_metrics.csv', *sheets]},
            legend=COLORS, limitations=[
                'Detector confidence and tracker assignments do not establish visibility, occlusion or physical identity.',
                'Dashed model limbs lack supported source endpoints; the motion remains an estimate.',
                'Invalid model markers use drawable detector locations as anchors, not recovered model projections.',
                'ViTPose also feeds GVHMR; 2D agreement is not independent 3D, room or contact accuracy.',
                'Sampled sheets are review aids; rendering and full decoding do not constitute human visual review.'])
        (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        return report
    except Exception as error:
        (output / 'failure.json').write_text(json.dumps(dict(status='failed', error=str(error), source_frames_decoded=len(source_times)), indent=2) + '\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--prediction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, help='Defaults to provenance.json beside observations; binds source and NPZ hashes')
    parser.add_argument('--confidence-threshold', type=float, default=.5)
    parser.add_argument('--review-frames', type=int, default=12)
    args = parser.parse_args()
    report = render_quality(args.video, args.observations, args.prediction, args.output,
                            threshold=args.confidence_threshold, review_frames=args.review_frames,
                            provenance_path=args.provenance)
    print(json.dumps(dict(output=str(args.output), frames=report['output_frames_decoded'], visual_review='pending')))


if __name__ == '__main__':
    main()
