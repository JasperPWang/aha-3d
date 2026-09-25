"""Retain raw GVHMR tracking support without editing the upstream checkout.

Wrap the upstream demo in ``record_tracking_evidence(...)``. The temporary
method replacement uses the pinned upstream interpolation/smoothing helpers.
Selection uses the default area ranking, an explicit ID, or reviewed fragments.
Existing dense caches cannot supply raw detection evidence and must not be reused.

An explicit actor review may instead select several non-overlapping fragments
from a hash-bound retained raw-history file. Unusable person detections remain
separate from usable body-box observations; neither establishes body visibility.
"""
from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import tempfile

import numpy as np

REVISION = "cac2d9dacc6b4b6f145ca02c2e6e616719fff916"


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_sha256(values):
    """Hash the float32 box representation saved by upstream demo.py."""
    a = np.ascontiguousarray(values, dtype="<f4")
    return hashlib.sha256(str(a.shape).encode() + a.tobytes()).hexdigest()


def validate_times(values):
    t = np.asarray(values, dtype=float)
    if t.ndim != 1 or len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError("Need finite, increasing full-frame timestamps")
    if not np.allclose(np.diff(t), 1 / 30, atol=1e-6, rtol=0):
        raise ValueError("GVHMR evidence requires normalized 30 Hz timestamps with missing rows retained")
    return t


def video_timeline(path):
    """Fully decode the actual model input; PyAV is imported only at runtime."""
    import av
    times = []
    last_duration = 0.
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        size = [int(stream.width), int(stream.height)]
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError("Model-input video frame has no presentation timestamp")
            if [frame.width, frame.height] != size:
                raise ValueError("Video raster changes during the shot")
            times.append(float(frame.pts * frame.time_base))
            last_duration = float((getattr(frame, "duration", 0) or 0) * frame.time_base)
    t = validate_times(times)
    return dict(time_seconds=t, image_size=np.asarray(size, dtype=np.int64),
                frames=len(t), fully_decoded=True,
                duration_seconds=float(t[-1] - t[0] + (last_duration or 1 / 30)))


def normalize_history(history):
    """Keep IDs/boxes exactly as observed; missing frames remain empty lists."""
    normalized = []
    for frame in history:
        detections = []
        seen = set()
        for item in frame:
            raw_id = item["id"]
            if isinstance(raw_id, bool) or not isinstance(raw_id, (int, np.integer)):
                raise ValueError("Tracker IDs must be integers")
            track_id = int(raw_id)
            box = np.asarray(item["bbx_xyxy"], dtype=float)
            if track_id in seen or box.shape != (4,) or not np.isfinite(box).all() or np.any(box[2:] <= box[:2]):
                raise ValueError("Duplicate track ID or invalid raw box")
            seen.add(track_id)
            row = dict(id=track_id, bbx_xyxy=box.tolist())
            if "confidence" in item:
                score = float(item["confidence"])
                if not np.isfinite(score):
                    raise ValueError("Nonfinite raw detector confidence")
                row["confidence"] = score
            detections.append(row)
        normalized.append(detections)
    return normalized


def build_tracking_evidence(history, time_seconds, image_size, *, source_path,
                            source_sha256, selected_track_id=None, actor_id=None):
    """Pure evidence construction, preserving all tracks for identity review."""
    t = validate_times(time_seconds)
    size = np.asarray(image_size)
    if size.shape != (2,) or not np.isfinite(size).all() or (size <= 0).any():
        raise ValueError("Invalid tracking image size")
    rows = normalize_history(history)
    if len(rows) != len(t):
        raise ValueError("Raw tracking history does not cover every input frame")
    if selected_track_id is not None and (isinstance(selected_track_id, bool) or
                                          not isinstance(selected_track_id, (int, np.integer))):
        raise ValueError("Selected tracker ID must be an integer")
    tracks = {}
    for frame_index, frame in enumerate(rows):
        for item in frame:
            record = tracks.setdefault(item["id"], dict(frame_indices=[], area_sum=0.))
            box = np.asarray(item["bbx_xyxy"])
            record["frame_indices"].append(frame_index)
            record["area_sum"] += float(np.prod(box[2:] - box[:2]) / np.prod(size))
    # Stable sorting matches the upstream summed-box-area selection and tie order.
    ranked = sorted(tracks, key=lambda key: tracks[key]["area_sum"], reverse=True)
    selected = int(selected_track_id) if selected_track_id is not None else (ranked[0] if ranked else None)
    found = selected in tracks
    detected = np.zeros(len(t), dtype=bool)
    if found:
        detected[tracks[selected]["frame_indices"]] = True
    filling = np.full(len(t), "unavailable", dtype="U16")
    filling[detected] = "observed"
    if found:
        indices = np.flatnonzero(detected)
        filling[:indices[0]] = "held_leading"
        filling[indices[-1] + 1:] = "held_trailing"
        internal = (~detected) & (np.arange(len(t)) > indices[0]) & (np.arange(len(t)) < indices[-1])
        filling[internal] = "interpolated"
    return dict(schema_version=1, kind="gvhmr_raw_tracking_evidence",
                upstream_revision=REVISION, source=dict(path=str(source_path), sha256=source_sha256),
                time_seconds=t.tolist(), image_size=size.tolist(), frames=len(t),
                actor_id=actor_id, selection_policy="explicit_tracker_id" if selected_track_id is not None else "upstream_summed_box_area",
                selected_track_id=selected, selection_found=found,
                ranked_tracks=[dict(id=key, **tracks[key]) for key in ranked],
                detected=detected.tolist(), box_fill_status=filling.tolist(), raw_history=rows,
                raw_box_confidence="retained_where_supplied; stock Tracker.track omits scores",
                status="raw_captured_before_interpolation", identity_review="pending",
                limitations=["Tracking assignments do not establish physical identity or body-part visibility.",
                             "Held/interpolated boxes are model inputs, not observations."])


def _replace_json(path, payload):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _review_ids(values, name, *, allow_empty=False):
    if not isinstance(values, list) or (not values and not allow_empty) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in values) or len(set(values)) != len(values):
        raise ValueError(f'{name} must contain unique explicit integer track IDs')
    return values.copy()


def build_reviewed_fragment_evidence(raw, review, times, image_size, *, source_sha256,
                                     raw_tracking_sha256, source_path, actor_id=None):
    """Select only reviewed original raw boxes; never fit boxes or infer re-ID."""
    t = validate_times(times)
    if raw.get('schema_version') != 1 or raw.get('kind') != 'gvhmr_raw_tracking_evidence' or raw.get('upstream_revision') != REVISION:
        raise ValueError('Cached observations require pinned raw tracking evidence')
    if raw.get('status') not in ('raw_captured_before_interpolation', 'dense_boxes_returned'):
        raise ValueError('Cached observations lack a retained original raw tracking history')
    if review.get('schema_version') != 1 or review.get('kind') != 'gvhmr_reviewed_actor_fragments':
        raise ValueError('Expected explicit reviewed actor-fragment schema')
    if not raw_tracking_sha256 or review.get('raw_tracking_sha256') != raw_tracking_sha256:
        raise ValueError('Actor review raw tracking file hash differs')
    if raw['source']['sha256'] != source_sha256 or review.get('source_video_sha256') != source_sha256:
        raise ValueError('Reviewed/cached tracking source video hash differs')
    for label, data in [('Cached raw', raw), ('Actor review', review)]:
        prior = np.asarray(data['time_seconds'], dtype=float)
        if prior.shape != t.shape or not np.allclose(prior, t, atol=1e-6, rtol=0):
            raise ValueError(label + ' timestamps differ from exact normalized input PTS')
        if not np.array_equal(data['image_size'], image_size):
            raise ValueError(label + ' raster differs from normalized input')
    if raw.get('frames') != len(t):
        raise ValueError('Cached raw history frame count differs')
    for key in ('actor_id', 'reviewed_by', 'review_scope', 'raw_tracking_path'):
        if not isinstance(review.get(key), str) or not review[key].strip():
            raise ValueError('Actor review requires nonempty ' + key)
    if actor_id is not None and actor_id != review['actor_id']:
        raise ValueError('Explicit actor_id differs from reviewed physical-person label')
    reviewed_frames = np.asarray(review['reviewed_frame_indices'])
    if reviewed_frames.ndim != 1 or not len(reviewed_frames) or reviewed_frames.dtype.kind not in 'iu' or \
            reviewed_frames.min() < 0 or reviewed_frames.max() >= len(t) or len(np.unique(reviewed_frames)) != len(reviewed_frames):
        raise ValueError('Review frame indices must identify actually reviewed source frames')
    usable = _review_ids(review['usable_body_box_track_ids'], 'usable_body_box_track_ids')
    unusable = _review_ids(review['observed_but_body_box_unusable_ids'], 'observed_but_body_box_unusable_ids', allow_empty=True)
    if set(usable) & set(unusable):
        raise ValueError('Usable and unusable body-box track IDs must be disjoint')
    rows = normalize_history(raw['raw_history'])
    if len(rows) != len(t):
        raise ValueError('Cached raw history must retain every source frame')
    found = {row['id'] for frame in rows for row in frame}
    missing = (set(usable) | set(unusable)) - found
    if missing:
        raise ValueError('Every requested reviewed track ID must exist in raw history: ' + str(sorted(missing)))
    selected_ids, observed_ids, body_boxes, source_frames = [], [], [], []
    actor_present, unusable_present = [], []
    for index, frame in enumerate(rows):
        available = [row for row in frame if row['id'] in usable]
        if len(available) > 1:
            raise ValueError(f'Overlapping selected usable track IDs at frame {index}; review ambiguity first')
        all_actor_ids = [row['id'] for row in frame if row['id'] in usable + unusable]
        observed_ids.append(all_actor_ids)
        selected_ids.append(available[0]['id'] if available else None)
        actor_present.append(bool(all_actor_ids))
        unusable_present.append(any(value in unusable for value in all_actor_ids))
        if available:
            source_frames.append(index)
            body_boxes.append(available[0]['bbx_xyxy'])
    detected = np.asarray([value is not None for value in selected_ids])
    fill = np.full(len(t), 'interpolated', dtype='U16')
    fill[:source_frames[0]], fill[source_frames[-1] + 1:] = 'held_leading', 'held_trailing'
    fill[detected] = 'observed'
    payload = build_tracking_evidence(rows, t, image_size, source_path=source_path,
        source_sha256=source_sha256, selected_track_id=usable[0], actor_id=review['actor_id'])
    payload.update(selection_policy='reviewed_actor_fragments', selected_track_id=None,
        selected_track_ids=usable, usable_body_box_track_ids=usable,
        observed_but_body_box_unusable_ids=unusable, selection_found=True,
        detected=detected.tolist(), usable_body_box_detected=detected.tolist(),
        detected_semantics='usable reviewed actor body-box observation; not body-part visibility',
        actor_detection_present=actor_present, unusable_body_box_detection_present=unusable_present,
        usable_track_id_by_frame=selected_ids, observed_actor_track_ids_by_frame=observed_ids,
        usable_source_frame_indices=source_frames, observed_usable_body_boxes_xyxy=body_boxes,
        box_fill_status=fill.tolist(),
        body_box_support_status=['reviewed_usable_raw_box' if use else 'reviewed_unusable_detection_only' if bad else
                                 'no_reviewed_actor_detection' for use, bad in zip(detected, unusable_present)],
        observation_origin='explicit cached raw detections; tracker inference not repeated',
        actor_fragment_review=review, actor_review_content_sha256=_json_sha256(review),
        cached_raw_history_sha256=_json_sha256(raw['raw_history']),
        cached_raw_tracking=dict(sha256=raw_tracking_sha256, declared_path=review['raw_tracking_path']),
        identity_review='reviewer_associated_fragments_with_declared_scope',
        limitations=[
            'Actor fragment association and body-box usability are explicit reviewer assertions, not automatic re-identification.',
            'Usable person crops may be partial height; detector presence and box usability do not establish body-part visibility.',
            'Head-only/unusable detections remain actor evidence but never supply a usable whole-person crop.',
            'Unselected raw tracks are retained; they are not silently associated with this actor.',
            'Held/interpolated boxes are model inputs, not observations.'])
    # Preserve the original complete JSON history, including optional raw fields.
    payload['raw_history'] = json.loads(json.dumps(raw['raw_history'], allow_nan=False))
    return payload


def load_reviewed_fragment_evidence(raw_tracking_path, actor_review_path, times, image_size, *,
                                    source_sha256, source_path, actor_id=None):
    raw_path, review_path = Path(raw_tracking_path).resolve(strict=True), Path(actor_review_path).resolve(strict=True)
    raw, review = json.loads(raw_path.read_text()), json.loads(review_path.read_text())
    payload = build_reviewed_fragment_evidence(raw, review, times, image_size,
        source_sha256=source_sha256, source_path=source_path, actor_id=actor_id,
        raw_tracking_sha256=file_sha256(raw_path))
    payload['cached_raw_tracking']['path'] = str(raw_path)
    payload['actor_review_file'] = dict(path=str(review_path), sha256=file_sha256(review_path))
    return payload


@contextmanager
def record_tracking_evidence(path, *, selected_track_id=None, actor_id=None,
                             expected_video=None, time_seconds=None, tracker_module=None,
                             cached_raw_tracking_path=None, actor_review_path=None):
    """Instrument one fresh-box demo call, restoring upstream methods on exit.

    Supply ``tracker_module`` only for a dependency-injected test. The ordinary
    path imports the configured upstream module lazily. A skipped cached tracking
    stage raises instead of manufacturing an all-true detected mask.
    """
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    cached_mode = cached_raw_tracking_path is not None or actor_review_path is not None
    if cached_mode and (cached_raw_tracking_path is None or actor_review_path is None or selected_track_id is not None):
        raise ValueError('Reviewed fragments require both cached raw tracking and actor review, without selected_track_id')
    module = tracker_module or importlib.import_module("hmr4d.utils.preproc.tracker")
    cls = module.Tracker
    original = cls.get_one_track
    calls = 0

    def instrumented(self, video_path):
        nonlocal calls
        if calls:
            raise RuntimeError("One evidence sidecar may describe only one tracking call")
        calls += 1
        video = Path(video_path).resolve(strict=True)
        if expected_video is not None and video != Path(expected_video).resolve(strict=True):
            raise ValueError("Tracked video differs from requested evidence source")
        length, width, height = module.get_video_lwh(video_path)
        times = video_timeline(video)["time_seconds"] if time_seconds is None else validate_times(time_seconds)
        if len(times) != length:
            raise ValueError("Tracker/video/timestamp frame counts differ")
        if cached_mode:
            payload = load_reviewed_fragment_evidence(cached_raw_tracking_path, actor_review_path, times, [width, height],
                source_sha256=file_sha256(video), source_path=video, actor_id=actor_id)
            selected_frames = payload['usable_source_frame_indices']
            selected_boxes = np.asarray(payload['observed_usable_body_boxes_xyxy'], dtype=np.float32)
            payload['cached_box_dtype'] = 'float32, matching stock YOLO xyxy detections'
        else:
            history = self.track(video_path)
            if len(history) != length:
                raise ValueError("Tracker/video/timestamp frame counts differ")
            frame_ids, boxes, ranked = self.sort_track_length(history, video_path)
            chosen = selected_track_id if selected_track_id is not None else (ranked[0] if ranked else None)
            payload = build_tracking_evidence(history, times, [width, height], source_path=video,
                source_sha256=file_sha256(video), selected_track_id=chosen, actor_id=actor_id)
            # Preserve upstream numerical ordering, including nearly tied area sums.
            payload["selection_policy"] = "explicit_tracker_id" if selected_track_id is not None else "upstream_summed_box_area"
            by_id = {row["id"]: row for row in payload["ranked_tracks"]}
            payload["ranked_tracks"] = [by_id[track_id] for track_id in ranked]
            selected_frames = frame_ids.get(chosen, [])
            selected_boxes = boxes.get(chosen, [])
        payload["instrumentation_sha256"] = file_sha256(__file__)
        if getattr(module, "__file__", None):
            payload["upstream_tracker_sha256"] = file_sha256(module.__file__)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Save raw evidence even if selection or later interpolation fails.
        with path.open("x") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
        if not payload["selection_found"]:
            raise ValueError(f"Requested tracker ID was not observed; inspect raw history in {path}")
        # The same operations as pinned Tracker.get_one_track, without discarding mask.
        ids = module.torch.tensor(selected_frames)
        observed_boxes = module.torch.tensor(np.asarray(selected_boxes))
        mask = module.frame_id_to_mask(ids, length)
        dense = module.rearrange_by_mask(observed_boxes, mask)
        gaps = module.get_frame_id_list_from_mask(~mask)
        dense = module.linear_interpolate_frame_ids(dense, gaps)
        if not (dense.sum(1) != 0).all():
            raise ValueError("Upstream box interpolation returned empty boxes")
        for _ in range(2):
            dense = module.moving_average_smooth(dense, window_size=5, dim=0)
        payload["dense_bbx_xyxy_sha256"] = array_sha256(dense.detach().cpu().numpy())
        payload["status"] = "dense_boxes_returned"
        payload["interpolation_policy"] = "upstream linear gaps/endpoint hold; two 5-frame moving averages"
        _replace_json(path, payload)
        return dense

    cls.get_one_track = instrumented
    try:
        yield
        if calls != 1:
            raise RuntimeError("Tracking was not executed; existing dense caches cannot recover raw detection support")
    finally:
        cls.get_one_track = original


def validated_detected(payload, times, image_size, source_sha256, dense_boxes):
    """Reject a sidecar from another source, timeline, actor box cache or schema."""
    if payload.get("schema_version") != 1 or payload.get("kind") != "gvhmr_raw_tracking_evidence":
        raise ValueError("Unsupported raw tracking evidence schema")
    if payload.get("upstream_revision") != REVISION or payload.get("status") != "dense_boxes_returned":
        raise ValueError("Tracking evidence lacks completed pinned box construction")
    t = validate_times(times)
    old = np.asarray(payload["time_seconds"], dtype=float)
    if old.shape != t.shape or not np.allclose(old, t, atol=1e-6, rtol=0):
        raise ValueError("Tracking evidence timestamps differ from model input")
    if not np.array_equal(payload["image_size"], image_size) or payload["source"]["sha256"] != source_sha256:
        raise ValueError("Tracking evidence raster/source hash differs from model input")
    if payload.get('selection_policy') == 'reviewed_actor_fragments':
        if payload.get('cached_raw_history_sha256') != _json_sha256(payload['raw_history']) or \
                payload.get('actor_review_content_sha256') != _json_sha256(payload['actor_fragment_review']):
            raise ValueError('Reviewed tracking embedded raw history or review content hash differs')
        reconstructed = build_reviewed_fragment_evidence(payload, payload['actor_fragment_review'], t, image_size,
            source_path=payload['source']['path'], source_sha256=source_sha256, actor_id=payload.get('actor_id'),
            raw_tracking_sha256=payload['cached_raw_tracking']['sha256'])
        for name in ('selected_track_id', 'selected_track_ids', 'usable_body_box_track_ids',
                     'observed_but_body_box_unusable_ids', 'usable_body_box_detected',
                     'actor_detection_present', 'unusable_body_box_detection_present',
                     'usable_track_id_by_frame', 'observed_actor_track_ids_by_frame',
                     'usable_source_frame_indices', 'observed_usable_body_boxes_xyxy', 'box_fill_status',
                     'body_box_support_status'):
            if payload.get(name) != reconstructed[name]:
                raise ValueError('Reviewed detection support disagrees with original raw history: ' + name)
    else:
        reconstructed = build_tracking_evidence(payload["raw_history"], t, image_size,
            source_path=payload["source"]["path"], source_sha256=source_sha256,
            selected_track_id=payload["selected_track_id"], actor_id=payload.get("actor_id"))
    if not reconstructed["selection_found"] or payload["detected"] != reconstructed["detected"]:
        raise ValueError("Detection mask disagrees with original selected-track history")
    boxes = np.asarray(dense_boxes)
    from tools.gvhmr.track_lifecycle import track_active_mask, source_frame_mapping
    active = track_active_mask(payload.get('track_active'), len(t))
    source_frame_mapping(payload.get('source_frame_indices'), len(t))
    if boxes.shape != (len(t), 4) or not np.isfinite(boxes[active]).all() or (not active.all() and not np.isnan(boxes[~active]).all()):
        raise ValueError("Invalid cached dense bounding boxes")
    if payload.get("dense_bbx_xyxy_sha256") != array_sha256(boxes):
        raise ValueError("Tracking sidecar belongs to a different actor bounding-box cache")
    detected = np.asarray(reconstructed["detected"], dtype=bool)
    if np.any(detected & ~active):
        raise ValueError('Detected tracking observations after terminal exit')
    return detected
