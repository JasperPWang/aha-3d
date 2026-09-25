"""Explicit scene-frame sampling; the final recipe and saved animation stay intact."""
from fractions import Fraction

from aha3d.config import timing


def plan(source_timing, fps='5'):
    source = timing({k: source_timing[k] for k in ('fps', 'frames', 'start')})
    rate = Fraction(source['fps'])
    count = source['frames']
    if fps == 'source':
        target = rate
    else:
        try:
            target = Fraction(str(fps))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError('Preview FPS must be positive or source') from exc
        if not 0 < target <= 1000:
            raise ValueError('Preview FPS must be positive and at most 1000, or source')
    duration = Fraction(count, 1) / rate
    samples = min(count, max(min(2, count), round(duration * min(target, rate))))
    frames = ([source['start']] if samples == 1 else
              [source['start'] + round(Fraction(i * (count-1), samples-1)) for i in range(samples)])
    # A rational presentation rate preserves clip duration even at fractional
    # source FPS; evaluated poses always use the original integer scene frames.
    output = timing(dict(fps=str(Fraction(samples, 1) / duration), frames=samples, start=1))
    return dict(schema_version=1, requested_fps=str(fps), source_timing=source,
                preview_timing=output, scene_frames=frames,
                source_times_seconds=[float(Fraction(f-source['start'], 1)/rate) for f in frames],
                temporally_sampled=samples < count,
                limitations='Covers the source timeline and endpoints; sampled images do not prove every-frame visual correctness. Final delivery retains the requested source timing and full decoding.')


def validate_review(review, sampling):
    if sampling and sampling.get('temporally_sampled'):
        if (review.get('preview_reviewed') is not True or
                review.get('reviewed_scene_frames') != sampling['scene_frames'] or
                not review.get('sampling_limitations', '').strip()):
            raise ValueError('Sampled preview review needs preview_reviewed, exact reviewed_scene_frames and sampling_limitations')
    elif review.get('whole_clip_reviewed') is not True:
        raise ValueError('Record full-duration visual review')
