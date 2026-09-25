#!/usr/bin/env python3
"""Child-process compatibility and reversible instrumentation for trusted GVHMR."""
import argparse
from contextlib import contextmanager, ExitStack
from functools import wraps
import inspect
import json
import math
import numbers
import os
from pathlib import Path
import runpy
import sys

BODY_INPUT_MODES = ('keep', 'confidence-only', 'confidence-and-features')


def _numpy(value):
    import numpy as np
    return value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)


def gate_body_conditions(data, detected, mode):
    """Clone ablated inputs only; body-box support is not physical visibility."""
    import numpy as np
    if mode not in BODY_INPUT_MODES:
        raise ValueError('Unknown unsupported-body input mode')
    if mode == 'keep':
        return data
    support = np.asarray(detected)
    kp, features = data['kp2d'], data['f_imgseq']
    if support.dtype != np.bool_ or support.shape != (len(kp),):
        raise ValueError('Body support must be an exact boolean per-frame mask')
    if kp.shape != (len(support), 17, 3) or features.ndim != 2 or len(features) != len(support):
        raise ValueError('Invalid keypoint/image-feature frame shapes')
    if not np.isfinite(_numpy(kp)).all() or not np.isfinite(_numpy(features)).all():
        raise ValueError('Body conditions must be finite')
    result = dict(data)
    result['kp2d'] = kp.clone() if hasattr(kp, 'clone') else kp.copy()
    mask = ~support
    if hasattr(kp, 'device') and hasattr(kp, 'detach'):
        import torch
        mask = torch.as_tensor(mask, device=kp.device)
    result['kp2d'][mask, :, 2] = 0
    if mode == 'confidence-and-features':
        result['f_imgseq'] = features.clone() if hasattr(features, 'clone') else features.copy()
        if hasattr(features, 'detach'):
            import torch
            mask = torch.as_tensor(~support, device=features.device)
        result['f_imgseq'][mask] = 0
    return result


def validated_body_support(data, raw_tracking_path, boxes_path, expected_video,
                           time_seconds, image_size, actor_id=None):
    """Bind retained history to actual decoded video, dense cache and model data."""
    import numpy as np
    import torch
    try:
        from .tracking_evidence import validated_detected, video_timeline, file_sha256, validate_times
    except ImportError:
        from tracking_evidence import validated_detected, video_timeline, file_sha256, validate_times
    times = validate_times(time_seconds)
    actual = video_timeline(expected_video)
    if not np.array_equal(actual['time_seconds'], times) or not np.array_equal(actual['image_size'], image_size):
        raise ValueError('Body gate source PTS/raster differs from the exact normalized video')
    raw_path, boxes_path = Path(raw_tracking_path).resolve(strict=True), Path(boxes_path).resolve(strict=True)
    raw = json.loads(raw_path.read_text())
    if not np.array_equal(np.asarray(raw.get('time_seconds')), times):
        raise ValueError('Raw body-support timestamps must match exact normalized PTS')
    boxes = torch.load(boxes_path, map_location='cpu', weights_only=False)
    digest = file_sha256(expected_video)
    detected = validated_detected(raw, times, image_size, digest, _numpy(boxes['bbx_xyxy']))
    if actor_id is not None and raw.get('actor_id') != actor_id:
        raise ValueError('Body gate actor differs from reviewed tracking evidence')
    if _numpy(data['length']).shape != () or _numpy(data['length']).item() != len(times):
        raise ValueError('Body gate must retain the full source length')
    if not np.array_equal(_numpy(data['bbx_xys']), _numpy(boxes['bbx_xys'])):
        raise ValueError('Model boxes differ from the history-bound dense cache')
    return detected, dict(source_sha256=digest, actor_id=raw.get('actor_id'),
        raw_tracking=dict(path=str(raw_path), sha256=file_sha256(raw_path)),
        boxes=dict(path=str(boxes_path), sha256=file_sha256(boxes_path)),
        selection_policy=raw.get('selection_policy'), selected_track_id=raw.get('selected_track_id'),
        selected_track_ids=raw.get('selected_track_ids'),
        dense_bbx_xyxy_sha256=raw['dense_bbx_xyxy_sha256'])


@contextmanager
def unsupported_body_inputs(path, *, mode, raw_tracking_path, boxes_path, expected_video,
                            time_seconds, image_size, actor_id=None, demo_class=None):
    """Reversibly gate cloned inputs at the same pre-predict point as the ablation."""
    import numpy as np
    try:
        from .tracking_evidence import file_sha256, _replace_json
    except ImportError:
        from tracking_evidence import file_sha256, _replace_json
    if mode not in BODY_INPUT_MODES[1:]:
        raise ValueError('Body gate context requires an explicit non-keep mode')
    path = Path(path).resolve()
    arrays_path = path.with_suffix('.npz')
    if path.exists() or arrays_path.exists():
        raise FileExistsError('Body gate evidence must be fresh')
    if demo_class is None:
        from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL
        demo_class = DemoPL
    original = demo_class.predict
    signature = inspect.signature(original)
    if 'data' not in signature.parameters:
        raise ValueError('Audited DemoPL.predict data parameter is unavailable')
    report = dict(schema_version=1, kind='gvhmr_body_input_gating', mode=mode,
        status='running', calls=0, source_time_seconds=[float(v) for v in time_seconds], image_size=[int(v) for v in image_size],
        implementation_sha256=file_sha256(__file__),
        gating_rule='No usable selected target body box; conservative input gating, not physical visibility',
        remaining_prior='Bbox/CLIFF condition and bbox-derived camera depth remain active',
        raw_observations_modified=False, observed_inputs_preserved=True,
        observed_outputs_preservation_guaranteed=False, motion_accepted=False,
        limitations=['Head-only detections may contain valid head evidence despite unusable body boxes.',
            'Zero raw image features retain learned affine terms; they are the training null-input representation.',
            'Temporal context and shape averaging may alter predictions on supported frames.'])
    upstream_path = Path(inspect.getfile(inspect.unwrap(original)))
    if upstream_path.is_file():
        report['upstream_predict_source'] = dict(path=str(upstream_path.resolve()), sha256=file_sha256(upstream_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(report, stream, indent=2)

    @wraps(original)
    def predict(self, *args, **kwargs):
        if report['calls']:
            raise ValueError('One body-gating sidecar supports exactly one prediction')
        report['calls'] += 1
        bound = signature.bind(self, *args, **kwargs)
        data = bound.arguments['data']
        detected, evidence = validated_body_support(data, raw_tracking_path, boxes_path,
            expected_video, time_seconds, image_size, actor_id)
        effective = gate_body_conditions(data, detected, mode)
        arrays = dict(time_seconds=np.asarray(time_seconds), detected=detected,
            original_kp2d=_numpy(data['kp2d']), effective_kp2d=_numpy(effective['kp2d']),
            original_f_imgseq=_numpy(data['f_imgseq']), effective_f_imgseq=_numpy(effective['f_imgseq']))
        for name in ('length', 'bbx_xys', 'K_fullimg', 'cam_angvel'):
            arrays[name] = _numpy(data[name])
        with arrays_path.open('xb') as stream:
            np.savez_compressed(stream, **arrays)
        report.update(evidence, usable_body_box_frames=int(detected.sum()),
            gated_frames=int((~detected).sum()), gated_frame_indices=np.flatnonzero(~detected).tolist(),
            effective_inputs=dict(path=str(arrays_path), sha256=file_sha256(arrays_path)))
        _replace_json(path, report)
        bound.arguments['data'] = effective
        return original(*bound.args, **bound.kwargs)

    demo_class.predict = predict
    try:
        yield
        if report['calls'] != 1:
            raise ValueError('Body-gating prediction did not execute; stale output cache is unsupported')
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        demo_class.predict = original
        _replace_json(path, report)


def legacy_compatibility():
    """Keep legacy NumPy/Chumpy aliases inside the model child process."""
    import numpy as np
    for name, value in {'bool': bool, 'int': int, 'float': float, 'complex': complex,
                        'object': object, 'str': str, 'unicode': str}.items():
        if name not in np.__dict__:
            setattr(np, name, value)
    if not hasattr(inspect, 'getargspec'):
        from collections import namedtuple
        ArgSpec = namedtuple('ArgSpec', 'args varargs keywords defaults')
        def getargspec(function):
            spec = inspect.getfullargspec(function)
            return ArgSpec(spec.args, spec.varargs, spec.varkw, spec.defaults)
        inspect.getargspec = getargspec


@contextmanager
def disable_postprocessing(pipeline_class=None):
    """DemoPL.predict hardcodes postproc=True; override the called pipeline only."""
    if pipeline_class is None:
        from hmr4d.model.gvhmr.pipeline.gvhmr_pipeline import Pipeline
        pipeline_class = Pipeline
    original = pipeline_class.forward
    signature = inspect.signature(original)
    if 'postproc' not in signature.parameters:
        raise ValueError('Upstream Pipeline.forward no longer exposes the audited postproc argument')

    @wraps(original)
    def forward(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.arguments['postproc'] = False
        return original(*bound.args, **bound.kwargs)

    pipeline_class.forward = forward
    try:
        yield
    finally:
        pipeline_class.forward = original


@contextmanager
def overview_camera(renderer):
    original = renderer.get_global_cameras_static
    @wraps(original)
    def camera(*args, **kwargs):
        kwargs['beta'] = float(os.environ.get('GVHMR_GLOBAL_CAMERA_BETA', '4.0'))
        return original(*args, **kwargs)
    renderer.get_global_cameras_static = camera
    try:
        yield
    finally:
        renderer.get_global_cameras_static = original


@contextmanager
def dpvo_timing(path, time_seconds, expected_video, *, mode='source-pts', dpvo_class=None):
    """Replace only the DPVO timestamp argument; retain upstream timer profiling.

    DPVO.counter counts incoming video frames, including frames omitted from its
    optimization window. This is distinct from its current keyframe count n.
    No sidecar I/O occurs inside a timed DPVO call.
    """
    try:
        from .tracking_evidence import validate_times, file_sha256, _replace_json
    except ImportError:
        from tracking_evidence import validate_times, file_sha256, _replace_json
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    times = validate_times(time_seconds).tolist()
    if mode not in ('source-pts', 'upstream-wallclock'):
        raise ValueError('Unknown DPVO timestamp mode')
    video = Path(expected_video).resolve(strict=True)
    if dpvo_class is None:
        from dpvo.dpvo import DPVO
        dpvo_class = DPVO
    original = dpvo_class.__call__
    signature = inspect.signature(original)
    if 'tstamp' not in signature.parameters:
        raise ValueError('Audited DPVO.__call__ tstamp parameter is unavailable')
    calls = []
    instance = None
    report = dict(schema_version=1, kind='gvhmr_dpvo_timing_evidence', mode=mode,
        source=dict(path=str(video), sha256=file_sha256(video)),
        source_time_seconds=times, expected_frames=len(times), calls=calls,
        status='running', completed_calls=0, single_instance=True,
        frame_index_source='DPVO.counter before each call; never DPVO.n',
        algorithm_modified=False, timestamp_argument_replaced=mode == 'source-pts',
        upstream_timer_profiling_unchanged=True, implementation_sha256=file_sha256(__file__))
    original_path = Path(inspect.getfile(inspect.unwrap(original)))
    if original_path.is_file():
        report['upstream_dpvo_source'] = dict(path=str(original_path.resolve()), sha256=file_sha256(original_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')

    @wraps(original)
    def timed(self, *args, **kwargs):
        nonlocal instance
        if instance is None:
            instance = self
        elif instance is not self:
            report['single_instance'] = False
            raise ValueError('DPVO timing evidence allows exactly one instance')
        index = getattr(self, 'counter', None)
        if isinstance(index, bool) or not isinstance(index, numbers.Integral) or index != len(calls) or index >= len(times):
            raise ValueError('DPVO.counter must match the next exact source frame within timeline bounds')
        bound = signature.bind(self, *args, **kwargs)
        received = bound.arguments['tstamp']
        if isinstance(received, bool) or not isinstance(received, numbers.Real) or not math.isfinite(received):
            raise ValueError('Upstream DPVO timestamp must be a finite scalar')
        supplied = times[index] if mode == 'source-pts' else float(received)
        if calls and supplied <= calls[-1]['supplied_time_seconds']:
            raise ValueError('Supplied DPVO timestamps must be strictly increasing')
        bound.arguments['tstamp'] = supplied
        row = dict(frame_index=int(index), source_time_seconds=times[index],
            upstream_received_time_seconds=float(received), supplied_time_seconds=supplied,
            status='started')
        calls.append(row)
        result = original(*bound.args, **bound.kwargs)
        if getattr(self, 'counter', None) != index + 1:
            raise ValueError('DPVO.counter did not advance exactly once for the supplied frame')
        row['status'] = 'completed'
        report['completed_calls'] += 1
        return result

    dpvo_class.__call__ = timed
    try:
        yield
        if len(calls) != len(times) or report['completed_calls'] != len(times):
            raise ValueError('DPVO did not consume every exact source frame; cached/skipped or incomplete run')
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        dpvo_class.__call__ = original
        _replace_json(path, report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher-options', type=Path)
    parser.add_argument('script', type=Path)
    parser.add_argument('script_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    script = args.script.resolve(strict=True)
    options = json.loads(args.launcher_options.read_text()) if args.launcher_options else None
    if options is not None:
        legacy = {'raw_tracking_path', 'selected_track_id', 'actor_id', 'expected_video', 'time_seconds', 'no_postprocess'}
        expected = legacy | {'cached_raw_tracking_path', 'actor_review_path', 'camera_mode', 'camera_estimator',
                             'dpvo_timing', 'dpvo_timing_path'}
        with_body_gate = expected | {'unsupported_body_inputs', 'body_input_evidence_path', 'image_size', 'bbx_path'}
        if not isinstance(options, dict) or set(options) not in (legacy, expected, with_body_gate) or not isinstance(options['no_postprocess'], bool):
            raise ValueError('Invalid launcher instrumentation options')
        if expected <= set(options):
            use_dpvo = options['camera_mode'] == 'moving' and options['camera_estimator'] == 'dpvo'
            if options['camera_mode'] not in ('static', 'moving') or options['camera_estimator'] not in ('dpvo', 'pi3x') or \
                    (use_dpvo and (options['dpvo_timing'] not in ('source-pts', 'upstream-wallclock') or not options['dpvo_timing_path'])) or \
                    (not use_dpvo and (options['dpvo_timing'] is not None or options['dpvo_timing_path'] is not None)):
                raise ValueError('Invalid conditional DPVO instrumentation options')
        if set(options) == with_body_gate:
            mode = options['unsupported_body_inputs']
            if mode not in BODY_INPUT_MODES or (mode == 'keep') != (options['body_input_evidence_path'] is None):
                raise ValueError('Invalid conditional unsupported-body input options')
        if script.name != 'demo.py' or script.parent.name != 'demo':
            raise ValueError('Tracking/postprocessing instrumentation requires the upstream demo.py')
    legacy_compatibility()
    old_argv, old_path = sys.argv, sys.path.copy()
    sys.argv = [str(script), *args.script_args]
    sys.path.insert(0, str(script.parents[2]))
    try:
        with ExitStack() as stack:
            if script.name == 'demo.py' and script.parent.name == 'demo':
                from hmr4d.utils.vis import renderer
                stack.enter_context(overview_camera(renderer))
            if options is not None:
                try:
                    from .tracking_evidence import record_tracking_evidence
                except ImportError:
                    from tracking_evidence import record_tracking_evidence
                stack.enter_context(record_tracking_evidence(options['raw_tracking_path'],
                    selected_track_id=options['selected_track_id'], actor_id=options['actor_id'],
                    expected_video=options['expected_video'], time_seconds=options['time_seconds'],
                    cached_raw_tracking_path=options.get('cached_raw_tracking_path'), actor_review_path=options.get('actor_review_path')))
                if options.get('unsupported_body_inputs', 'keep') != 'keep':
                    stack.enter_context(unsupported_body_inputs(options['body_input_evidence_path'],
                        mode=options['unsupported_body_inputs'], raw_tracking_path=options['raw_tracking_path'],
                        boxes_path=options['bbx_path'], expected_video=options['expected_video'],
                        time_seconds=options['time_seconds'], image_size=options['image_size'], actor_id=options['actor_id']))
                if options.get('dpvo_timing') is not None:
                    stack.enter_context(dpvo_timing(options['dpvo_timing_path'], options['time_seconds'],
                                                   options['expected_video'], mode=options['dpvo_timing']))
                if options['no_postprocess']:
                    stack.enter_context(disable_postprocessing())
            runpy.run_path(str(script), run_name='__main__')
    finally:
        sys.argv = old_argv
        sys.path[:] = old_path


if __name__ == '__main__':
    main()
