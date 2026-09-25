"""Build source-bound actor depth anchors from cached Pi3X and GVHMR geometry.

No model execution. All paths are explicit config inputs, relative to the config
file unless absolute. Pixel grids, timelines, camera transforms, confidence-selected or reviewed
anchors and source/actor hashes are checked before fitting. Pi3X local Z is axial
camera depth; its metric factor is already applied and is never applied again.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from tools.gvhmr.align_depth_trajectory import sample_surface
from tools.gvhmr.root_constraints import active_mask, frames_mask, sha256


def rigid_transform(value):
    value = np.asarray(value, float)
    if value.shape != (4, 4) or not np.isfinite(value).all() or not np.allclose(value[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError('Finite homogeneous rigid transform required')
    if not np.allclose(value[:3, :3].T @ value[:3, :3], np.eye(3), atol=2e-6) or abs(np.linalg.det(value[:3, :3]) - 1) > 2e-6:
        raise ValueError('Room transform must preserve metric body dimensions')
    return value


def resize_uv(uv, source_size_wh, target_size_wh):
    source, target = np.asarray(source_size_wh, float), np.asarray(target_size_wh, float)
    if source.shape != (2,) or target.shape != (2,) or not np.isfinite(source).all() or not np.isfinite(target).all() or (source <= 0).any() or (target <= 0).any():
        raise ValueError('Positive source and target raster dimensions required')
    return (np.asarray(uv, float) + .5) * (target / source) - .5


def ray_hit(vertices, faces, direction):
    """Nearest positive triangle hit from the OpenCV camera origin."""
    triangles = np.asarray(vertices, float)[faces]
    direction = np.asarray(direction, float)
    if direction.shape != (3,) or not np.isfinite(direction).all() or direction[2] <= 0:
        return None
    a = triangles[:, 0]; e1 = triangles[:, 1] - a; e2 = triangles[:, 2] - a
    p = np.cross(np.broadcast_to(direction, e2.shape), e2)
    det = (e1 * p).sum(axis=1)
    ok = np.abs(det) > 1e-10
    inv = np.zeros_like(det); inv[ok] = 1 / det[ok]
    tv = -a; u = (tv * p).sum(axis=1) * inv
    q = np.cross(tv, e1); v = (q * direction).sum(axis=1) * inv
    distance = (e2 * q).sum(axis=1) * inv
    ok &= (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 0)
    return direction * distance[ok].min() if ok.any() else None


def camera_mesh(vertices, pelvis, global_rotation, incam_rotation, incam_translation, rest_pelvis):
    """Exact posed mesh transform, with the shaped SMPL pelvis/transl offset."""
    rotation = incam_rotation @ global_rotation.T
    camera_pelvis = incam_translation + rest_pelvis
    return (vertices - pelvis) @ rotation.T + camera_pelvis, camera_pelvis, rotation


def floor_up_yaw(native, cameras, frames, *, observation_policy='reviewed'):
    if len(frames) < 3:
        raise ValueError('Three active TRAIN camera/body relation frames required')
    rg = Rotation.from_rotvec(native['smpl_params_global__global_orient'][frames]).as_matrix()
    ri = Rotation.from_rotvec(native['smpl_params_incam__global_orient'][frames]).as_matrix()
    relations = cameras[frames, :3, :3] @ ri @ rg.transpose(0, 2, 1)
    mean = Rotation.from_matrix(relations).mean().as_matrix()
    native_y_to_room_z = np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]])
    delta = mean @ native_y_to_room_z.T
    yaw = np.arctan2(delta[1, 0] - delta[0, 1], delta[0, 0] + delta[1, 1])
    rotation = Rotation.from_rotvec([0., 0., yaw]).as_matrix() @ native_y_to_room_z
    error = Rotation.from_matrix(relations @ rotation.T).magnitude()
    return rotation, dict(yaw_degrees=float(np.degrees(yaw)), frames=frames.tolist(),
                          relation_error_degrees_p50_p90=np.degrees(np.percentile(error, [50, 90])).tolist(),
                          scope=f'One {observation_policy} TRAIN camera-up yaw; no per-frame body rotation or floor calibration')


def _same_times(a, b, label):
    if np.asarray(a).shape != np.asarray(b).shape or not np.allclose(a, b, atol=1e-8, rtol=0):
        raise ValueError('Mismatched source times: ' + label)


def cache_identity_fields(ground, times, smplx_joint_names):
    """Complete shared Blender importer/exporter schema for the actual joint set."""
    times = np.asarray(times, float)
    if len(times) < 2 or not np.isfinite(times).all() or (np.diff(times) <= 0).any():
        raise ValueError('At least two increasing source times required')
    step = float(np.median(np.diff(times)))
    if not np.allclose(np.diff(times), step, atol=1e-8, rtol=0):
        raise ValueError('Shared Blender cache requires a uniform resampled timeline')
    count = ground['joints'].shape[1]
    if count not in (127, 144) or len(smplx_joint_names) < count:
        raise ValueError('Expected the actual SMPL-X 127 or 144 joint set and official names')
    names = np.asarray(smplx_joint_names[:count])
    body_names = np.asarray(ground['body_joint_names'])
    if body_names.shape != (22,) or not np.array_equal(names[:22], body_names):
        raise ValueError('Official joint names differ from source SMPL-X skeleton')
    return dict(fps=np.asarray(1. / step), joint_names=names, body_joint_names=body_names)


def official_joint_names(path):
    # Read the pinned upstream data literal without importing an external package.
    tree = ast.parse(Path(path).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'JOINT_NAMES' for t in node.targets):
            names = ast.literal_eval(node.value)
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                break
            return names
    raise ValueError('Official SMPL-X JOINT_NAMES literal missing')


def confidence_anchors(keypoints, active, threshold=.5):
    """Choose hips first, otherwise shoulders, without manual visibility gates."""
    kp, active = np.asarray(keypoints), np.asarray(active)
    if kp.shape != (len(active), 17, 3) or active.dtype != bool or active.ndim != 1:
        raise ValueError('COCO17 keypoints[T,17,3] and boolean active[T] required')
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Keypoint confidence threshold must be between zero and one')
    def supported(pair):
        data = kp[:, pair]
        return np.isfinite(data).all(axis=(1, 2)) & (data[:, :, 2] >= threshold).all(axis=1) & active
    hips = supported([11, 12])
    shoulders = supported([5, 6]) & ~hips
    return hips, shoulders


def validate_cache_binding(binding, paths, source, actor):
    """Freeze caller-verified legacy cache pairing without reading diagnostics.

    Old observations lack identity fields. This explicit caller assertion binds
    their exact bytes to the actor/video; it is not independent provenance proof.
    Native identity, source parameter equality and timelines are checked below.
    """
    if binding.get('actor_id') != actor or binding.get('source_video_sha256') != source:
        raise ValueError('Confidence cache binding actor/video mismatch')
    for name in ('native', 'ground', 'observations'):
        if binding.get(name + '_sha256') != sha256(paths[name]):
            raise ValueError('Confidence cache binding hash mismatch: ' + name)


def prepare(config_path, output):
    start = time.perf_counter()
    config_path, output = Path(config_path).resolve(), Path(output)
    cfg = json.loads(config_path.read_text())
    if cfg.get('schema_version') != 1:
        raise ValueError('Depth preparation config schema_version:1 required')
    policy = cfg.get('observation_policy', 'reviewed')
    if policy not in ('reviewed', 'confidence'):
        raise ValueError('observation_policy must be reviewed or confidence')
    paths = {key: (config_path.parent / value).resolve() for key, value in cfg['paths'].items()
             if policy != 'confidence' or key not in ('review', 'ground_report', 'quality_report')}
    source, actor = cfg['source_video_sha256'], cfg['actor_id']
    native = dict(np.load(paths['native'], allow_pickle=False))
    ground = dict(np.load(paths['ground'], allow_pickle=False))
    obs = dict(np.load(paths['observations'], allow_pickle=False))
    camera = dict(np.load(paths['cameras'], allow_pickle=False))
    inputs = dict(np.load(paths['pi3x_inputs'], allow_pickle=False))
    predictions = dict(np.load(paths['pi3x_predictions'], allow_pickle=False))
    tracking = json.loads(paths['tracking'].read_text())
    review = json.loads(paths['review'].read_text()) if policy == 'reviewed' else None
    masks = np.load(paths['masks'], mmap_mode='r', allow_pickle=False)
    if tracking['actor_id'] != actor or tracking.get('source_video_sha256', tracking.get('source', {}).get('sha256')) != source:
        raise ValueError('Tracking actor/video binding mismatch')
    if str(native['source_actor_id']) != actor or str(native['source_video_sha256']) != source:
        raise ValueError('Native source binding mismatch')
    if policy == 'confidence':
        validate_cache_binding(cfg.get('cache_binding', {}), paths, source, actor)
    else:
        if review['actor_id'] != actor or review['source_video_sha256'] != source:
            raise ValueError('Review source binding mismatch')
        gr = json.loads(paths['ground_report'].read_text())
        qr = json.loads(paths['quality_report'].read_text())
        if gr['actor_id'] != actor or gr['inputs']['video']['sha256'] != source or gr['inputs']['motion']['sha256'] != sha256(paths['native']) or gr['outputs']['native_ground.npz'] != sha256(paths['ground']):
            raise ValueError('Ground cache provenance mismatch')
        if qr['actor_id'] != actor or qr['inputs']['video']['sha256'] != source or qr['outputs']['observations.npz'] != sha256(paths['observations']):
            raise ValueError('2D observation provenance mismatch')
    for name in ('body_pose', 'betas', 'global_orient', 'transl'):
        if not np.array_equal(ground[name], native['smpl_params_global__' + name]):
            raise ValueError('Ground mesh source parameter mismatch: ' + name)
    times = np.asarray(ground['time_seconds'], float)
    count = len(times)
    lifecycle = dict(time_seconds=times)
    for key in ('track_active', 'source_frame_indices', 'track_lifecycle_sha256', 'track_lifecycle_json'):
        if key in native:
            lifecycle[key] = native[key]
        if key in ground and key in native and not np.array_equal(ground[key], native[key]):
            raise ValueError('Native/ground lifecycle mismatch: ' + key)
    active = active_mask(lifecycle)
    for other, label in ((native['frame_times_seconds'], 'native'), (obs['time_seconds'], '2D observations'), (camera['dense_time_seconds'], 'cameras')):
        _same_times(times, other, label)
    ids = np.asarray(inputs['frame_indices'])
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or not len(ids) or ids.min() < 0 or ids.max() >= count or (np.diff(ids) <= 0).any():
        raise ValueError('Invalid Pi3X source frame indices')
    _same_times(times[ids], inputs['timestamps_seconds'], 'Pi3X')
    source_size = np.asarray(obs['image_size'])
    if source_size.shape != (2,) or masks.shape != (count, int(source_size[1]), int(source_size[0])):
        raise ValueError('Actor masks must use the full source raster')
    train = np.asarray(cfg.get('train_row_mask', np.ones(len(ids), dtype=bool)) if policy == 'confidence' else cfg['train_row_mask'])
    if train.dtype != bool or train.shape != ids.shape:
        raise ValueError('Explicit frozen train_row_mask for all Pi3X rows required')
    C = camera['dense_c2w_room_cv']
    if C.shape != (count, 4, 4):
        raise ValueError('Full source camera timeline required')
    for c in C:
        rigid_transform(c)
    if 'source_video_sha256' in camera:
        if str(camera['source_video_sha256']) != source:
            raise ValueError('Room camera video binding mismatch')
    else:
        # Older room-camera caches use an independently frozen basis report.
        # Bind the raw prediction and input-report hashes as well as its transform.
        if 'room_basis_report' not in paths:
            raise ValueError('Room camera requires embedded video hash or source-bound room_basis_report')
        basis = json.loads(paths['room_basis_report'].read_text())
        transform = basis.get('raw_to_room', basis.get('T_raw_pi3x_to_room'))
        hashes = set(basis.get('input_hashes', {}).values())
        if basis.get('source_video_sha256') != source or transform is None or not np.allclose(transform, cfg['raw_to_room'], atol=1e-8, rtol=0):
            raise ValueError('Room basis report source/transform binding mismatch')
        if sha256(paths['pi3x_predictions']) not in hashes or sha256(paths['pi3x_input_report']) not in hashes:
            raise ValueError('Room basis report does not bind these Pi3X predictions and source inputs')
    input_report = json.loads(paths['pi3x_input_report'].read_text())
    if input_report.get('source_sha256') != source or input_report.get('source_frame_count') != count:
        raise ValueError('Pi3X source video or frame-count binding mismatch')
    if input_report.get('original_size_wh') != source_size.tolist() or input_report.get('processed_size_wh') != [inputs['rgb'].shape[2], inputs['rgb'].shape[1]]:
        raise ValueError('Pi3X source/processed raster binding mismatch')
    if not np.array_equal(input_report['frame_indices'], ids):
        raise ValueError('Pi3X source frame mapping mismatch')
    _same_times(input_report['timestamps_seconds'], inputs['timestamps_seconds'], 'Pi3X report')
    raw_to_room = rigid_transform(cfg['raw_to_room'])
    camera_residual = float(np.max(abs(raw_to_room @ predictions['camera_poses'] - C[ids])))
    if camera_residual > 3e-6:
        raise ValueError('Pi3X raw camera and supplied room camera relation differs')
    rgb = inputs['rgb']; h, w = rgb.shape[1:3]
    local, confidence, edge = predictions['local_points'], predictions['conf'], predictions['non_edge']
    if local.shape != (len(ids), h, w, 3) or confidence.squeeze(-1).shape != (len(ids), h, w) or edge.shape != (len(ids), h, w):
        raise ValueError('Pi3X raster/row shape mismatch')
    kp = obs['keypoints']
    if kp.shape != (count, 17, 3):
        raise ValueError('Full source COCO17 observations required')
    threshold = float(cfg.get('min_keypoint_score', .5))
    if policy == 'confidence':
        hips, shoulders = confidence_anchors(kp, active, threshold)
    else:
        hips = frames_mask(review['torso_visible_intervals'], count) & active
        shoulders = frames_mask(review.get('shoulder_visible_intervals', []), count) & active
    rotation_frames = ids[(hips | shoulders)[ids] & train]
    rotation, rotation_report = floor_up_yaw(native, C, rotation_frames, observation_policy=policy)
    # These are licensed-model-independent numeric regressors from the pinned
    # upstream checkout. Both explicit files are hashed; no model download occurs.
    import torch
    coco_regressor = torch.load(paths['coco_regressor'], weights_only=True, map_location='cpu')
    mapping = torch.load(paths['smplx_to_smpl'], weights_only=True, map_location='cpu')
    if mapping.is_sparse:
        mapping = mapping.to_dense()
    regressor = (coco_regressor @ mapping).numpy()
    vg, jg = ground['vertices'], ground['joints']; roots = jg[:, 0]
    if regressor.shape != (17, vg.shape[1]):
        raise ValueError('COCO17 regressor does not match the actual posed mesh')
    coco = np.einsum('jv,tvc->tjc', regressor, vg)
    rg = Rotation.from_rotvec(native['smpl_params_global__global_orient']).as_matrix()
    ri = Rotation.from_rotvec(native['smpl_params_incam__global_orient']).as_matrix()
    rest_pelvis = roots - native['smpl_params_global__transl']
    raw = np.full((len(ids), 3), np.nan); corrected = raw.copy(); offsets = raw.copy()
    valid = np.zeros(len(ids), bool); weights = np.zeros(len(ids)); rows = []
    max_uv_error = float(cfg.get('max_model_anchor_error_px', 80.))
    for row, frame in enumerate(ids):
        pair = [11, 12] if hips[frame] else [5, 6]
        uv = kp[frame, pair, :2].mean(axis=0); scores = kp[frame, pair, 2]
        record = dict(row=row, frame=int(frame), time_seconds=float(times[frame]), active=bool(active[frame]),
                      anatomical_anchor='hip_midpoint' if hips[frame] else 'shoulder_midpoint',
                      anchor_uv_source=[float(x) if np.isfinite(x) else None for x in uv],
                      scores=[float(x) if np.isfinite(x) else None for x in scores])
        rows.append(record)
        if not (hips[frame] or shoulders[frame]) or not np.isfinite(kp[frame, pair]).all() or scores.min() < threshold:
            record.update(valid=False, reason=('inactive or low-score/nonfinite anatomical anchor' if policy == 'confidence'
                                               else 'inactive, unreviewed/hidden or low-score anatomical anchor'))
            continue
        mask = np.asarray(Image.fromarray(masks[frame]).resize((w, h), resample=Image.Resampling.NEAREST), bool)
        surface, detail = sample_surface(local[row, :, :, 2], confidence[row], edge[row], mask,
                                         resize_uv(uv, source_size, [w, h]), predictions['intrinsics'][row], C[frame],
                                         **cfg.get('surface_sampling', {}))
        record.update(detail)
        if surface is None:
            continue
        vcam, pelvis_cam, relR = camera_mesh(vg[frame], roots[frame], rg[frame], ri[frame],
                                             native['smpl_params_incam__transl'][frame], rest_pelvis[frame])
        anatomical_cam = (coco[frame, pair].mean(axis=0) - roots[frame]) @ relR.T + pelvis_cam
        if anatomical_cam[2] <= 0:
            record.update(valid=False, reason='model anatomical anchor behind camera'); continue
        projected = native['K_fullimg'][frame] @ anatomical_cam
        model_uv = projected[:2] / projected[2]
        error = float(np.linalg.norm(model_uv - uv))
        record.update(model_anchor_uv_source=model_uv.tolist(), model_to_observed_anchor_residual_px=error)
        if policy == 'reviewed' and error > max_uv_error:
            record.update(valid=False, reason='model/source anatomical correspondence exceeds declared pixel limit'); continue
        front = ray_hit(vcam, ground['faces'], anatomical_cam / anatomical_cam[2])
        if front is None:
            record.update(valid=False, reason='no positive actual posed-mesh front intersection'); continue
        delta = C[frame, :3, :3] @ (pelvis_cam - front)
        raw[row], corrected[row], offsets[row], valid[row] = surface, surface + delta, delta, True
        weights[row] = float(scores.min()) * (1. if hips[frame] else float(cfg.get('shoulder_weight', .7)))
        record.update(valid=True, surface_world=surface.tolist(), root_target_world=corrected[row].tolist(),
                      model_front_camera=front.tolist(), surface_to_root_camera_m=(pelvis_cam - front).tolist())
    use = valid & train & active[ids]
    if use.sum() < 3:
        raise ValueError('Fewer than three active supported training depth rows')
    translation = np.median(corrected[use] - (roots @ rotation.T)[ids[use]], axis=0)
    baseline = dict(schema_version=np.asarray(1), vertices=(vg @ rotation.T + translation).astype('f4'),
                    joints=(jg @ rotation.T + translation).astype('f4'), faces=ground['faces'],
                    vertex_ids=np.arange(vg.shape[1]), time_seconds=times, body_scale=np.asarray(1.),
                    source_video_sha256=np.asarray(source), source_actor_id=np.asarray(actor),
                    room_basis_sha256=np.asarray(sha256(paths['cameras'])), motion_source=np.asarray(str(paths['native'])),
                    native_to_room_rotation=rotation, native_to_room_translation=translation,
                    surface_model_type=np.asarray('Source-shaped GVHMR SMPL-X; fixed body dimensions'),
                    track_active=active, source_frame_indices=np.arange(count))
    baseline.update(cache_identity_fields(ground, times, official_joint_names(paths['smplx_joint_names'])))
    for key in ('left_vertex_ids', 'right_vertex_ids', 'lbs_weights'):
        if key in ground:
            baseline[key] = ground[key]
    for key in ('track_lifecycle_sha256', 'track_lifecycle_json'):
        if key in lifecycle:
            baseline[key] = lifecycle[key]
    baseline.update({'source_native__' + k: native[k] for k in native if k.startswith('smpl_params_')})
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / 'rigid_body_room.npz', **baseline)
    body_hash = sha256(output / 'rigid_body_room.npz')
    hip_cohort = valid & hips[ids]
    for name, target, cohort in [('raw_hip_depth', raw, hip_cohort), ('surface_corrected_hips', corrected, hip_cohort), ('surface_corrected', corrected, valid)]:
        np.savez_compressed(output / (name + '.npz'), frame_indices=ids, time_seconds=times[ids], root_targets=target,
                            surface_world=raw, model_surface_to_pelvis_offsets=offsets, valid=cohort,
                            weights=weights, train=train, source_video_sha256=np.asarray(source),
                            source_actor_id=np.asarray(actor), room_basis_sha256=baseline['room_basis_sha256'],
                            source_body_sha256=np.asarray(body_hash), target_semantics=np.asarray(name + '; estimated depth, not pelvis truth'))
    report = dict(schema_version=1, actor_id=actor, source_video_sha256=source, rotation=rotation_report,
                  observation_policy=policy, min_keypoint_score=threshold,
                  anchor_counts=dict(hip_frames=int(hips.sum()), shoulder_frames=int(shoulders.sum()),
                                     sampled_hip_rows=int(hips[ids].sum()), sampled_shoulder_rows=int(shoulders[ids].sum()),
                                     valid_hip_rows=int((valid & hips[ids]).sum()),
                                     valid_shoulder_rows=int((valid & ~hips[ids] & shoulders[ids]).sum())),
                  selection_inputs=['keypoints', 'min_keypoint_score', 'inherited_track_active'] if policy == 'confidence'
                                   else ['review', 'keypoints', 'min_keypoint_score', 'inherited_track_active'],
                  model_anchor_reprojection_filter_enabled=(policy == 'reviewed'),
                  cache_binding=cfg.get('cache_binding') if policy == 'confidence' else None,
                  rigid_translation=translation.tolist(), camera_relation_residual=camera_residual, rows=rows,
                  valid_rows=np.flatnonzero(valid).tolist(), train_rows=np.flatnonzero(use).tolist(),
                  heldout_rows=np.flatnonzero(valid & ~train).tolist(), source_size_wh=source_size.tolist(),
                  pi3x_size_wh=[w, h], active_frame_count=int(active.sum()), inactive_frame_count=int((~active).sum()),
                  input_hashes={str(p): sha256(p) for p in list(paths.values()) + [config_path, Path(__file__), Path(__file__).with_name('align_depth_trajectory.py')]},
                  output_hashes={p.name: sha256(p) for p in output.glob('*.npz')}, wall_seconds=time.perf_counter() - start,
                  limits=[('Confidence threshold and masks select estimates, not proven visibility; no manual visibility or diagnostic gates.'
                           if policy == 'confidence' else 'Source review establishes visibility; confidence and propagated masks do not.'),
                          'Unclothed model surface-to-pelvis offset only approximates clothing.',
                          'Frozen estimated scene/cameras and unknown metric scale make heldout evaluation conditional.',
                          'One training camera-up yaw; dimensions remain fixed and no metric scale is asserted.'])
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.config, args.output)
    print(json.dumps({k: v for k, v in report.items() if k not in ('rows', 'input_hashes')}, indent=2))


if __name__ == '__main__':
    main()
