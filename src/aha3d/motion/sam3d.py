"""Run local SAM 3D Body weights on selected Pi3X RGB frames and save observations."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import numpy as np

from .. import runtime
from .reference import camera_to_world, digest, dump, finite, intrinsic, project, unique_frames

PINNED_REVISION = 'b5c765a0d89d789985e186d396315e7590887b94'
DINO_REVISION = '6876159a11b4df116f30f667f8c9888617df0751'


def local_hub_loader(original, dinov3):
    """Route SAM's unpinned GitHub hub request to a verified local DINO checkout."""
    def load(repo, model, *args, **kwargs):
        if repo != 'facebookresearch/dinov3' or kwargs.get('pretrained', False):
            raise ValueError('Unexpected Torch Hub request; local untrained DINO architecture only')
        kwargs['source'] = 'local'
        return original(str(dinov3), model, *args, **kwargs)
    return load


def canonical_camera(k, width, height):
    """Image homography preserves camera rays while matching SAM full-path projection."""
    k = intrinsic(k)
    focal = float(np.sqrt(k[0, 0] * k[1, 1]))
    canonical = np.array([[focal, 0., width / 2], [0., focal, height / 2], [0., 0., 1.]])
    return canonical, canonical @ np.linalg.inv(k)


def pixel_transform(uv, homography):
    uv = np.asarray(uv, dtype=np.float64)
    p = np.column_stack([uv, np.ones(len(uv))]) @ homography.T
    return p[:, :2] / p[:, 2:]


def normalize_output(output, original_k, canonical_k, homography, width, height):
    points = finite(output['pred_keypoints_3d'], (70, 3), 'SAM keypoints')
    translation = finite(output['pred_cam_t'], (3,), 'SAM camera translation')
    camera_points = points + translation
    uv = finite(output['pred_keypoints_2d'], (70, 2), 'SAM pixels')
    error = float(np.linalg.norm(project(camera_points, canonical_k) - uv, axis=1).max())
    if error > 2:
        raise ValueError(f'SAM projection convention mismatch: {error:.3f} pixels')
    original_uv = pixel_transform(uv, np.linalg.inv(homography))
    original_error = float(np.linalg.norm(project(camera_points, original_k) - original_uv, axis=1).max())
    return dict(keypoints_camera_m=camera_points.tolist(), keypoints_2d=original_uv.tolist(),
                projection_max_error_px=original_error,
                canonical_projection_max_error_px=error,
                in_frame=((original_uv >= 0).all(axis=1) & (original_uv <= [width-1, height-1]).all(axis=1)).tolist(),
                visibility_note='Image bounds only; neither occlusion nor confidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi3x', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True, help='JSON events with source_frame and bbox_xyxy')
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--dinov3', type=Path, required=True, help='Pinned local DINOv3 architecture checkout')
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--mhr', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): parser.error('Output exists; use a new claimed directory')
    for path in (args.checkpoint, args.mhr, args.pi3x/'inputs.npz', args.upstream/'sam_3d_body/__init__.py'):
        if not path.is_file(): parser.error(f'Missing input: {path}')
    revision = subprocess.check_output(['git', '-C', str(args.upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != PINNED_REVISION:
        parser.error(f'Adapter validated against source revision {PINNED_REVISION}; review changes before updating pin')
    if subprocess.check_output(['git', '-C', str(args.upstream), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        parser.error('SAM tracked source is modified; restore pinned source or review adapter')
    dino_revision = subprocess.check_output(['git', '-C', str(args.dinov3), 'rev-parse', 'HEAD'], text=True).strip()
    if dino_revision != DINO_REVISION or subprocess.check_output(
        ['git', '-C', str(args.dinov3), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        parser.error('DINO architecture must be an unmodified pinned checkout')
    import cv2
    import torch
    from PIL import Image, ImageDraw
    if not torch.cuda.is_available(): parser.error('CUDA GPU required')
    # Use the checkpoint-bundled MHR TorchScript rather than optional global MHR assets.
    os.environ['MOMENTUM_ENABLED'] = '0'
    sys.path.insert(0, str(args.upstream.resolve()))
    from sam_3d_body import load_sam_3d_body, SAM3DBodyEstimator
    from sam_3d_body.metadata.mhr70 import mhr_names
    package = importlib.import_module('sam_3d_body')
    if not Path(package.__file__).resolve().is_relative_to(args.upstream.resolve()):
        raise ValueError('Imported SAM from a different checkout')
    inputs_path, cameras_path = args.pi3x/'inputs.json', args.pi3x/'cameras.json'
    inputs, cameras = [json.loads(p.read_text()) for p in (inputs_path, cameras_path)]
    selection = json.loads(args.selection.read_text())
    cam_frames = unique_frames(cameras['frames'])
    selected = {}
    for event in selection['events']:
        frame = event['source_frame']
        if type(frame) is not int or frame not in cam_frames: raise ValueError('Missing exact Pi3X event frame')
        box = finite(event['bbox_xyxy'], (4,), 'person bbox')
        if frame in selected and not np.array_equal(selected[frame], box):
            raise ValueError('One selected person/box per frame; hands must share the box')
        selected[frame] = box
    if not selected: raise ValueError('No frames selected')
    width, height = cameras['processed_size_wh']
    with np.load(args.pi3x/'inputs.npz', allow_pickle=False) as data:
        rgb = data['rgb']; frame_ids = data['frame_indices'].tolist()
        timestamps = data['timestamps_seconds']
    if len(set(frame_ids)) != len(frame_ids) or rgb.shape != (len(frame_ids), height, width, 3) or rgb.dtype != np.uint8:
        raise ValueError('Malformed Pi3X RGB bundle')
    if frame_ids != inputs['frame_indices'] or not np.allclose(timestamps, inputs['timestamps_seconds'], atol=1e-6):
        raise ValueError('Pi3X inputs JSON and NPZ disagree')
    if inputs['processed_size_wh'] != [width, height]: raise ValueError('Pi3X image sizes disagree')
    positions = {f: i for i, f in enumerate(frame_ids)}
    for f, box in selected.items():
        if f not in positions or abs(float(timestamps[positions[f]]) - cam_frames[f]['timestamp_seconds']) > 1e-6:
            raise ValueError('Pi3X RGB/camera frame or timestamp mismatch')
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError('Person bbox must lie inside processed Pi3X image')
        camera_to_world(np.zeros((1, 3)), cam_frames[f]['c2w'])
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'raw').mkdir(); (args.out/'overlays').mkdir()
    started = time.perf_counter()
    with patch.object(torch.hub, 'load', local_hub_loader(torch.hub.load, args.dinov3.resolve())):
        model, cfg = load_sam_3d_body(str(args.checkpoint.resolve()), device='cuda', mhr_path=str(args.mhr.resolve()))
    estimator = SAM3DBodyEstimator(model, cfg)
    outputs = []
    for f in sorted(selected):
        source = rgb[positions[f]]
        k = intrinsic(cam_frames[f]['intrinsics'])
        ck, h = canonical_camera(k, width, height)
        image = cv2.warpPerspective(source, h, (width, height), flags=cv2.INTER_LINEAR)
        x0, y0, x1, y1 = selected[f]
        corners = pixel_transform([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], h)
        low = np.maximum(corners.min(axis=0), [0, 0]); high = np.minimum(corners.max(axis=0), [width, height])
        if np.any(high <= low): raise ValueError('Transformed person bbox is empty')
        box = np.concatenate([low, high]).astype(np.float32)[None]
        pred = estimator.process_one_image(image, bboxes=box,
                  cam_int=torch.tensor(ck, dtype=torch.float32)[None], inference_type='full')
        if len(pred) != 1: raise ValueError('Expected one person prediction')
        raw = pred[0]
        numeric = {key: value for key, value in raw.items() if isinstance(value, (np.ndarray, np.number, float, int))}
        np.savez_compressed(args.out/'raw'/f'{f:06d}.npz', **numeric)
        normalized = normalize_output(raw, k, ck, h, width, height)
        record = dict(source_frame=f, timestamp_seconds=float(timestamps[positions[f]]),
                      bbox_xyxy=selected[f].tolist(), canonical_intrinsics=ck.tolist(),
                      source_to_canonical_pixels=h.tolist(), reviewed=False, **normalized)
        outputs.append(record)
        from .observations import draw_full_body
        overlay = draw_full_body(Image.fromarray(source), record, mhr_names)
        overlay.save(args.out/'overlays'/f'{f:06d}.png')
    dump(args.out/'observations.json', dict(schema_version=1, source_sha256=inputs['source_sha256'],
         person_id=selection.get('person_id'),
         pi3x_inputs_sha256=digest(inputs_path), pi3x_cameras_sha256=digest(cameras_path),
         processed_size_wh=[width, height], keypoint_names=mhr_names,
         coordinate_convention='opencv_camera_metres_with_translation', frames=outputs,
         model_revision=revision, dinov3_revision=dino_revision,
         checkpoint_sha256=digest(args.checkpoint), mhr_sha256=digest(args.mhr),
         checkpoint_config_sha256=digest(Path(args.checkpoint).parent/'model_config.yaml') if (Path(args.checkpoint).parent/'model_config.yaml').exists() else digest(Path(args.checkpoint).parent.parent/'model_config.yaml'),
         selection_sha256=digest(args.selection), script_sha256=digest(__file__),
         total_seconds=time.perf_counter()-started, run_id=runtime.run_id(),
         status='Estimates exported; visual and room alignment review required'))
    print(args.out/'observations.json')


if __name__ == '__main__':
    main()
