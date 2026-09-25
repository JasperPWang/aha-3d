#!/usr/bin/env python3
"""Track one actor with SAMURAI and save masks.npz in the project's schema.

SAMURAI mode, one
fresh predictor (a reset_state alone does not reset the Kalman filter), a box
prompt on frame 0 only, and no forward/backward edits or re-identification.

The frame-0 box comes from the run's own raw_tracking.json, so the choice being
made here is only *which* detected person to follow -- the box itself is the
detector's.
"""
import argparse, hashlib, json, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
SAMURAI = ROOT / 'third_party/samurai'
CKPT = ROOT / '.runtime/samurai-checkpoints/sam2.1_hiera_base_plus.pt'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', required=True)
    ap.add_argument('--raw-tracking', required=True, help='for the frame-0 box only')
    ap.add_argument('--track-id', type=int, default=None,
                    help='which frame-0 detection to follow')
    ap.add_argument('--box', help='explicit x0,y0,x1,y1, for a reviewed anchor')
    ap.add_argument('--actor-id', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--prompt-frame', type=int, default=0,
                    help='frame to take the box prompt from; the actor is not always\n'
                         'in frame 0 (clip42 first appears at 12)')
    ap.add_argument('--samurai', type=Path, default=SAMURAI)
    ap.add_argument('--checkpoint', type=Path, default=CKPT)
    ap.add_argument('--deps', type=Path, nargs='*', default=[])
    a = ap.parse_args()

    import sys, torch, av
    from PIL import Image
    # Extra dependencies normally belong in the configured GVHMR environment.
    sys.path[:0] = [str(d) for d in a.deps] + [str(a.samurai / 'sam2')]
    from sam2.build_sam import build_sam2_video_predictor
    # both imports are load-bearing: hydra resolves the predictor by dotted name,
    # so the modules have to be in sys.modules before the config is instantiated
    import sam2.modeling.backbones.hieradet  # noqa: F401
    import sam2.sam2_video_predictor as vp

    # Decode once with PyAV, keeping exact source PTS, and feed the predictor
    # directly. Upstream would go through Decord or a JPEG image folder; neither
    # is available here and the JPEG round-trip is lossy.
    mean = torch.tensor([0.485, 0.456, 0.406])[:, None, None]
    std = torch.tensor([0.229, 0.224, 0.225])[:, None, None]
    times, frames = [], []
    with av.open(a.video) as c:
        st = c.streams.video[0]
        for f in c.decode(video=0):
            times.append(float(f.pts * st.time_base))
            im = Image.fromarray(f.to_ndarray(format='rgb24')).resize((1024, 1024))
            t = torch.from_numpy(np.asarray(im)).permute(2, 0, 1).float().div_(255)
            frames.append((t - mean) / std)
    times = np.asarray(times)
    n = len(times)
    images = torch.stack(frames)

    def _loader(tensor, expect):
        def bound(*, video_path, image_size, offload_video_to_cpu,
                  async_loading_frames, compute_device, **kw):
            assert Path(video_path).resolve() == Path(expect).resolve()
            assert image_size == 1024 and offload_video_to_cpu and not async_loading_frames
            return tensor, 720, 1280
        return bound

    if a.box:
        box = [float(v) for v in a.box.split(',')]
    else:
        hist = json.load(open(a.raw_tracking))['raw_history'][a.prompt_frame]
        box = {d['id']: d['bbx_xyxy'] for d in hist}[a.track_id]

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    masks = np.zeros((n, 720, 1280), dtype=bool)
    area = np.zeros(n, dtype=np.int64)
    bb = np.full((n, 4), np.nan)
    t0 = time.monotonic()

    # SAMURAI reads output_dict['non_cond_frame_outputs'][i] unconditionally, so a
    # conditioning frame anywhere but local index 0 raises KeyError. When the actor
    # is not in frame 0 -- clip42's man first appears at 12 -- the anchor has to sit
    # elsewhere. Do what the project's own clip42 run did: two source-ordered
    # streams, anchor->end and anchor->0 reversed, each with the anchor at local 0
    # and a fresh predictor, then map local indices back to source.
    obj_id = a.track_id if a.track_id is not None else 1
    streams = [list(range(a.prompt_frame, n))]
    if a.prompt_frame > 0:
        streams.append(list(range(a.prompt_frame, -1, -1)))
    for order in streams:
        model = build_sam2_video_predictor(
            'configs/samurai/sam2.1_hiera_b+.yaml', str(a.checkpoint), device='cuda:0')
        assert model.samurai_mode and model.kf_mean is None and model.stable_frames == 0
        vp.load_video_frames = _loader(images[order], a.video)
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
            state = model.init_state(a.video, offload_video_to_cpu=True,
                                     offload_state_to_cpu=True)
            model.add_new_points_or_box(state, box=np.asarray(box, np.float32),
                                        frame_idx=0, obj_id=obj_id)
            for local, ids, logits in model.propagate_in_video(state, start_frame_idx=0):
                src = order[local]
                m = (logits[0, 0] > 0).cpu().numpy()
                masks[src] = m
                area[src] = int(m.sum())
                if area[src]:
                    ys, xs = np.nonzero(m)
                    bb[src] = [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]
        del model
        torch.cuda.empty_cache()
    np.savez_compressed(out / 'masks.npz', masks=masks, time_seconds=times,
                        image_size=np.asarray([1280, 720]),
                        source_video_sha256=np.asarray(sha(a.video)),
                        actor_id=np.asarray(a.actor_id),
                        mask_area_pixels=area, bbox_xyxy_boundary=bb)
    (out / 'tracking.json').write_text(json.dumps(dict(
        actor_id=a.actor_id, tracker_id=a.track_id, frames=n,
        source_video_sha256=sha(a.video), initial_box_xyxy=box,
        initial_frame=a.prompt_frame, initial_box_xyxy_used=list(map(float, box)), empty_frames=int((area == 0).sum()),
        elapsed_seconds=time.monotonic() - t0,
        checkpoint_sha256=sha(a.checkpoint),
        bbox_semantics='mask-derived pixel extents; NaN when empty; not a visibility claim',
        model_algorithm='SAMURAI mode, fresh predictor, box prompt frame 0 only',
    ), indent=1))
    print(json.dumps({'actor': a.actor_id, 'frames': n,
                      'empty_frames': int((area == 0).sum()),
                      'seconds': round(time.monotonic() - t0, 1)}))


if __name__ == '__main__':
    main()
