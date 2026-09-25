#!/usr/bin/env python3
"""GVHMR BEDLAM2 launcher on the local GPU (device 0 unless --gpu or CUDA_VISIBLE_DEVICES says otherwise)."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d import runtime  # noqa: E402  (stdlib-only run identity)
REVISION = 'cac2d9dacc6b4b6f145ca02c2e6e616719fff916'
NORMALIZATION_FILTER = 'setpts=PTS-STARTPTS,fps=30:eof_action=pass'
ASSETS = [
    'inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz',
    'inputs/checkpoints/body_models/smpl/SMPL_NEUTRAL.pkl',
    'inputs/checkpoints/hmr2/epoch=10-step=25000.ckpt',
    'inputs/checkpoints/vitpose/vitpose-h-multi-coco.pth',
    'inputs/checkpoints/yolo/yolov8x.pt',
]
MODULES = ['torch', 'pytorch3d', 'pytorch_lightning', 'hydra', 'hydra_zen',
           'smplx', 'ultralytics', 'timm', 'cv2', 'av', 'cython_bbox', 'lap', 'yacs', 'omegaconf']


def call(args, **kwargs):
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def git_command(repo, *args):
    """Scope NFS ownership trust to this command and this exact checkout."""
    repo = Path(repo).resolve()
    return ['git', '-c', f'safe.directory={repo}', '-C', str(repo), *args]


def configure_execution(gpu, *, environ=None, hostnames=None):
    """Pure local GPU-visibility construction; no Torch import or GPU query."""
    env = dict(os.environ if environ is None else environ)
    hosts = hostnames or (socket.gethostname(), socket.getfqdn())
    env['INDOOR_RUN_ID'] = env.get('INDOOR_RUN_ID') or runtime.run_id()
    if gpu is not None and (isinstance(gpu, bool) or not isinstance(gpu, int) or gpu < 0):
        raise ValueError('--gpu must be a nonnegative integer')
    if gpu is None:
        if 'CUDA_VISIBLE_DEVICES' in env:
            gpu_policy = 'inherited_cuda_visible_devices'
        else:
            env['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
            env['CUDA_VISIBLE_DEVICES'] = '0'
            gpu_policy = 'default_physical_device_0'
    else:
        if 'CUDA_VISIBLE_DEVICES' in env:
            devices = [value.strip() for value in env['CUDA_VISIBLE_DEVICES'].split(',')]
            if not devices or any(not value.isdecimal() for value in devices):
                raise ValueError('Existing CUDA_VISIBLE_DEVICES is empty or uses nonnumeric identifiers; cannot safely map --gpu physical index')
            if gpu not in [int(value) for value in devices]:
                raise ValueError('--gpu is outside the existing CUDA_VISIBLE_DEVICES restriction')
            # Existing numeric masks belong to their original CUDA device order.
            gpu_policy = 'explicit_device_within_inherited_numeric_mask'
        else:
            env['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
            gpu_policy = 'explicit_physical_device_index'
        env['CUDA_VISIBLE_DEVICES'] = str(gpu)
    return env, dict(execution='local', host=hosts[0], gpu_argument=gpu,
        gpu_selection_policy=gpu_policy, cuda_visible_devices=env.get('CUDA_VISIBLE_DEVICES'),
        cuda_device_order=env.get('CUDA_DEVICE_ORDER'), run_id=env['INDOOR_RUN_ID'])


def probe_video(path):
    import av
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        timestamps = []
        last_duration = 0.0
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError(f'Missing presentation timestamp in {path}')
            timestamps.append(float(frame.pts * frame.time_base))
            last_duration = float((getattr(frame, 'duration', 0) or 0) * frame.time_base)
        if not timestamps:
            raise ValueError(f'No decodable video frames in {path}')
        fps = float(stream.average_rate or 30)
        duration = timestamps[-1] - timestamps[0] + (last_duration or 1 / fps)
        return {'streams': [{'nb_read_frames': str(len(timestamps)),
                             'duration': str(duration), 'avg_frame_rate': str(stream.average_rate),
                             'width': stream.width, 'height': stream.height,
                             'time_base': str(stream.time_base)}],
                'presentation_timestamps_seconds': timestamps, 'probe_backend': 'PyAV'}


def check_timing(reference, candidate):
    ref = reference['streams'][0]
    out = candidate['streams'][0]
    if int(ref['nb_read_frames']) != int(out['nb_read_frames']):
        raise ValueError('Output frame count differs from normalized source')
    if abs(float(ref['duration']) - float(out['duration'])) > 1 / 30 + 1e-4:
        raise ValueError('Output duration differs from normalized source')


def normalization_frame_count(source):
    """Bound EOF pass to the nearest complete 30 Hz presentation duration."""
    duration = float(source['streams'][0]['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Source presentation duration must be finite and positive')
    return max(1, math.floor(duration * 30 + .5))


def normalization_timing(source, normalized):
    try:
        from .tracking_evidence import validate_times
    except ImportError:
        from tracking_evidence import validate_times
    times = validate_times(normalized['presentation_timestamps_seconds'])
    if abs(float(times[0])) > 1e-6:
        raise ValueError('Normalized video must start at zero PTS after source-origin removal')
    before, after = source['streams'][0], normalized['streams'][0]
    duration_source, duration_normalized = float(before['duration']), float(after['duration'])
    tolerance = 1 / 30 + 1e-4
    if abs(duration_normalized - duration_source) > tolerance:
        raise ValueError('Normalized duration differs from source by more than one 30 Hz frame')
    target_frames = normalization_frame_count(source)
    if len(times) != target_frames or int(after['nb_read_frames']) != target_frames:
        raise ValueError('Normalized frame count differs from the bounded source-duration target')
    if [before['width'], before['height']] != [after['width'], after['height']]:
        raise ValueError('Temporal normalization changed the source raster')
    offset = float(source['presentation_timestamps_seconds'][0])
    return dict(filter=NORMALIZATION_FILTER, source_first_pts_seconds=offset,
        target_frame_count=target_frames,
        endpoint_policy='fps EOF pass bounded by max(1, floor(source_duration_seconds * 30 + 0.5)) frames',
        normalized_first_pts_seconds=float(times[0]), source_duration_seconds=duration_source,
        normalized_duration_seconds=duration_normalized, duration_difference_seconds=duration_normalized-duration_source,
        duration_tolerance_seconds=tolerance,
        source_to_normalized_time='normalized_time_seconds = source_time_seconds - source_first_pts_seconds',
        normalized_to_source_time='source_time_seconds = normalized_time_seconds + source_first_pts_seconds',
        mapping_scope='nominal presentation-time relation; fps resampling may duplicate or drop source frames')


def validate_camera_selection(camera, estimator, bundle):
    if camera == 'static':
        if bundle is not None or estimator != 'dpvo':
            raise ValueError('Static camera uses identity rotations; Pi3X estimator/bundle requires --camera moving')
    elif estimator == 'pi3x' and bundle is None:
        raise ValueError('--camera-estimator pi3x requires --pi3x-bundle')
    elif estimator == 'dpvo' and bundle is not None:
        raise ValueError('--pi3x-bundle requires --camera-estimator pi3x')


def validate_tracking_selection(track_id, cached_raw, review):
    if (cached_raw is None) != (review is None):
        raise ValueError('--cached-raw-tracking and --actor-review must be supplied together')
    if cached_raw is not None and track_id is not None:
        raise ValueError('Reviewed fragments are mutually exclusive with --track-id')


def preflight(repo, checkpoint, static, camera_estimator='dpvo', pi3x_bundle=None):
    missing = [str(repo / p) for p in ASSETS if not (repo / p).is_file()]
    for path in [checkpoint, repo / 'tools/demo/demo.py']:
        if not path.is_file():
            missing.append(str(path))
    if not static and camera_estimator == 'dpvo':
        path = repo / 'inputs/checkpoints/dpvo/dpvo.pth'
        if not path.is_file():
            missing.append(str(path))
    if not static and camera_estimator == 'pi3x':
        for name in ('inputs.json', 'cameras.json', 'camera_review.json'):
            if pi3x_bundle is None or not (Path(pi3x_bundle) / name).is_file():
                missing.append(str(Path(pi3x_bundle or '<pi3x-bundle>') / name))
    modules = MODULES + ([] if static else ['dpvo'] if camera_estimator == 'dpvo' else ['scipy'])
    unavailable = [m for m in modules if importlib.util.find_spec(m) is None]
    binaries = [m for m in ['ffmpeg'] if shutil.which(m) is None]
    revision = None
    if (repo / '.git').exists():
        revision = call(git_command(repo, 'rev-parse', 'HEAD'), capture_output=True, text=True).stdout.strip()
    return dict(missing_files=missing, missing_modules=unavailable, missing_binaries=binaries,
                camera_estimator='static_identity' if static else camera_estimator,
                intrinsics_estimator='unchanged upstream estimate_K; Pi3X intrinsics unused',
                source_revision=revision, expected_revision=REVISION,
                ready_for_attempt=not (missing or unavailable or binaries) and revision == REVISION,
                quality_validated=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'run'])
    parser.add_argument('--repo', type=Path, default=Path(os.environ.get('GVHMR_ROOT', ROOT / '.runtime/gvhmr-bedlam2')))
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--camera', choices=['static', 'moving'], required=True,
                        help='Use static only when confirmed from the source video.')
    parser.add_argument('--camera-estimator', choices=['dpvo', 'pi3x'], default='dpvo',
                        help='Moving camera rotation source; DPVO remains the default')
    parser.add_argument('--pi3x-bundle', type=Path, help='Hash-bound cameras.json/inputs.json/camera_review.json bundle')
    parser.add_argument('--dpvo-timing', choices=['source-pts', 'upstream-wallclock'], default='source-pts',
                        help='DPVO timestamp input; source PTS is default, wall clock is a recorded ablation')
    parser.add_argument('--video', type=Path)
    parser.add_argument('--output', type=Path, help='New claimed runs/<scene>/<run> directory')
    parser.add_argument('--gpu', type=int, help='Physical GPU index; default: inherited CUDA_VISIBLE_DEVICES, else device 0')
    parser.add_argument('--track-id', type=int, help='Explicit numeric tracker ID; otherwise preserve upstream area-based selection')
    parser.add_argument('--cached-raw-tracking', type=Path, help='Exact retained raw observations for reviewed actor fragments')
    parser.add_argument('--actor-review', type=Path, help='Hash-bound reviewed actor-fragment selection')
    parser.add_argument('--actor-id', help='Reviewed actor label; does not infer identity from appearance')
    parser.add_argument('--unsupported-body-inputs', choices=['keep', 'confidence-only', 'confidence-and-features'], default='keep',
                        help='Optional conservative gate on frames without a usable selected body box; keep preserves existing behavior')
    parser.add_argument('--no-postprocess', action='store_true', help='Controlled ablation: disable upstream stationary-joint correction and IK')
    args = parser.parse_args(argv)
    try:
        validate_camera_selection(args.camera, args.camera_estimator, args.pi3x_bundle)
        validate_tracking_selection(args.track_id, args.cached_raw_tracking, args.actor_review)
        use_dpvo = args.camera == 'moving' and args.camera_estimator == 'dpvo'
        if not use_dpvo and args.dpvo_timing != 'source-pts':
            raise ValueError('--dpvo-timing upstream-wallclock requires moving-camera DPVO')
        execution_env, execution_report = configure_execution(args.gpu)
    except ValueError as error:
        parser.error(str(error))
    # Set visibility before preflight or any subsequent import can initialize Torch.
    for key in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER'):
        if key in execution_env:
            os.environ[key] = execution_env[key]
    repo = args.repo.expanduser().resolve()
    checkpoint = (args.checkpoint or repo / 'inputs/checkpoints/gvhmr/gvhmr_b1b2.ckpt').expanduser().resolve()
    pi3x_bundle = args.pi3x_bundle.expanduser().resolve() if args.pi3x_bundle else None
    report = preflight(repo, checkpoint, args.camera == 'static', args.camera_estimator, pi3x_bundle)
    report.update(camera_estimator='static_identity' if args.camera == 'static' else args.camera_estimator,
                  intrinsics_estimator='unchanged upstream estimate_K; Pi3X intrinsics unused',
                  dpvo_timing=args.dpvo_timing if use_dpvo else 'not_used',
                  unsupported_body_inputs=args.unsupported_body_inputs)
    report.update(execution_report)
    if args.action == 'check':
        print(json.dumps(report, indent=2))
        return 0 if report['ready_for_attempt'] else 2
    if not args.video or not args.output:
        parser.error('run requires --video and --output')
    if not report['ready_for_attempt']:
        print(json.dumps(report, indent=2))
        return 2
    video = args.video.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never reuse stale upstream caches.
    probe = probe_video(video)
    (output / 'source_probe.json').write_text(json.dumps(probe, indent=2) + '\n')
    # Upstream motion code assumes 30 Hz. Resample by timestamps instead of relabelling frames.
    normalized = output / '0_input_video.mp4'
    # Default fps EOF rounding drops clip31's last frame. EOF pass retains it;
    # the duration-derived bound prevents an extra endpoint frame on 30 Hz clips.
    call(['ffmpeg', '-v', 'error', '-n', '-i', video, '-map', '0:v:0', '-an',
          '-vf', NORMALIZATION_FILTER, '-frames:v', normalization_frame_count(probe),
          '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', normalized])
    call(['ffmpeg', '-v', 'error', '-xerror', '-i', normalized, '-f', 'null', '-'])
    normalized_probe = probe_video(normalized)
    try:
        from .tracking_evidence import validate_times, file_sha256
    except ImportError:
        from tracking_evidence import validate_times, file_sha256
    normalized_times = validate_times(normalized_probe['presentation_timestamps_seconds']).tolist()
    source_time_relation = normalization_timing(probe, normalized_probe)
    (output / 'normalized_probe.json').write_text(json.dumps(normalized_probe, indent=2) + '\n')
    cached_raw = args.cached_raw_tracking.expanduser().resolve(strict=True) if args.cached_raw_tracking else None
    actor_review = args.actor_review.expanduser().resolve(strict=True) if args.actor_review else None
    if cached_raw is not None:
        try:
            from .tracking_evidence import load_reviewed_fragment_evidence
        except ImportError:
            from tracking_evidence import load_reviewed_fragment_evidence
        reviewed = load_reviewed_fragment_evidence(cached_raw, actor_review, normalized_times,
            [normalized_probe['streams'][0]['width'], normalized_probe['streams'][0]['height']],
            source_sha256=file_sha256(normalized), source_path=normalized, actor_id=args.actor_id)
        args.actor_id = reviewed['actor_id']
        report['reviewed_actor_selection'] = dict(actor_id=args.actor_id,
            usable_body_box_track_ids=reviewed['usable_body_box_track_ids'],
            observed_but_body_box_unusable_ids=reviewed['observed_but_body_box_unusable_ids'],
            raw_tracking=reviewed['cached_raw_tracking'], actor_review=reviewed['actor_review_file'])
    from omegaconf import OmegaConf
    cfg = OmegaConf.load(repo / 'hmr4d/configs/gvhmr_b1_demo.yaml')
    cfg.video_name = str(normalized)
    cfg.video_path = str(normalized)
    cfg.output_root = str(output)
    cfg.output_dir = str(output)
    cfg.static_cam = args.camera == 'static'
    cfg.ckpt_path = str(checkpoint)
    cfg.paths.incam_global_horiz_video = str(output / '3_incam_global_horiz.mp4')
    if args.camera == 'moving':
        cfg.paths.slam = str(output / 'preprocess/slam_results.pt')
    camera_adapter = None
    if args.camera_estimator == 'pi3x':
        try:
            from .camera_tracks import preload_pi3x_slam
        except ImportError:
            from camera_tracks import preload_pi3x_slam
        # A fresh explicit cache makes upstream skip SLAMModel.track and its lazy DPVO imports.
        camera_adapter = preload_pi3x_slam(repo=repo, bundle=pi3x_bundle, slam_path=cfg.paths.slam,
            output=output / 'camera_adapter', times=normalized_times,
            image_size=[normalized_probe['streams'][0]['width'], normalized_probe['streams'][0]['height']],
            source_sha256=file_sha256(normalized))
    config = output / 'demo.yaml'
    OmegaConf.save(cfg, config, resolve=True)
    launcher_options = dict(raw_tracking_path=str(output / 'raw_tracking.json'),
        selected_track_id=args.track_id, actor_id=args.actor_id, expected_video=str(normalized),
        time_seconds=normalized_times, no_postprocess=args.no_postprocess,
        cached_raw_tracking_path=str(cached_raw) if cached_raw else None,
        actor_review_path=str(actor_review) if actor_review else None,
        camera_mode=args.camera, camera_estimator=args.camera_estimator,
        dpvo_timing=args.dpvo_timing if use_dpvo else None,
        dpvo_timing_path=str(output / 'dpvo_timing.json') if use_dpvo else None,
        unsupported_body_inputs=args.unsupported_body_inputs,
        body_input_evidence_path=str(output / 'body_input_gating.json') if args.unsupported_body_inputs != 'keep' else None,
        image_size=[normalized_probe['streams'][0]['width'], normalized_probe['streams'][0]['height']],
        bbx_path=str(output / 'preprocess/bbx.pt'))
    launcher_options_path = output / 'launcher_options.json'
    launcher_options_path.write_text(json.dumps(launcher_options, indent=2) + '\n')
    report.update(source_video=str(video), model_fps=30, camera_mode=args.camera,
                  checkpoint=str(checkpoint), upstream_postprocessing=not args.no_postprocess,
                  selected_track_id=args.track_id, actor_id=args.actor_id,
                  source_sha256=file_sha256(video), normalized_input_sha256=file_sha256(normalized),
                  normalization=source_time_relation,
                  camera_adapter=camera_adapter,
                  launcher_options_sha256=file_sha256(launcher_options_path),
                  implementation_sha256={name: file_sha256(Path(__file__).with_name(name))
                      for name in ('run.py', 'demo_entry.py', 'tracking_evidence.py')},
                  coordinate_alignment='not performed', blender_import='not performed')
    if camera_adapter is not None:
        report['implementation_sha256']['camera_tracks.py'] = file_sha256(Path(__file__).with_name('camera_tracks.py'))
    (output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    env = dict(execution_env)
    env['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'  # Trusted upstream checkpoint formats.
    env['PYTHONPATH'] = os.pathsep.join([str(repo / 'third-party/DPVO'), str(repo), env.get('PYTHONPATH', '')])
    call([sys.executable, Path(__file__).with_name('demo_entry.py'), '--launcher-options', launcher_options_path,
          repo / 'tools/demo/demo.py', '--cfg_file', config], cwd=repo, env=env)
    if args.unsupported_body_inputs != 'keep':
        gate_path = output / 'body_input_gating.json'
        gate = json.loads(gate_path.read_text())
        if gate.get('status') != 'completed' or gate.get('mode') != args.unsupported_body_inputs or \
                gate.get('calls') != 1 or gate.get('source_sha256') != file_sha256(normalized) or \
                gate.get('source_time_seconds') != normalized_times or \
                gate.get('raw_tracking', {}).get('sha256') != file_sha256(output / 'raw_tracking.json') or \
                gate.get('boxes', {}).get('sha256') != file_sha256(output / 'preprocess/bbx.pt') or \
                gate.get('effective_inputs', {}).get('sha256') != file_sha256(output / 'body_input_gating.npz'):
            raise ValueError('Body-gating evidence lacks completed, unchanged exact-source support')
        report['body_input_gating_evidence'] = dict(path=str(gate_path), sha256=file_sha256(gate_path),
            mode=args.unsupported_body_inputs, gated_frames=gate['gated_frames'])
        (output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.camera == 'moving':
        slam_path = Path(cfg.paths.slam).resolve(strict=True)
        report['camera_track'] = dict(path=str(slam_path), sha256=file_sha256(slam_path),
            estimator=args.camera_estimator, convention='OpenCV c2w: tx,ty,tz,qx,qy,qz,qw',
            usage='relative camera rotations only; translations ignored; intrinsics remain estimate_K')
        if use_dpvo:
            timing_path = output / 'dpvo_timing.json'
            timing = json.loads(timing_path.read_text())
            if timing.get('status') != 'completed' or timing.get('mode') != args.dpvo_timing or \
                    timing.get('completed_calls') != len(normalized_times) or timing.get('source_time_seconds') != normalized_times or \
                    timing.get('source', {}).get('sha256') != file_sha256(normalized):
                raise ValueError('DPVO timing evidence lacks completed exact-source coverage')
            report['dpvo_timing_evidence'] = dict(path=str(timing_path), sha256=file_sha256(timing_path),
                                                  mode=args.dpvo_timing, completed_calls=timing['completed_calls'])
        (output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    validation = {'normalized_input': normalized_probe, 'outputs': {}, 'visual_review': 'pending'}
    for name in ['1_incam.mp4', '2_global.mp4', '3_incam_global_horiz.mp4']:
        call(['ffmpeg', '-v', 'error', '-xerror', '-i', output / name, '-f', 'null', '-'])
        metadata = probe_video(output / name)
        check_timing(normalized_probe, metadata)
        validation['outputs'][name] = metadata
    (output / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    print('Inference and full decoding finished. Whole-clip visual review and room alignment are still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
