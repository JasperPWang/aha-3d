#!/usr/bin/env python3
"""Audit unmodified GVHMR global geometry against an explicit native Y plane.

The GVHMR assumed native plane is not scene-aligned ground. Stationary-foot
sliding is unknown unless independently reviewed source intervals are supplied.
Run model skinning in the configured GVHMR environment; nothing is downloaded.
"""
import argparse
import importlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

try:
    from .motion_quality import boolean_mask, stats, intervals
    from .tracking_evidence import REVISION, file_sha256, validate_times, video_timeline
except ImportError:
    from motion_quality import boolean_mask, stats, intervals
    from tracking_evidence import REVISION, file_sha256, validate_times, video_timeline

PARAMETERS = dict(body_pose=63, betas=10, global_orient=3, transl=3)
FOOT_NAMES = ['left', 'right']
FOOT_JOINT_IDS = ([7, 10], [8, 11])
BODY_NAMES = ['pelvis', 'left_hip', 'right_hip', 'spine1', 'left_knee', 'right_knee',
              'spine2', 'left_ankle', 'right_ankle', 'spine3', 'left_foot', 'right_foot',
              'neck', 'left_collar', 'right_collar', 'head', 'left_shoulder',
              'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist']
SOURCES = ['hmr4d/__init__.py', 'hmr4d/utils/smplx_utils.py',
           'hmr4d/utils/body_model/__init__.py', 'hmr4d/utils/body_model/body_model_smplx.py',
           'hmr4d/utils/geo/hmr_global.py', 'hmr4d/model/gvhmr/pipeline/gvhmr_pipeline.py',
           'hmr4d/model/gvhmr/utils/postprocess.py']
BODY_ASSET = 'inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz'
PLANE_LABEL = 'GVHMR assumed native plane, not scene-aligned ground'


def validate_parameters(params, times):
    t = validate_times(times)
    if set(params) != set(PARAMETERS):
        raise ValueError('Expected the four native global SMPL-X parameter arrays')
    result = {}
    for name, width in PARAMETERS.items():
        value = np.asarray(params[name])
        if value.shape != (len(t), width) or not np.isfinite(value).all() or value.dtype.kind != 'f':
            raise ValueError(f'Expected finite floating-point {name} of shape {(len(t), width)}')
        result[name] = value.copy()
    return result


def load_parameters(path, times, torch_module):
    path = Path(path)
    if path.suffix == '.npz':
        with np.load(path, allow_pickle=False) as data:
            native_times = data['frame_times_seconds']
            if native_times.shape != np.asarray(times).shape or not np.allclose(native_times, times, atol=1e-6, rtol=0):
                raise ValueError('Native NPZ timestamps differ from exact decoded input PTS')
            params = {key: data['smpl_params_global__' + key].copy() for key in PARAMETERS}
    elif path.suffix == '.pt':
        prediction = torch_module.load(path, map_location='cpu', weights_only=True)
        params = {key: value.detach().cpu().numpy() for key, value in prediction['smpl_params_global'].items()}
    else:
        raise ValueError('Motion input must be hmr4d_results.pt or native parameter .npz')
    return validate_parameters(params, times)


def foot_vertices_from_weights(weights, threshold=.5):
    weights = np.asarray(weights, dtype=float)
    if not np.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError('Foot weight threshold must be in (0,1]')
    if weights.ndim != 2 or weights.shape[1] < 12 or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError('Expected finite nonnegative SMPL-X LBS weights')
    if not np.allclose(weights.sum(1), 1., atol=1e-4, rtol=0):
        raise ValueError('SMPL-X skinning weights must sum to one per vertex')
    ids = [np.flatnonzero(weights[:, joints].sum(1) >= threshold) for joints in FOOT_JOINT_IDS]
    if any(len(value) == 0 for value in ids) or np.intersect1d(*ids).size:
        raise ValueError('Foot weight threshold creates empty or overlapping foot patches')
    return ids


def reviewed_stationary(data, times, source_sha256, actor_id):
    """True means reviewer-established stationary foot; false includes unknown."""
    t = np.asarray(data['time_seconds'])
    if t.shape != np.asarray(times).shape or not np.allclose(t, times, atol=1e-6, rtol=0):
        raise ValueError('Reviewed stationary timestamps differ from normalized source PTS')
    if np.asarray(data['foot_names']).tolist() != FOOT_NAMES:
        raise ValueError('Reviewed mask must name feet in left,right order')
    if str(np.asarray(data['source_video_sha256']).item()) != source_sha256:
        raise ValueError('Reviewed stationary mask source hash differs')
    review_actor = str(np.asarray(data['actor_id']).item()).strip()
    if actor_id is None or not review_actor or review_actor != actor_id:
        raise ValueError('Reviewed stationary mask requires matching explicit actor identity')
    reviewer = str(np.asarray(data['reviewed_by']).item()).strip()
    if not reviewer:
        raise ValueError('Reviewed stationary mask requires reviewed_by attribution')
    mask = boolean_mask(data['stationary'], (len(times), 2), 'reviewed stationary')
    return mask, dict(reviewed_by=reviewer, actor_id=review_actor,
                      false_means='not reviewed stationary; may be moving or unknown')


def native_ground_arrays(vertices, joints, faces, foot_ids, times, ground_y, *, stationary=None, track_active=None):
    """Fixed native plane, fixed vertex correspondence, no fitting or correction."""
    t = validate_times(times)
    from tools.gvhmr.track_lifecycle import track_active_mask
    active = track_active_mask(track_active, len(t))
    v, j = np.asarray(vertices), np.asarray(joints)
    f = np.asarray(faces)
    if not np.isfinite(ground_y) or isinstance(ground_y, bool):
        raise ValueError('ground_y must be an explicit finite scalar')
    for name, value in [('vertices', v), ('joints', j)]:
        if value.ndim != 3 or value.shape[0] != len(t) or value.shape[-1] != 3 or not np.isfinite(value).all():
            raise ValueError(f'Expected finite complete [T,N,3] {name}')
    if v.shape[1] < 1 or j.shape[1] < 22:
        raise ValueError('Need nonempty mesh and at least 22 body joints')
    if f.ndim != 2 or f.shape[1] != 3 or f.dtype.kind not in 'iu' or not len(f) or f.min() < 0 or f.max() >= v.shape[1]:
        raise ValueError('Invalid integer triangle topology')
    if len(foot_ids) != 2:
        raise ValueError('Need fixed left and right foot vertex IDs')
    ids_list = []
    for value in foot_ids:
        ids = np.asarray(value)
        if ids.ndim != 1 or not ids.size or ids.dtype.kind not in 'iu' or ids.min() < 0 or ids.max() >= v.shape[1] or len(np.unique(ids)) != len(ids):
            raise ValueError('Invalid or duplicate fixed foot vertex IDs')
        ids_list.append(ids)
    if np.intersect1d(*ids_list).size:
        raise ValueError('Left and right foot patches must not overlap')
    mask = None if stationary is None else boolean_mask(stationary, (len(t), 2), 'reviewed stationary')
    if mask is not None and np.any(mask[~active]):
        raise ValueError('Reviewed stationary contact after terminal track exit')
    height = v[..., 1] - float(ground_y)
    height = height.astype(float); height[~active] = np.nan
    arrays = dict(time_seconds=t.copy(), interval_start_seconds=t[:-1].copy(),
        interval_end_seconds=t[1:].copy(), vertices=v.copy(), joints=j.copy(),
        body_joints=j[:, :22].copy(), body_joint_names=np.asarray(BODY_NAMES), faces=f.copy(),
        ground_y=np.asarray(float(ground_y)), foot_names=np.asarray(FOOT_NAMES),
        track_active=active, source_frame_indices=np.arange(len(t)),
        mesh_min_height_m=height.min(1), mesh_max_penetration_m=np.maximum(0, -height.min(1)),
        mesh_vertices_below_plane=(height < 0).sum(1), mesh_vertex_fraction_below_plane=(height < 0).mean(1))
    for key in ('mesh_vertices_below_plane','mesh_vertex_fraction_below_plane'):
        arrays[key]=arrays[key].astype(float);arrays[key][~active]=np.nan
    if mask is not None:
        arrays['reviewed_stationary'] = mask.copy()
    reports = {}
    for side, ids in enumerate(ids_list):
        name = FOOT_NAMES[side]
        foot = v[:, ids].copy()
        velocity = np.diff(foot.astype(np.float64), axis=0) / np.diff(t)[:, None, None]
        velocity[~(active[:-1] & active[1:])] = np.nan
        tangent = np.linalg.norm(velocity[..., [0, 2]], axis=-1)
        speed = np.linalg.norm(velocity, axis=-1)
        foot_height = foot[..., 1].astype(float) - float(ground_y)
        foot_height[~active] = np.nan
        selected = np.zeros(len(t) - 1, bool) if mask is None else mask[:-1, side] & mask[1:, side]
        arrays.update({name + '_vertex_ids': ids.copy(), name + '_surface_vertices': foot,
            name + '_height_m': foot_height, name + '_min_height_m': foot_height.min(1),
            name + '_vertex_velocity_m_s': velocity, name + '_vertex_speed_m_s': speed,
            name + '_vertex_tangential_speed_m_s': tangent,
            name + '_mean_vertex_tangential_speed_m_s': tangent.mean(1),
            name + '_maximum_vertex_tangential_speed_m_s': tangent.max(1),
            name + '_reviewed_stationary_pairs': selected})
        reports[name] = dict(vertex_count=len(ids), min_height_m=float(foot_height[active].min()),
            maximum_frame_min_height_m=float(foot_height[active].min(1).max()),
            frame_min_height_m=stats(foot_height[active].min(1)),
            general_motion=dict(scope='all fixed foot-patch vertices; not contact or slip',
                vertex_speed_m_s=stats(speed[active[:-1] & active[1:]]), vertex_tangential_speed_m_s=stats(tangent[active[:-1] & active[1:]])),
            reviewed_stationary_slip=dict(
                status='unknown_no_reviewed_mask' if mask is None else 'reviewed_stationary_intervals' if selected.any() else 'no_reviewed_stationary_pairs',
                reviewed_pair_count=int(selected.sum()), reviewed_duration_seconds=float(np.diff(t)[selected].sum()),
                vertex_samples=int(selected.sum() * len(ids)),
                tangential_vertex_speed_m_s=stats(tangent[selected]),
                vertical_vertex_speed_m_s=stats(np.abs(velocity[selected, :, 1])),
                stationary_frame_intervals=[] if mask is None else intervals(mask[:, side], t),
                pair_start_frame_ids=np.flatnonzero(selected).tolist()))
    summary = dict(plane=dict(y_m=float(ground_y), label=PLANE_LABEL, basis='+Y up; XZ tangent plane',
                              plane_fitted=False, plane_fitted_per_variant=False),
        active_frames=int(active.sum()), inactive_frames=int((~active).sum()),
        mesh=dict(maximum_penetration_m=float(arrays['mesh_max_penetration_m'][active].max()),
                  minimum_signed_height_m=float(height[active].min()),
                  frames_with_vertices_below_plane=int((height.min(1) < 0).sum()),
                  maximum_vertex_fraction_below_plane=float(arrays['mesh_vertex_fraction_below_plane'][active].max())),
        feet=reports, motion_modified=False, contact_validated=False, room_aligned=False)
    return arrays, summary


def skin_global_parameters(params, model, torch_module, *, device='cpu', batch_size=32):
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    vertices, joints = [], []
    with torch_module.inference_mode():
        for start in range(0, len(params['body_pose']), batch_size):
            batch = {key: torch_module.as_tensor(value[start:start + batch_size], dtype=torch_module.float32,
                                                device=device) for key, value in params.items()}
            result = model(**batch)
            vertices.append(result.vertices.detach().cpu().numpy())
            joints.append(result.joints.detach().cpu().numpy())
    if not vertices:
        raise ValueError('Empty native motion')
    return np.concatenate(vertices), np.concatenate(joints)


def verify_upstream(repo):
    repo = Path(repo).resolve(strict=True)
    git = ['git', '-c', f'safe.directory={repo}', '-C', str(repo)]
    revision = subprocess.run([*git, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    if revision != REVISION:
        raise ValueError('Native-floor audit requires pinned GVHMR BEDLAM2 revision ' + REVISION)
    dirty = subprocess.run([*git, 'diff', 'HEAD', '--name-only', '--', *SOURCES],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    if dirty:
        raise ValueError('Audited native body/global/floor source changed: ' + ', '.join(dirty))
    return dict(path=str(repo), revision=revision, sources={name:file_sha256(repo / name) for name in SOURCES},
                body_asset=dict(path=str(repo / BODY_ASSET), sha256=file_sha256(repo / BODY_ASSET)))


def audit(*, repo, motion_path, video_path, output, ground_y, stationary_path=None,
          actor_id=None, foot_weight_threshold=.5, device='cpu', batch_size=32, max_frames=1800):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if not np.isfinite(ground_y) or isinstance(ground_y, bool):
        raise ValueError('An explicit finite native ground_y is required')
    if isinstance(max_frames, bool) or not isinstance(max_frames, int) or max_frames < 2:
        raise ValueError('max_frames must be an integer >=2')
    repo = Path(repo).resolve(strict=True)
    paths = dict(motion=Path(motion_path).resolve(strict=True), video=Path(video_path).resolve(strict=True))
    upstream = verify_upstream(repo)
    timeline = video_timeline(paths['video'])
    if timeline['frames'] > max_frames:
        raise ValueError('Full native mesh exceeds max_frames; explicitly raise the bound without trimming source rows')
    hashes = {name:dict(path=str(path), sha256=file_sha256(path)) for name, path in paths.items()}
    inference = None
    manifest_path = paths['motion'].parent / 'provenance.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('normalized_input_sha256') != hashes['video']['sha256']:
            raise ValueError('Inference provenance does not bind this normalized source video')
        if actor_id is not None and manifest.get('actor_id') not in [None, actor_id]:
            raise ValueError('Explicit actor_id differs from inference provenance')
        actor_id = actor_id or manifest.get('actor_id')
        inference = dict(path=str(manifest_path), sha256=file_sha256(manifest_path),
                         upstream_postprocessing=manifest.get('upstream_postprocessing'),
                         actor_id=manifest.get('actor_id'), selected_track_id=manifest.get('selected_track_id'))
    stationary, review = None, None
    if stationary_path is not None:
        path = Path(stationary_path).resolve(strict=True)
        with np.load(path, allow_pickle=False) as data:
            stationary, review = reviewed_stationary(data, timeline['time_seconds'], hashes['video']['sha256'], actor_id)
        hashes['reviewed_stationary'] = dict(path=str(path), sha256=file_sha256(path))
    import torch
    params = load_parameters(paths['motion'], timeline['time_seconds'], torch)
    from tools.gvhmr.track_lifecycle import track_active_mask, pad_inactive, source_frame_mapping
    if paths['motion'].suffix == '.npz':
        with np.load(paths['motion'],allow_pickle=False) as z:
            active=track_active_mask(z.get('track_active'),timeline['frames'])
            mapping=source_frame_mapping(z.get('source_frame_indices'),timeline['frames'])
    else:
        raw=torch.load(paths['motion'],map_location='cpu',weights_only=True)
        active=track_active_mask(raw['track_active'].numpy() if 'track_active' in raw else None,timeline['frames'])
        mapping=source_frame_mapping(raw['source_frame_indices'].numpy() if 'source_frame_indices' in raw else None,timeline['frames'])
    old_path = sys.path.copy()
    try:
        sys.path.insert(0, str(repo))
        smplx_utils = importlib.import_module('hmr4d.utils.smplx_utils')
    finally:
        sys.path[:] = old_path
    if Path(smplx_utils.__file__).resolve() != repo / 'hmr4d/utils/smplx_utils.py':
        raise ValueError('Imported GVHMR body model belongs to another checkout')
    model = smplx_utils.make_smplx('supermotion').to(device).eval()
    weights = model.bm.lbs_weights.detach().cpu().numpy()
    ids = foot_vertices_from_weights(weights, foot_weight_threshold)
    vertices, joints = skin_global_parameters({k:v[:int(active.sum())] for k,v in params.items()}, model, torch, device=device, batch_size=batch_size)
    vertices,joints=pad_inactive(vertices,active),pad_inactive(joints,active)
    arrays, summary = native_ground_arrays(vertices, joints, model.faces, ids, timeline['time_seconds'],
                                            ground_y, stationary=stationary, track_active=active)
    arrays['source_frame_indices']=mapping
    arrays.update({name:value for name, value in params.items()})
    arrays['lbs_weights'] = weights
    arrays['image_size'] = timeline['image_size']
    report = dict(schema_version=1, scope='native_ground_assumption_diagnostic', actor_id=actor_id,
        frames=timeline['frames'], fps=30, duration_seconds=timeline['duration_seconds'],
        source_video_fully_decoded=True, source_presentation_timestamps_preserved=True,
        method="pinned make_smplx('supermotion') applied to unmodified native global parameters",
        source_betas_preserved=True, rotations_resampled=False, foot_weight_threshold=foot_weight_threshold,
        foot_joint_ids=dict(zip(FOOT_NAMES, FOOT_JOINT_IDS)), stationary_review=review,
        inference_provenance=inference, input_pairing='launcher_video_hash' if inference else 'caller_supplied; no launcher provenance',
        upstream=upstream, inputs=hashes, summary=summary, motion_accepted=False,
        versions={name:importlib.metadata.version(name) for name in ['numpy', 'torch', 'smplx', 'av']},
        external_smplx_source_sha256=file_sha256(inspect.getfile(model.bm.__class__)),
        external_smplx_lbs_sha256=file_sha256(importlib.import_module('smplx.lbs').__file__),
        implementation_sha256=file_sha256(__file__), visual_review='pending',
        limitations=[PLANE_LABEL,
            'The same explicit native plane must be used for raw/default variants; this tool never fits or translates it.',
            'Raw motion vertical origin can be arbitrary. Native-plane penetration does not establish scene-ground error.',
            'Native dimensions use the body model nominal metres; no independent metric scale calibration is established.',
            'Foot patches use ankle/toe skin weights, not observed shoe soles or reviewed contact patches.',
            'Vertex counts/fractions are not contact area, penetration volume, or mesh-intersection measurements.',
            'Stationary-interval tangential speed uses corresponding vertices, including rotation; summaries are vertex-weighted.',
            'Reviewed stationarity is source evidence, not proof that the predicted foot touches this assumed plane.',
            'Unreviewed intervals remain unknown; slow predicted motion never supplies stationary labels.',
            'Default mean hand pose is inherited from upstream; GVHMR does not estimate source finger articulation.'])
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / 'native_ground.npz', **arrays)
    report['outputs'] = {'native_ground.npz':file_sha256(output / 'native_ground.npz')}
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--motion', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True, help='Exact normalized 30 Hz GVHMR input')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ground-y', type=float, required=True, help=PLANE_LABEL)
    parser.add_argument('--stationary-mask', type=Path)
    parser.add_argument('--actor-id')
    parser.add_argument('--foot-weight-threshold', type=float, default=.5)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--max-frames', type=int, default=1800)
    args = parser.parse_args()
    report = audit(repo=args.repo, motion_path=args.motion, video_path=args.video, output=args.output,
        ground_y=args.ground_y, stationary_path=args.stationary_mask, actor_id=args.actor_id,
        foot_weight_threshold=args.foot_weight_threshold, device=args.device,
        batch_size=args.batch_size, max_frames=args.max_frames)
    print(json.dumps(dict(output=str(args.output), frames=report['frames'], motion_accepted=False)))


if __name__ == '__main__':
    main()
